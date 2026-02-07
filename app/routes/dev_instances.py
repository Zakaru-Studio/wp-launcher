"""
Dev Instances API routes
"""
import os
import time
from flask import Blueprint, request, jsonify, g, current_app
from app.middleware.auth_middleware import login_required, admin_required


dev_instances_bp = Blueprint('dev_instances', __name__, url_prefix='/api/dev-instances')


@dev_instances_bp.route('/create', methods=['POST'])
@login_required
def create_instance():
    """Create a new dev instance"""
    from app.utils.logger import wp_logger
    
    data = request.json
    parent_project = data.get('parent_project')
    
    if not parent_project:
        return jsonify({'success': False, 'error': 'Projet parent manquant'}), 400
    
    # Déterminer le propriétaire
    if g.current_user.role == 'admin' and 'owner_username' in data:
        owner_username = data['owner_username']
    else:
        owner_username = g.current_user.username
    
    # Vérifier la limite d'1 instance par projet pour les devs
    dev_instance_service = current_app.extensions['dev_instance_service']
    existing = dev_instance_service.get_instances_by_parent(parent_project)
    user_has_instance = any(i.owner_username == owner_username for i in existing)
    
    if user_has_instance and g.current_user.role != 'admin':
        error_msg = 'Vous avez déjà une instance pour ce projet'
        wp_logger.log_system_info(f"Instance creation blocked: {error_msg} (user: {owner_username})")
        return jsonify({
            'success': False, 
            'error': error_msg
        }), 400
    
    # Émettre un événement pour créer une tâche côté client
    socketio = current_app.extensions.get('socketio')
    task_id = f"create_instance_{parent_project}_{owner_username}_{int(time.time() * 1000)}"
    
    if socketio:
        socketio.emit('task_start', {
            'task_id': task_id,
            'task_name': f'Création instance dev',
            'task_type': 'create_instance',
            'project_name': parent_project,
            'owner': owner_username,
            'status': 'running',
            'message': f'Création de l\'instance pour {owner_username}...'
        })
    
    wp_logger.log_system_info(f"Creating instance for {owner_username} on project {parent_project}")
    
    try:
        instance = dev_instance_service.create_dev_instance(
            parent_project, 
            owner_username,
            socketio=socketio
        )
        
        wp_logger.log_system_info(f"Instance created successfully: {instance.name}")
        
        # Émettre la completion de la tâche
        if socketio:
            socketio.emit('task_complete', {
                'task_id': task_id,
                'success': True,
                'message': f'Instance créée avec succès pour {owner_username}',
                'instance': instance.to_dict()
            })
        
        return jsonify({
            'success': True, 
            'instance': instance.to_dict()
        })
    except Exception as e:
        error_msg = str(e)
        wp_logger.log_system_info(f"ERROR creating instance: {error_msg}")
        
        # Émettre l'échec de la tâche
        if socketio:
            socketio.emit('task_complete', {
                'task_id': task_id,
                'success': False,
                'message': f'Erreur lors de la création: {error_msg}'
            })
        
        return jsonify({'success': False, 'error': error_msg}), 500


@dev_instances_bp.route('/list', methods=['GET'])
@login_required
def list_user_instances():
    """List user's instances"""
    dev_instance_service = current_app.extensions['dev_instance_service']
    instances = dev_instance_service.get_user_instances(g.current_user.username)
    return jsonify({
        'success': True,
        'instances': [i.to_dict() for i in instances]
    })


@dev_instances_bp.route('/by-project/<project_name>', methods=['GET'])
@login_required
def list_by_project(project_name):
    """List instances for a project"""
    dev_instance_service = current_app.extensions['dev_instance_service']
    instances = dev_instance_service.get_instances_by_parent(project_name)
    
    # Filter by user if not admin
    if g.current_user.role != 'admin':
        instances = [i for i in instances if i.owner_username == g.current_user.username]
    
    return jsonify({
        'success': True,
        'instances': [i.to_dict() for i in instances]
    })


@dev_instances_bp.route('/<instance_name>', methods=['GET'])
@login_required
def get_instance(instance_name):
    """Get instance details"""
    dev_instance_service = current_app.extensions['dev_instance_service']
    instance = dev_instance_service.get_instance_by_name(instance_name)
    
    if not instance:
        return jsonify({'success': False, 'error': 'Instance non trouvée'}), 404
    
    # Check ownership
    if instance.owner_username != g.current_user.username and g.current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'Accès refusé'}), 403
    
    return jsonify({
        'success': True,
        'instance': instance.to_dict()
    })


