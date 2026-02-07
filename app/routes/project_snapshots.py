#!/usr/bin/env python3
"""
Routes pour la gestion des snapshots de projets
"""

from flask import Blueprint, request, jsonify, current_app
from app.models.project import Project
from app.config.docker_config import DockerConfig

project_snapshots_bp = Blueprint('project_snapshots', __name__)

# Configuration des constantes
PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'


@project_snapshots_bp.route('/snapshots/create/<project_name>', methods=['POST'])
def create_snapshot(project_name):
    """
    Crée un snapshot d'un projet
    
    Body JSON:
        description: str - Description optionnelle du snapshot
    """
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({
                'success': False,
                'message': 'Projet non trouvé'
            })
        
        # Récupérer le service de snapshots
        snapshot_service = current_app.extensions.get('snapshot_service')
        if not snapshot_service:
            return jsonify({
                'success': False,
                'message': 'Service de snapshots non disponible'
            })
        
        # Récupérer la description et les options
        data = request.get_json() or {}
        description = data.get('description', '')
        options = data.get('options', {
            'include_themes': True,
            'include_plugins': True,
            'include_languages': True,
            'include_uploads': False
        })
        
        print(f"📸 [SNAPSHOT API] Création pour {project_name} avec options: {options}")
        
        # Créer le snapshot
        result = snapshot_service.create_snapshot(project_name, description, options)
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ [SNAPSHOT API] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@project_snapshots_bp.route('/snapshots/list/<project_name>', methods=['GET'])
def list_snapshots(project_name):
    """Liste tous les snapshots d'un projet"""
    try:
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({
                'success': False,
                'message': 'Projet non trouvé'
            })
        
        snapshot_service = current_app.extensions.get('snapshot_service')
        if not snapshot_service:
            return jsonify({
                'success': False,
                'message': 'Service de snapshots non disponible'
            })
        
        result = snapshot_service.list_snapshots(project_name)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@project_snapshots_bp.route('/snapshots/info/<snapshot_id>', methods=['GET'])
def get_snapshot_info(snapshot_id):
    """Récupère les informations détaillées d'un snapshot"""
    try:
        snapshot_service = current_app.extensions.get('snapshot_service')
        if not snapshot_service:
            return jsonify({
                'success': False,
                'message': 'Service de snapshots non disponible'
            })
        
        result = snapshot_service.get_snapshot_info(snapshot_id)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@project_snapshots_bp.route('/snapshots/rollback/<snapshot_id>', methods=['POST'])
def rollback_snapshot(snapshot_id):
    """Restaure un snapshot"""
    try:
        snapshot_service = current_app.extensions.get('snapshot_service')
        if not snapshot_service:
            return jsonify({
                'success': False,
                'message': 'Service de snapshots non disponible'
            })
        
        print(f"🔄 [SNAPSHOT API] Rollback de {snapshot_id}")
        
        result = snapshot_service.rollback_snapshot(snapshot_id)
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ [SNAPSHOT API] Erreur rollback: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@project_snapshots_bp.route('/snapshots/preview/<project_name>', methods=['GET'])
def preview_snapshot(project_name):
    """Prévisualise les fichiers qui seront inclus dans un snapshot"""
    try:
        import os
        
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({
                'success': False,
                'message': 'Projet non trouvé'
            })
        
        # Récupérer le service Git
        git_service = current_app.extensions.get('git_service')
        
        result = {
            'success': True,
            'project_name': project_name,
            'git_directories': [],
            'themes': [],
            'plugins': [],
            'config_files': [],
            'has_database': True
        }
        
        # 1. Détecter les dossiers Git (optionnel)
        if git_service:
            git_directories = git_service.detect_git_directories(project.path)
            
            # Récupérer le statut de chaque dossier Git
            for git_dir_info in git_directories:
                status = git_service.get_git_status(git_dir_info['path'])
                if status:
                    result['git_directories'].append({
                        'path': git_dir_info['relative_path'],
                        'commit': status['commit'],
                        'branch': status['branch'],
                        'status': status['status']
                    })
        
        # 2. Lister les thèmes WordPress
        themes_path = os.path.join(project.path, 'wp-content', 'themes')
        if os.path.exists(themes_path):
            result['themes'] = [d for d in os.listdir(themes_path) 
                               if os.path.isdir(os.path.join(themes_path, d)) and not d.startswith('.')]
        
        # 3. Lister les plugins WordPress
        plugins_path = os.path.join(project.path, 'wp-content', 'plugins')
        if os.path.exists(plugins_path):
            result['plugins'] = [d for d in os.listdir(plugins_path) 
                                if os.path.isdir(os.path.join(plugins_path, d)) and not d.startswith('.')]
        
        # 4. Lister les fichiers de configuration présents
        config_files = ['wp-config.php', 'docker-compose.yml', '.env', 'php.ini', 'mysql.cnf']
        for config_file in config_files:
            if os.path.exists(os.path.join(project.path, config_file)):
                result['config_files'].append(config_file)
        
        # 5. Vérifier le dossier uploads
        uploads_path = os.path.join(project.path, 'wp-content', 'uploads')
        result['uploads_status'] = 'unavailable'
        result['uploads_size_mb'] = 0
        
        if os.path.exists(uploads_path):
            # Calculer la taille des uploads (en excluant index.php de sécurité)
            uploads_size = 0
            file_count = 0
            for dirpath, dirnames, filenames in os.walk(uploads_path):
                for filename in filenames:
                    if filename != 'index.php':  # Ignorer le fichier de sécurité
                        file_path = os.path.join(dirpath, filename)
                        uploads_size += os.path.getsize(file_path)
                        file_count += 1
            
            uploads_size_mb = uploads_size / (1024 * 1024)
            result['uploads_size_mb'] = round(uploads_size_mb, 2)
            
            if file_count == 0:
                result['uploads_status'] = 'empty'
            elif uploads_size_mb < 100:
                result['uploads_status'] = 'available'
            else:
                result['uploads_status'] = 'too_large'
        
        return jsonify(result)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@project_snapshots_bp.route('/snapshots/delete/<snapshot_id>', methods=['DELETE'])
def delete_snapshot(snapshot_id):
    """Supprime un snapshot"""
    try:
        snapshot_service = current_app.extensions.get('snapshot_service')
        if not snapshot_service:
            return jsonify({
                'success': False,
                'message': 'Service de snapshots non disponible'
            })
        
        result = snapshot_service.delete_snapshot(snapshot_id)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })

