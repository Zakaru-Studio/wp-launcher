"""
Admin routes for user and instance management
"""
from flask import Blueprint, render_template, request, jsonify, current_app
from app.middleware.auth_middleware import admin_required


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/users', methods=['GET'])
@admin_required
def users_page():
    """Admin page for user management"""
    user_service = current_app.extensions['user_service']
    users = user_service.list_users()
    return render_template('admin_users.html', users=users)


@admin_bp.route('/api/users/create', methods=['POST'])
@admin_required
def create_user():
    """Create a new user"""
    data = request.json
    user_service = current_app.extensions['user_service']
    
    try:
        user = user_service.create_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            role=data.get('role', 'developer')
        )
        return jsonify({'success': True, 'user': user.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/users/<username>', methods=['DELETE'])
@admin_required
def delete_user(username):
    """Delete a user"""
    user_service = current_app.extensions['user_service']
    user_service.delete_user(username)
    return jsonify({'success': True})


@admin_bp.route('/api/users/<username>/role', methods=['PUT'])
@admin_required
def update_role(username):
    """Update user role"""
    data = request.json
    user_service = current_app.extensions['user_service']
    user_service.update_user(username, role=data['role'])
    return jsonify({'success': True})


@admin_bp.route('/api/users/list', methods=['GET'])
@admin_required
def list_users_api():
    """Liste des utilisateurs pour les selects"""
    user_service = current_app.extensions['user_service']
    users = user_service.list_users()
    return jsonify({
        'success': True,
        'users': [{'username': u.username, 'email': u.email, 'role': u.role} for u in users]
    })


# Route /instances supprimée - la gestion se fait maintenant via le dropdown des projets

