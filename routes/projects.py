#!/usr/bin/env python3
"""
Routes pour la gestion des projets WordPress
"""

import os
import time
from flask import Blueprint, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename

from models.project import Project
from services.port_service import PortService
from services.docker_service import DockerService
from services.database_service import DatabaseService
from utils.file_utils import allowed_file, secure_project_name, secure_hostname

# Créer le blueprint
projects_bp = Blueprint('projects', __name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
PROJECTS_FOLDER = 'projets'

# Services
port_service = PortService(PROJECTS_FOLDER)
docker_service = DockerService()
database_service = None  # Sera initialisé avec SocketIO

def init_database_service(socketio):
    """Initialise le service de base de données avec SocketIO"""
    global database_service
    database_service = DatabaseService(socketio)

@projects_bp.route('/create_project', methods=['POST'])
def create_project():
    """Crée un nouveau projet WordPress"""
    try:
        print("🚀 Début de création du projet")
        
        # Récupérer les données du formulaire
        project_name = request.form['project_name'].strip()
        project_hostname = request.form.get('project_hostname', '').strip()
        
        if not project_name:
            flash('Le nom du projet est requis', 'error')
            return redirect(url_for('main.index'))
        
        # Nettoyer le nom du projet
        project_name = secure_project_name(project_name)
        
        # Générer l'hostname s'il n'est pas fourni
        if not project_hostname:
            project_hostname = f"{project_name}.local"
        else:
            project_hostname = secure_hostname(project_hostname)
        
        print(f"📝 Nom du projet: {project_name}")
        print(f"🌐 Hostname: {project_hostname}")
        
        # Vérifier si Next.js est demandé
        enable_nextjs = request.form.get('enable_nextjs') == 'on'
        print(f"⚡ Next.js demandé: {enable_nextjs}")
        
        # Créer l'objet projet
        project = Project(project_name, PROJECTS_FOLDER)
        
        if project.exists:
            flash(f'Le projet {project_name} existe déjà', 'error')
            return redirect(url_for('main.index'))
        
        # Vérifier le fichier archive WP Migrate Pro (optionnel)
        wp_migrate_archive = request.files.get('wp_migrate_archive')
        
        # Valider l'archive si fournie
        if wp_migrate_archive and wp_migrate_archive.filename:
            if not allowed_file(wp_migrate_archive.filename):
                flash('Type de fichier archive non autorisé', 'error')
                return redirect(url_for('main.index'))
            print(f"📦 Archive WP Migrate Pro: {wp_migrate_archive.filename}")
        else:
            wp_migrate_archive = None
            print("📦 Aucune archive WP Migrate Pro - site WordPress vierge")
        
        # Créer le répertoire du projet
        project.create_directory()
        
        # Allouer les ports
        ports = port_service.allocate_ports_for_project(enable_nextjs)
        print(f"🌐 Ports alloués: {ports}")
        
        # Copier et configurer le template Docker
        docker_service.copy_template(project.path, enable_nextjs)
        docker_service.configure_compose_file(project.path, project_name, ports, enable_nextjs)
        
        # Sauvegarder les ports
        project.port = ports['wordpress']
        project.pma_port = ports['phpmyadmin']
        project.mailpit_port = ports['mailpit']
        project.smtp_port = ports['smtp']
        if enable_nextjs:
            project.nextjs_port = ports['nextjs']
        
        # Sauvegarder l'hostname
        project.hostname = project_hostname
        
        # Traiter l'archive WP Migrate Pro si fournie
        wp_content_path = None
        db_path = None
        temp_paths = []
        
        if wp_migrate_archive:
            wp_migrate_filename = secure_filename(wp_migrate_archive.filename)
            wp_migrate_path = os.path.join(UPLOAD_FOLDER, wp_migrate_filename)
            wp_migrate_archive.save(wp_migrate_path)
            temp_paths.append(wp_migrate_path)
            
            # Traiter l'archive
            archive_data = project.process_wp_migrate_archive(wp_migrate_path, UPLOAD_FOLDER)
            wp_content_path = archive_data['wp_content_path']
            db_path = archive_data['db_path']
            temp_paths.append(archive_data['temp_extract_path'])
        
        # Créer wp-content
        project.create_wp_content(wp_content_path)
        
        # Configurer Next.js si demandé
        if enable_nextjs:
            project.setup_nextjs()
        
        # Démarrer les conteneurs
        print("🐳 Lancement de Docker Compose...")
        success, error = docker_service.start_containers(project.path)
        
        if not success:
            raise Exception(f"Erreur Docker Compose: {error}")
        
        print("✅ Conteneurs Docker lancés")
        
        # Attendre un peu que les conteneurs se lancent
        print("⏳ Attente du démarrage des conteneurs...")
        time.sleep(45)
        
        # Importer la base de données ou créer une base vierge
        if db_path:
            print("🗃️ Début import de la base de données...")
            if not database_service.import_database(project.path, db_path, project_name):
                flash('Projet créé mais erreur lors de l\'import de la base de données', 'warning')
            else:
                flash(f'Projet {project_name} créé avec succès !', 'success')
        else:
            print("🗃️ Création d'une base de données WordPress vierge...")
            if not database_service.create_clean_database(project.path, project_name):
                flash('Projet créé mais erreur lors de la création de la base de données', 'warning')
            else:
                flash(f'Projet {project_name} créé avec succès ! Rendez-vous sur le site pour terminer l\'installation WordPress.', 'success')
        
        print(f"🌐 Configuration terminée - Site accessible via http://192.168.1.21:{project.port}")
        
        # Nettoyer les fichiers temporaires
        print("🧹 Nettoyage des fichiers temporaires...")
        project.cleanup_temp_files(temp_paths)
        
        return redirect(url_for('main.index'))
        
    except Exception as e:
        print(f"❌ Erreur lors de la création du projet: {e}")
        flash(f'Erreur lors de la création du projet: {str(e)}', 'error')
        return redirect(url_for('main.index'))

@projects_bp.route('/projects')
def list_projects():
    """Liste les projets existants (ancienne route pour compatibilité)"""
    projects, _ = Project.list_all(PROJECTS_FOLDER)
    return jsonify([project.name for project in projects])

@projects_bp.route('/projects_with_status')
def list_projects_with_status():
    """Liste les projets existants avec leur statut et informations"""
    projects, projects_to_cleanup = Project.list_all(PROJECTS_FOLDER)
    
    # Nettoyer les projets corrompus
    if projects_to_cleanup:
        print(f"🧹 Nettoyage de {len(projects_to_cleanup)} projets corrompus...")
        for project_path in projects_to_cleanup:
            try:
                import subprocess
                subprocess.run(['sudo', 'rm', '-rf', project_path], 
                             capture_output=True, text=True, timeout=30)
                print(f"✅ Projet corrompu supprimé: {project_path}")
            except Exception as e:
                print(f"⚠️ Erreur lors du nettoyage de {project_path}: {e}")
    
    # Préparer les données des projets
    projects_data = []
    for project in projects:
        status = docker_service.get_container_status(project.name)
        project_data = project.to_dict()
        project_data['status'] = status
        projects_data.append(project_data)
    
    return jsonify(projects_data)

@projects_bp.route('/start_project/<project_name>', methods=['POST'])
def start_project(project_name):
    """Démarre tous les conteneurs d'un projet"""
    try:
        print(f"▶️ Démarrage du projet: {project_name}")
        
        project = Project(project_name, PROJECTS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        success, error = docker_service.start_containers(project.path)
        
        if success:
            print(f"✅ Projet {project_name} démarré")
            return jsonify({'success': True, 'message': 'Projet démarré avec succès'})
        else:
            print(f"❌ Erreur démarrage: {error}")
            return jsonify({'success': False, 'message': f'Erreur: {error}'})
            
    except Exception as e:
        print(f"❌ Erreur lors du démarrage: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@projects_bp.route('/stop_project/<project_name>', methods=['POST'])
def stop_project(project_name):
    """Arrête tous les conteneurs d'un projet"""
    try:
        print(f"⏹️ Arrêt du projet: {project_name}")
        
        project = Project(project_name, PROJECTS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        success, error = docker_service.stop_containers(project.path)
        
        if success:
            print(f"✅ Projet {project_name} arrêté")
            return jsonify({'success': True, 'message': 'Projet arrêté avec succès'})
        else:
            print(f"❌ Erreur arrêt: {error}")
            return jsonify({'success': False, 'message': f'Erreur: {error}'})
            
    except Exception as e:
        print(f"❌ Erreur lors de l'arrêt: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@projects_bp.route('/delete_project/<project_name>', methods=['DELETE'])
def delete_project(project_name):
    """Supprime complètement un projet"""
    try:
        print(f"🗑️ Suppression du projet: {project_name}")
        
        project = Project(project_name, PROJECTS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Arrêter et supprimer les conteneurs
        print("🐳 Arrêt des conteneurs Docker...")
        success, error = docker_service.remove_containers(project.path)
        
        if not success:
            print(f"⚠️ Erreur lors de l'arrêt des conteneurs: {error}")
        
        # Supprimer le dossier du projet
        print("📁 Suppression des fichiers du projet...")
        import subprocess
        result = subprocess.run([
            'sudo', 'rm', '-rf', project.path
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            print(f"✅ Projet {project_name} supprimé avec succès")
            
            # Nettoyer les ressources Docker
            docker_service.cleanup_unused_resources()
            
            return jsonify({'success': True, 'message': 'Projet supprimé avec succès'})
        else:
            return jsonify({'success': False, 'message': f'Erreur lors de la suppression: {result.stderr}'})
            
    except Exception as e:
        print(f"❌ Erreur lors de la suppression: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@projects_bp.route('/add_nextjs/<project_name>', methods=['POST'])
def add_nextjs_to_project(project_name):
    """Ajoute Next.js à un projet existant"""
    try:
        print(f"⚡ Ajout de Next.js au projet: {project_name}")
        
        project = Project(project_name, PROJECTS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if project.has_nextjs:
            return jsonify({'success': False, 'message': 'Next.js est déjà configuré pour ce projet'})
        
        # Allouer un port pour Next.js
        nextjs_port = port_service.find_free_port(3000)
        project.nextjs_port = nextjs_port
        
        # Configurer Next.js
        project.setup_nextjs()
        
        # Reconfigurer docker-compose avec Next.js
        ports = {
            'wordpress': project.port,
            'phpmyadmin': project.pma_port,
            'mailpit': project.mailpit_port,
            'smtp': project.smtp_port,
            'nextjs': nextjs_port
        }
        
        # Copier le template avec Next.js
        docker_service.copy_template(project.path, True)
        docker_service.configure_compose_file(project.path, project_name, ports, True)
        
        print(f"✅ Next.js ajouté au projet {project_name} sur le port {nextjs_port}")
        return jsonify({
            'success': True, 
            'message': 'Next.js ajouté avec succès',
            'nextjs_port': nextjs_port
        })
        
    except Exception as e:
        print(f"❌ Erreur lors de l'ajout de Next.js: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@projects_bp.route('/remove_nextjs/<project_name>', methods=['POST'])
def remove_nextjs_from_project(project_name):
    """Supprime Next.js d'un projet existant"""
    try:
        print(f"⚡ Suppression de Next.js du projet: {project_name}")
        
        project = Project(project_name, PROJECTS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Next.js n\'est pas configuré pour ce projet'})
        
        # Supprimer Next.js
        project.remove_nextjs()
        
        # Reconfigurer docker-compose sans Next.js
        ports = {
            'wordpress': project.port,
            'phpmyadmin': project.pma_port,
            'mailpit': project.mailpit_port,
            'smtp': project.smtp_port
        }
        
        # Copier le template sans Next.js
        docker_service.copy_template(project.path, False)
        docker_service.configure_compose_file(project.path, project_name, ports, False)
        
        print(f"✅ Next.js supprimé du projet {project_name}")
        return jsonify({'success': True, 'message': 'Next.js supprimé avec succès'})
        
    except Exception as e:
        print(f"❌ Erreur lors de la suppression de Next.js: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@projects_bp.route('/update_database/<project_name>', methods=['POST'])
def update_database(project_name):
    """Met à jour la base de données d'un projet existant"""
    try:
        print(f"🔄 Début mise à jour DB pour le projet: {project_name}")
        
        project = Project(project_name, PROJECTS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier le fichier uploadé
        if 'db_file' not in request.files:
            return jsonify({'success': False, 'message': 'Aucun fichier de base de données fourni'})
        
        db_file = request.files['db_file']
        if db_file.filename == '':
            return jsonify({'success': False, 'message': 'Aucun fichier sélectionné'})
        
        if not allowed_file(db_file.filename):
            return jsonify({'success': False, 'message': 'Type de fichier non autorisé'})
        
        # Sauvegarder le fichier temporairement
        db_filename = secure_filename(db_file.filename)
        db_path = os.path.join(UPLOAD_FOLDER, f"update_{db_filename}")
        db_file.save(db_path)
        
        # Vérifier que le conteneur MySQL est actif
        status = docker_service.get_container_status(project_name)
        if status != 'active':
            return jsonify({'success': False, 'message': 'Le conteneur MySQL n\'est pas actif. Veuillez d\'abord démarrer le projet.'})
        
        # Lancer l'import en arrière-plan
        database_service.import_database_async(project.path, db_path, project_name)
        
        return jsonify({
            'success': True, 
            'message': 'Import de la base de données démarré en arrière-plan'
        })
        
    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@projects_bp.route('/edit_hostname/<project_name>', methods=['POST'])
def edit_hostname(project_name):
    """Modifie l'hostname d'un projet"""
    try:
        project = Project(project_name, PROJECTS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        new_hostname = request.form.get('new_hostname', '').strip()
        if not new_hostname:
            return jsonify({'success': False, 'message': 'Hostname requis'})
        
        # Sécuriser l'hostname
        new_hostname = secure_hostname(new_hostname)
        
        # Mettre à jour l'hostname
        project.hostname = new_hostname
        
        print(f"✅ Hostname mis à jour pour {project_name}: {new_hostname}")
        return jsonify({'success': True, 'message': 'Hostname mis à jour avec succès'})
        
    except Exception as e:
        print(f"❌ Erreur lors de la modification de l'hostname: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@projects_bp.route('/export_database/<project_name>')
def export_database(project_name):
    """Exporte la base de données d'un projet"""
    try:
        project = Project(project_name, PROJECTS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier que le projet est actif
        status = docker_service.get_container_status(project_name)
        if status != 'active':
            return jsonify({'success': False, 'message': 'Le projet doit être actif pour exporter la base de données'})
        
        # Effectuer l'export
        export_path = os.path.join(UPLOAD_FOLDER, f"{project_name}_export.sql")
        success, error = database_service.export_database(project_name, export_path)
        
        if success:
            return jsonify({
                'success': True, 
                'message': 'Base de données exportée avec succès',
                'export_path': export_path
            })
        else:
            return jsonify({'success': False, 'message': f'Erreur lors de l\'export: {error}'})
            
    except Exception as e:
        print(f"❌ Erreur lors de l'export: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@projects_bp.route('/project_logs/<project_name>/<service_name>')
def get_project_logs(project_name, service_name):
    """Récupère les logs d'un service d'un projet"""
    try:
        project = Project(project_name, PROJECTS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        lines = request.args.get('lines', 50, type=int)
        logs = docker_service.get_container_logs(project_name, service_name, lines)
        
        return jsonify({'success': True, 'logs': logs})
        
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des logs: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@projects_bp.route('/server_info')
def server_info():
    """Retourne les informations du serveur"""
    try:
        import socket
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        # Informations sur les ports
        port_info = port_service.get_port_usage_info()
        
        return jsonify({
            'hostname': hostname,
            'ip': local_ip,
            'ports': port_info
        })
    except Exception as e:
        return jsonify({'error': str(e)}) 