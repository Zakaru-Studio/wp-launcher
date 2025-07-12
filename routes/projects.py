#!/usr/bin/env python3
"""
Routes pour la gestion des projets WordPress
"""

import os
import json
import tempfile
import subprocess
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from utils.file_utils import allowed_file, extract_zip, is_sql_file, is_zip_file
from utils.port_utils import find_free_port_for_project, get_used_ports
from utils.project_utils import (
    secure_project_name, copy_docker_template, copy_docker_template_nextjs_mongo,
    copy_docker_template_nextjs_mysql, create_default_wp_content, create_wordpress_base_files,
    create_nextjs_app_structure, project_exists, create_project_marker, update_project_wordpress_urls_in_files
)
from utils.database_utils import (
    create_clean_wordpress_database, intelligent_mysql_wait
)
from utils.logger import wp_logger
from models.project import Project
from utils.port_conflict_resolver import PortConflictResolver

projects_bp = Blueprint('projects', __name__)

# Configuration des constantes
PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'


@projects_bp.route('/projects')
def list_projects():
    """Liste tous les projets disponibles"""
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
        if project.port:
            ports['wordpress'] = project.port
        if project.pma_port:
            ports['phpmyadmin'] = project.pma_port
        if project.mailpit_port:
            ports['mailpit'] = project.mailpit_port
        if project.has_nextjs and project.nextjs_port:
            ports['nextjs'] = project.nextjs_port
        
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
            'urls': urls
        }
        
        projects.append(project_info)
    
    return jsonify({'projects': projects})


