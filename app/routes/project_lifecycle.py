#!/usr/bin/env python3
"""
Routes pour le cycle de vie des projets (create, start, stop, restart, delete)
"""

import os
import json
import time
import tempfile
import subprocess
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from app.utils.file_utils import allowed_file, extract_zip, is_sql_file, is_zip_file
from app.utils.port_utils import find_free_port_for_project, get_used_ports, get_comprehensive_used_ports
from app.utils.project_utils import (
    secure_project_name, copy_docker_template, copy_docker_template_nextjs_mongo,
    copy_docker_template_nextjs_mysql, create_default_wp_content, create_wordpress_base_files,
    create_nextjs_app_structure, project_exists, create_project_marker, update_project_wordpress_urls_in_files
)
from app.utils.database_utils import (
    create_clean_wordpress_database, intelligent_mysql_wait
)
from app.utils.logger import wp_logger
from app.models.project import Project
from app.utils.port_conflict_resolver import PortConflictResolver
from app.services.fast_import_service import FastImportService
from app.utils.debug_logger import create_debug_logger
from app.config.docker_config import DockerConfig
from app.middleware.auth_middleware import login_required, admin_required

project_lifecycle_bp = Blueprint('project_lifecycle', __name__)

# Configuration des constantes
PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'


@project_lifecycle_bp.route('/create_project', methods=['POST'])
@login_required
def create_project():
    """Crée un nouveau projet WordPress ou Next.js.

    Ouvert aux développeurs (pas seulement admins) : chaque membre
    authentifié peut créer ses propres sites. Les actions destructives
    (start/stop/rebuild/delete) restent réservées aux admins tant que
    l'ownership par projet n'est pas généralisé dans metadata_service.
    """
    project_name = "unknown"
    debug_logger = None
    try:
        # Gestion robuste des erreurs I/O pour les prints
        try:
            print("🚀 Début de création du projet")
        except (OSError, IOError) as io_error:
            # Si erreur I/O, utiliser logging à la place
            import logging
            logging.info(f"🚀 Début de création du projet (print failed: {io_error})")
        
        # Récupérer les données du formulaire ou JSON
        if request.is_json:
            # Données JSON depuis l'API
            data = request.get_json()
            project_name = data['project_name'].strip()
            project_type = data.get('project_type', 'wordpress')
            enable_nextjs = data.get('enable_nextjs', False)
            wordpress_type = data.get('wordpress_type', 'showcase')  # Type WordPress
            # Pour WordPress, toujours utiliser MySQL, pour Next.js utiliser la sélection
            database_type = data.get('database_type', 'mongodb') if project_type == 'nextjs' else 'mysql'
        else:
            # Données de formulaire depuis l'interface web
            project_name = request.form['project_name'].strip()
            project_type = request.form.get('project_type', 'wordpress')
            enable_nextjs = request.form.get('enable_nextjs') == 'on'
            wordpress_type = request.form.get('wordpress_type', 'showcase')  # Type WordPress
            # Pour WordPress, toujours utiliser MySQL, pour Next.js utiliser la sélection
            database_type = request.form.get('database_type', 'mongodb') if project_type == 'nextjs' else 'mysql'
        
        # Initialiser le logger de debug pour ce projet
        debug_logger = create_debug_logger(project_name)
        
        debug_logger.step("PROJECT_CREATE_START", f"Type: {project_type}, NextJS: {enable_nextjs}, DB: {database_type}, IP: {request.remote_addr}")
        
        # Log du début de l'opération (système existant)
        wp_logger.log_operation_start(
            'create', 
            project_name, 
            project_type=project_type,
            enable_nextjs=enable_nextjs,
            database_type=database_type if project_type == 'nextjs' else None,
            user_ip=request.remote_addr
        )
        
        debug_logger.step("VALIDATE_PROJECT_NAME", f"Validating project name: {project_name}")
        if not project_name:
            debug_logger.error("VALIDATE_PROJECT_NAME", "Project name is empty")
            return jsonify({'success': False, 'message': 'Le nom du projet est requis'})
        
        # Nettoyer le nom du projet
        original_name = project_name
        project_name = secure_project_name(project_name)
        
        if original_name != project_name:
            debug_logger.warning("VALIDATE_PROJECT_NAME", f"Project name sanitized: {original_name} -> {project_name}")
        else:
            debug_logger.success("VALIDATE_PROJECT_NAME", f"Project name is valid: {project_name}")
        
        print(f"📝 Nom du projet: {project_name}")
        print(f"🎯 Type de projet: {project_type}")
        
        # Vérifier si le projet existe déjà
        debug_logger.step("CHECK_PROJECT_EXISTS", "Checking if project already exists")
        if project_exists(project_name, PROJECTS_FOLDER):
            debug_logger.error("CHECK_PROJECT_EXISTS", f"Project {project_name} already exists")
            return jsonify({'success': False, 'message': f'Le projet {project_name} existe déjà'})
        
        debug_logger.success("CHECK_PROJECT_EXISTS", "Project does not exist, proceeding")
        
        # Créer les dossiers du projet
        debug_logger.step("CREATE_DIRECTORIES", "Creating base directories")
        editable_path = os.path.join(PROJECTS_FOLDER, project_name)
        container_path = os.path.join(CONTAINERS_FOLDER, project_name)
        
        debug_logger.debug("CREATE_DIRECTORIES", f"Editable path: {editable_path}")
        debug_logger.debug("CREATE_DIRECTORIES", f"Container path: {container_path}")
        
        print(f"📂 Création du dossier fichiers éditables: {editable_path}")
        try:
            os.makedirs(editable_path, exist_ok=True)
            debug_logger.log_file_operation("CREATE_DIR", editable_path, True, "Editable directory created")
        except Exception as e:
            debug_logger.log_file_operation("CREATE_DIR", editable_path, False, f"Failed to create: {str(e)}")
            raise
        
        print(f"📂 Création du dossier configuration Docker: {container_path}")
        try:
            os.makedirs(container_path, exist_ok=True)
            debug_logger.log_file_operation("CREATE_DIR", container_path, True, "Container directory created")
        except Exception as e:
            debug_logger.log_file_operation("CREATE_DIR", container_path, False, f"Failed to create: {str(e)}")
            raise
        
        debug_logger.success("CREATE_DIRECTORIES", "Base directories created successfully")
        
        # Créer le marqueur de type de projet
        debug_logger.step("CREATE_PROJECT_MARKER", f"Creating project marker for type: {project_type}")
        try:
            create_project_marker(editable_path, project_type)
            debug_logger.success("CREATE_PROJECT_MARKER", "Project marker created")
        except Exception as e:
            debug_logger.error("CREATE_PROJECT_MARKER", f"Failed to create project marker", e)
            raise
        
        # Traitement selon le type de projet
        debug_logger.step("CREATE_PROJECT_TYPE", f"Creating {project_type} project")
        if project_type == 'wordpress':
            return _create_wordpress_project(project_name, editable_path, container_path, enable_nextjs, debug_logger, wordpress_type)
        else:
            return _create_nextjs_project(project_name, editable_path, container_path, database_type, debug_logger)
            
    except Exception as e:
        if debug_logger:
            debug_logger.error("PROJECT_CREATE_EXCEPTION", f"Unexpected error: {str(e)}", e)
        
        # Log de l'erreur avec le système centralisé
        wp_logger.log_operation_error('create', project_name, e, 
                                    context="General exception during project creation",
                                    project_type=locals().get('project_type', 'unknown'),
                                    user_ip=request.remote_addr)
        
        # Gestion robuste des erreurs I/O
        try:
            print(f"❌ Erreur lors de la création du projet: {e}")
            import traceback
            traceback.print_exc()
        except (OSError, IOError):
            # Si erreur I/O, utiliser logging à la place
            import logging
            logging.error(f"❌ Erreur lors de la création du projet: {e}")
        return jsonify({'success': False, 'message': f'Erreur lors de la création: {str(e)}'})
    finally:
        if debug_logger:
            debug_logger.close()


def _create_wordpress_project(project_name, editable_path, container_path, enable_nextjs, debug_logger=None, wordpress_type='showcase'):
    """Crée un projet WordPress avec ou sans Next.js"""
    # Initialiser la variable pour tous les cas
    containers_started_by_service = False
    
    if debug_logger:
        debug_logger.step("WP_CREATE_START", f"Creating WordPress project, NextJS: {enable_nextjs}, Type: {wordpress_type}")
    
    # Sauvegarder le type WordPress
    from app.services.wordpress_type_service import WordPressTypeService
    wp_type_service = WordPressTypeService()
    wp_type_service.save_wordpress_type(project_name, wordpress_type)
    
    # Récupérer les limites de ressources selon le type
    resource_limits = wp_type_service.get_memory_limits(wordpress_type)
    
    if debug_logger:
        debug_logger.step("WP_TYPE_LIMITS", f"Resource limits: {resource_limits}")
    
    # Vérifier que l'image WordPress personnalisée existe
    if debug_logger:
        debug_logger.step("CHECK_WP_IMAGE", "Checking WordPress custom image")
    
    from app.services.wordpress_image_service import ensure_wordpress_image
    if not ensure_wordpress_image():
        if debug_logger:
            debug_logger.error("CHECK_WP_IMAGE", "Failed to ensure WordPress custom image exists")
        return jsonify({'success': False, 'message': 'Impossible de construire l\'image WordPress personnalisée'})
    
    if debug_logger:
        debug_logger.success("CHECK_WP_IMAGE", "WordPress custom image is available")
    
    # Configurer les ports
    if debug_logger:
        debug_logger.step("CONFIGURE_PORTS", "Configuring project ports")
    
    ports = _configure_wordpress_ports(project_name, enable_nextjs)
    
    if debug_logger:
        debug_logger.success("CONFIGURE_PORTS", f"Ports configured: {ports}")
    
    # Sauvegarder les ports immédiatement
    if debug_logger:
        debug_logger.step("SAVE_PORTS", "Saving project ports")
    
    _save_project_ports(project_name, ports)
    
    if debug_logger:
        debug_logger.success("SAVE_PORTS", "Project ports saved")
    
    print(f"📋 Copie du template Docker pour WordPress...")
    if debug_logger:
        debug_logger.step("COPY_DOCKER_TEMPLATE", f"Copying Docker template, NextJS enabled: {enable_nextjs}")
    
    try:
        if enable_nextjs:
            copy_docker_template(container_path, project_name, ports, enable_nextjs=True, resource_limits=resource_limits)
        else:
            copy_docker_template(container_path, project_name, ports, enable_nextjs=False, resource_limits=resource_limits)
        
        if debug_logger:
            debug_logger.success("COPY_DOCKER_TEMPLATE", "Docker template copied successfully")
    except Exception as e:
        if debug_logger:
            debug_logger.error("COPY_DOCKER_TEMPLATE", f"Failed to copy Docker template", e)
        raise
    
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
    
    # Configuration spécifique selon le type de projet
    wp_content_dest = os.path.join(editable_path, 'wp-content')
    print(f"📦 Configuration wp-content externe: {wp_content_dest}")
    
    # Assurer que wp-content existe
    os.makedirs(wp_content_dest, exist_ok=True)
    
    # Traiter selon si Next.js est activé ou non
    if enable_nextjs:
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            print(f"🚀 Utilisation de la méthode WordPress+Next.js avec wp-content de référence")
            success = docker_service.create_wordpress_nextjs_project(container_path, editable_path, project_name, ports)
            if not success:
                return jsonify({'success': False, 'message': 'Erreur lors de la création du projet WordPress+Next.js'})
            containers_started_by_service = True  # Les conteneurs ont été démarrés par le service
        else:
            print(f"⚠️ Service Docker non disponible, utilisation de la méthode classique")
            # Méthode classique comme fallback
    
    # Si aucune archive n'est fournie, installer WordPress automatiquement après le démarrage
    if not archive_path and not enable_nextjs:
        if debug_logger:
            debug_logger.step("AUTO_INSTALL_WP", "No archive provided, WordPress will be installed automatically after containers start")
        # Marquer pour installation après démarrage
        wp_needs_install = True
    else:
        wp_needs_install = False
    
    if not enable_nextjs:
            # Créer les fichiers de base WordPress (.htaccess et wp-config.php)
            if not create_wordpress_base_files(editable_path):
                return jsonify({'success': False, 'message': 'Erreur lors de la création des fichiers de base WordPress'})
            
            # Mettre à jour les URLs dans les fichiers WordPress
            update_project_wordpress_urls_in_files(editable_path, ports['wordpress'])
            
            # Créer la structure Next.js
            nextjs_path = os.path.join(editable_path, 'client')
            print(f"📦 Création de la structure Next.js dans: {nextjs_path}")
            
            # Utiliser la fonction existante ou créer un package.json minimal
            try:
                create_nextjs_app_structure(editable_path, project_name)
                print(f"✅ Structure Next.js complète créée")
            except Exception as e:
                print(f"⚠️ Erreur avec la structure complète, création minimale: {e}")
                from app.utils.project_utils import create_nextjs_package_json
                create_nextjs_package_json(nextjs_path, project_name)
                
            # Sauvegarder le port Next.js
            _save_project_ports(project_name, ports)
    else:
        # Projet WordPress simple - Créer les fichiers de base
        print(f"📝 Création des fichiers de base WordPress...")
        
        if debug_logger:
            debug_logger.step("PRE_FIX_WP_CONTENT_PERMISSIONS", "Pre-fixing wp-content permissions for simple WordPress project")
        
        # Corriger les permissions du wp-content AVANT la création des fichiers
        wp_content_path = os.path.join(editable_path, 'wp-content')
        if os.path.exists(wp_content_path):
            try:
                import subprocess
                current_user = os.getenv('USER', 'dev-server')
                subprocess.run(['sudo', 'chown', '-R', f'{current_user}:{current_user}', wp_content_path], check=True)
                subprocess.run(['chmod', '-R', '755', wp_content_path], check=True)
                
                if debug_logger:
                    debug_logger.success("PRE_FIX_WP_CONTENT_PERMISSIONS", "wp-content permissions fixed before file creation")
                print(f"✅ Permissions wp-content pré-corrigées pour {project_name}")
            except Exception as e:
                if debug_logger:
                    debug_logger.warning("PRE_FIX_WP_CONTENT_PERMISSIONS", f"Failed to fix permissions: {e}")
                print(f"⚠️ Erreur lors de la pré-correction des permissions: {e}")
        
        # Créer les fichiers de base WordPress (.htaccess et wp-config.php)
        if debug_logger:
            debug_logger.step("CREATE_WP_BASE_FILES", "Creating WordPress base files")
        
        if not create_wordpress_base_files(editable_path):
            if debug_logger:
                debug_logger.error("CREATE_WP_BASE_FILES", "Failed to create WordPress base files")
            return jsonify({'success': False, 'message': 'Erreur lors de la création des fichiers de base WordPress'})
        
        if debug_logger:
            debug_logger.success("CREATE_WP_BASE_FILES", "WordPress base files created successfully")
        
        # Corriger les permissions après la création aussi
        if os.path.exists(wp_content_path):
            try:
                import subprocess
                current_user = os.getenv('USER', 'dev-server')
                subprocess.run(['sudo', 'chown', '-R', f'{current_user}:{current_user}', wp_content_path], check=True)
                subprocess.run(['chmod', '-R', '755', wp_content_path], check=True)
                # Créer le dossier uploads s'il n'existe pas
                uploads_dir = os.path.join(wp_content_path, 'uploads')
                if not os.path.exists(uploads_dir):
                    os.makedirs(uploads_dir, mode=0o775, exist_ok=True)
                    subprocess.run(['sudo', 'chown', '-R', f'{current_user}:{current_user}', uploads_dir], check=True)
                subprocess.run(['chmod', '-R', '775', uploads_dir], check=True)
                
                if debug_logger:
                    debug_logger.success("POST_FIX_WP_CONTENT_PERMISSIONS", "wp-content permissions fixed after file creation")
                print(f"✅ Permissions wp-content post-corrigées pour {project_name}")
            except Exception as e:
                if debug_logger:
                    debug_logger.warning("POST_FIX_WP_CONTENT_PERMISSIONS", f"Failed to fix permissions: {e}")
                print(f"⚠️ Erreur lors de la post-correction des permissions: {e}")
        
        # Mettre à jour les URLs dans les fichiers WordPress
        if debug_logger:
            debug_logger.step("UPDATE_WP_URLS", "Updating WordPress URLs in files")
        
        try:
            update_project_wordpress_urls_in_files(editable_path, ports['wordpress'])
            if debug_logger:
                debug_logger.success("UPDATE_WP_URLS", "WordPress URLs updated successfully")
        except Exception as e:
            if debug_logger:
                debug_logger.error("UPDATE_WP_URLS", f"Failed to update WordPress URLs", e)
            raise
        
        # Pour les projets WordPress simples, utiliser aussi le service Docker pour l'installation automatique
        if debug_logger:
            debug_logger.step("DOCKER_SERVICE_START", "Starting Docker service for containers")
        
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            if debug_logger:
                debug_logger.step("START_CONTAINERS", "Starting Docker containers")
            
            print(f"🚀 Démarrage des conteneurs...")
            try:
                success, error = docker_service.start_containers(container_path)
                if success:
                    if debug_logger:
                        debug_logger.success("START_CONTAINERS", "Docker containers started successfully")
                    
                    print(f"✅ Conteneurs démarrés, lancement de l'installation automatique...")
                    
                    if debug_logger:
                        debug_logger.step("AUTO_INSTALL_WP", "Starting automatic WordPress installation")
                    
                    # Utiliser la fonction robuste d'installation automatique
                    try:
                        print(f"🔍 [DEBUG] Lancement installation automatique WordPress...")
                        install_success = docker_service.auto_install_wordpress_after_creation(project_name, container_path, debug_logger=debug_logger)
                        print(f"🔍 [DEBUG] Résultat installation: {install_success}")
                        
                        if install_success:
                            containers_started_by_service = True
                            if debug_logger:
                                debug_logger.success("AUTO_INSTALL_WP", f"WordPress installed automatically for {project_name}")
                            print(f"✅ WordPress installé automatiquement pour {project_name}")
                            
                            # AJOUT: Application automatique des permissions SEULEMENT après installation réussie
                            print(f"🔍 [DEBUG] Démarrage application permissions automatiques...")
                            if debug_logger:
                                debug_logger.step("AUTO_PERMISSIONS", "Applying automatic file permissions after successful installation")
                            
                            print(f"🔧 Application des permissions automatiques après installation...")
                            from app.utils.project_utils import apply_automatic_project_permissions
                            
                            print(f"🔍 [DEBUG] Chemin projet: {editable_path}")
                            permissions_success = apply_automatic_project_permissions(editable_path, 'wordpress')
                            print(f"🔍 [DEBUG] Résultat permissions: {permissions_success}")
                            
                            if permissions_success:
                                if debug_logger:
                                    debug_logger.success("AUTO_PERMISSIONS", f"Permissions automatically configured for {project_name}")
                                print(f"✅ Permissions automatiques configurées pour {project_name}")
                            else:
                                if debug_logger:
                                    debug_logger.warning("AUTO_PERMISSIONS", f"Failed to apply automatic permissions for {project_name}")
                                print(f"⚠️ Échec des permissions automatiques pour {project_name} - correction manuelle nécessaire")
                        else:
                            if debug_logger:
                                debug_logger.warning("AUTO_INSTALL_WP", f"Automatic installation failed for {project_name}")
                            print(f"⚠️ Installation automatique échouée pour {project_name}")
                            print(f"💡 Les permissions seront appliquées mais l'installation WordPress nécessite une intervention manuelle")
                    except Exception as auto_install_error:
                        if debug_logger:
                            debug_logger.error("AUTO_INSTALL_WP", f"Exception during automatic installation", auto_install_error)
                        print(f"❌ Exception lors de l'installation automatique: {auto_install_error}")
                        print(f"📋 Stack trace: {auto_install_error.__class__.__name__}: {auto_install_error}")
                        
                        # Continuer quand même pour permettre l'installation manuelle
                        containers_started_by_service = True
                        print(f"💡 L'installation WordPress devra être completée manuellement")
                        print(f"💡 Les permissions seront appliquées après l'installation manuelle via l'interface")
                else:
                    if debug_logger:
                        debug_logger.error("START_CONTAINERS", f"Failed to start containers: {error}")
                    print(f"⚠️ Erreur lors du démarrage des conteneurs: {error}")
            except Exception as e:
                if debug_logger:
                    debug_logger.error("DOCKER_OPERATIONS", f"Exception during Docker operations", e)
                raise
        else:
            if debug_logger:
                debug_logger.warning("DOCKER_SERVICE_START", "Docker service not available")
    
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
    
    # Démarrer les conteneurs (seulement si pas déjà démarrés par le service)
    docker_service = current_app.extensions.get('docker')
    if docker_service and not containers_started_by_service:
        success, error = docker_service.start_containers(container_path)
        if not success:
            return jsonify({'success': False, 'message': f'Erreur lors du démarrage: {error}'})
    
    # Appliquer les bonnes permissions après le premier démarrage
    print(f"🔧 Application des permissions correctes pour {project_name}...")
    from app.utils.project_utils import set_project_permissions
    
    if docker_service and not containers_started_by_service:
        # Arrêter temporairement les conteneurs pour corriger les permissions
        docker_service.stop_containers(container_path)
        import time
        time.sleep(2)  # Attendre que Docker libère les fichiers
        
        # Appliquer les permissions
        if set_project_permissions(editable_path):
            print(f"✅ Permissions appliquées avec succès")
            # Redémarrer les conteneurs
            success, error = docker_service.start_containers(container_path)
            if not success:
                print(f"⚠️ Erreur lors du redémarrage: {error}")
        else:
            print(f"⚠️ Erreur lors de l'application des permissions")
    elif not containers_started_by_service:
        print(f"⚠️ Service Docker non disponible pour corriger les permissions")
    else:
        print(f"✅ Permissions gérées par le service Docker")
    
    # Configurer la base de données et installer WordPress automatiquement
    if db_path:
        # TODO: Implémenter l'import de base de données
        success_message = f'Projet WordPress {project_name} créé avec succès !'
    elif containers_started_by_service:
        # La base de données et WordPress ont déjà été installés par le service
        success_message = f'Projet WordPress {project_name} créé et installé avec succès ! Prêt à utiliser.'
        print(f"✅ WordPress installé automatiquement par le service Docker")
    else:
        # Lancer l'installation automatique en arrière-plan pour tous les projets WordPress
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            print(f"🚀 Programmation de l'installation automatique WordPress...")
            
            # Lancer l'installation en arrière-plan avec un thread
            import threading
            def install_wordpress_background():
                try:
                    import time
                    print(f"⏳ [BACKGROUND] Attente de 10 secondes avant installation...")
                    time.sleep(10)  # Attendre que la réponse soit envoyée
                    
                    print(f"🚀 [BACKGROUND] Début import de base de données pour {project_name}")
                    
                    # Utiliser FastImportService pour importer db-migrate.sql
                    fast_import_service = FastImportService()
                    db_migrate_path = os.path.join(os.path.dirname(__file__), '..', 'docker-template', 'wordpress', 'db-migrate.sql')
                    
                    if os.path.exists(db_migrate_path):
                        result = fast_import_service.import_database(project_name, db_migrate_path)
                        if result.get('success'):
                            print(f"✅ [BACKGROUND] Base de données importée avec succès pour {project_name}")
                        else:
                            print(f"⚠️ [BACKGROUND] Import de base de données échoué pour {project_name}: {result.get('error', 'Erreur inconnue')}")
                    else:
                        print(f"❌ [BACKGROUND] Fichier db-migrate.sql introuvable: {db_migrate_path}")
                        
                except Exception as e:
                    print(f"❌ [BACKGROUND] Erreur import base de données: {e}")
            
            # Lancer le thread d'installation en arrière-plan
            install_thread = threading.Thread(target=install_wordpress_background, daemon=True)
            install_thread.start()
            
            success_message = f'Projet WordPress {project_name} créé avec succès ! Import de base de données en cours...'
        else:
            success_message = f'Projet WordPress {project_name} créé avec succès ! Import de base de données désactivé.'
    
    # Correction finale et robuste des permissions avant de terminer
    if debug_logger:
        debug_logger.step("FINAL_PERMISSIONS_SKIP", "Skipping host permissions fix - Docker handles container permissions")
    
    # CORRECTION: Ne pas écraser les permissions Docker optimales avec les permissions hôte
    # Le script init-permissions.sh dans le conteneur gère déjà les permissions parfaitement
    # wp_content_final_path = os.path.join(editable_path, 'wp-content')
    # fix_wp_content_permissions_robust(wp_content_final_path, debug_logger)
    
    if debug_logger:
        debug_logger.success("WORDPRESS_PROJECT_COMPLETE", f"WordPress project {project_name} created successfully")
    
    # Log du succès avec le système centralisé
    wp_logger.log_operation_success('create', project_name, 
                                  "Projet WordPress créé avec succès",
                                  project_path=editable_path,
                                  container_path=container_path,
                                  project_type="wordpress",
                                  enable_nextjs=enable_nextjs,
                                  urls=_get_project_urls(project_name, ports))
    
    return jsonify({
        'success': True, 
        'message': success_message,
        'project_name': project_name,
        'urls': _get_project_urls(project_name, ports)
    })