@dev_instances_bp.route('/<instance_name>/status', methods=['GET'])
@login_required
def get_instance_status(instance_name):
    """Get instance status (running/stopped)"""
    from app.utils.logger import wp_logger
    try:
        # Obtenir le service Docker depuis les extensions (clé 'docker', pas 'docker_service')
        if 'docker' not in current_app.extensions:
            wp_logger.log_system_info(f"Error: docker service not found in extensions")
            return jsonify({'success': False, 'error': 'Service Docker non disponible'}), 500
            
        docker_service = current_app.extensions['docker']
        container_name = f"{instance_name}_wordpress"
        
        wp_logger.log_system_info(f"Checking status for container: {container_name}")
        
        # Utiliser la nouvelle méthode au lieu de docker_service.client
        status = docker_service.get_individual_container_status(container_name)
        
        wp_logger.log_system_info(f"Container {container_name} status: {status}")
        
        return jsonify({
            'success': True,
            'status': status,
            'instance_name': instance_name
        })
    except Exception as e:
        wp_logger.log_system_info(f"Error in get_instance_status: {str(e)}")
        import traceback
        wp_logger.log_system_info(f"Traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@dev_instances_bp.route('/<instance_name>/start', methods=['POST'])
@login_required
def start_instance(instance_name):
    """Start an instance"""
    try:
        from app.utils.logger import wp_logger
        import subprocess
        
        wp_logger.log_system_info(f"Starting instance: {instance_name}")
        
        # Get instance from DB
        dev_instance_service = current_app.extensions['dev_instance_service']
        instance = dev_instance_service.get_instance_by_name(instance_name)
        
        if not instance:
            return jsonify({'success': False, 'error': 'Instance non trouvée'}), 404
        
        # Check ownership
        if instance.owner_username != g.current_user.username and g.current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Accès refusé'}), 403
        
        # Get instance path
        instance_path = os.path.join('projets', instance.parent_project, '.dev-instances', instance.slug)
        
        if not os.path.exists(instance_path):
            return jsonify({'success': False, 'error': 'Dossier d\'instance non trouvé'}), 404
        
        # Start container
        result = subprocess.run(
            ['docker-compose', 'up', '-d'],
            cwd=instance_path,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            wp_logger.log_system_info(f"Instance {instance_name} started successfully")
            return jsonify({'success': True, 'message': 'Instance démarrée'})
        else:
            wp_logger.log_system_info(f"Failed to start instance {instance_name}: {result.stderr}")
            return jsonify({'success': False, 'error': result.stderr}), 500
            
    except Exception as e:
        from app.utils.logger import wp_logger
        wp_logger.log_system_info(f"Error starting instance {instance_name}: {str(e)}")
        import traceback
        wp_logger.log_system_info(f"Traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@dev_instances_bp.route('/<instance_name>/stop', methods=['POST'])
@login_required
def stop_instance(instance_name):
    """Stop an instance"""
    try:
        from app.utils.logger import wp_logger
        import subprocess
        
        wp_logger.log_system_info(f"Stopping instance: {instance_name}")
        
        # Get instance from DB
        dev_instance_service = current_app.extensions['dev_instance_service']
        instance = dev_instance_service.get_instance_by_name(instance_name)
        
        if not instance:
            return jsonify({'success': False, 'error': 'Instance non trouvée'}), 404
        
        # Check ownership
        if instance.owner_username != g.current_user.username and g.current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Accès refusé'}), 403
        
        # Get instance path
        instance_path = os.path.join('projets', instance.parent_project, '.dev-instances', instance.slug)
        
        if not os.path.exists(instance_path):
            return jsonify({'success': False, 'error': 'Dossier d\'instance non trouvé'}), 404
        
        # Stop container
        result = subprocess.run(
            ['docker-compose', 'down'],
            cwd=instance_path,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            wp_logger.log_system_info(f"Instance {instance_name} stopped successfully")
            return jsonify({'success': True, 'message': 'Instance arrêtée'})
        else:
            wp_logger.log_system_info(f"Failed to stop instance {instance_name}: {result.stderr}")
            return jsonify({'success': False, 'error': result.stderr}), 500
            
    except Exception as e:
        from app.utils.logger import wp_logger
        wp_logger.log_system_info(f"Error stopping instance {instance_name}: {str(e)}")
        import traceback
        wp_logger.log_system_info(f"Traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@dev_instances_bp.route('/<instance_name>', methods=['DELETE'])
@login_required
def delete_instance(instance_name):
    """Delete an instance"""
    from app.utils.logger import wp_logger
    
    is_admin = g.current_user.role == 'admin'
    
    # Émettre un événement pour créer une tâche côté client
    socketio = current_app.extensions.get('socketio')
    task_id = f"delete_instance_{instance_name}_{int(time.time() * 1000)}"
    
    if socketio:
        socketio.emit('task_start', {
            'task_id': task_id,
            'task_name': 'Suppression instance',
            'task_type': 'delete_instance',
            'project_name': instance_name,
            'status': 'running',
            'message': f'Suppression de l\'instance {instance_name}...'
        })
    
    try:
        wp_logger.log_system_info(f"Attempting to delete instance: {instance_name} by user: {g.current_user.username} (admin: {is_admin})")
        
        if 'dev_instance_service' not in current_app.extensions:
            error_msg = 'Service d\'instances non disponible'
            wp_logger.log_system_info(f"Error: dev_instance_service not found in extensions")
            
            if socketio:
                socketio.emit('task_complete', {
                    'task_id': task_id,
                    'success': False,
                    'message': f'Erreur: {error_msg}'
                })
            
            return jsonify({'success': False, 'error': error_msg}), 500
        
        dev_instance_service = current_app.extensions['dev_instance_service']
        # Passer le flag is_admin au service
        dev_instance_service.delete_instance(instance_name, g.current_user.username, is_admin=is_admin)
        
        wp_logger.log_system_info(f"Instance {instance_name} deleted successfully")
        
        # Émettre la completion de la tâche
        if socketio:
            socketio.emit('task_complete', {
                'task_id': task_id,
                'success': True,
                'message': f'Instance {instance_name} supprimée avec succès'
            })
        
        return jsonify({'success': True, 'message': 'Instance supprimée avec succès'})
    except Exception as e:
        error_msg = str(e)
        wp_logger.log_system_info(f"Error deleting instance {instance_name}: {error_msg}")
        import traceback
        wp_logger.log_system_info(f"Traceback: {traceback.format_exc()}")
        
        # Émettre l'échec de la tâche
        if socketio:
            socketio.emit('task_complete', {
                'task_id': task_id,
                'success': False,
                'message': f'Erreur lors de la suppression: {error_msg}'
            })
        
        return jsonify({'success': False, 'error': error_msg}), 500

