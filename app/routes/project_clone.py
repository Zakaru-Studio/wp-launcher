#!/usr/bin/env python3
"""
Routes pour le clonage de projets
"""

from flask import Blueprint, request, jsonify, current_app
from app.models.project import Project
from app.config.docker_config import DockerConfig
from app.middleware.auth_middleware import login_required, admin_required

project_clone_bp = Blueprint('project_clone', __name__)

# Configuration des constantes
PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'


@project_clone_bp.route('/clone/<source_name>', methods=['POST'])
@admin_required
def clone_project(source_name):
    """
    Clone un projet existant
    
    Body JSON:
        target_name: str - Nom du projet cible
        clone_database: bool - Cloner la base de données (défaut: true)
        clone_uploads: bool - Cloner les uploads (défaut: false)
    """
    try:
        # Vérifier que le projet source existe
        source_project = Project(source_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not source_project.exists:
            return jsonify({
                'success': False,
                'message': 'Projet source non trouvé'
            })
        
        # Récupérer le service de clonage
        clone_service = current_app.extensions.get('clone_service')
        if not clone_service:
            return jsonify({
                'success': False,
                'message': 'Service de clonage non disponible'
            })
        
        # Récupérer les paramètres
        data = request.get_json()
        target_name = data.get('target_name', '').strip()
        
        if not target_name:
            return jsonify({
                'success': False,
                'message': 'Nom du projet cible requis'
            })
        
        options = {
            'clone_database': data.get('clone_database', True),
            'clone_uploads': data.get('clone_uploads', False)
        }
        
        print(f"🔄 [CLONE API] Début du clonage: {source_name} → {target_name}")
        print(f"📋 [CLONE API] Options: DB={options['clone_database']}, Uploads={options['clone_uploads']}")
        
        # Effectuer le clonage
        result = clone_service.clone_project(source_name, target_name, options)
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ [CLONE API] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@project_clone_bp.route('/validate-name/<name>', methods=['GET'])
@login_required
def validate_clone_name(name):
    """Valide qu'un nom de projet est disponible"""
    try:
        from app.utils.project_utils import secure_project_name
        
        # Sécuriser le nom
        safe_name = secure_project_name(name)
        
        # Vérifier si le projet existe
        project = Project(safe_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        
        if project.exists:
            return jsonify({
                'valid': False,
                'message': f'Le projet "{safe_name}" existe déjà',
                'safe_name': safe_name
            })
        
        return jsonify({
            'valid': True,
            'message': 'Nom disponible',
            'safe_name': safe_name
        })
        
    except Exception as e:
        return jsonify({
            'valid': False,
            'message': f'Erreur: {str(e)}'
        })


