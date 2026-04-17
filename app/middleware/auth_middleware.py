"""
Authentication middleware.

IMPORTANT: no silent bypass. If user_service is not initialized, the request
is rejected — that's a misconfiguration, not a reason to grant access.
"""
from functools import wraps
from flask import session, redirect, url_for, g, current_app, abort


def _ensure_auth_configured():
    """Abort with 500 if user_service is not registered. Never let requests
    through unauthenticated because of an init failure — that turns a broken
    deploy into a full auth bypass."""
    if not hasattr(current_app, 'extensions') or 'user_service' not in current_app.extensions:
        current_app.logger.error(
            "auth_middleware: user_service extension missing — refusing request"
        )
        abort(500, description="Authentication system not initialized")


def login_required(f):
    """Decorator to require login for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        _ensure_auth_configured()

        if 'user_id' not in session:
            return redirect(url_for('auth.login'))

        user_service = current_app.extensions['user_service']
        g.current_user = user_service.get_user_by_id(session['user_id'])

        if not g.current_user:
            session.pop('user_id', None)
            return redirect(url_for('auth.login'))

        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator to require admin role for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        _ensure_auth_configured()

        if 'user_id' not in session:
            return redirect(url_for('auth.login'))

        user_service = current_app.extensions['user_service']
        g.current_user = user_service.get_user_by_id(session['user_id'])

        if not g.current_user or g.current_user.role != 'admin':
            return redirect(url_for('main.index'))

        return f(*args, **kwargs)
    return decorated_function
