#!/usr/bin/env python3
"""
Routes pour WP-CLI - Exécution de commandes WordPress en ligne de commande
"""

from flask import Blueprint, request, jsonify, current_app
from app.models.project import Project
from app.config.docker_config import DockerConfig

project_wpcli_bp = Blueprint('project_wpcli', __name__)

# Configuration des constantes
PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'


def is_dev_instance(project_name):
    """Vérifie si le nom correspond à une instance dev"""
    return '_dev_' in project_name


def validate_project_or_instance(project_name):
    """
    Valide qu'un projet ou une instance existe
    Retourne (success, error_message)
    """
    if is_dev_instance(project_name):
        # Pour les instances dev, on ne vérifie pas l'existence dans projets/
        # Le service WP-CLI gère directement le conteneur
        return True, None
    
    # Pour les projets normaux, vérifier l'existence
    project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
    if not project.exists:
        return False, 'Projet non trouvé'
    
    return True, None


@project_wpcli_bp.route('/wpcli/execute/<project_name>', methods=['POST'])
def execute_wpcli(project_name):
    """
    Exécute une commande WP-CLI dans le conteneur WordPress du projet
    
    Body JSON:
        command: str - Commande WP-CLI (ex: "plugin list")
        args: list - Arguments supplémentaires optionnels
    """
    try:
        # Valider le projet ou l'instance
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        # Récupérer le service WP-CLI
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        # Récupérer la commande depuis le body
        data = request.get_json()
        command = data.get('command', '').strip()
        args = data.get('args', [])
        
        if not command:
            return jsonify({
                'success': False,
                'error': 'Commande vide'
            })
        
        print(f"🔧 [WP-CLI API] Exécution pour {project_name}: {command}")
        
        # Exécuter la commande
        result = wpcli_service.execute_command(project_name, command, args)
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ [WP-CLI API] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/templates', methods=['GET'])
def get_command_templates():
    """Retourne les templates de commandes WP-CLI disponibles"""
    try:
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        result = wpcli_service.get_command_templates()
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/allowed-commands', methods=['GET'])
def get_allowed_commands():
    """Retourne la liste des commandes autorisées"""
    try:
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        commands = wpcli_service.get_allowed_commands()
        return jsonify({
            'success': True,
            'commands': commands
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/plugins/<project_name>', methods=['GET'])
def list_plugins(project_name):
    """Liste tous les plugins installés dans un projet"""
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        result = wpcli_service.get_plugin_list(project_name)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/plugins/<project_name>/install', methods=['POST'])
def install_plugin(project_name):
    """
    Installe un plugin
    
    Body JSON:
        plugin: str - Slug du plugin (ex: "contact-form-7")
        activate: bool - Activer après installation (défaut: true)
    """
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        data = request.get_json()
        plugin = data.get('plugin', '').strip()
        activate = data.get('activate', True)
        
        if not plugin:
            return jsonify({
                'success': False,
                'error': 'Slug du plugin requis'
            })
        
        result = wpcli_service.install_plugin(project_name, plugin, activate)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/plugins/<project_name>/<action>', methods=['POST'])
def manage_plugin(project_name, action):
    """
    Gère un plugin (activate, deactivate, delete)
    
    Body JSON:
        plugin: str - Slug du plugin
    """
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        data = request.get_json()
        plugin = data.get('plugin', '').strip()
        
        if not plugin:
            return jsonify({
                'success': False,
                'error': 'Slug du plugin requis'
            })
        
        if action == 'activate':
            result = wpcli_service.activate_plugin(project_name, plugin)
        elif action == 'deactivate':
            result = wpcli_service.deactivate_plugin(project_name, plugin)
        elif action == 'delete':
            result = wpcli_service.delete_plugin(project_name, plugin)
        else:
            return jsonify({
                'success': False,
                'error': f'Action non reconnue: {action}'
            })
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/themes/<project_name>', methods=['GET'])
def list_themes(project_name):
    """Liste tous les thèmes installés dans un projet"""
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        result = wpcli_service.get_theme_list(project_name)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/users/<project_name>', methods=['GET'])
def list_users(project_name):
    """Liste tous les utilisateurs d'un projet"""
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        result = wpcli_service.get_user_list(project_name)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/users/<project_name>/create', methods=['POST'])
def create_user(project_name):
    """
    Crée un utilisateur WordPress
    
    Body JSON:
        username: str - Nom d'utilisateur
        email: str - Email
        role: str - Rôle (administrator, editor, author, contributor, subscriber)
    """
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        data = request.get_json()
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        role = data.get('role', 'subscriber').strip()
        
        if not username or not email:
            return jsonify({
                'success': False,
                'error': 'Username et email requis'
            })
        
        result = wpcli_service.create_user(project_name, username, email, role)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/search-replace/<project_name>', methods=['POST'])
def search_replace(project_name):
    """
    Effectue un search-replace dans la base de données
    
    Body JSON:
        old: str - Ancienne valeur
        new: str - Nouvelle valeur
        dry_run: bool - Mode test (défaut: true)
    """
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        data = request.get_json()
        old = data.get('old', '').strip()
        new = data.get('new', '').strip()
        dry_run = data.get('dry_run', True)
        
        if not old or not new:
            return jsonify({
                'success': False,
                'error': 'Valeurs old et new requises'
            })
        
        result = wpcli_service.search_replace(project_name, old, new, dry_run)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/cache/<project_name>/flush', methods=['POST'])
def flush_cache(project_name):
    """Vide le cache WordPress"""
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        result = wpcli_service.flush_cache(project_name)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/maintenance/<project_name>/<action>', methods=['POST'])
def maintenance_mode(project_name, action):
    """Active/désactive le mode maintenance (action: on|off)"""
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        if action not in ['on', 'off']:
            return jsonify({
                'success': False,
                'error': 'Action doit être "on" ou "off"'
            })
        
        activate = (action == 'on')
        result = wpcli_service.maintenance_mode(project_name, activate)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/core/<project_name>/version', methods=['GET'])
def get_core_version(project_name):
    """Récupère la version de WordPress"""
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        result = wpcli_service.get_core_version(project_name)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


@project_wpcli_bp.route('/wpcli/rewrite/<project_name>/flush', methods=['POST'])
def flush_rewrite(project_name):
    """Régénère les règles de réécriture"""
    try:
        valid, error = validate_project_or_instance(project_name)
        if not valid:
            return jsonify({'success': False, 'error': error})
        
        wpcli_service = current_app.extensions.get('wpcli_service')
        if not wpcli_service:
            return jsonify({
                'success': False,
                'error': 'Service WP-CLI non disponible'
            })
        
        result = wpcli_service.flush_rewrite_rules(project_name)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })


