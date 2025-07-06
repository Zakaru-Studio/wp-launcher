#!/usr/bin/env python3
import os
import shutil
import subprocess
import zipfile
import sqlite3
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import tempfile
import time
import threading
import re

# Imports des services modularisés
from models.project import Project
from services.docker_service import DockerService
from services.port_service import PortService
from services.database_service import DatabaseService

app = Flask(__name__)
app.secret_key = 'wp-launcher-secret-key-2024'

# Configuration SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialisation des services
docker_service = DockerService()
port_service = PortService()
database_service = DatabaseService(socketio)

# Configuration
UPLOAD_FOLDER = 'uploads'
PROJECTS_FOLDER = 'projets'
ALLOWED_EXTENSIONS = {'zip', 'sql', 'gz'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024  # 5GB max

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def find_free_port_for_project(start_port=8080):
    """Trouve un port libre pour un nouveau projet"""
    import re
    
    # Récupérer les ports utilisés par Docker
    try:
        result = subprocess.run(['docker', 'ps', '--format', '{{.Ports}}'], 
                               capture_output=True, text=True)
        used_ports = []
        for line in result.stdout.strip().split('\n'):
            if line:
                port_matches = re.findall(r'0\.0\.0\.0:(\d+)->', line)
                used_ports.extend([int(port) for port in port_matches])
    except Exception:
        used_ports = []
    
    # Récupérer les ports des projets existants
    if os.path.exists(PROJECTS_FOLDER):
        for project in os.listdir(PROJECTS_FOLDER):
            project_path = os.path.join(PROJECTS_FOLDER, project)
            if os.path.isdir(project_path):
                port_file = os.path.join(project_path, '.port')
                if os.path.exists(port_file):
                    try:
                        with open(port_file, 'r') as f:
                            used_ports.append(int(f.read().strip()))
                    except (ValueError, IOError):
                        pass
    
    # Trouver un port libre
    port = start_port
    while port in used_ports:
        port += 1
        if port > 9000:
            raise Exception("Aucun port libre trouvé entre 8080 et 9000")
    
    return port

def extract_zip(zip_path, extract_to):
    """Extrait un fichier ZIP vers le dossier de destination"""
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)

def copy_docker_template(project_path):
    """Copie le template docker-compose dans le projet"""
    template_path = 'docker-template'
    if os.path.exists(template_path):
        for item in os.listdir(template_path):
            src = os.path.join(template_path, item)
            dst = os.path.join(project_path, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

def create_default_wp_content(wp_content_dest):
    """Crée un wp-content vierge avec les éléments de base"""
    print("📁 Création des dossiers wp-content de base...")
    
    # Créer les dossiers de base
    os.makedirs(os.path.join(wp_content_dest, 'themes'), exist_ok=True)
    os.makedirs(os.path.join(wp_content_dest, 'plugins'), exist_ok=True)
    os.makedirs(os.path.join(wp_content_dest, 'uploads'), exist_ok=True)
    
    # Créer un fichier index.php de sécurité
    index_content = "<?php\n// Silence is golden.\n"
    
    with open(os.path.join(wp_content_dest, 'index.php'), 'w') as f:
        f.write(index_content)
    
    with open(os.path.join(wp_content_dest, 'themes', 'index.php'), 'w') as f:
        f.write(index_content)
    
    with open(os.path.join(wp_content_dest, 'plugins', 'index.php'), 'w') as f:
        f.write(index_content)
    
    with open(os.path.join(wp_content_dest, 'uploads', 'index.php'), 'w') as f:
        f.write(index_content)
    
    print("✅ wp-content vierge créé avec succès")

def create_clean_wordpress_database(project_path, project_name):
    """Crée une base de données WordPress vierge prête pour l'installation"""
    try:
        container_name = f"{project_name}_mysql_1"
        print(f"🐳 Conteneur MySQL: {container_name}")
        
        # Attendre que MySQL soit prêt
        print("🧠 Attente de la disponibilité MySQL...")
        if not intelligent_mysql_wait(container_name, project_name, max_wait_time=60):
            print("❌ MySQL n'est pas prêt après 60 secondes")
            return False
        
        # Créer la base de données WordPress vierge
        print("🗃️ Création de la base de données WordPress vierge...")
        result = subprocess.run([
            'docker', 'exec', container_name, 'mysql', 
            '-u', 'wordpress', '-pwordpress', 
            '-e', 'CREATE DATABASE IF NOT EXISTS wordpress DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            print(f"❌ Erreur lors de la création de la base: {result.stderr}")
            return False
        
        print("✅ Base de données WordPress vierge créée avec succès")
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la création de la base de données: {e}")
        return False

def smart_mysql_check(container_name, timeout=2):
    """Test instantané pour vérifier si MySQL est prêt"""
    try:
        result = subprocess.run([
            'docker', 'exec', container_name, 'mysql', 
            '-u', 'wordpress', '-pwordpress', 
            '-e', 'SELECT 1'
        ], capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        return False

def intelligent_mysql_wait(container_name, project_name, max_wait_time=60):
    """Attente intelligente de MySQL - teste d'abord, puis attend seulement si nécessaire"""
    
    # 🚀 TEST INSTANTANÉ : MySQL est-il déjà prêt ?
    print("🔍 Test instantané de MySQL...")
    if smart_mysql_check(container_name, timeout=1):
        print("✅ MySQL déjà prêt ! Aucune attente nécessaire.")
        return True
    
    print("⏳ MySQL pas encore prêt, attente intelligente...")
    
    # 🎯 ATTENTE PROGRESSIVE : Intervalles adaptatifs
    wait_phases = [
        (3, 1),    # 3 tentatives × 1 seconde = tests rapides
        (5, 2),    # 5 tentatives × 2 secondes = redémarrage normal  
        (8, 3),    # 8 tentatives × 3 secondes = démarrage standard
        (10, 5)    # 10 tentatives × 5 secondes = gros démarrage
    ]
    
    total_attempts = 0
    start_time = time.time()
    
    for phase_attempts, interval in wait_phases:
        for attempt in range(phase_attempts):
            total_attempts += 1
            elapsed = time.time() - start_time
            
            # Arrêter si on dépasse le temps maximum
            if elapsed > max_wait_time:
                print(f"❌ Timeout après {elapsed:.1f}s d'attente")
                return False
            
            print(f"⏳ Test MySQL {total_attempts} (intervalle: {interval}s)")
            
            # Emmettre le progrès pour l'interface
            socketio.emit('import_progress', {
                'project': project_name,
                'progress': min(15 + (elapsed / max_wait_time) * 10, 25),
                'message': f'Attente MySQL... ({elapsed:.0f}s)',
                'status': 'waiting'
            })
            
            if smart_mysql_check(container_name, timeout=3):
                print(f"✅ MySQL prêt après {elapsed:.1f}s ({total_attempts} tentatives)")
                return True
            
            time.sleep(interval)
    
    print(f"❌ MySQL non disponible après {max_wait_time}s d'attente")
    return False

def import_database(project_path, db_file_path, project_name):
    """Importe la base de données dans le conteneur MySQL avec progress bar"""
    try:
        print(f"🔍 DEBUG: Début import DB pour {project_name}")
        print(f"🔍 DEBUG: Chemin projet: {project_path}")
        print(f"🔍 DEBUG: Fichier DB: {db_file_path}")
        
        # Envoyer le statut initial
        socketio.emit('import_progress', {
            'project': project_name,
            'progress': 0,
            'message': 'Initialisation...',
            'status': 'starting'
        })
        
        # Attendre que Docker soit prêt (optimisé)
        print("⏳ Attente que Docker soit prêt...")
        socketio.emit('import_progress', {
            'project': project_name,
            'progress': 5,
            'message': 'Attente de Docker...',
            'status': 'waiting'
        })
        time.sleep(5)  # Attente réduite à 5 secondes
        
        # Vérifier que le fichier existe
        if not os.path.exists(db_file_path):
            raise Exception(f"Fichier de base de données non trouvé: {db_file_path}")
        
        socketio.emit('import_progress', {
            'project': project_name,
            'progress': 10,
            'message': 'Vérification du fichier...',
            'status': 'checking'
        })
        
        # Si c'est un fichier ZIP, l'extraire d'abord
        if db_file_path.endswith('.zip'):
            print("📦 Extraction de l'archive ZIP...")
            socketio.emit('import_progress', {
                'project': project_name,
                'progress': 15,
                'message': 'Extraction de l\'archive...',
                'status': 'extracting'
            })
            
            with tempfile.TemporaryDirectory() as temp_dir:
                extract_zip(db_file_path, temp_dir)
                # Chercher le fichier .sql dans l'extraction
                sql_files = [f for f in os.listdir(temp_dir) if f.endswith('.sql')]
                if not sql_files:
                    raise Exception("Aucun fichier .sql trouvé dans l'archive")
                sql_file = os.path.join(temp_dir, sql_files[0])
                print(f"📄 Fichier SQL trouvé: {sql_files[0]}")
                
                socketio.emit('import_progress', {
                    'project': project_name,
                    'progress': 20,
                    'message': 'Détection de l\'encodage...',
                    'status': 'analyzing'
                })
                
                # Détecter l'encodage du fichier SQL extrait
                print("🔍 Détection de l'encodage du fichier SQL...")
                detected_encoding = 'utf-8'
                encodings_to_try = ['utf-8', 'latin-1', 'windows-1252', 'iso-8859-1']
                
                sql_content = None
                for encoding in encodings_to_try:
                    try:
                        with open(sql_file, 'r', encoding=encoding) as f:
                            sql_content = f.read()
                            detected_encoding = encoding
                            print(f"✅ Encodage détecté: {encoding}")
                            break
                    except UnicodeDecodeError:
                        print(f"⚠️ Échec avec encodage {encoding}")
                        continue
                
                if sql_content is None:
                    raise Exception("Impossible de lire le fichier SQL avec les encodages supportés")
        else:
            sql_file = db_file_path
            print(f"📄 Utilisation du fichier SQL: {os.path.basename(sql_file)}")
            
            # Détecter l'encodage du fichier SQL
            print("🔍 Détection de l'encodage du fichier SQL...")
            detected_encoding = 'utf-8'
            encodings_to_try = ['utf-8', 'latin-1', 'windows-1252', 'iso-8859-1']
            
            sql_content = None
            for encoding in encodings_to_try:
                try:
                    with open(sql_file, 'r', encoding=encoding) as f:
                        sql_content = f.read()
                        detected_encoding = encoding
                        print(f"✅ Encodage détecté: {encoding}")
                        break
                except UnicodeDecodeError:
                    print(f"⚠️ Échec avec encodage {encoding}")
                    continue
            
            if sql_content is None:
                raise Exception("Impossible de lire le fichier SQL avec les encodages supportés")
            
        # Nom du conteneur
        container_name = f"{project_name}_mysql_1"
        print(f"🐳 Conteneur MySQL: {container_name}")
        
        # Vérifier que le conteneur existe et fonctionne
        print("🔍 Vérification du conteneur MySQL...")
        result = subprocess.run([
            'docker', 'ps', '--filter', f'name={container_name}', '--format', '{{.Names}}'
        ], capture_output=True, text=True, cwd=project_path)
        
        if container_name not in result.stdout:
            raise Exception(f"Conteneur MySQL {container_name} non trouvé ou arrêté")
        
        print("✅ Conteneur MySQL trouvé et actif")
        
        # 🚀 ATTENTE INTELLIGENTE DE MYSQL
        print("🧠 Démarrage de l'attente intelligente MySQL...")
        if not intelligent_mysql_wait(container_name, project_name, max_wait_time=60):
            raise Exception("MySQL n'est pas prêt après 1 minute d'attente intelligente")
        
        # Copier le fichier SQL dans le conteneur
        print("📋 Copie du fichier SQL dans le conteneur...")
        result = subprocess.run([
            'docker', 'cp', sql_file, f'{container_name}:/tmp/import.sql'
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Erreur lors de la copie du fichier SQL: {result.stderr}")
        
        print("✅ Fichier SQL copié dans le conteneur")
        
        # Importer la base de données avec méthode robuste
        print("🗃️ Import de la base de données...")
        print(f"🔍 Taille du fichier SQL: {os.path.getsize(sql_file)} bytes")
        
        # Déterminer la méthode d'import selon la taille
        file_size_mb = os.path.getsize(sql_file) / (1024 * 1024)
        print(f"📊 Taille du fichier: {file_size_mb:.1f} MB")
        
        if file_size_mb > 100:  # Plus de 100MB, utiliser la méthode streaming
            print("🔄 Méthode streaming pour gros fichier...")
            
            socketio.emit('import_progress', {
                'project': project_name,
                'progress': 40,
                'message': 'Préparation du fichier pour import...',
                'status': 'preparing'
            })
            
            # Créer un fichier temporaire UTF-8 dans le conteneur
            print("📝 Création du fichier temporaire UTF-8...")
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False, encoding='utf-8') as temp_file:
                temp_file.write(sql_content)
                temp_sql_file = temp_file.name
            
            socketio.emit('import_progress', {
                'project': project_name,
                'progress': 50,
                'message': 'Copie vers le conteneur...',
                'status': 'copying'
            })
            
            # Copier le fichier temporaire vers le conteneur
            result = subprocess.run([
                'docker', 'cp', temp_sql_file, f'{container_name}:/tmp/import_stream.sql'
            ], capture_output=True, text=True, timeout=300)
            
            # Nettoyer le fichier temporaire local
            os.unlink(temp_sql_file)
            
            if result.returncode != 0:
                raise Exception(f"Erreur lors de la copie: {result.stderr}")
                
            print("✅ Fichier copié, début de l'import...")
            
            socketio.emit('import_progress', {
                'project': project_name,
                'progress': 60,
                'message': f'Import en cours... ({file_size_mb:.1f} MB)',
                'status': 'importing'
            })
            
            # Démarrer le monitoring en arrière-plan
            def monitor_import():
                for i in range(60, 95, 5):
                    time.sleep(30)  # Attendre 30 secondes entre chaque update
                    socketio.emit('import_progress', {
                        'project': project_name,
                        'progress': i,
                        'message': f'Import en cours... ({i-50}% estimé)',
                        'status': 'importing'
                    })
            
            monitoring_thread = threading.Thread(target=monitor_import)
            monitoring_thread.daemon = True
            monitoring_thread.start()
            
            # Import avec monitoring
            result = subprocess.run([
                'docker', 'exec', container_name, 'mysql', 
                '-u', 'wordpress', '-pwordpress', 'wordpress',
                '--max_allowed_packet=2048M',
                '--default-character-set=utf8mb4',
                '-e', 'source /tmp/import_stream.sql'
            ], capture_output=True, text=True, timeout=7200)  # 2 heures max
            
            # Nettoyer le fichier dans le conteneur
            subprocess.run([
                'docker', 'exec', container_name, 'rm', '-f', '/tmp/import_stream.sql'
            ], capture_output=True, text=True)
            
        else:
            # Méthode 1: Utilisation de mysql avec redirection (petits fichiers)
            print("🔄 Méthode 1: Import via redirection...")
            result = subprocess.run([
                'docker', 'exec', '-i', container_name, 'mysql', 
                '-u', 'wordpress', '-pwordpress', 'wordpress',
                '--max_allowed_packet=1024M',
                '--default-character-set=utf8mb4'
            ], input=sql_content, text=True, capture_output=True, timeout=1800)
        
        if result.returncode == 0:
            print("✅ Base de données importée avec succès (méthode 1)")
        else:
            print(f"⚠️ Erreur méthode 1: {result.stderr}")
            print(f"⚠️ Output: {result.stdout}")
            
            # Méthode 2: Import via source (copier le fichier avec le bon encodage)
            print("🔄 Méthode 2: Import via source...")
            # Réécrire le fichier avec UTF-8 dans le conteneur
            result = subprocess.run([
                'docker', 'exec', '-i', container_name, 'bash', '-c',
                'cat > /tmp/import_utf8.sql'
            ], input=sql_content, text=True, capture_output=True, timeout=300)
            
            if result.returncode == 0:
                result = subprocess.run([
                    'docker', 'exec', container_name, 'mysql', 
                    '-u', 'wordpress', '-pwordpress', 'wordpress',
                    '--max_allowed_packet=1024M',
                    '--default-character-set=utf8mb4',
                    '-e', 'source /tmp/import_utf8.sql'
                ], capture_output=True, text=True, cwd=project_path, timeout=1800)
            
            if result.returncode == 0:
                print("✅ Base de données importée avec succès (méthode 2)")
            else:
                print(f"⚠️ Erreur méthode 2: {result.stderr}")
                print(f"⚠️ Output: {result.stdout}")
                
                # Méthode 3: Import par chunks
                print("🔄 Méthode 3: Import par chunks...")
                try:
                    # Utiliser le contenu déjà lu avec le bon encodage
                    statements = sql_content.split(';')
                    total_statements = len(statements)
                    print(f"📊 {total_statements} statements à importer")
                    
                    for i, statement in enumerate(statements):
                        if statement.strip():
                            chunk_result = subprocess.run([
                                'docker', 'exec', '-i', container_name, 'mysql', 
                                '-u', 'wordpress', '-pwordpress', 'wordpress',
                                '--default-character-set=utf8mb4'
                            ], input=statement + ';', text=True, capture_output=True, timeout=300)
                            
                            if chunk_result.returncode != 0:
                                if 'Duplicate entry' not in chunk_result.stderr:
                                    print(f"❌ Erreur statement {i+1}: {chunk_result.stderr}")
                            
                            if i % 100 == 0:
                                print(f"📊 Progress: {i}/{total_statements} statements")
                    
                    print("✅ Base de données importée avec succès (méthode 3)")
                except Exception as chunk_error:
                    print(f"❌ Erreur méthode 3: {chunk_error}")
                    raise Exception(f"Toutes les méthodes d'import ont échoué. Dernière erreur: {result.stderr}")
        
        # Vérifier que l'import a réussi
        print("🔍 Vérification de l'import...")
        check_result = subprocess.run([
            'docker', 'exec', container_name, 'mysql', 
            '-u', 'wordpress', '-pwordpress', 'wordpress',
            '-e', 'SHOW TABLES;'
        ], capture_output=True, text=True, timeout=30)
        
        if check_result.returncode == 0 and check_result.stdout.strip():
            table_count = len(check_result.stdout.strip().split('\n')) - 1
            print(f"✅ Import vérifié: {table_count} tables trouvées")
        else:
            print(f"⚠️ Vérification échouée: {check_result.stderr}")
        
        print("✅ Import de la base de données terminé")
        
        # Nettoyer le fichier temporaire dans le conteneur
        subprocess.run([
            'docker', 'exec', container_name, 'rm', '-f', '/tmp/import.sql', '/tmp/import_stream.sql', '/tmp/import_utf8.sql'
        ], capture_output=True, cwd=project_path)
        
        socketio.emit('import_progress', {
            'project': project_name,
            'progress': 100,
            'message': 'Import terminé avec succès !',
            'status': 'completed'
        })
        
        return True
    except Exception as e:
        print(f"❌ Erreur lors de l'import de la base de données: {e}")
        socketio.emit('import_progress', {
            'project': project_name,
            'progress': 0,
            'message': f'Erreur: {str(e)}',
            'status': 'error'
        })
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return '', 204  # Retourner une réponse vide avec code 204 (No Content)

@app.route('/create_project', methods=['POST'])
def create_project():
    try:
        print("🚀 Début de création du projet")
        
        # Récupérer les données du formulaire
        project_name = request.form['project_name'].strip()
        project_hostname = request.form.get('project_hostname', '').strip()
        enable_nextjs = request.form.get('enable_nextjs') == 'on'
        
        if not project_name:
            return jsonify({'success': False, 'message': 'Le nom du projet est requis'})
        
        # Nettoyer le nom du projet
        project_name = secure_filename(project_name.replace(' ', '-').lower())
        
        # Générer l'hostname s'il n'est pas fourni
        if not project_hostname:
            project_hostname = f"{project_name}.local"
        else:
            # Nettoyer l'hostname
            project_hostname = project_hostname.lower().replace(' ', '-')
            if not project_hostname.endswith('.local') and not project_hostname.endswith('.dev'):
                project_hostname += '.local'
        
        print(f"📝 Nom du projet: {project_name}")
        print(f"🌐 Hostname: {project_hostname}")
        print(f"⚛️ Next.js activé: {enable_nextjs}")
        
        # Vérifier le fichier uploadé (optionnel)
        wp_migrate_archive = request.files.get('wp_migrate_archive')
        
        # Valider le fichier s'il est fourni
        if wp_migrate_archive and wp_migrate_archive.filename:
            if not allowed_file(wp_migrate_archive.filename):
                return jsonify({'success': False, 'message': 'Type de fichier non autorisé'})
            print(f"📁 Fichier WP Migrate: {wp_migrate_archive.filename}")
        else:
            wp_migrate_archive = None
            print("📁 Aucun fichier WP Migrate - site WordPress vierge")
        
        # ÉTAPE 1: Créer l'objet Project et vérifier s'il existe déjà
        project = Project(project_name, PROJECTS_FOLDER)
        if project.exists:
            return jsonify({'success': False, 'message': f'Le projet {project_name} existe déjà'})
        
        # ÉTAPE 2: Créer le répertoire du projet
        print(f"📂 Création du dossier: {project.path}")
        project.create_directory()
        
        # ÉTAPE 3: Allouer les ports pour le projet
        print("🔍 Allocation des ports...")
        ports = port_service.allocate_ports_for_project(enable_nextjs)
        print(f"🌐 Ports alloués: {ports}")
        
        # ÉTAPE 4: Configurer les ports du projet
        project.port = ports['wordpress']
        project.pma_port = ports['phpmyadmin']
        project.mailpit_port = ports['mailpit']
        project.smtp_port = ports['smtp']
        if enable_nextjs:
            project.nextjs_port = ports['nextjs']
        
        # ÉTAPE 5: Définir l'hostname
        project.hostname = project_hostname
        
        # ÉTAPE 6: Copier et configurer Docker
        print("📋 Configuration Docker...")
        docker_service.copy_template(project.path, enable_nextjs)
        docker_service.configure_compose_file(project.path, project_name, ports, enable_nextjs)
        print("✅ Configuration Docker terminée")
        
        # ÉTAPE 7: Traiter le fichier uploadé
        wp_content_path = None
        db_path = None
        temp_extract_path = None
        
        if wp_migrate_archive and wp_migrate_archive.filename:
            # Sauvegarder le fichier temporairement
            archive_filename = secure_filename(wp_migrate_archive.filename)
            archive_path = os.path.join(app.config['UPLOAD_FOLDER'], archive_filename)
            wp_migrate_archive.save(archive_path)
            print(f"💾 Fichier sauvegardé: {archive_path}")
            
            # Analyser le type de fichier
            filename_lower = archive_path.lower()
            if filename_lower.endswith('.sql') or filename_lower.endswith('.gz'):
                # Fichier SQL pour base de données
                db_path = archive_path
                print(f"📄 Fichier SQL détecté: {db_path}")
            elif filename_lower.endswith('.zip'):
                # Fichier ZIP - traiter avec la méthode Project
                print(f"📦 Archive ZIP détectée: {archive_path}")
                archive_data = project.process_wp_migrate_archive(archive_path, app.config['UPLOAD_FOLDER'])
                wp_content_path = archive_data['wp_content_path']
                db_path = archive_data['db_path']
                temp_extract_path = archive_data['temp_extract_path']
                print(f"📦 Archive traitée - wp-content: {wp_content_path}, DB: {db_path}")
        
        # ÉTAPE 8: Créer wp-content
        print("📦 Configuration wp-content...")
        project.create_wp_content(wp_content_path)
        print("✅ wp-content configuré")
        
        # ÉTAPE 8.5: Configurer wp-config.php
        print("⚙️ Configuration wp-config.php...")
        docker_service.configure_wp_config(project.path, ports)
        print("✅ wp-config.php configuré")
        
        # ÉTAPE 9: Configurer Next.js si activé
        if enable_nextjs:
            print("⚛️ Configuration Next.js...")
            project.setup_nextjs()
            print("✅ Next.js configuré")
        
        # ÉTAPE 10: Démarrer les conteneurs Docker
        print("🐳 Démarrage des conteneurs Docker...")
        success, error = docker_service.start_containers(project.path)
        if not success:
            raise Exception(f"Erreur lors du démarrage des conteneurs: {error}")
        print("✅ Conteneurs Docker démarrés")
        
        # ÉTAPE 11: Attendre que les services soient prêts
        print("⏳ Attente du démarrage des services...")
        time.sleep(5)  # Attendre un peu avant de vérifier MySQL
        
        # ÉTAPE 12: Configurer la base de données
        if db_path:
            print("🗃️ Import de la base de données...")
            # Utiliser DatabaseService pour l'import
            success = database_service.import_database(project.path, db_path, project_name)
            if not success:
                return jsonify({'success': False, 'message': 'Projet créé mais erreur lors de l\'import de la base de données'})
            success_message = f'Projet {project_name} créé avec succès !'
        else:
            print("🗃️ Création d'une base de données WordPress vierge...")
            # Utiliser DatabaseService pour créer une base vierge
            success = database_service.create_clean_database(project.path, project_name)
            if not success:
                return jsonify({'success': False, 'message': 'Projet créé mais erreur lors de la création de la base de données'})
            success_message = f'Projet {project_name} créé avec succès ! Rendez-vous sur le site pour terminer l\'installation WordPress.'
        
        # ÉTAPE 13: Ajouter l'hostname au fichier /etc/hosts
        print(f"🌐 Ajout de l'hostname {project_hostname} au fichier /etc/hosts...")
        try:
            script_path = os.path.join(os.path.dirname(__file__), 'manage_hosts.sh')
            if os.path.exists(script_path):
                subprocess.run(['sudo', script_path, 'add', project_hostname], check=True, timeout=10)
                print(f"✅ Hostname {project_hostname} ajouté aux hosts")
        except Exception as e:
            print(f"⚠️ Erreur lors de l'ajout de l'hostname: {e}")
            print("💡 Vous pouvez ajouter manuellement l'entrée:")
            print(f"   echo '127.0.0.1    {project_hostname}' | sudo tee -a /etc/hosts")
        
        # ÉTAPE 14: Nettoyer les fichiers temporaires
        print("🧹 Nettoyage des fichiers temporaires...")
        temp_files = []
        if wp_migrate_archive and wp_migrate_archive.filename:
            temp_files.append(archive_path)
        if temp_extract_path:
            temp_files.append(temp_extract_path)
        
        project.cleanup_temp_files(temp_files)
        print("✅ Fichiers temporaires nettoyés")
        
        print(f"🎉 Projet {project_name} créé avec succès !")
        return jsonify({'success': True, 'message': success_message})
        
    except Exception as e:
        print(f"❌ Erreur lors de la création du projet: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur lors de la création du projet: {str(e)}'})

@app.route('/projects')
def list_projects():
    """Liste les projets existants (ancienne route pour compatibilité)"""
    projects = []
    if os.path.exists(PROJECTS_FOLDER):
        for project_name in os.listdir(PROJECTS_FOLDER):
            project_path = os.path.join(PROJECTS_FOLDER, project_name)
            if os.path.isdir(project_path):
                # Ignorer les dossiers marqués comme supprimés
                deleted_marker = os.path.join(project_path, '.DELETED_PROJECT')
                if os.path.exists(deleted_marker):
                    continue
                
                # Vérifier si le dossier est accessible (permissions)
                if not os.access(project_path, os.R_OK):
                    continue
                
                projects.append(project_name)
    return jsonify(projects)

@app.route('/projects_with_status')
def list_projects_with_status():
    """Liste les projets existants avec leur statut et hostname"""
    projects = []
    
    # Lire le fichier global des projets supprimés
    deleted_projects_file = os.path.join(PROJECTS_FOLDER, '.deleted_projects')
    globally_deleted_projects = set()
    if os.path.exists(deleted_projects_file):
        try:
            with open(deleted_projects_file, 'r') as f:
                globally_deleted_projects = set(line.strip() for line in f.readlines() if line.strip())
        except Exception:
            pass
    
    if os.path.exists(PROJECTS_FOLDER):
        for project_name in os.listdir(PROJECTS_FOLDER):
            project_path = os.path.join(PROJECTS_FOLDER, project_name)
            if os.path.isdir(project_path):
                # Ignorer les dossiers marqués comme supprimés localement
                deleted_marker = os.path.join(project_path, '.DELETED_PROJECT')
                if os.path.exists(deleted_marker):
                    print(f"⚠️ Projet {project_name} marqué comme supprimé localement, ignoré")
                    continue
                
                # Ignorer les projets marqués comme supprimés globalement
                if project_name in globally_deleted_projects:
                    print(f"⚠️ Projet {project_name} marqué comme supprimé globalement, ignoré")
                    continue
                
                # Vérifier si le dossier est accessible (permissions)
                if not os.access(project_path, os.R_OK):
                    print(f"⚠️ Projet {project_name} non accessible, permissions problématiques")
                    continue
                
                # Créer l'objet Project et utiliser ses propriétés
                project = Project(project_name, PROJECTS_FOLDER)
                
                # Vérifier le statut des conteneurs
                status = docker_service.get_container_status(project_name)
                
                projects.append({
                    'name': project_name,
                    'status': status,
                    'hostname': project.hostname,
                    'port': project.port,
                    'pma_port': project.pma_port,
                    'mailpit_port': project.mailpit_port,
                    'smtp_port': project.smtp_port,
                    'nextjs_enabled': project.has_nextjs,
                    'nextjs_port': project.nextjs_port if project.has_nextjs else None
                })
    return jsonify({'projects': projects})

@app.route('/server_info')
def server_info():
    """Retourne les informations du serveur"""
    import socket
    try:
        # Obtenir l'IP du serveur
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        server_ip = s.getsockname()[0]
        s.close()
    except Exception:
        server_ip = "127.0.0.1"
    
    return jsonify({
        'server_ip': server_ip,
        'wordpress_port': 8080,
        'launcher_port': 5000
    })

def check_project_status(project_name):
    """Vérifie si les conteneurs d'un projet sont actifs"""
    try:
        mysql_container = f"{project_name}_mysql_1"
        wp_container = f"{project_name}_wordpress_1"
        
        # Vérifier si les conteneurs sont en cours d'exécution
        result = subprocess.run([
            'docker', 'ps', '--format', '{{.Names}}'
        ], capture_output=True, text=True)
        
        running_containers = result.stdout.strip().split('\n')
        
        if mysql_container in running_containers and wp_container in running_containers:
            return 'active'
        else:
            return 'inactive'
    except Exception:
        return 'inactive'

@app.route('/update_database/<project_name>', methods=['POST'])
def update_database(project_name):
    """Met à jour la base de données d'un projet existant"""
    try:
        print(f"🔄 Début mise à jour DB pour le projet: {project_name}")
        
        # Vérifier que le projet existe
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier le fichier uploadé
        if 'db_file' not in request.files:
            return jsonify({'success': False, 'message': 'Aucun fichier de base de données fourni'})
        
        db_file = request.files['db_file']
        if db_file.filename == '':
            return jsonify({'success': False, 'message': 'Aucun fichier sélectionné'})
        
        if not allowed_file(db_file.filename):
            return jsonify({'success': False, 'message': 'Type de fichier non autorisé'})
        
        print(f"📁 Fichier reçu: {db_file.filename}")
        
        # Sauvegarder le fichier temporairement
        if db_file.filename:
            db_filename = secure_filename(db_file.filename)
            db_path = os.path.join(app.config['UPLOAD_FOLDER'], f"update_{db_filename}")
            db_file.save(db_path)
        else:
            return jsonify({'success': False, 'message': 'Nom de fichier invalide'})
        
        print(f"💾 Fichier sauvegardé: {db_path}")
        
        # Vérifier que le conteneur MySQL est actif
        mysql_container = f"{project_name}_mysql_1"
        result = subprocess.run([
            'docker', 'ps', '--format', '{{.Names}}'
        ], capture_output=True, text=True)
        
        if mysql_container not in result.stdout:
            return jsonify({'success': False, 'message': 'Le conteneur MySQL n\'est pas actif. Veuillez d\'abord démarrer le projet.'})
        
        # 🚀 ATTENTE INTELLIGENTE DE MYSQL POUR UPDATE
        print("🧠 Test intelligent MySQL pour mise à jour...")
        if not intelligent_mysql_wait(mysql_container, project_name, max_wait_time=45):
            return jsonify({'success': False, 'message': 'MySQL n\'est pas prêt après 45 secondes d\'attente intelligente'})
        
        # Supprimer l'ancienne base de données
        print("🗑️ Suppression de l'ancienne base de données...")
        drop_result = subprocess.run([
            'docker', 'exec', mysql_container, 'mysql', 
            '-u', 'wordpress', '-pwordpress', 
            '-e', 'DROP DATABASE IF EXISTS wordpress; CREATE DATABASE wordpress;'
        ], capture_output=True, text=True, timeout=60)
        
        if drop_result.returncode != 0:
            print(f"⚠️ Erreur lors de la suppression: {drop_result.stderr}")
            return jsonify({'success': False, 'message': 'Erreur lors de la suppression de l\'ancienne base de données'})
        
        print("✅ Ancienne base de données supprimée")
        
        # Importer la nouvelle base de données
        print("📥 Import de la nouvelle base de données...")
        import_success = import_database(project_path, db_path, project_name)
        
        # Nettoyer le fichier temporaire
        try:
            os.remove(db_path)
        except Exception as e:
            print(f"⚠️ Erreur lors du nettoyage: {e}")
        
        if import_success:
            print("✅ Base de données mise à jour avec succès")
            return jsonify({'success': True, 'message': 'Base de données mise à jour avec succès'})
        else:
            return jsonify({'success': False, 'message': 'Erreur lors de l\'import de la nouvelle base de données'})
        
    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour de la base de données: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/delete_project/<project_name>', methods=['DELETE'])
def delete_project(project_name):
    """Supprime complètement un projet (conteneurs, images, volumes, fichiers)"""
    try:
        print(f"🗑️ Début suppression du projet: {project_name}")
        
        # Créer l'objet Project
        project = Project(project_name, PROJECTS_FOLDER)
        
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # ÉTAPE 1: Arrêter et supprimer les conteneurs Docker
        print("🐳 Suppression des conteneurs Docker...")
        
        # Méthode 1: Utiliser DockerService si le fichier docker-compose.yml existe
        compose_file_exists = os.path.exists(os.path.join(project.path, 'docker-compose.yml'))
        if compose_file_exists:
            success, error = docker_service.remove_containers(project.path)
            if success:
                print("✅ Conteneurs Docker supprimés via docker-compose")
            else:
                print(f"⚠️ Erreur docker-compose: {error}")
                compose_file_exists = False  # Passer à la méthode manuelle
        
        # Méthode 2: Suppression manuelle des conteneurs si docker-compose échoue ou n'existe pas
        if not compose_file_exists:
            print("🔧 Suppression manuelle des conteneurs Docker...")
            try:
                # Arrêter et supprimer tous les conteneurs avec le nom du projet
                containers_result = subprocess.run([
                    'docker', 'ps', '-a', '--format', '{{.Names}}', '--filter', f'name={project_name}'
                ], capture_output=True, text=True)
                
                if containers_result.stdout.strip():
                    for container in containers_result.stdout.strip().split('\n'):
                        if container and project_name in container:
                            print(f"🛑 Arrêt du conteneur: {container}")
                            subprocess.run(['docker', 'stop', container], capture_output=True, timeout=30)
                            subprocess.run(['docker', 'rm', '-f', container], capture_output=True, timeout=30)
                            print(f"✅ Conteneur supprimé: {container}")
                    print("✅ Tous les conteneurs du projet supprimés")
                else:
                    print("ℹ️ Aucun conteneur Docker trouvé pour ce projet")
            except Exception as e:
                print(f"⚠️ Erreur lors de la suppression manuelle des conteneurs: {e}")
        
        # ÉTAPE 2: Nettoyer les volumes Docker spécifiques au projet
        print("💾 Suppression des volumes Docker...")
        try:
            volumes_result = subprocess.run([
                'docker', 'volume', 'ls', '--format', '{{.Name}}', '--filter', f'name={project_name}'
            ], capture_output=True, text=True)
            
            if volumes_result.stdout.strip():
                for volume in volumes_result.stdout.strip().split('\n'):
                    if volume and project_name in volume.lower():
                        subprocess.run(['docker', 'volume', 'rm', '-f', volume], capture_output=True)
                        print(f"💾 Volume supprimé: {volume}")
            
            # Aussi essayer avec des patterns plus larges
            for pattern in [f'*{project_name}*', f'{project_name}_*', f'*_{project_name}*']:
                volumes_result = subprocess.run([
                    'docker', 'volume', 'ls', '-q', '--filter', f'name={pattern}'
                ], capture_output=True, text=True)
                
                if volumes_result.stdout.strip():
                    for volume in volumes_result.stdout.strip().split('\n'):
                        if volume:
                            subprocess.run(['docker', 'volume', 'rm', '-f', volume], capture_output=True)
                            print(f"💾 Volume pattern supprimé: {volume}")
                            
        except Exception as e:
            print(f"⚠️ Erreur lors de la suppression des volumes: {e}")
        
        # ÉTAPE 3: Nettoyer les images Docker spécifiques au projet
        print("🗑️ Suppression des images Docker...")
        try:
            images_result = subprocess.run([
                'docker', 'images', '--format', '{{.Repository}}:{{.Tag}}', '--filter', f'reference=*{project_name}*'
            ], capture_output=True, text=True)
            
            if images_result.stdout.strip():
                for image in images_result.stdout.strip().split('\n'):
                    if image and project_name in image.lower():
                        subprocess.run(['docker', 'rmi', '-f', image], capture_output=True)
                        print(f"🗑️ Image supprimée: {image}")
        except Exception as e:
            print(f"⚠️ Erreur lors de la suppression des images: {e}")
        
        # ÉTAPE 4: Nettoyer les réseaux Docker du projet
        print("🌐 Suppression des réseaux Docker...")
        try:
            networks_result = subprocess.run([
                'docker', 'network', 'ls', '--format', '{{.Name}}', '--filter', f'name={project_name}'
            ], capture_output=True, text=True)
            
            if networks_result.stdout.strip():
                for network in networks_result.stdout.strip().split('\n'):
                    if network and project_name in network.lower() and network not in ['bridge', 'host', 'none']:
                        subprocess.run(['docker', 'network', 'rm', network], capture_output=True)
                        print(f"🌐 Réseau supprimé: {network}")
        except Exception as e:
            print(f"⚠️ Erreur lors de la suppression des réseaux: {e}")
        
        # ÉTAPE 5: Supprimer l'hostname du fichier /etc/hosts
        print(f"🌐 Suppression de l'hostname du fichier /etc/hosts...")
        try:
            hostname = project.hostname
            script_path = os.path.join(os.path.dirname(__file__), 'manage_hosts.sh')
            if os.path.exists(script_path):
                subprocess.run(['sudo', script_path, 'remove', hostname], check=True, timeout=10)
                print(f"✅ Hostname {hostname} supprimé des hosts")
        except Exception as e:
            print(f"⚠️ Erreur lors de la suppression de l'hostname: {e}")
        
        # ÉTAPE 6: Marquer le projet comme supprimé (TOUJOURS)
        print("🏷️ Marquage du projet comme supprimé...")
        deleted_marker = os.path.join(project.path, '.DELETED_PROJECT')
        
        try:
            # Corriger les permissions du dossier d'abord
            subprocess.run(['sudo', 'chmod', '777', project.path], 
                         capture_output=True, text=True, timeout=5)
            
            # Essayer d'écrire le fichier marqueur
            with open(deleted_marker, 'w') as f:
                f.write('deleted\n')
            print("✅ Projet marqué comme supprimé")
        except Exception as e:
            print(f"⚠️ Erreur création fichier marqueur: {e}")
            # Tentative avec sudo
            try:
                subprocess.run(['sudo', 'touch', deleted_marker], capture_output=True, timeout=5)
                print("✅ Projet marqué comme supprimé (avec sudo)")
            except Exception as e2:
                print(f"⚠️ Erreur marquage avec sudo: {e2}")
                # Dernière tentative: fichier global
                try:
                    deleted_projects_file = os.path.join(PROJECTS_FOLDER, '.deleted_projects')
                    with open(deleted_projects_file, 'a') as f:
                        f.write(f"{project_name}\n")
                    print("✅ Projet marqué comme supprimé (fichier global)")
                except Exception as e3:
                    print(f"⚠️ Erreur marquage global: {e3}")
                    # Ultime tentative avec sudo sur fichier global
                    try:
                        subprocess.run(['sudo', 'bash', '-c', f'echo "{project_name}" >> {deleted_projects_file}'], 
                                     capture_output=True, timeout=5)
                        print("✅ Projet marqué comme supprimé (fichier global avec sudo)")
                    except Exception as e4:
                        print(f"⚠️ Erreur finale: {e4}")
                        print("❌ Impossible de marquer le projet comme supprimé")
        
        # ÉTAPE 7: Nettoyage final des ressources Docker orphelines
        print("🧹 Nettoyage final des ressources Docker...")
        try:
            docker_service.cleanup_unused_resources()
        except Exception as e:
            print(f"⚠️ Erreur nettoyage final: {e}")
        
        # ÉTAPE 8: Tentative de suppression physique des fichiers (optionnelle)
        print("📁 Tentative de suppression des fichiers...")
        try:
            # Correction des permissions
            subprocess.run(['sudo', 'chmod', '-R', '777', project.path], 
                         capture_output=True, text=True, timeout=10)
            
            # Suppression avec sudo
            result = subprocess.run([
                'sudo', 'rm', '-rf', project.path
            ], capture_output=True, text=True, timeout=20)
            
            if result.returncode == 0:
                print("✅ Fichiers supprimés physiquement")
            else:
                print(f"⚠️ Suppression physique échouée: {result.stderr}")
        except Exception as e:
            print(f"⚠️ Erreur suppression physique: {e}")
        
        print(f"✅ Suppression du projet {project_name} terminée")
        
        return jsonify({
            'success': True,
            'message': 'Projet supprimé avec succès',
            'details': 'Conteneurs Docker supprimés, volumes nettoyés, projet marqué comme supprimé'
        })
        
    except Exception as e:
        print(f"❌ Erreur lors de la suppression du projet: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/edit_hostname/<project_name>', methods=['POST'])
def edit_hostname(project_name):
    """Édite l'hostname d'un projet existant"""
    try:
        print(f"✏️ Début édition hostname pour le projet: {project_name}")
        
        # Vérifier que le projet existe
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Récupérer les données JSON
        data = request.get_json()
        if not data or 'new_hostname' not in data:
            return jsonify({'success': False, 'message': 'Nouveau hostname non fourni'})
        
        new_hostname = data['new_hostname'].strip()
        if not new_hostname:
            return jsonify({'success': False, 'message': 'Hostname vide'})
        
        # Validation du hostname
        if not re.match(r'^[a-zA-Z0-9.-]+$', new_hostname):
            return jsonify({'success': False, 'message': 'Le hostname ne peut contenir que des lettres, chiffres, points et tirets'})
        
        # Validation supplémentaire pour éviter les erreurs
        if new_hostname.startswith('http://') or new_hostname.startswith('https://') or new_hostname.startswith('@'):
            return jsonify({'success': False, 'message': 'Le hostname ne doit pas contenir de protocole (http://) ou de caractères spéciaux (@)'})
        
        # Vérifier que le hostname se termine par .local ou .dev
        if not (new_hostname.endswith('.local') or new_hostname.endswith('.dev')):
            new_hostname += '.local'
        
        print(f"🌐 Nouveau hostname: {new_hostname}")
        
        # Lire l'ancien hostname
        hostname_file = os.path.join(project_path, '.hostname')
        old_hostname = f"{project_name}.local"  # Valeur par défaut
        
        if os.path.exists(hostname_file):
            try:
                with open(hostname_file, 'r') as f:
                    old_hostname = f.read().strip()
            except Exception:
                pass
        
        print(f"🔄 Ancien hostname: {old_hostname}")
        
        # Vérifier si le hostname a changé
        if old_hostname == new_hostname:
            return jsonify({'success': True, 'message': 'Hostname déjà correct'})
        
        # Mettre à jour le fichier docker-compose.yml
        compose_file = os.path.join(project_path, 'docker-compose.yml')
        if os.path.exists(compose_file):
            print("⚙️ Mise à jour du fichier docker-compose.yml...")
            
            with open(compose_file, 'r') as f:
                compose_content = f.read()
            
            # Remplacer l'ancien hostname par le nouveau
            compose_content = compose_content.replace(old_hostname, new_hostname)
            
            with open(compose_file, 'w') as f:
                f.write(compose_content)
            
            print("✅ docker-compose.yml mis à jour")
        else:
            return jsonify({'success': False, 'message': 'Fichier docker-compose.yml non trouvé'})
        
        # Sauvegarder le nouveau hostname
        with open(hostname_file, 'w') as f:
            f.write(new_hostname)
        print(f"✅ Nouveau hostname sauvegardé: {new_hostname}")
        
        # Mettre à jour le wp-config.php avec le nouveau hostname
        wp_config_file = os.path.join(project_path, 'wordpress', 'wp-config.php')
        print(f"⚙️ Mise à jour WordPress config: {wp_config_file}")
        if os.path.exists(wp_config_file):
            with open(wp_config_file, 'r') as f:
                wp_content = f.read()
            # Remplacer les URLs avec l'ancien hostname par le nouveau
            wp_content = wp_content.replace(f'http://{old_hostname}:8080', f'http://{new_hostname}:8080')
            with open(wp_config_file, 'w') as f:
                f.write(wp_content)
            print("✅ WordPress config mis à jour avec le nouveau hostname")
        else:
            print("⚠️ Fichier wp-config.php non trouvé")
        
        # Mettre à jour les URLs dans la base de données WordPress
        mysql_container = f"{project_name}_mysql_1"
        print("🗃️ Mise à jour des URLs WordPress dans la base de données...")
        try:
            # Mettre à jour les options WordPress pour utiliser le nouveau hostname
            update_sql = f"""
                UPDATE wp_options SET option_value = 'http://{new_hostname}:8080' WHERE option_name = 'home';
                UPDATE wp_options SET option_value = 'http://{new_hostname}:8080' WHERE option_name = 'siteurl';
            """
            
            result = subprocess.run([
                'docker', 'exec', mysql_container, 'mysql', 
                '-u', 'wordpress', '-pwordpress', 'wordpress',
                '-e', update_sql
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("✅ URLs WordPress mises à jour dans la base de données")
            else:
                print(f"⚠️ Erreur lors de la mise à jour des URLs WordPress: {result.stderr}")
                
        except Exception as e:
            print(f"⚠️ Erreur lors de la mise à jour de la base de données: {e}")
        
        # Mettre à jour le fichier /etc/hosts
        print("🌐 Mise à jour du fichier /etc/hosts...")
        try:
            script_path = os.path.join(os.path.dirname(__file__), 'manage_hosts.sh')
            
            # Supprimer l'ancien hostname
            subprocess.run(['sudo', script_path, 'remove', old_hostname], check=True)
            print(f"✅ Ancien hostname {old_hostname} supprimé des hosts")
            
            # Ajouter le nouveau hostname
            subprocess.run(['sudo', script_path, 'add', new_hostname], check=True)
            print(f"✅ Nouveau hostname {new_hostname} ajouté aux hosts")
            
        except subprocess.CalledProcessError as e:
            print(f"⚠️ Erreur lors de la mise à jour des hosts: {e}")
            return jsonify({'success': False, 'message': 'Erreur lors de la mise à jour du fichier /etc/hosts'})
        
        # Redémarrer les conteneurs pour appliquer les changements
        print("🔄 Redémarrage des conteneurs...")
        try:
            original_cwd = os.getcwd()
            os.chdir(project_path)
            
            try:
                # Arrêter les conteneurs
                result = subprocess.run([
                    'docker-compose', 'down'
                ], capture_output=True, text=True)
                
                if result.returncode != 0:
                    print(f"⚠️ Erreur lors de l'arrêt: {result.stderr}")
                
                # Relancer les conteneurs
                result = subprocess.run([
                    'docker-compose', 'up', '-d'
                ], capture_output=True, text=True)
                
                if result.returncode != 0:
                    print(f"⚠️ Erreur lors du redémarrage: {result.stderr}")
                    return jsonify({'success': False, 'message': 'Erreur lors du redémarrage des conteneurs'})
                
                print("✅ Conteneurs redémarrés")
                
            finally:
                os.chdir(original_cwd)
                
        except Exception as e:
            print(f"⚠️ Erreur lors du redémarrage: {e}")
            return jsonify({'success': False, 'message': 'Erreur lors du redémarrage des conteneurs'})
        
        print(f"✅ Hostname du projet {project_name} mis à jour avec succès")
        return jsonify({'success': True, 'message': f'Hostname mis à jour avec succès. Le site est maintenant accessible sur {new_hostname}'})
        
    except Exception as e:
        print(f"❌ Erreur lors de l'édition de l'hostname: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/add_nextjs/<project_name>', methods=['POST'])
def add_nextjs_to_project(project_name):
    """Ajoute Next.js à un projet existant"""
    try:
        print(f"⚡ Ajout de Next.js au projet: {project_name}")
        
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier si Next.js n'est pas déjà présent
        nextjs_port_file = os.path.join(project_path, '.nextjs_port')
        if os.path.exists(nextjs_port_file):
            return jsonify({'success': False, 'message': 'Next.js est déjà configuré pour ce projet'})
        
        # Trouver un port libre pour Next.js
        nextjs_port = find_free_port_for_project(3000)
        
        # Sauvegarder le port Next.js
        with open(nextjs_port_file, 'w') as f:
            f.write(str(nextjs_port))
        
        # Créer le dossier nextjs
        nextjs_path = os.path.join(project_path, 'nextjs')
        os.makedirs(nextjs_path, exist_ok=True)
        
        # Créer package.json et README comme dans la création
        package_json = {
            "name": f"{project_name}-frontend",
            "version": "0.1.0",
            "private": True,
            "scripts": {
                "dev": "next dev",
                "build": "next build", 
                "start": "next start",
                "lint": "next lint"
            },
            "dependencies": {
                "next": "14.0.0",
                "react": "^18",
                "react-dom": "^18"
            },
            "devDependencies": {
                "eslint": "^8",
                "eslint-config-next": "14.0.0"
            }
        }
        
        import json
        with open(os.path.join(nextjs_path, 'package.json'), 'w') as f:
            json.dump(package_json, f, indent=2)
        
        # Créer une page d'exemple Next.js
        pages_dir = os.path.join(nextjs_path, 'pages')
        os.makedirs(pages_dir, exist_ok=True)
        
        index_content = f"""import Head from 'next/head';

export default function Home() {{
  return (
    <div style={{{{ padding: '20px', fontFamily: 'Arial, sans-serif' }}}}>
      <Head>
        <title>{project_name} - Next.js Frontend</title>
        <meta name="description" content="Frontend Next.js pour {project_name}" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <main>
        <h1 style={{{{ color: '#0070f3' }}}}>🚀 {project_name}</h1>
        <p>Bienvenue sur le frontend Next.js de votre projet !</p>
        
        <div style={{{{ marginTop: '30px' }}}}>
          <h2>🔗 Connexion WordPress</h2>
          <p>Votre WordPress est accessible depuis Next.js via : <strong>http://wordpress</strong></p>
          
          <h3>API WordPress</h3>
          <p>L'API REST WordPress est disponible à :</p>
          <ul>
            <li>Depuis Next.js : <code>http://wordpress/wp-json/wp/v2/</code></li>
            <li>Depuis l'extérieur : <code>http://192.168.1.21/wp-json/wp/v2/</code></li>
          </ul>
          
          <h3>Exemple d'utilisation</h3>
          <pre style={{{{ background: '#f4f4f4', padding: '15px', borderRadius: '5px' }}}}>
{{`// Récupérer les articles WordPress
const response = await fetch('http://wordpress/wp-json/wp/v2/posts');
const posts = await response.json();`}}
          </pre>
        </div>
        
        <div style={{{{ marginTop: '30px' }}}}>
          <h2>🛠️ Développement</h2>
          <p>Modifiez ce fichier dans <code>nextjs/pages/index.js</code> pour commencer !</p>
          <p>Le serveur Next.js redémarre automatiquement lors des modifications.</p>
        </div>
      </main>
    </div>
  );
}}
"""
        
        with open(os.path.join(pages_dir, 'index.js'), 'w') as f:
            f.write(index_content)
        
        # Modifier le docker-compose.yml pour ajouter le service Next.js
        compose_file = os.path.join(project_path, 'docker-compose.yml')
        if os.path.exists(compose_file):
            with open(compose_file, 'r') as f:
                content = f.read()
            
            # Ajouter le service Next.js avant la section volumes
            nextjs_service = f"""
  nextjs:
    image: node:18-alpine
    container_name: {project_name}_nextjs_1
    restart: unless-stopped
    working_dir: /app
    volumes:
      - ./nextjs:/app
    networks:
      - wordpress_network
    ports:
      - "0.0.0.0:{nextjs_port}:3000"  # Port Next.js
    environment:
      - NODE_ENV=development
    command: sh -c "if [ -f package.json ]; then npm install && npm run dev; else echo 'Next.js non configuré - créez votre projet dans le dossier nextjs/'; tail -f /dev/null; fi"
    # Optimisations
    mem_limit: 512M
    cpus: '2'
    # Configuration sécurité pour éviter les problèmes AppArmor
    security_opt:
      - "apparmor:unconfined"
"""
            
            # Insérer le service avant la section volumes
            if 'volumes:' in content:
                content = content.replace('volumes:', nextjs_service + '\nvolumes:')
            else:
                content += nextjs_service
            
            with open(compose_file, 'w') as f:
                f.write(content)
        
        print(f"✅ Next.js ajouté au projet {project_name} sur le port {nextjs_port}")
        return jsonify({'success': True, 'message': f'Next.js ajouté avec succès sur le port {nextjs_port}'})
        
    except Exception as e:
        print(f"❌ Erreur lors de l'ajout de Next.js: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/remove_nextjs/<project_name>', methods=['POST'])
def remove_nextjs_from_project(project_name):
    """Supprime Next.js d'un projet existant"""
    try:
        print(f"🗑️ Suppression de Next.js du projet: {project_name}")
        
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Arrêter le conteneur Next.js s'il tourne
        nextjs_container = f"{project_name}_nextjs_1"
        subprocess.run(['docker', 'stop', nextjs_container], capture_output=True, text=True)
        subprocess.run(['docker', 'rm', '-f', nextjs_container], capture_output=True, text=True)
        
        # Supprimer le fichier de port
        nextjs_port_file = os.path.join(project_path, '.nextjs_port')
        if os.path.exists(nextjs_port_file):
            os.remove(nextjs_port_file)
        
        # Modifier le docker-compose.yml pour supprimer le service Next.js
        compose_file = os.path.join(project_path, 'docker-compose.yml')
        if os.path.exists(compose_file):
            with open(compose_file, 'r') as f:
                content = f.read()
            
            # Supprimer le service Next.js
            import re
            nextjs_pattern = r'\s*nextjs:.*?(?=\s*[a-zA-Z_][a-zA-Z0-9_]*:|volumes:|$)'
            content = re.sub(nextjs_pattern, '', content, flags=re.DOTALL)
            
            with open(compose_file, 'w') as f:
                f.write(content)
        
        print(f"✅ Next.js supprimé du projet {project_name}")
        return jsonify({'success': True, 'message': 'Next.js supprimé avec succès'})
        
    except Exception as e:
        print(f"❌ Erreur lors de la suppression de Next.js: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

if __name__ == '__main__':
    # Créer les dossiers nécessaires
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(PROJECTS_FOLDER, exist_ok=True)
    
    # Démarrer l'application
    print("🚀 Démarrage de WordPress Launcher...")
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True) 