def _create_nextjs_project(project_name, editable_path, container_path, database_type, debug_logger=None):
    """Crée un projet Next.js"""
    print("📋 Copie du template Docker pour Next.js...")
    
    # Configurer les ports d'abord
    ports = _configure_nextjs_ports(project_name, database_type)
    
    if database_type == 'mongodb':
        copy_docker_template_nextjs_mongo(container_path, project_name, ports)
    else:
        copy_docker_template_nextjs_mysql(container_path, project_name, ports)
    
    # Créer la structure Next.js avec le type de base de données
    print("📦 Création de la structure Next.js App...")
    create_nextjs_app_structure(editable_path, project_name, database_type)
    
    # Sauvegarder les ports alloués
    _save_project_ports(project_name, ports)
    
    # Démarrer les conteneurs
    docker_service = current_app.extensions.get('docker')
    if docker_service:
        success, error = docker_service.start_containers(container_path)
        if not success:
            return jsonify({'success': False, 'message': f'Erreur lors du démarrage: {error}'})
    
    # AJOUT: Application automatique des permissions pour les projets Next.js
    print(f"🔧 Application des permissions automatiques pour le projet Next.js...")
    from app.utils.project_utils import apply_automatic_project_permissions
    
    permissions_success = apply_automatic_project_permissions(editable_path, 'nextjs')
    if permissions_success:
        print(f"✅ Permissions automatiques configurées pour {project_name}")
        success_message = f'Application Next.js {project_name} créée avec succès ! Permissions configurées automatiquement.'
    else:
        print(f"⚠️ Échec des permissions automatiques pour {project_name} - correction manuelle nécessaire")
        success_message = f'Application Next.js {project_name} créée avec succès ! (Permissions à corriger manuellement)'
    
    # Log du succès avec le système centralisé
    wp_logger.log_operation_success('create', project_name, 
                                  "Projet Next.js créé avec succès",
                                  project_path=editable_path,
                                  container_path=container_path,
                                  project_type="nextjs",
                                  database_type=database_type,
                                  permissions_success=permissions_success)
    
    return jsonify({
        'success': True, 
        'message': success_message,
        'project_name': project_name,
        'urls': _get_project_urls(project_name, ports)
    })


