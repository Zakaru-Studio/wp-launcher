#!/usr/bin/env python3
"""
Routes pour la gestion des configurations PHP et MySQL
"""

from flask import Blueprint, request, jsonify, current_app, Response
from app.utils.logger import wp_logger
from app.middleware.auth_middleware import login_required, admin_required
import json

config_bp = Blueprint('config', __name__, url_prefix='/api/config')


@config_bp.route('/app', methods=['GET'])
@login_required
def get_app_config():
    """Returns app-level configuration for the frontend"""
    from app.config.docker_config import DockerConfig
    return jsonify({
        'app_host': DockerConfig.LOCAL_IP,
        'app_port': DockerConfig.APP_PORT,
        'app_url': f"http://{DockerConfig.LOCAL_IP}:{DockerConfig.APP_PORT}",
        'wp_admin_user': DockerConfig.WP_ADMIN_USER,
        'wp_admin_password': DockerConfig.WP_ADMIN_PASSWORD
    })


@config_bp.route('/php/<project_name>', methods=['GET'])
@login_required
def get_php_config(project_name):
    """Récupère la configuration PHP d'un projet"""
    try:
        config_service = current_app.extensions['config']
        
        # Récupérer la configuration actuelle
        config = config_service.get_php_config(project_name)
        
        # Récupérer le schéma pour l'interface
        schema = config_service.get_php_config_schema()
        
        wp_logger.log_system_info(f"Configuration PHP récupérée via API pour {project_name}", 
                                 config_keys=list(config.keys()))
        
        # Utiliser json.dumps pour préserver l'ordre des clés
        response_data = json.dumps({
            'success': True,
            'config': config,
            'schema': schema
        }, sort_keys=False, ensure_ascii=False)
        
        return Response(response_data, mimetype='application/json')
        
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API récupération config PHP pour {project_name}: {e}", 
                                 error=str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@config_bp.route('/php/<project_name>', methods=['POST'])
@admin_required
def update_php_config(project_name):
    """Met à jour la configuration PHP d'un projet"""
    try:
        config_service = current_app.extensions['config']
        docker_service = current_app.extensions['docker']
        
        # Récupérer les données de configuration
        config_data = request.get_json()
        if not config_data:
            return jsonify({
                'success': False,
                'error': 'Aucune donnée de configuration fournie'
            }), 400
        
        # Valider les données
        validated_config = _validate_php_config(config_data)
        if not validated_config['valid']:
            return jsonify({
                'success': False,
                'error': validated_config['error']
            }), 400
        
        # Vérifier si la version PHP a changé
        php_version_changed = False
        if 'php_version' in validated_config['config']:
            current_version = config_service.get_php_version(project_name)
            new_version = validated_config['config']['php_version']
            if current_version != new_version:
                php_version_changed = True
                config_service.set_php_version(project_name, new_version)
        
        # Extraire php_version avant de mettre à jour le php.ini
        config_without_version = {k: v for k, v in validated_config['config'].items() if k != 'php_version'}
        
        # Mettre à jour la configuration
        success = config_service.update_php_config(project_name, config_without_version)
        
        if success:
            # Si la version PHP a changé, rebuild le conteneur
            if php_version_changed:
                rebuild_success = _rebuild_wordpress_container(project_name, docker_service)
                if not rebuild_success:
                    return jsonify({
                        'success': False,
                        'error': 'Erreur lors du changement de version PHP'
                    }), 500
                
                wp_logger.log_system_info(f"Version PHP changée et conteneur rebuil pour {project_name}")
                
                return jsonify({
                    'success': True,
                    'message': 'Configuration PHP et version mises à jour avec succès. Le conteneur a été recréé.',
                    'php_version_changed': True
                })
            else:
                # Redémarrer seulement les services WordPress et phpMyAdmin
                restart_success = _restart_php_services(project_name, docker_service)
                
                wp_logger.log_system_info(f"Configuration PHP mise à jour via API pour {project_name}", 
                                         config_updated=True,
                                         services_restarted=restart_success)
                
                return jsonify({
                    'success': True,
                    'message': 'Configuration PHP mise à jour avec succès',
                    'services_restarted': restart_success
                })
        else:
            return jsonify({
                'success': False,
                'error': 'Erreur lors de la mise à jour de la configuration'
            }), 500
            
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API mise à jour config PHP pour {project_name}: {e}", 
                                 error=str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@config_bp.route('/mysql/<project_name>', methods=['GET'])