@projects_bp.route('/create_project', methods=['POST'])
def create_project():
    """Crée un nouveau projet WordPress ou Next.js"""
    project_name = "unknown"
    try:
        print("🚀 Début de création du projet")
        
        # Récupérer les données du formulaire
        project_name = request.form['project_name'].strip()
        project_hostname = request.form.get('project_hostname', '').strip()
        project_type = request.form.get('project_type', 'wordpress')
        enable_nextjs = request.form.get('enable_nextjs') == 'on'
        database_type = request.form.get('database_type', 'mongodb')
        
        # Log du début de l'opération
        wp_logger.log_operation_start(
            'create', 
            project_name, 
            project_type=project_type,
            enable_nextjs=enable_nextjs,
            database_type=database_type if project_type == 'nextjs' else None,
            user_ip=request.remote_addr
        )
        
        if not project_name:
            return jsonify({'success': False, 'message': 'Le nom du projet est requis'})
        
        if not project_hostname:
            return jsonify({'success': False, 'message': 'Le hostname est requis'})
        
        # Nettoyer le nom du projet et le hostname
        project_name = secure_project_name(project_name)
        project_hostname = secure_project_name(project_hostname)
        
        print(f"📝 Nom du projet: {project_name}")
        print(f"🎯 Type de projet: {project_type}")
        
        # Vérifier si le projet existe déjà
        if project_exists(project_name, PROJECTS_FOLDER):
            return jsonify({'success': False, 'message': f'Le projet {project_name} existe déjà'})
        
        # Créer les dossiers du projet
        editable_path = os.path.join(PROJECTS_FOLDER, project_name)
        container_path = os.path.join(CONTAINERS_FOLDER, project_name)
        
        print(f"📂 Création du dossier fichiers éditables: {editable_path}")
        os.makedirs(editable_path, exist_ok=True)
        
        print(f"📂 Création du dossier configuration Docker: {container_path}")
        os.makedirs(container_path, exist_ok=True)
        
        # Créer le marqueur de type de projet
        create_project_marker(editable_path, project_type)
        
        # Traitement selon le type de projet
        if project_type == 'wordpress':
            return _create_wordpress_project(project_name, project_hostname, editable_path, container_path, enable_nextjs)
        else:
            return _create_nextjs_project(project_name, project_hostname, editable_path, container_path, database_type)
            
    except Exception as e:
        print(f"❌ Erreur lors de la création du projet: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur lors de la création: {str(e)}'})


def _create_wordpress_project(project_name, project_hostname, editable_path, container_path, enable_nextjs):
    """Crée un projet WordPress"""
    print("📋 Copie du template Docker pour WordPress...")
    
    # Configurer les ports d'abord
    ports = _configure_wordpress_ports(project_name, enable_nextjs)
    
    if enable_nextjs:
        copy_docker_template(container_path, project_name, project_hostname, ports, enable_nextjs=True)
    else:
        copy_docker_template(container_path, project_name, project_hostname, ports, enable_nextjs=False)
    
    # Gérer le fichier uploadé
    wp_migrate_archive = request.files.get('wp_migrate_archive')
    archive_path = None
    
    if wp_migrate_archive and wp_migrate_archive.filename:
        if not allowed_file(wp_migrate_archive.filename):
            return jsonify({'success': False, 'message': 'Type de fichier non autorisé'})
        
        filename = secure_filename(wp_migrate_archive.filename)
        archive_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        wp_migrate_archive.save(archive_path)
        print(f"📁 Fichier WP Migrate sauvegardé: {archive_path}")
    
    # Créer wp-content
    wp_content_dest = os.path.join(editable_path, 'wp-content')
    print(f"📦 Configuration wp-content externe: {wp_content_dest}")
    os.makedirs(wp_content_dest, exist_ok=True)
    
    # Créer les fichiers de base WordPress (.htaccess et wp-config.php)
    create_wordpress_base_files(editable_path)
    
    # Mettre à jour les URLs dans les fichiers WordPress
    update_project_wordpress_urls_in_files(editable_path, project_hostname, ports['wordpress'])
    
    # Traiter le fichier selon son type
    db_path = None
    if archive_path:
        if is_sql_file(archive_path):
            db_path = archive_path
            print(f"📦 Fichier SQL détecté: {db_path}")
            create_default_wp_content(wp_content_dest)
        elif is_zip_file(archive_path):
            print(f"📦 Fichier ZIP détecté: {archive_path}")
            extract_zip(archive_path, wp_content_dest)
        else:
            create_default_wp_content(wp_content_dest)
    else:
        create_default_wp_content(wp_content_dest)
    
    # Les ports sont déjà configurés et appliqués via copy_docker_template
    
    # Démarrer les conteneurs
    docker_service = current_app.extensions.get('docker')
    if docker_service:
        success, error = docker_service.start_containers(container_path)
        if not success:
            return jsonify({'success': False, 'message': f'Erreur lors du démarrage: {error}'})
    
    # Configurer la base de données
    if db_path:
        # TODO: Implémenter l'import de base de données
        success_message = f'Projet WordPress {project_name} créé avec succès !'
    else:
        if not create_clean_wordpress_database(container_path, project_name):
            return jsonify({'success': False, 'message': 'Erreur lors de la création de la base de données'})
        success_message = f'Projet WordPress {project_name} créé avec succès ! Installation WordPress à terminer.'
    
    return jsonify({
        'success': True, 
        'message': success_message,
        'project_name': project_name,
        'urls': _get_project_urls(project_name, ports)
    })


def _create_nextjs_project(project_name, project_hostname, editable_path, container_path, database_type):
    """Crée un projet Next.js"""
    print("📋 Copie du template Docker pour Next.js...")
    
    if database_type == 'mongodb':
        copy_docker_template_nextjs_mongo(container_path, project_name, project_hostname)
    else:
        copy_docker_template_nextjs_mysql(container_path, project_name, project_hostname)
    
    # Créer la structure Next.js
    print("📦 Création de la structure Next.js App...")
    create_nextjs_app_structure(editable_path, project_name)
    
    # Configurer les ports
    ports = _configure_nextjs_ports(project_name, database_type)
    
    # Démarrer les conteneurs
    docker_service = current_app.extensions.get('docker')
    if docker_service:
        success, error = docker_service.start_containers(container_path)
        if not success:
            return jsonify({'success': False, 'message': f'Erreur lors du démarrage: {error}'})
    
    success_message = f'Application Next.js {project_name} créée avec succès !'
    
    return jsonify({
        'success': True, 
        'message': success_message,
        'project_name': project_name,
        'urls': _get_project_urls(project_name, ports)
    })


def _configure_wordpress_ports(project_name, enable_nextjs):
    """Configure les ports pour un projet WordPress avec sauvegarde automatique"""
    ports = {}
    
    # Port principal WordPress
    ports['wordpress'] = find_free_port_for_project()
    ports['phpmyadmin'] = find_free_port_for_project(ports['wordpress'] + 1)
    
    # Port Next.js si activé
    if enable_nextjs:
        ports['nextjs'] = find_free_port_for_project(ports['phpmyadmin'] + 1)
        ports['mailpit'] = find_free_port_for_project(ports['nextjs'] + 1)
    else:
        ports['mailpit'] = find_free_port_for_project(ports['phpmyadmin'] + 1)
    
    ports['smtp'] = find_free_port_for_project(ports['mailpit'] + 1)
    
    # Sauvegarder les ports alloués
    _save_project_ports(project_name, ports)
    
    print(f"📋 Ports alloués pour {project_name}: {ports}")
    return ports


def _configure_nextjs_ports(project_name, database_type):
    """Configure les ports pour un projet Next.js"""
    ports = {}
    
    # Port principal Next.js
    ports['nextjs'] = find_free_port_for_project()
    
    # Port base de données
    if database_type == 'mongodb':
        ports['mongodb'] = find_free_port_for_project(ports['nextjs'] + 1)
        ports['mongo_express'] = find_free_port_for_project(ports['mongodb'] + 1)
    else:
        ports['mysql'] = find_free_port_for_project(ports['nextjs'] + 1)
        ports['phpmyadmin'] = find_free_port_for_project(ports['mysql'] + 1)
    
    ports['mailpit'] = find_free_port_for_project(ports['phpmyadmin'] + 1 if 'phpmyadmin' in ports else ports['mongo_express'] + 1)
    ports['smtp'] = find_free_port_for_project(ports['mailpit'] + 1)
    
    return ports


def _get_project_urls(project_name, ports):
    """Génère les URLs du projet"""
    urls = {}
    
    if 'wordpress' in ports:
        urls['wordpress'] = f'http://192.168.1.21:{ports["wordpress"]}'
        urls['wordpress_admin'] = f'http://192.168.1.21:{ports["wordpress"]}/wp-admin'
    
    if 'phpmyadmin' in ports:
        urls['phpmyadmin'] = f'http://192.168.1.21:{ports["phpmyadmin"]}'
    
    if 'mailpit' in ports:
        urls['mailpit'] = f'http://192.168.1.21:{ports["mailpit"]}'
    
    if 'nextjs' in ports:
        urls['nextjs'] = f'http://192.168.1.21:{ports["nextjs"]}'
    
    return urls


def _save_project_ports(project_name, ports):
    """Sauvegarde les ports d'un projet dans des fichiers dédiés"""
    try:
        container_path = os.path.join(CONTAINERS_FOLDER, project_name)
        os.makedirs(container_path, exist_ok=True)
        
        # Mapper les ports vers leurs fichiers
        port_files = {
            'wordpress': '.port',
            'phpmyadmin': '.pma_port',
            'mailpit': '.mailpit_port',
            'smtp': '.smtp_port',
            'nextjs': '.nextjs_port'
        }
        
        # Sauvegarder chaque port dans son fichier
        for service, port in ports.items():
            if service in port_files:
                port_file_path = os.path.join(container_path, port_files[service])
                with open(port_file_path, 'w') as f:
                    f.write(str(port))
                print(f"💾 Port {service}: {port} → {port_files[service]}")
        
        print(f"✅ Ports sauvegardés pour le projet {project_name}")
        
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde des ports pour {project_name}: {e}")





@projects_bp.route('/start_project/<project_name>', methods=['POST'])
def start_project(project_name):
    """Démarre un projet"""
    try:
        print(f"🚀 Démarrage du projet: {project_name}")
        
        # Vérifier si le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier si le projet est valide
        if not project.is_valid:
            return jsonify({'success': False, 'message': 'Projet invalide (fichier docker-compose.yml manquant)'})
        
        # Démarrer les conteneurs
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            success, error = docker_service.start_containers(project.container_path)
            if success:
                return jsonify({
                    'success': True,
                    'message': f'Projet {project_name} démarré avec succès'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Erreur lors du démarrage: {error}'
                })
        else:
            return jsonify({
                'success': False,
                'message': 'Service Docker non disponible'
            })
        
    except Exception as e:
        print(f"❌ Erreur lors du démarrage du projet {project_name}: {e}")
        return jsonify({
            'success': False,
            'message': f'Erreur lors du démarrage: {str(e)}'
        })


@projects_bp.route('/stop_project/<project_name>', methods=['POST'])
def stop_project(project_name):
    """Arrête un projet"""
    try:
        print(f"🛑 Arrêt du projet: {project_name}")
        
        # Vérifier si le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier si le projet est valide
        if not project.is_valid:
            return jsonify({'success': False, 'message': 'Projet invalide (fichier docker-compose.yml manquant)'})
        
        # Arrêter les conteneurs
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            success, error = docker_service.stop_containers(project.container_path)
            if success:
                return jsonify({
                    'success': True,
                    'message': f'Projet {project_name} arrêté avec succès'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Erreur lors de l\'arrêt: {error}'
                })
        else:
            return jsonify({
                'success': False,
                'message': 'Service Docker non disponible'
            })
        
    except Exception as e:
        print(f"❌ Erreur lors de l'arrêt du projet {project_name}: {e}")
        return jsonify({
            'success': False,
            'message': f'Erreur lors de l\'arrêt: {str(e)}'
        })


@projects_bp.route('/delete_project/<project_name>', methods=['DELETE'])
def delete_project(project_name):
    """Supprime un projet avec gestion robuste des permissions"""
    try:
        print(f"🗑️ Suppression du projet: {project_name}")
        
        # Vérifier si le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Arrêter et supprimer les conteneurs
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            print(f"🐳 Arrêt des conteneurs...")
            docker_service.stop_containers(project.container_path)
            docker_service.remove_containers(project.container_path)
        
        # Supprimer les dossiers avec gestion des permissions
        import shutil
        
        # Fonction pour suppression robuste avec permissions
        def safe_remove_tree(path, description):
            if not os.path.exists(path):
                print(f"⚠️ {description} non trouvé: {path}")
                return True
                
            try:
                print(f"🗑️ Suppression de {description}: {path}")
                
                # Première tentative : suppression normale
                shutil.rmtree(path)
                print(f"✅ {description} supprimé avec succès")
                return True
                
            except PermissionError as pe:
                print(f"⚠️ Erreur de permissions pour {description}: {pe}")
                
                try:
                    # Deuxième tentative : correction des permissions puis suppression
                    print(f"🔧 Correction des permissions pour {description}...")
                    
                    # Changer les permissions récursivement
                    for root, dirs, files in os.walk(path):
                        # Permissions sur les dossiers
                        for dir_name in dirs:
                            dir_path = os.path.join(root, dir_name)
                            try:
                                os.chmod(dir_path, 0o755)
                            except:
                                pass
                        
                        # Permissions sur les fichiers
                        for file_name in files:
                            file_path = os.path.join(root, file_name)
                            try:
                                os.chmod(file_path, 0o644)
                            except:
                                pass
                    
                    # Tenter la suppression après correction des permissions
                    shutil.rmtree(path)
                    print(f"✅ {description} supprimé après correction des permissions")
                    return True
                    
                except Exception as e2:
                    print(f"❌ Échec de suppression même après correction des permissions: {e2}")
                    
                    try:
                        # Troisième tentative : suppression avec sudo
                        print(f"🔓 Tentative de suppression avec sudo pour {description}...")
                        result = subprocess.run(['sudo', 'rm', '-rf', path], 
                                              capture_output=True, text=True, timeout=30)
                        
                        if result.returncode == 0:
                            print(f"✅ {description} supprimé avec sudo")
                            return True
                        else:
                            print(f"❌ Erreur sudo: {result.stderr}")
                            return False
                            
                    except Exception as e3:
                        print(f"❌ Échec final de suppression: {e3}")
                        return False
            
            except Exception as e:
                print(f"❌ Erreur lors de la suppression de {description}: {e}")
                return False
        
        # Supprimer le dossier des fichiers éditables
        success_editable = safe_remove_tree(project.path, "dossier des fichiers éditables")
        
        # Supprimer le dossier des conteneurs
        success_container = safe_remove_tree(project.container_path, "dossier des conteneurs")
        
        # Retourner le résultat
        if success_editable and success_container:
            return jsonify({
                'success': True,
                'message': f'Projet {project_name} supprimé avec succès'
            })
        elif success_editable or success_container:
            return jsonify({
                'success': True,
                'message': f'Projet {project_name} partiellement supprimé. Quelques fichiers peuvent subsister.'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Erreur lors de la suppression du projet {project_name}. Vérifiez les permissions.'
            })
        
    except Exception as e:
        print(f"❌ Erreur lors de la suppression du projet {project_name}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur lors de la suppression: {str(e)}'
        })