def _configure_wordpress_ports(project_name, enable_nextjs):
    """Configure les ports pour un projet WordPress avec sauvegarde automatique"""
    # Obtenir tous les ports utilisés
    existing_used_ports = get_used_ports()
    # Créer une liste locale pour suivre les ports alloués dans cette session
    allocated_ports = []
    ports = {}
    used_ports = set()
    
    # Commencer à partir de 8080 et chercher des ports libres séquentiellement
    current_port = 8080
    
    # Trouver le prochain port libre
    while current_port in existing_used_ports or current_port in allocated_ports:
        current_port += 1
        if current_port > 9000:
            raise Exception("Aucun port libre trouvé dans la plage 8080-9000")
    
    # Allouer les ports séquentiellement
    ports['wordpress'] = current_port
    allocated_ports.append(current_port)
    current_port += 1
    
    # Port phpMyAdmin
    while current_port in existing_used_ports or current_port in allocated_ports:
        current_port += 1
        if current_port > 9000:
            raise Exception("Aucun port libre trouvé pour phpMyAdmin")
    
    ports['phpmyadmin'] = current_port
    allocated_ports.append(current_port)
    current_port += 1
    
    # Port Next.js si activé
    if enable_nextjs:
        while current_port in existing_used_ports or current_port in allocated_ports:
            current_port += 1
            if current_port > 9000:
                raise Exception("Aucun port libre trouvé pour Next.js")
        
        ports['nextjs'] = current_port
        allocated_ports.append(current_port)
        current_port += 1
    
    # Port Mailpit
    while current_port in existing_used_ports or current_port in allocated_ports:
        current_port += 1
        if current_port > 9000:
            raise Exception("Aucun port libre trouvé pour Mailpit")
    
    ports['mailpit'] = current_port
    allocated_ports.append(current_port)
    current_port += 1
    
    # Port SMTP
    while current_port in existing_used_ports or current_port in allocated_ports:
        current_port += 1
        if current_port > 9000:
            raise Exception("Aucun port libre trouvé pour SMTP")
    
    ports['smtp'] = current_port
    
    # Sauvegarder les ports alloués
    _save_project_ports(project_name, ports)
    
    print(f"📋 Ports alloués pour {project_name}: {ports}")
    return ports


