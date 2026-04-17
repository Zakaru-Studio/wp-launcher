#!/usr/bin/env python3
"""
Routes pour la gestion des projets WordPress - Core (Liste et Statut)
"""

import os
from flask import Blueprint, jsonify, current_app
from app.models.project import Project
from app.config.docker_config import DockerConfig
from app.middleware.auth_middleware import login_required, admin_required

projects_bp = Blueprint('projects', __name__)

# Configuration des constantes
PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'


@projects_bp.route('/projects')
@login_required
def list_projects():
    """Liste tous les projets disponibles"""
    project_service = current_app.extensions.get('project_service')
    
    if project_service:
        projects = project_service.get_project_list()
        return jsonify(projects)
    
    # Fallback si le service n'est pas disponible
    projects = []
    
    if not os.path.exists(PROJECTS_FOLDER):
        return jsonify([])
    
    for project_name in os.listdir(PROJECTS_FOLDER):
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        
        if not os.path.isdir(project_path):
            continue
            
        # Ignorer les dossiers marqués comme supprimés
        deleted_marker = os.path.join(project_path, '.DELETED_PROJECT')
        if os.path.exists(deleted_marker):
            continue
        
        projects.append(project_name)
    
    return jsonify(projects)


@projects_bp.route('/projects_with_status')
@login_required
def list_projects_with_status():
    """Liste les projets avec leurs informations complètes"""
    projects = []
    
    if not os.path.exists(PROJECTS_FOLDER):
        return jsonify([])
    
    # Obtenir les services depuis l'application
    docker_service = current_app.extensions.get('docker')
    
    for project_name in os.listdir(PROJECTS_FOLDER):
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        
        if not os.path.isdir(project_path):
            continue
            
        # Ignorer les dossiers marqués comme supprimés
        deleted_marker = os.path.join(project_path, '.DELETED_PROJECT')
        if os.path.exists(deleted_marker):
            continue
        
        # Vérifier si le dossier est accessible (permissions)
        if not os.access(project_path, os.R_OK):
            continue
        
        # Utiliser la classe Project pour récupérer les informations
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        
        # Statut du conteneur
        container_status = 'stopped'
        if docker_service:
            container_status = docker_service.get_container_status(project_name)
        
        # Créer les URLs du projet
        ports = {}
        
        # Ports WordPress uniquement pour les projets WordPress
        if project.project_type == 'wordpress' and project.port:
            ports['wordpress'] = project.port
            
        if project.pma_port:
            ports['phpmyadmin'] = project.pma_port
        if project.mailpit_port:
            ports['mailpit'] = project.mailpit_port
        if project.has_nextjs and project.nextjs_port:
            ports['nextjs'] = project.nextjs_port
        
        # Ajouter les ports des projets Next.js purs
        if project.api_port:
            ports['api'] = project.api_port
        if project.mysql_port:
            ports['mysql'] = project.mysql_port
        if project.mongodb_port:
            ports['mongodb'] = project.mongodb_port
        if project.mongo_express_port:
            ports['mongo_express'] = project.mongo_express_port
        
        urls = _get_project_urls(project_name, ports)
        
        project_info = {
            'name': project_name,
            'port': project.port,
            'container_status': container_status,
            'has_nextjs': project.has_nextjs,
            'type': project.project_type,
            'valid': project.is_valid,
            'status': 'active' if container_status == 'active' else 'inactive',
            'pma_port': project.pma_port,
            'mailpit_port': project.mailpit_port,
            'smtp_port': project.smtp_port,
            'nextjs_port': project.nextjs_port if project.has_nextjs else None,
            'nextjs_enabled': project.has_nextjs,
            'api_port': project.api_port,
            'mysql_port': project.mysql_port,
            'mongodb_port': project.mongodb_port,
            'mongo_express_port': project.mongo_express_port,
            'urls': urls
        }
        
        projects.append(project_info)
    
    return jsonify({'projects': projects})


@projects_bp.route('/project_status/<project_name>')
@login_required
def check_project_status(project_name):
    """Vérifie le statut d'un projet"""
    project_service = current_app.extensions.get('project_service')
    
    if project_service:
        result = project_service.get_project_status(project_name)
        if result['success']:
            return jsonify({
                'success': True,
                'status': 'active' if result['status'] == 'active' else 'inactive',
                'container_status': result['status'],
                'project_name': project_name
            })
        else:
            return jsonify(result)
    
    # Fallback si le service n'est pas disponible
    try:
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier le statut des conteneurs
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            container_status = docker_service.get_container_status(project_name)
            return jsonify({
                'success': True,
                'status': 'active' if container_status == 'active' else 'inactive',
                'container_status': container_status,
                'project_name': project_name
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Service Docker non disponible'
            })
        
    except Exception as e:
        print(f"❌ Erreur lors de la vérification du statut: {e}")
        return jsonify({
            'success': False,
            'message': f'Erreur lors de la vérification: {str(e)}'
        })


def _get_project_urls(project_name, ports):
    """Génère les URLs du projet"""
    urls = {}
    
    # URLs WordPress uniquement pour les projets WordPress
    if 'wordpress' in ports:
        urls['wordpress'] = f'http://{DockerConfig.LOCAL_IP}:{ports["wordpress"]}'
        urls['wordpress_admin'] = f'http://{DockerConfig.LOCAL_IP}:{ports["wordpress"]}/wp-admin'
    
    if 'phpmyadmin' in ports:
        urls['phpmyadmin'] = f'http://{DockerConfig.LOCAL_IP}:{ports["phpmyadmin"]}'
    
    if 'mailpit' in ports:
        urls['mailpit'] = f'http://{DockerConfig.LOCAL_IP}:{ports["mailpit"]}'
    
    if 'nextjs' in ports:
        urls['client'] = f'http://{DockerConfig.LOCAL_IP}:{ports["nextjs"]}'
        urls['nextjs'] = f'http://{DockerConfig.LOCAL_IP}:{ports["nextjs"]}'  # Garde compatibilité
    
    if 'api' in ports:
        urls['api'] = f'http://{DockerConfig.LOCAL_IP}:{ports["api"]}'
        urls['api_health'] = f'http://{DockerConfig.LOCAL_IP}:{ports["api"]}/health'
        urls['api_docs'] = f'http://{DockerConfig.LOCAL_IP}:{ports["api"]}/api'
    
    if 'mongodb' in ports:
        urls['mongodb'] = f'mongodb://{DockerConfig.LOCAL_IP}:{ports["mongodb"]}'
    
    if 'mysql' in ports:
        urls['mysql'] = f'mysql://{DockerConfig.LOCAL_IP}:{ports["mysql"]}'
    
    if 'mongo_express' in ports:
        urls['mongo_express'] = f'http://{DockerConfig.LOCAL_IP}:{ports["mongo_express"]}'
    
    return urls