@projects_bp.route('/project_status/<project_name>')
def check_project_status(project_name):
    """Vérifie le statut d'un projet"""
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
                'status': 'active' if container_status == 'running' else 'inactive',
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

@projects_bp.route('/cleanup_containers', methods=['POST'])
def cleanup_containers():
    """Nettoie les conteneurs orphelins"""
    try:
        subprocess.run(['docker', 'container', 'prune', '-f'], 
                      capture_output=True, text=True)
        
        return jsonify({
            'success': True,
            'message': 'Conteneurs orphelins nettoyés'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        }) 

@projects_bp.route('/resolve_port_conflicts', methods=['POST'])
def resolve_port_conflicts():
    """Résout automatiquement les conflits de ports"""
    try:
        data = request.get_json() or {}
        project_name = data.get('project_name')
        
        resolver = PortConflictResolver()
        
        if project_name:
            # Résoudre les conflits pour un projet spécifique
            result = resolver.resolve_project_conflicts(project_name)
            return jsonify(result)
        else:
            # Diagnostic général
            report = resolver.get_diagnostic_report()
            return jsonify({
                'success': True,
                'diagnostic': report
            })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erreur lors de la résolution des conflits: {str(e)}'
        }), 500

@projects_bp.route('/port_diagnostic', methods=['GET'])
def port_diagnostic():
    """Obtient un diagnostic complet des ports"""
    try:
        resolver = PortConflictResolver()
        report = resolver.get_diagnostic_report()
        
        return jsonify({
            'success': True,
            'report': report
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erreur lors du diagnostic: {str(e)}'
        }), 500 