def _configure_nextjs_ports(project_name, database_type):
    """Configure les ports pour un projet Next.js"""
    # Obtenir tous les ports utilisés
    existing_used_ports = get_used_ports()
    # Créer une liste locale pour suivre les ports alloués dans cette session
    allocated_ports = []
    ports = {}
    
    # Commencer à partir de 8080 et chercher des ports libres séquentiellement
    current_port = 8080
    
    # Trouver le prochain port libre
    while current_port in existing_used_ports or current_port in allocated_ports:
        current_port += 1
        if current_port > 9000:
            raise Exception("Aucun port libre trouvé dans la plage 8080-9000")
    
    # Port principal Next.js
    ports['nextjs'] = current_port
    allocated_ports.append(current_port)
    current_port += 1
    
    # Port API Express
    while current_port in existing_used_ports or current_port in allocated_ports:
        current_port += 1
        if current_port > 9000:
            raise Exception("Aucun port libre trouvé pour l'API")
    
    ports['api'] = current_port
    allocated_ports.append(current_port)
    current_port += 1
    
    # Port base de données
    if database_type == 'mongodb':
        # Port MongoDB
        while current_port in existing_used_ports or current_port in allocated_ports:
            current_port += 1
            if current_port > 9000:
                raise Exception("Aucun port libre trouvé pour MongoDB")
        
        ports['mongodb'] = current_port
        allocated_ports.append(current_port)
        current_port += 1
        
        # Port Mongo Express
        while current_port in existing_used_ports or current_port in allocated_ports:
            current_port += 1
            if current_port > 9000:
                raise Exception("Aucun port libre trouvé pour Mongo Express")
        
        ports['mongo_express'] = current_port
        allocated_ports.append(current_port)
        current_port += 1
    else:
        # Port MySQL
        while current_port in existing_used_ports or current_port in allocated_ports:
            current_port += 1
            if current_port > 9000:
                raise Exception("Aucun port libre trouvé pour MySQL")
        
        ports['mysql'] = current_port
        allocated_ports.append(current_port)
        current_port += 1
        
        # Port phpMyAdmin
        while current_port in existing_used_ports or current_port in allocated_ports:
            current_port += 1
            if current_port > 9000:
                raise Exception("Aucun port libre trouvé pour phpMyAdmin")
        
        ports['phpmyadmin'] = current_port
        allocated_ports.append(current_port)
        current_port += 1
    
    # Port Mailpit
    while current_port in existing_used_ports or current_port in allocated_ports:
        current_port += 1
        if current_port > 9000:
            raise Exception("Aucun port libre trouvé pour Mailpit")
    
    ports['mailpit'] = current_port
    allocated_ports.append(current_port)
    current_port += 1
    
    # Port SMTP
    while current_port in existing_used_ports or current_port in allocated_ports:
        current_port += 1
        if current_port > 9000:
            raise Exception("Aucun port libre trouvé pour SMTP")
    
    ports['smtp'] = current_port
    
    print(f"📋 Ports alloués pour {project_name}: {ports}")
    return ports


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
            'nextjs': '.nextjs_port',
            'api': '.api_port',
            'mongodb': '.mongodb_port',
            'mysql': '.mysql_port',
            'mongo_express': '.mongo_express_port'
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