@login_required
def get_mysql_config(project_name):
    """Récupère la configuration MySQL d'un projet"""
    try:
        config_service = current_app.extensions['config']
        
        # Récupérer la configuration actuelle
        config = config_service.get_mysql_config(project_name)
        
        # Récupérer le schéma pour l'interface
        schema = config_service.get_mysql_config_schema()
        
        wp_logger.log_system_info(f"Configuration MySQL récupérée via API pour {project_name}", 
                                 config_keys=list(config.keys()))
        
        return jsonify({
            'success': True,
            'config': config,
            'schema': schema
        })
        
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API récupération config MySQL pour {project_name}: {e}", 
                                 error=str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@config_bp.route('/mysql/<project_name>', methods=['POST'])
@admin_required
def update_mysql_config(project_name):
    """Met à jour la configuration MySQL d'un projet"""
    try:
        config_service = current_app.extensions['config']
        docker_service = current_app.extensions['docker']
        
        # Récupérer les données de configuration
        config_data = request.get_json()
        if not config_data:
            return jsonify({
                'success': False,
                'error': 'Aucune donnée de configuration fournie'
            }), 400
        
        # Valider les données
        validated_config = _validate_mysql_config(config_data)
        if not validated_config['valid']:
            return jsonify({
                'success': False,
                'error': validated_config['error']
            }), 400
        
        # Mettre à jour la configuration
        success = config_service.update_mysql_config(project_name, validated_config['config'])
        
        if success:
            # Redémarrer le service MySQL pour appliquer les changements
            restart_success = _restart_mysql_service(project_name, docker_service)
            
            wp_logger.log_system_info(f"Configuration MySQL mise à jour via API pour {project_name}", 
                                     config_updated=True,
                                     services_restarted=restart_success)
            
            return jsonify({
                'success': True,
                'message': 'Configuration MySQL mise à jour avec succès',
                'services_restarted': restart_success
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Erreur lors de la mise à jour de la configuration'
            }), 500
            
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API mise à jour config MySQL pour {project_name}: {e}", 
                                 error=str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def _validate_php_config(config_data):
    """Valide les données de configuration PHP"""
    try:
        validated = {}
        
        # Validation de la version PHP
        if 'php_version' in config_data:
            version = str(config_data['php_version']).strip()
            valid_versions = ['7.4', '8.0', '8.1', '8.2', '8.3', '8.4']
            if version not in valid_versions:
                return {'valid': False, 'error': f'Version PHP invalide. Versions supportées: {", ".join(valid_versions)}'}
            validated['php_version'] = version
        
        # Validation des champs numériques
        numeric_fields = ['max_execution_time', 'max_input_vars']
        for field in numeric_fields:
            if field in config_data:
                try:
                    validated[field] = str(int(config_data[field]))
                except (ValueError, TypeError):
                    return {'valid': False, 'error': f'Valeur invalide pour {field}'}
        
        # Validation des champs de taille (avec suffixes M, G, etc.)
        size_fields = ['memory_limit', 'post_max_size', 'upload_max_filesize']
        for field in size_fields:
            if field in config_data:
                value = str(config_data[field]).strip()
                if not _validate_size_value(value):
                    return {'valid': False, 'error': f'Format invalide pour {field} (ex: 512M, 1G)'}
                validated[field] = value
        
        # Validation des champs On/Off
        boolean_fields = ['display_errors', 'log_errors']
        for field in boolean_fields:
            if field in config_data:
                value = str(config_data[field]).strip()
                if value not in ['On', 'Off']:
                    return {'valid': False, 'error': f'Valeur invalide pour {field} (On ou Off)'}
                validated[field] = value
        
        # Autres champs texte
        text_fields = ['realpath_cache_size', 'realpath_cache_ttl', 'opcache.enable', 
                      'opcache.memory_consumption', 'error_reporting', 
                      'session.gc_maxlifetime', 'session.cookie_lifetime']
        for field in text_fields:
            if field in config_data:
                validated[field] = str(config_data[field]).strip()
        
        # Validation des constantes WordPress
        wp_debug_fields = ['wp_debug', 'wp_debug_log', 'wp_debug_display']
        for field in wp_debug_fields:
            if field in config_data:
                value = str(config_data[field]).strip().lower()
                if value not in ['true', 'false']:
                    return {'valid': False, 'error': f'Valeur invalide pour {field} (true ou false)'}
                validated[field] = value
        
        return {'valid': True, 'config': validated}
        
    except Exception as e:
        return {'valid': False, 'error': f'Erreur de validation: {str(e)}'}