@projects_bp.route('/nextjs_npm/<project_name>/<command>', methods=['POST'])
def nextjs_npm_command(project_name, command):
    """Exécute une commande npm pour un projet NextJS"""
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Ce projet n\'a pas NextJS activé'})
        
        # Vérifier que la commande est autorisée
        allowed_commands = ['install', 'dev', 'build', 'start']
        if command not in allowed_commands:
            return jsonify({'success': False, 'message': f'Commande non autorisée: {command}'})
        
        # Obtenir le service Docker
        docker_service = current_app.extensions.get('docker')
        if not docker_service:
            return jsonify({'success': False, 'message': 'Service Docker non disponible'})
        
        # Vérifier le statut du conteneur
        container_status = docker_service.get_container_status(project_name)
        if container_status != 'active':
            return jsonify({'success': False, 'message': 'Le conteneur doit être démarré pour exécuter des commandes npm'})
        
        # Construire la commande npm
        container_name = f"{project_name}_nextjs_1"
        
        if command == 'install':
            npm_command = ['docker', 'exec', container_name, 'npm', 'install']
        elif command == 'dev':
            npm_command = ['docker', 'exec', '-d', container_name, 'npm', 'run', 'dev']
        elif command == 'build':
            npm_command = ['docker', 'exec', container_name, 'npm', 'run', 'build']
        elif command == 'start':
            npm_command = ['docker', 'exec', '-d', container_name, 'npm', 'start']
        
        # Exécuter la commande
        result = subprocess.run(npm_command, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            return jsonify({
                'success': True, 
                'message': f'Commande npm {command} exécutée avec succès',
                'output': result.stdout
            })
        else:
            return jsonify({
                'success': False, 
                'message': f'Erreur lors de l\'exécution de npm {command}',
                'error': result.stderr
            })
            
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'message': 'Timeout: la commande a pris trop de temps'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@projects_bp.route('/check_nextjs_status/<project_name>')
def check_nextjs_status(project_name):
    """Vérifie le statut npm dev d'un projet NextJS"""
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Ce projet n\'a pas NextJS activé'})
        
        # Obtenir le service Docker
        docker_service = current_app.extensions.get('docker')
        if not docker_service:
            return jsonify({'success': False, 'message': 'Service Docker non disponible'})
        
        # Vérifier le statut du conteneur
        container_status = docker_service.get_container_status(project_name)
        if container_status != 'active':
            return jsonify({
                'success': True,
                'dev_running': False,
                'message': 'Conteneur arrêté'
            })
        
        # Vérifier si npm run dev est en cours
        container_name = f"{project_name}_nextjs_1"
        check_command = ['docker', 'exec', container_name, 'pgrep', '-f', 'npm.*dev']
        
        result = subprocess.run(check_command, capture_output=True, text=True)
        dev_running = result.returncode == 0
        
        return jsonify({
            'success': True,
            'dev_running': dev_running,
            'message': 'npm run dev en cours' if dev_running else 'npm run dev arrêté'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@projects_bp.route('/stop_nextjs_dev/<project_name>', methods=['POST'])
def stop_nextjs_dev(project_name):
    """Arrête npm run dev pour un projet NextJS"""
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Ce projet n\'a pas NextJS activé'})
        
        # Obtenir le service Docker
        docker_service = current_app.extensions.get('docker')
        if not docker_service:
            return jsonify({'success': False, 'message': 'Service Docker non disponible'})
        
        # Vérifier le statut du conteneur
        container_status = docker_service.get_container_status(project_name)
        if container_status != 'active':
            return jsonify({'success': False, 'message': 'Le conteneur n\'est pas actif'})
        
        # Arrêter npm run dev
        container_name = f"{project_name}_nextjs_1"
        stop_command = ['docker', 'exec', container_name, 'pkill', '-f', 'npm.*dev']
        
        result = subprocess.run(stop_command, capture_output=True, text=True)
        
        return jsonify({
            'success': True,
            'message': 'npm run dev arrêté avec succès'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@projects_bp.route('/start_nextjs_container/<project_name>', methods=['POST'])
def start_nextjs_container(project_name):
    """Démarre le conteneur NextJS et lance npm run dev"""
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Ce projet n\'a pas NextJS activé'})
        
        # Obtenir le service Docker
        docker_service = current_app.extensions.get('docker')
        if not docker_service:
            return jsonify({'success': False, 'message': 'Service Docker non disponible'})
        
        # Démarrer le conteneur
        container_path = os.path.join(CONTAINERS_FOLDER, project_name)
        success, error = docker_service.start_containers(container_path)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Conteneur NextJS démarré avec succès'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Erreur lors du démarrage: {error}'
            })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'}) 

 