@project_lifecycle_bp.route('/start_project/<project_name>', methods=['POST'])
@login_required
def start_project(project_name):
    """Démarre un projet"""
    # Log du début de l'opération
    wp_logger.log_operation_start('start', project_name)
    
    try:
        print(f"🚀 Démarrage du projet: {project_name}")
        
        # Vérifier si le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            error_msg = 'Projet non trouvé'
            wp_logger.log_operation_error('start', project_name, error_msg, 
                                        context="Project validation", 
                                        project_path=project.path)
            return jsonify({'success': False, 'message': error_msg})
        
        # Vérifier si le projet est valide
        if not project.is_valid:
            error_msg = 'Projet invalide (fichier docker-compose.yml manquant)'
            wp_logger.log_operation_error('start', project_name, error_msg, 
                                        context="Docker compose validation", 
                                        container_path=project.container_path)
            return jsonify({'success': False, 'message': error_msg})
        
        # Démarrer les conteneurs
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            success, error = docker_service.start_containers(project.container_path)
            
            if success:
                wp_logger.log_operation_success('start', project_name, 
                                              "Conteneurs démarrés avec succès",
                                              container_path=project.container_path)
                
                # Récupérer l'URL du projet
                project_url = f'http://{DockerConfig.LOCAL_IP}:{project.port}'
                
                return jsonify({
                    'success': True,
                    'message': f'Projet {project_name} démarré avec succès',
                    'project_url': project_url,
                    'project_name': project_name
                })
            else:
                wp_logger.log_operation_error('start', project_name, f'Erreur Docker: {error}', 
                                            context="Docker container startup", 
                                            container_path=project.container_path)
                return jsonify({
                    'success': False,
                    'message': f'Erreur lors du démarrage: {error}'
                })
        else:
            error_msg = 'Service Docker non disponible'
            wp_logger.log_operation_error('start', project_name, error_msg, 
                                        context="Service availability check")
            return jsonify({
                'success': False,
                'message': error_msg
            })
        
    except Exception as e:
        print(f"❌ Erreur lors du démarrage du projet {project_name}: {e}")
        wp_logger.log_operation_error('start', project_name, e, 
                                    context="General exception during startup")
        return jsonify({
            'success': False,
            'message': f'Erreur lors du démarrage: {str(e)}'
        })


