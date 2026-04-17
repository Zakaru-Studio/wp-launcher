"""
Main routes with optional authentication support
"""
from flask import Blueprint, render_template, session, redirect, url_for, g, current_app, request

main_bp = Blueprint('main', __name__)


@main_bp.before_request
def load_user():
    """Load user before each request (optional auth mode)"""
    g.current_user = None
    
    # Si système auth activé, charger l'utilisateur
    if hasattr(current_app, 'extensions') and 'user_service' in current_app.extensions:
        if 'user_id' in session:
            user_service = current_app.extensions['user_service']
            g.current_user = user_service.get_user_by_id(session['user_id'])


@main_bp.route('/')
def index():
    """Page principale"""
    # Si auth activé et user non connecté, rediriger vers login
    if hasattr(current_app, 'extensions') and 'user_service' in current_app.extensions:
        if not g.current_user:
            return redirect(url_for('auth.login'))

    return render_template('index.html')


@main_bp.route('/set-locale', methods=['POST'])
def set_locale():
    """Persist user's preferred locale in the session.

    CSRF is enforced globally via Flask-WTF. Only whitelisted locales are stored.
    """
    locale = request.form.get('locale', 'en')
    supported = current_app.config.get('BABEL_SUPPORTED_LOCALES', ['en', 'fr'])
    if locale in supported:
        session['locale'] = locale
    return redirect(request.referrer or url_for('main.index'))
