"""
Authentication middleware with backward compatibility
"""
from functools import wraps
from flask import session, redirect, url_for, g, current_app


def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Mode compatibilité: si pas de système d'auth, passer
        if not hasattr(current_app, 'extensions') or 'user_service' not in current_app.extensions:
            return f(*args, **kwargs)
        
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
    """Decorator to require admin role for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Mode compatibilité: si pas de système d'auth, passer
        if not hasattr(current_app, 'extensions') or 'user_service' not in current_app.extensions:
            return f(*args, **kwargs)
        
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        
        user_service = current_app.extensions['user_service']
        g.current_user = user_service.get_user_by_id(session['user_id'])
        
        if not g.current_user or g.current_user.role != 'admin':
            return redirect(url_for('main.index'))
        
        return f(*args, **kwargs)
    return decorated_function