@project_lifecycle_bp.route('/stop_project/<project_name>', methods=['POST'])
@login_required
def stop_project(project_name):
    """Arrête un projet"""
    # Log du début de l'opération
    wp_logger.log_operation_start('stop', project_name)
    
    try:
        print(f"🛑 Arrêt du projet: {project_name}")
        
        # Vérifier si le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            error_msg = 'Projet non trouvé'
            wp_logger.log_operation_error('stop', project_name, error_msg, 
                                        context="Project validation", 
                                        project_path=project.path)
            return jsonify({'success': False, 'message': error_msg})
        
        # Vérifier si le projet est valide
        if not project.is_valid:
            error_msg = 'Projet invalide (fichier docker-compose.yml manquant)'
            wp_logger.log_operation_error('stop', project_name, error_msg, 
                                        context="Docker compose validation", 
                                        container_path=project.container_path)
            return jsonify({'success': False, 'message': error_msg})
        
        # Arrêter les conteneurs
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            success, error = docker_service.stop_containers(project.container_path)
            if success:
                wp_logger.log_operation_success('stop', project_name, 
                                              "Conteneurs arrêtés avec succès",
                                              container_path=project.container_path)
                return jsonify({
                    'success': True,
                    'message': f'Projet {project_name} arrêté avec succès'
                })
            else:
                wp_logger.log_operation_error('stop', project_name, f'Erreur Docker: {error}', 
                                            context="Docker container shutdown", 
                                            container_path=project.container_path)
                return jsonify({
                    'success': False,
                    'message': f'Erreur lors de l\'arrêt: {error}'
                })
        else:
            error_msg = 'Service Docker non disponible'
            wp_logger.log_operation_error('stop', project_name, error_msg, 
                                        context="Service availability check")
            return jsonify({
                'success': False,
                'message': error_msg
            })
        
    except Exception as e:
        print(f"❌ Erreur lors de l'arrêt du projet {project_name}: {e}")
        wp_logger.log_operation_error('stop', project_name, e, 
                                    context="General exception during shutdown")
        return jsonify({
            'success': False,
            'message': f'Erreur lors de l\'arrêt: {str(e)}'
        })


@project_lifecycle_bp.route('/restart_project/<project_name>', methods=['POST'])
@login_required
def restart_project(project_name):
    """Redémarre un projet (stop puis start)"""
    # Log du début de l'opération
    wp_logger.log_operation_start('restart', project_name)
    
    try:
        print(f"🔄 [RESTART_PROJECT] Début redémarrage du projet: {project_name}")
        
        # Récupérer le docker_service depuis les extensions
        docker_service = current_app.extensions.get('docker')
        if not docker_service:
            print(f"❌ [RESTART_PROJECT] Service Docker non disponible")
            return jsonify({
                'success': False,
                'message': 'Service Docker non disponible'
            }), 500
        
        # Vérifier que le projet existe
        container_path = os.path.join(CONTAINERS_FOLDER, project_name)
        if not os.path.exists(container_path):
            print(f"❌ [RESTART_PROJECT] Projet non trouvé: {container_path}")
            return jsonify({
                'success': False,
                'message': f'Le projet {project_name} n\'existe pas'
            })
        
        # Étape 1: Arrêter le projet
        print(f"🛑 [RESTART_PROJECT] Arrêt du projet {project_name}...")
        stop_success, stop_error = docker_service.stop_containers(container_path, timeout=60)
        
        if not stop_success:
            print(f"❌ [RESTART_PROJECT] Erreur lors de l'arrêt: {stop_error}")
            return jsonify({
                'success': False,
                'message': f'Erreur lors de l\'arrêt: {stop_error}'
            })
        
        print(f"✅ [RESTART_PROJECT] Conteneurs arrêtés avec succès")
        
        # Attendre un peu pour que l'arrêt soit complet
        time.sleep(2)
        
        # Étape 2: Démarrer le projet
        print(f"▶️ [RESTART_PROJECT] Démarrage du projet {project_name}...")
        start_success, start_error = docker_service.start_containers(container_path, timeout=120)
        
        if start_success:
            print(f"✅ [RESTART_PROJECT] Conteneurs démarrés avec succès")
            
            # Récupérer le projet pour avoir les infos de ports
            print(f"🔍 [RESTART_PROJECT] Récupération des informations du projet...")
            project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
            
            port = project.port or 'unknown'
            pma_port = project.pma_port
            mailpit = project.mailpit_port
            
            print(f"📊 [RESTART_PROJECT] Ports du projet:")
            print(f"   - WordPress: {port}")
            print(f"   - phpMyAdmin: {pma_port}")
            print(f"   - Mailpit: {mailpit}")
            
            # Construire l'URL du projet
            project_url = f"http://{DockerConfig.LOCAL_IP}:{port}"
            
            wp_logger.log_operation_success('restart', project_name, 
                                          context=f"Project restarted successfully on port {port}")
            
            print(f"🎉 [RESTART_PROJECT] Redémarrage terminé avec succès - URL: {project_url}")
            
            return jsonify({
                'success': True,
                'message': f'Projet {project_name} redémarré avec succès',
                'project_url': project_url,
                'details': {
                    'port': port,
                    'pma_port': pma_port,
                    'mailpit_port': mailpit
                }
            })
        else:
            print(f"❌ [RESTART_PROJECT] Erreur lors du démarrage: {start_error}")
            wp_logger.log_operation_error('restart', project_name, 
                                        Exception(start_error), 
                                        context="Failed to start after stop")
            return jsonify({
                'success': False,
                'message': f'Erreur lors du démarrage: {start_error}'
            })
        
    except Exception as e:
        import traceback
        print(f"❌ [RESTART_PROJECT] Exception lors du redémarrage du projet {project_name}:")
        print(traceback.format_exc())
        wp_logger.log_operation_error('restart', project_name, e, 
                                    context="General exception during restart")
        return jsonify({
            'success': False,
            'message': f'Erreur lors du redémarrage: {str(e)}'
        })