def _validate_mysql_config(config_data):
    """Valide les données de configuration MySQL"""
    try:
        validated = {}
        
        # Validation des champs numériques
        numeric_fields = ['max_connections', 'interactive_timeout', 'wait_timeout', 
                         'net_read_timeout', 'net_write_timeout']
        for field in numeric_fields:
            if field in config_data:
                try:
                    validated[field] = str(int(config_data[field]))
                except (ValueError, TypeError):
                    return {'valid': False, 'error': f'Valeur invalide pour {field}'}
        
        # Validation des champs de taille
        size_fields = ['max_allowed_packet', 'innodb_buffer_pool_size', 'innodb_log_file_size', 
                      'innodb_log_buffer_size']
        for field in size_fields:
            if field in config_data:
                value = str(config_data[field]).strip()
                if not _validate_size_value(value):
                    return {'valid': False, 'error': f'Format invalide pour {field} (ex: 512M, 1G)'}
                validated[field] = value
        
        # Champs texte
        text_fields = ['character-set-server', 'collation-server']
        for field in text_fields:
            if field in config_data:
                validated[field] = str(config_data[field]).strip()
        
        return {'valid': True, 'config': validated}
        
    except Exception as e:
        return {'valid': False, 'error': f'Erreur de validation: {str(e)}'}

def _validate_size_value(value):
    """Valide une valeur de taille (ex: 512M, 1G, 2048K)"""
    import re
    pattern = r'^\d+[KMGT]?$'
    return bool(re.match(pattern, value.upper()))

def _restart_php_services(project_name, docker_service):
    """Redémarre les services utilisant PHP (WordPress et phpMyAdmin)"""
    try:
        success, error = docker_service.restart_php_services(project_name)
        return success
        
    except Exception as e:
        wp_logger.log_system_info(f"Erreur redémarrage services PHP pour {project_name}: {e}", 
                                 error=str(e))
        return False

def _restart_mysql_service(project_name, docker_service):
    """Redémarre le service MySQL"""
    try:
        success, error = docker_service.restart_mysql_service(project_name)
        return success
        
    except Exception as e:
        wp_logger.log_system_info(f"Erreur redémarrage service MySQL pour {project_name}: {e}", 
                                 error=str(e))
        return False

def _rebuild_wordpress_container(project_name, docker_service):
    """Rebuild le conteneur WordPress avec une nouvelle version PHP"""
    try:
        success, error = docker_service.rebuild_wordpress_container(project_name)
        return success
        
    except Exception as e:
        wp_logger.log_system_info(f"Erreur rebuild conteneur WordPress pour {project_name}: {e}", 
                                 error=str(e))
        return False

@config_bp.route('/wordpress-type/<project_name>', methods=['GET'])
@login_required
def get_wordpress_type(project_name):
    """Récupère le type WordPress d'un projet (showcase ou woocommerce)"""
    try:
        from app.services.wordpress_type_service import WordPressTypeService
        
        wp_type_service = WordPressTypeService()
        wp_type = wp_type_service.get_wordpress_type(project_name)
        all_types = wp_type_service.get_all_types()
        
        wp_logger.log_system_info(f"Type WordPress récupéré via API pour {project_name}: {wp_type}")
        
        return jsonify({
            'success': True,
            'type': wp_type,
            'types': all_types,
            'current_info': all_types.get(wp_type, {})
        })
        
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API récupération type WordPress pour {project_name}: {e}", 
                                 error=str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@config_bp.route('/wordpress-type/<project_name>', methods=['POST'])
