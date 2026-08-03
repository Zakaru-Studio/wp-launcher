"""
Authentication routes with GitHub OAuth support
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, current_app
import secrets
import os
from werkzeug.utils import secure_filename

from app import csrf
from app.middleware.auth_middleware import login_required
from app.utils import login_throttle


auth_bp = Blueprint('auth', __name__)


def _reset_session_on_login(user_id):
    """Repartir d'une session vierge au moment où l'utilisateur s'authentifie.

    Contre la fixation de session : un identifiant planté par un tiers avant
    l'authentification ne doit pas survivre à l'élévation de privilège. La
    langue choisie sur la page de login est le seul élément réinjecté — la
    perdre renverrait l'utilisateur au défaut du navigateur juste après
    l'avoir changée.
    """
    locale = session.get('locale')
    session.clear()
    if locale:
        session['locale'] = locale
    session['user_id'] = user_id


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page and authentication"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        ip = login_throttle.client_ip()

        wait = login_throttle.check(ip, username)
        if wait:
            current_app.logger.warning(
                "Login blocked by throttle: user=%r ip=%s wait=%ss", username, ip, wait
            )
            flash(
                f'Too many failed attempts. Try again in {_format_wait(wait)}.',
                'error'
            )
            return render_template('login.html'), 429

        user_service = current_app.extensions['user_service']
        user = user_service.authenticate(username, password)

        if user:
            login_throttle.record_success(ip, username)
            _reset_session_on_login(user.id)
            return redirect(url_for('main.index'))
        else:
            penalty = login_throttle.record_failure(ip, username)
            current_app.logger.warning(
                "Failed login: user=%r ip=%s%s",
                username, ip, f" — locked for {penalty}s" if penalty else ""
            )
            flash('Invalid username or password', 'error')

    return render_template('login.html')


def _format_wait(seconds: int) -> str:
    """Human-readable lockout delay for the flash message."""
    if seconds < 60:
        return f'{seconds} seconds'
    minutes = (seconds + 59) // 60
    return f'{minutes} minute{"s" if minutes > 1 else ""}'


@auth_bp.route('/login/github')
def login_github():
    """Redirect to GitHub OAuth"""
    oauth_service = current_app.extensions['oauth_service']
    
    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state
    
    redirect_uri = url_for('auth.github_callback', _external=True)
    auth_url = oauth_service.get_authorization_url(redirect_uri, state)
    
    return redirect(auth_url)


@auth_bp.route('/login/github/callback')
@csrf.exempt
def github_callback():
    """GitHub OAuth callback"""
    # Verify state token
    state = request.args.get('state')
    if state != session.get('oauth_state'):
        flash('Invalid state token', 'error')
        return redirect(url_for('auth.login'))
    
    code = request.args.get('code')
    if not code:
        flash('No authorization code received', 'error')
        return redirect(url_for('auth.login'))
    
    oauth_service = current_app.extensions['oauth_service']
    user_service = current_app.extensions['user_service']
    
    # Exchange code for token
    redirect_uri = url_for('auth.github_callback', _external=True)
    token_data = oauth_service.exchange_code_for_token(code, redirect_uri)
    
    if 'error' in token_data:
        flash(f'OAuth error: {token_data["error"]}', 'error')
        return redirect(url_for('auth.login'))
    
    access_token = token_data.get('access_token')
    if not access_token:
        flash('No access token received', 'error')
        return redirect(url_for('auth.login'))
    
    # Get user info from GitHub
    user_info = oauth_service.get_user_info(access_token)
    
    if 'error' in user_info:
        flash(f'Error getting user info: {user_info["error"]}', 'error')
        return redirect(url_for('auth.login'))
    
    # Create or update user
    user = user_service.create_or_update_from_oauth('github', user_info)
    
    # Save OAuth token
    user_service.save_oauth_token(user.id, 'github', access_token)
    
    # Login user — nouvelle session sur élévation de privilège, comme sur le
    # chemin mot de passe : sinon un identifiant de session planté par un
    # tiers avant l'authentification reste valide après.
    _reset_session_on_login(user.id)

    return redirect(url_for('main.index'))


@auth_bp.route('/logout')
@login_required
def logout():
    """Logout user"""
    session.pop('user_id', None)
    return redirect(url_for('auth.login'))


@auth_bp.route('/profile')
@login_required
def profile():
    """User profile page"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    user_service = current_app.extensions['user_service']
    g.current_user = user_service.get_user_by_id(session['user_id'])
    
    if not g.current_user:
        session.pop('user_id', None)
        return redirect(url_for('auth.login'))
    
    return render_template('profile.html')


@auth_bp.route('/api/profile/update', methods=['POST'])
@login_required
def update_profile():
    """Update user profile"""
    if 'user_id' not in session:
        return {'success': False, 'error': 'Not authenticated'}, 401
    
    user_service = current_app.extensions['user_service']
    user = user_service.get_user_by_id(session['user_id'])
    
    if not user:
        return {'success': False, 'error': 'User not found'}, 404
    
    # Get form data
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    email = request.form.get('email')
    
    # Update user
    user_service.update_user(
        user.username,
        first_name=first_name,
        last_name=last_name,
        email=email
    )
    
    flash('Profile updated successfully', 'success')
    return redirect(url_for('auth.profile'))


@auth_bp.route('/api/profile/avatar', methods=['POST'])
@login_required
def upload_avatar():
    """Upload user avatar"""
    if 'user_id' not in session:
        return {'success': False, 'error': 'Not authenticated'}, 401
    
    user_service = current_app.extensions['user_service']
    user = user_service.get_user_by_id(session['user_id'])
    
    if not user:
        return {'success': False, 'error': 'User not found'}, 404
    
    if 'avatar' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('auth.profile'))
    
    file = request.files['avatar']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('auth.profile'))
    
    # Upload avatar
    avatar_url = user_service.upload_avatar(user.username, file)
    
    flash('Avatar updated successfully', 'success')
    return redirect(url_for('auth.profile'))


@auth_bp.route('/api/profile/ssh-key', methods=['POST'])
@login_required
def update_ssh_key():
    """Update SSH public key"""
    if 'user_id' not in session:
        return {'success': False, 'error': 'Not authenticated'}, 401
    
    user_service = current_app.extensions['user_service']
    user = user_service.get_user_by_id(session['user_id'])
    
    if not user:
        return {'success': False, 'error': 'User not found'}, 404
    
    ssh_key = request.json.get('ssh_key', '').strip()
    
    # Update SSH key
    user_service.update_user(user.username, ssh_public_key=ssh_key)
    
    return {'success': True, 'message': 'SSH key updated'}