@project_lifecycle_bp.route('/rebuild_project/<project_name>', methods=['POST'])
@login_required
def rebuild_project(project_name):
    """Rebuild les conteneurs d'un projet en préservant les volumes"""
    # Log du début de l'opération
    wp_logger.log_operation_start('rebuild', project_name)
    
    try:
        print(f"🔄 [REBUILD_PROJECT] Début rebuild du projet: {project_name}")
        
        # Récupérer le docker_service depuis les extensions
        docker_service = current_app.extensions.get('docker')
        if not docker_service:
            print(f"❌ [REBUILD_PROJECT] Service Docker non disponible")
            return jsonify({
                'success': False,
                'message': 'Service Docker non disponible'
            }), 500
        
        # Vérifier que le projet existe
        container_path = os.path.join(CONTAINERS_FOLDER, project_name)
        if not os.path.exists(container_path):
            print(f"❌ [REBUILD_PROJECT] Projet non trouvé: {container_path}")
            return jsonify({
                'success': False,
                'message': f'Le projet {project_name} n\'existe pas'
            })
        
        # Rebuild les conteneurs
        print(f"🔧 [REBUILD_PROJECT] Rebuild des conteneurs {project_name}...")
        rebuild_success, rebuild_error = docker_service.rebuild_containers(container_path, timeout=180)
        
        if rebuild_success:
            print(f"✅ [REBUILD_PROJECT] Conteneurs rebuilt avec succès")
            
            # Récupérer le projet pour avoir les infos de ports
            print(f"🔍 [REBUILD_PROJECT] Récupération des informations du projet...")
            project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
            
            port = project.port or 'unknown'
            pma_port = project.pma_port
            mailpit = project.mailpit_port
            
            print(f"📊 [REBUILD_PROJECT] Ports du projet:")
            print(f"   - WordPress: {port}")
            print(f"   - phpMyAdmin: {pma_port}")
            print(f"   - Mailpit: {mailpit}")
            
            # Construire l'URL du projet
            project_url = f"http://{DockerConfig.LOCAL_IP}:{port}"
            
            wp_logger.log_operation_success('rebuild', project_name, 
                                          context=f"Project rebuilt successfully on port {port}")
            
            print(f"🎉 [REBUILD_PROJECT] Rebuild terminé avec succès - URL: {project_url}")
            
            return jsonify({
                'success': True,
                'message': f'Projet {project_name} rebuilt avec succès (volumes préservés)',
                'project_url': project_url,
                'details': {
                    'port': port,
                    'pma_port': pma_port,
                    'mailpit_port': mailpit
                }
            })
        else:
            print(f"❌ [REBUILD_PROJECT] Erreur lors du rebuild: {rebuild_error}")
            wp_logger.log_operation_error('rebuild', project_name, 
                                        Exception(rebuild_error), 
                                        context="Failed to rebuild containers")
            return jsonify({
                'success': False,
                'message': f'Erreur lors du rebuild: {rebuild_error}'
            })
        
    except Exception as e:
        import traceback
        print(f"❌ [REBUILD_PROJECT] Exception lors du rebuild du projet {project_name}:")
        print(traceback.format_exc())
        wp_logger.log_operation_error('rebuild', project_name, e, 
                                    context="General exception during rebuild")
        return jsonify({
            'success': False,
            'message': f'Erreur lors du rebuild: {str(e)}'
        })


@project_lifecycle_bp.route('/delete_project/<project_name>', methods=['DELETE'])
@login_required
def delete_project(project_name):
    """Supprime un projet"""
    try:
        project_service = current_app.extensions.get('project_service')
        if not project_service:
            return jsonify({
                'success': False,
                'message': 'ProjectService non disponible'
            }), 500
        
        print(f"🗑️ [DELETE API] Suppression du projet {project_name}")
        
        result = project_service.delete_project(project_name)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
            
    except Exception as e:
        print(f"❌ [DELETE API] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        }), 500