@admin_required
def update_wordpress_type(project_name):
    """Met à jour le type WordPress d'un projet et relance les containers"""
    try:
        from app.services.wordpress_type_service import WordPressTypeService
        import os
        import re
        
        docker_service = current_app.extensions['docker']
        wp_type_service = WordPressTypeService()
        
        # Récupérer le nouveau type depuis le body
        data = request.get_json()
        if not data or 'type' not in data:
            return jsonify({
                'success': False,
                'error': 'Type WordPress non fourni'
            }), 400
        
        new_type = data['type']
        
        # Valider le type
        if new_type not in [wp_type_service.TYPE_SHOWCASE, wp_type_service.TYPE_WOOCOMMERCE]:
            return jsonify({
                'success': False,
                'error': f'Type invalide: {new_type}'
            }), 400
        
        # Récupérer le type actuel
        old_type = wp_type_service.get_wordpress_type(project_name)
        
        if old_type == new_type:
            return jsonify({
                'success': True,
                'message': 'Le type WordPress est déjà à jour',
                'type_changed': False
            })
        
        # Sauvegarder le nouveau type
        if not wp_type_service.save_wordpress_type(project_name, new_type):
            return jsonify({
                'success': False,
                'error': 'Erreur lors de la sauvegarde du type WordPress'
            }), 500
        
        # Mettre à jour le docker-compose.yml avec les nouvelles limites
        container_path = os.path.join('containers', project_name)
        docker_compose_path = os.path.join(container_path, 'docker-compose.yml')
        
        if not os.path.exists(docker_compose_path):
            return jsonify({
                'success': False,
                'error': 'Fichier docker-compose.yml non trouvé'
            }), 404
        
        # Récupérer les nouvelles limites
        limits = wp_type_service.get_memory_limits(new_type)
        
        # Lire et modifier le docker-compose.yml
        with open(docker_compose_path, 'r') as f:
            compose_content = f.read()
        
        # Remplacer les limites mémoire et CPU pour MySQL
        compose_content = re.sub(
            r'(mysql:[\s\S]*?mem_limit:\s*)\d+[mMgG]',
            rf'\g<1>{limits["mysql_memory"]}',
            compose_content
        )
        compose_content = re.sub(
            r'(mysql:[\s\S]*?cpus:\s*["\'])\d+\.?\d*(["\'])',
            rf'\g<1>{limits["mysql_cpu"]}\g<2>',
            compose_content
        )
        
        # Remplacer les limites mémoire et CPU pour WordPress
        compose_content = re.sub(
            r'(wordpress:[\s\S]*?mem_limit:\s*)\d+[mMgG]',
            rf'\g<1>{limits["wordpress_memory"]}',
            compose_content
        )
        compose_content = re.sub(
            r'(wordpress:[\s\S]*?cpus:\s*["\'])\d+\.?\d*(["\'])',
            rf'\g<1>{limits["wordpress_cpu"]}\g<2>',
            compose_content
        )
        
        # Sauvegarder le fichier modifié
        with open(docker_compose_path, 'w') as f:
            f.write(compose_content)
        
        wp_logger.log_system_info(
            f"Type WordPress changé pour {project_name}: {old_type} → {new_type}",
            limits=limits
        )
        
        # Redémarrer les containers pour appliquer les nouvelles limites
        print(f"🔄 Redémarrage des containers pour appliquer les nouvelles limites...")
        
        # Arrêter les containers
        stop_success, stop_error = docker_service.stop_containers(container_path)
        if not stop_success:
            return jsonify({
                'success': False,
                'error': f'Erreur lors de l\'arrêt des containers: {stop_error}'
            }), 500
        
        # Attendre un peu
        import time
        time.sleep(2)
        
        # Redémarrer les containers
        start_success, start_error = docker_service.start_containers(container_path)
        if not start_success:
            return jsonify({
                'success': False,
                'error': f'Erreur lors du démarrage des containers: {start_error}'
            }), 500
        
        wp_logger.log_system_info(
            f"Containers redémarrés avec succès pour {project_name}",
            new_type=new_type,
            limits=limits
        )
        
        return jsonify({
            'success': True,
            'message': f'Type WordPress changé en {wp_type_service.get_wordpress_type_label(new_type)}',
            'type_changed': True,
            'old_type': old_type,
            'new_type': new_type,
            'limits': limits
        })
        
    except Exception as e:
        wp_logger.log_system_info(f"Erreur API mise à jour type WordPress pour {project_name}: {e}", 
                                 error=str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
