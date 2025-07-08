#!/usr/bin/env python3
import os
import shutil
import subprocess
import zipfile
import sqlite3
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, send_file, send_from_directory
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
from services.fast_import_service import FastImportService
# DomainService supprimé - utilisation des IP:port directs

app = Flask(__name__)
app.secret_key = 'wp-launcher-secret-key-2024'

# Configuration SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialisation des services
docker_service = DockerService()
port_service = PortService()
database_service = DatabaseService(socketio)
fast_import_service = FastImportService(socketio)
# domain_service supprimé - utilisation des IP:port directs

# Configuration
UPLOAD_FOLDER = 'uploads'
PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'
ALLOWED_EXTENSIONS = {'zip', 'sql', 'gz'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024  # 5GB max

# Fonction supprimée - utilisation des IP:port directs uniquement

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

def copy_docker_template(project_path, enable_nextjs=False):
    """Copie le template docker-compose dans le projet selon la configuration"""
    template_path = 'docker-template'
    if os.path.exists(template_path):
        for item in os.listdir(template_path):
            src = os.path.join(template_path, item)
            dst = os.path.join(project_path, item)
            
            # Gérer les fichiers docker-compose selon enable_nextjs
            if item == 'docker-compose.yml' and not enable_nextjs:
                continue  # Ignorer le docker-compose avec Next.js si Next.js non activé
            if item == 'docker-compose-no-nextjs.yml':
                if enable_nextjs:
                    continue  # Ignorer le docker-compose sans Next.js si Next.js activé
                else:
                    dst = os.path.join(project_path, 'docker-compose.yml')  # Renommer
            
            if os.path.isdir(src):
                # Utiliser exist_ok=True pour éviter l'erreur "File exists"
                shutil.copytree(src, dst, dirs_exist_ok=True)
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

@app.route('/debug')
def debug_interface():
    """Page de debug pour identifier les problèmes de redirection de ports"""
    return send_from_directory('.', 'debug_interface.html')

@app.route('/favicon.png')
def favicon():
    return '', 204  # Retourner une réponse vide avec code 204 (No Content)

@app.route('/create_project', methods=['POST'])
def create_project():
    try:
        print("🚀 Début de création du projet")
        
        # Récupérer les données du formulaire
        project_name = request.form['project_name'].strip()
        enable_nextjs = request.form.get('enable_nextjs') == 'on'
        
        if not project_name:
            return jsonify({'success': False, 'message': 'Le nom du projet est requis'})
        
        # Nettoyer le nom du projet
        project_name = secure_filename(project_name.replace(' ', '-').lower())
        
        print(f"📝 Nom du projet: {project_name}")
        print(f"⚛️ Next.js activé: {enable_nextjs}")
        print(f"🌐 Accès via IP:port direct uniquement")
        
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
        
        # ======= NOUVELLE STRUCTURE: CRÉER LES DOSSIERS SÉPARÉS =======
        
        # 1. Créer le dossier des fichiers éditables (projets/)
        editable_path = os.path.join(PROJECTS_FOLDER, project_name)
        if os.path.exists(editable_path):
            return jsonify({'success': False, 'message': f'Le projet {project_name} existe déjà'})
        
        print(f"📂 Création du dossier fichiers éditables: {editable_path}")
        os.makedirs(editable_path, exist_ok=True)
        
        # 2. Créer le dossier de configuration Docker (containers/)
        container_path = os.path.join('containers', project_name)
        print(f"📂 Création du dossier configuration Docker: {container_path}")
        os.makedirs(container_path, exist_ok=True)
        
        # 3. Copier le template Docker vers containers/
        print("📋 Copie du template Docker...")
        copy_docker_template(container_path, enable_nextjs)
        
        # 4. Sauvegarder le fichier uploadé (si fourni)
        archive_path = None
        
        if wp_migrate_archive and wp_migrate_archive.filename:
            archive_filename = secure_filename(wp_migrate_archive.filename)
            archive_path = os.path.join(app.config['UPLOAD_FOLDER'], archive_filename)
            print(f"💾 Sauvegarde du fichier WP Migrate: {archive_path}")
            wp_migrate_archive.save(archive_path)
            
            if not os.path.exists(archive_path):
                raise Exception(f"Erreur: fichier WP Migrate non sauvegardé: {archive_path}")
            print(f"✅ Fichier WP Migrate sauvegardé")
        
        # 5. Créer wp-content directement dans projets/ (volume externe)
        wp_content_dest = os.path.join(editable_path, 'wp-content')
        print(f"📦 Configuration wp-content externe: {wp_content_dest}")
        os.makedirs(wp_content_dest, exist_ok=True)
        
        # Détecter le type de fichier archive
        db_path = None
        wp_content_path = None
        
        if archive_path:
            # Analyser le fichier pour déterminer s'il s'agit d'un ZIP ou d'un SQL
            filename_lower = archive_path.lower()
            if filename_lower.endswith('.sql') or filename_lower.endswith('.gz'):
                # Fichier SQL pour base de données
                db_path = archive_path
                print(f"📦 Fichier SQL détecté: {db_path}")
                # Utiliser un wp-content vierge avec les thèmes par défaut
                print("📦 Création d'un wp-content vierge avec thèmes par défaut")
                create_default_wp_content(wp_content_dest)
            elif filename_lower.endswith('.zip'):
                # Fichier ZIP - peut contenir wp-content ou une archive WP Migrate Pro
                wp_content_path = archive_path
                print(f"📦 Fichier ZIP détecté: {wp_content_path}")
                # Extraire le wp-content fourni
                print(f"📦 Extraction wp-content depuis: {wp_content_path}")
                extract_zip(wp_content_path, wp_content_dest)
            else:
                # Utiliser un wp-content vierge avec les thèmes par défaut
                print("📦 Création d'un wp-content vierge avec thèmes par défaut")
                create_default_wp_content(wp_content_dest)
        else:
            # Utiliser un wp-content vierge avec les thèmes par défaut
            print("📦 Création d'un wp-content vierge avec thèmes par défaut")
            create_default_wp_content(wp_content_dest)
        
        # 6. Trouver des ports libres automatiquement
        print("🔍 Recherche de ports libres...")
        project_port = find_free_port_for_project()
        pma_port = find_free_port_for_project(project_port + 1)
        print(f"🌐 Port WordPress attribué: {project_port}")
        print(f"🗃️ Port phpMyAdmin attribué: {pma_port}")
        
        # Port Next.js si activé
        nextjs_port = None
        if enable_nextjs:
            nextjs_port = find_free_port_for_project(pma_port + 1)
            print(f"⚛️ Port Next.js attribué: {nextjs_port}")
        
        # Ports Mailpit
        mailpit_port = find_free_port_for_project((nextjs_port or pma_port) + 1)
        smtp_port = find_free_port_for_project(mailpit_port + 1)
        print(f"📧 Port Mailpit attribué: {mailpit_port}")
        print(f"📮 Port SMTP attribué: {smtp_port}")
        
        # 7. Configurer le docker-compose.yml avec les ports et chemins
        print("⚙️ Configuration docker-compose.yml...")
        compose_file = os.path.join(container_path, 'docker-compose.yml')
        
        if os.path.exists(compose_file):
            with open(compose_file, 'r') as f:
                compose_content = f.read()
            
            # Remplacer les placeholders
            compose_content = compose_content.replace('PROJECT_NAME', project_name)
            compose_content = compose_content.replace('{project_name}', project_name)
            compose_content = compose_content.replace('PROJECT_PORT', str(project_port))
            compose_content = compose_content.replace('PROJECT_PMA_PORT', str(pma_port))
            compose_content = compose_content.replace('PROJECT_MAILPIT_PORT', str(mailpit_port))
            compose_content = compose_content.replace('PROJECT_SMTP_PORT', str(smtp_port))
            
            if enable_nextjs and nextjs_port:
                compose_content = compose_content.replace('PROJECT_NEXTJS_PORT', str(nextjs_port))
            
            with open(compose_file, 'w') as f:
                f.write(compose_content)
            print("✅ docker-compose.yml configuré")
        
        # 8. Créer le fichier wp-config.php externe
        print("📄 Création du wp-config.php externe...")
        wp_config_template = os.path.join(container_path, 'wordpress', 'wp-config.php')
        wp_config_dest = os.path.join(editable_path, 'wp-config.php')
        
        if os.path.exists(wp_config_template):
            with open(wp_config_template, 'r') as f:
                wp_config_content = f.read()
            
            # Remplacer les variables avec IP:port direct
            wp_config_content = wp_config_content.replace('PROJECT_HOSTNAME', f"192.168.1.21:{project_port}")
            wp_config_content = wp_config_content.replace('PROJECT_PORT', str(project_port))
            
            with open(wp_config_dest, 'w') as f:
                f.write(wp_config_content)
            print("✅ wp-config.php externe créé")
        
        # 9. Sauvegarder les fichiers de configuration dans containers/
        print("💾 Sauvegarde des fichiers de ports...")
        
        port_file = os.path.join(container_path, '.port')
        with open(port_file, 'w') as f:
            f.write(str(project_port))
        print(f"✅ Port WordPress {project_port} sauvegardé")
        
        pma_port_file = os.path.join(container_path, '.pma_port')
        with open(pma_port_file, 'w') as f:
            f.write(str(pma_port))
        print(f"✅ Port phpMyAdmin {pma_port} sauvegardé")
        
        # Sauvegarder les ports Mailpit
        mailpit_port_file = os.path.join(container_path, '.mailpit_port')
        with open(mailpit_port_file, 'w') as f:
            f.write(str(mailpit_port))
        print(f"✅ Port Mailpit {mailpit_port} sauvegardé")
        
        smtp_port_file = os.path.join(container_path, '.smtp_port')
        with open(smtp_port_file, 'w') as f:
            f.write(str(smtp_port))
        print(f"✅ Port SMTP {smtp_port} sauvegardé")
        
        # Sauvegarde hostname supprimée - utilisation des IP:port directs uniquement
        print("✅ Configuration IP:port direct - pas de hostname nécessaire")
        
        # 10. Configuration Next.js si activé
        if enable_nextjs and nextjs_port:
            nextjs_port_file = os.path.join(container_path, '.nextjs_port')
            with open(nextjs_port_file, 'w') as f:
                f.write(str(nextjs_port))
            nextjs_enabled_file = os.path.join(container_path, '.nextjs_enabled')
            with open(nextjs_enabled_file, 'w') as f:
                f.write('true')
            print(f"✅ Port Next.js {nextjs_port} sauvegardé")
            
            # Créer un dossier Next.js dans projets/ (fichiers éditables)
            nextjs_dir = os.path.join(editable_path, 'nextjs')
            os.makedirs(nextjs_dir, exist_ok=True)
            
            # Créer un package.json basique
            package_json = {
                "name": f"{project_name}-nextjs",
                "version": "1.0.0",
                "scripts": {
                    "dev": "next dev",
                    "build": "next build",
                    "start": "next start"
                },
                "dependencies": {
                    "next": "latest",
                    "react": "latest",
                    "react-dom": "latest"
                }
            }
            
            import json
            with open(os.path.join(nextjs_dir, 'package.json'), 'w') as f:
                json.dump(package_json, f, indent=2)
            
            # Créer une page d'accueil basique
            pages_dir = os.path.join(nextjs_dir, 'pages')
            os.makedirs(pages_dir, exist_ok=True)
            
            index_content = f"""import React from 'react';

export default function Home() {{
  return (
    <div style={{ padding: '50px', textAlign: 'center' }}>
      <h1>Next.js Frontend pour {project_name}</h1>
      <p>Votre application Next.js est prête !</p>
      <p>Backend WordPress disponible sur le port {project_port}</p>
    </div>
  );
}}
"""
            with open(os.path.join(pages_dir, 'index.js'), 'w') as f:
                f.write(index_content)
            
            print("✅ Structure Next.js créée dans projets/")
        
        # 11. Lancer Docker Compose depuis containers/
        print("🐳 Lancement de Docker Compose...")
        result = subprocess.run([
            'docker-compose', 'up', '-d'
        ], capture_output=True, text=True, cwd=container_path)
        
        if result.returncode != 0:
            raise Exception(f"Erreur Docker Compose: {result.stderr}")
        
        print("✅ Conteneurs Docker lancés")
        
        # Attendre un peu que les conteneurs se lancent
        print("⏳ Attente du démarrage des conteneurs...")
        time.sleep(15)  # Attente initiale
        
        # Attente intelligente pour MySQL (jusqu'à 3 minutes max)
        print("🔍 Vérification que MySQL est prêt...")
        mysql_ready = intelligent_mysql_wait(f"{project_name}_mysql_1", project_name, max_wait_time=180)
        if not mysql_ready:
            print("⚠️ MySQL prend plus de temps que prévu, mais continuons...")
        else:
            print("✅ MySQL est prêt pour l'import")
        
        # Importer la base de données ou créer une base vierge
        if db_path:
            print("🗃️ Début import de la base de données...")
            if not import_database(container_path, db_path, project_name):
                return jsonify({'success': False, 'message': 'Projet créé mais erreur lors de l\'import de la base de données'})
            else:
                success_message = f'Projet {project_name} créé avec succès !'
        else:
            print("🗃️ Création d'une base de données WordPress vierge...")
            if not create_clean_wordpress_database(container_path, project_name):
                return jsonify({'success': False, 'message': 'Projet créé mais erreur lors de la création de la base de données'})
            else:
                success_message = f'Projet {project_name} créé avec succès ! Rendez-vous sur le site pour terminer l\'installation WordPress.'
        
        # Configuration supprimée - utilisation des IP:port directs
        print(f"🌐 Projet accessible via IP:port direct")
        print(f"   WordPress: http://192.168.1.21:{project_port}")
        if enable_nextjs and nextjs_port:
            print(f"   Next.js: http://192.168.1.21:{nextjs_port}")
        print(f"   phpMyAdmin: http://192.168.1.21:{pma_port}")
        print(f"   Mailpit: http://192.168.1.21:{mailpit_port}")
        
        # Nettoyer les fichiers temporaires
        print("🧹 Nettoyage des fichiers temporaires...")
        try:
            if archive_path and os.path.exists(archive_path):
                os.remove(archive_path)
                print("✅ Fichier WP Migrate temporaire supprimé")
        except Exception as e:
            print(f"⚠️ Erreur lors du nettoyage: {e}")
        
        # Configuration automatique des permissions pour dev-server
        print("")
        print("🔑 Configuration des permissions pour dev-server...")
        try:
            # Utiliser le service Docker pour corriger les permissions
            if docker_service.fix_dev_permissions(project_name):
                print("✅ Permissions dev configurées via DockerService")
            else:
                print("⚠️ Erreur lors de la configuration via DockerService, correction manuelle...")
                # Fallback: correction manuelle
                subprocess.run([
                    'sudo', 'chown', '-R', 'dev-server:dev-server', editable_path
                ], check=True, timeout=30)
                
                subprocess.run([
                    'sudo', 'chmod', '-R', '755', editable_path
                ], check=True, timeout=30)
                
                # Aussi corriger les permissions du dossier containers
                subprocess.run([
                    'sudo', 'chown', '-R', 'dev-server:dev-server', container_path
                ], check=True, timeout=30)
                
                subprocess.run([
                    'sudo', 'chmod', '-R', '755', container_path
                ], check=True, timeout=30)
                
                print("✅ Permissions configurées manuellement pour dev-server")
            
            print("📋 dev-server a maintenant un accès complet aux fichiers du projet")
            
        except Exception as e:
            print(f"⚠️ Erreur lors de la configuration des permissions: {e}")
            print("💡 Vous pourrez corriger manuellement avec:")
            print(f"   sudo chown -R dev-server:dev-server {editable_path}")
            print(f"   sudo chmod -R 755 {editable_path}")
        
        return jsonify({'success': True, 'message': success_message})
        
    except Exception as e:
        print(f"❌ Erreur lors de la création du projet: {str(e)}")
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

def auto_fix_missing_mailpit_ports(project_path, project_name):
    """
    Corrige automatiquement les fichiers de ports Mailpit manquants 
    en lisant les ports depuis docker-compose.yml
    """
    try:
        compose_file = os.path.join(project_path, 'docker-compose.yml')
        if not os.path.exists(compose_file):
            return False
        
        # Lire docker-compose.yml
        with open(compose_file, 'r') as f:
            compose_content = f.read()
        
        # Extraire les ports Mailpit avec regex
        import re
        mailpit_web_match = re.search(r'"0\.0\.0\.0:(\d+):8025"', compose_content)
        smtp_match = re.search(r'"0\.0\.0\.0:(\d+):1025"', compose_content)
        
        if not mailpit_web_match or not smtp_match:
            return False
        
        mailpit_port = mailpit_web_match.group(1)
        smtp_port = smtp_match.group(1)
        
        # Créer les fichiers manquants
        fixed = False
        
        mailpit_port_file = os.path.join(project_path, '.mailpit_port')
        if not os.path.exists(mailpit_port_file):
            with open(mailpit_port_file, 'w') as f:
                f.write(mailpit_port)
            print(f"✅ Auto-correction: .mailpit_port créé pour {project_name} (port {mailpit_port})")
            fixed = True
        
        smtp_port_file = os.path.join(project_path, '.smtp_port')
        if not os.path.exists(smtp_port_file):
            with open(smtp_port_file, 'w') as f:
                f.write(smtp_port)
            print(f"✅ Auto-correction: .smtp_port créé pour {project_name} (port {smtp_port})")
            fixed = True
        
        return fixed
        
    except Exception as e:
        print(f"⚠️ Erreur auto-correction Mailpit pour {project_name}: {e}")
        return False

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
                
                # AUTO-CORRECTION: Vérifier et corriger les ports Mailpit manquants
                auto_fix_missing_mailpit_ports(project_path, project_name)
                
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

@app.route('/test_upload', methods=['POST'])
def test_upload():
    """Endpoint de test pour débugger l'upload de fichiers"""
    try:
        print(f"🧪 [TEST_UPLOAD] Test d'upload de fichier")
        print(f"🔍 [TEST_UPLOAD] Request method: {request.method}")
        print(f"🔍 [TEST_UPLOAD] Content-Type: {request.content_type}")
        print(f"🔍 [TEST_UPLOAD] Files in request: {list(request.files.keys())}")
        print(f"🔍 [TEST_UPLOAD] Form data: {list(request.form.keys())}")
        
        if 'db_file' in request.files:
            db_file = request.files['db_file']
            print(f"📁 [TEST_UPLOAD] Fichier trouvé: {db_file.filename}")
            print(f"📊 [TEST_UPLOAD] Content-Type du fichier: {db_file.content_type}")
            
            if db_file.filename:
                file_size = len(db_file.read())
                db_file.seek(0)  # Remettre le pointeur au début
                print(f"📊 [TEST_UPLOAD] Taille du fichier: {file_size} bytes")
                
                return jsonify({
                    'success': True,
                    'message': 'Test d\'upload réussi',
                    'details': {
                        'filename': db_file.filename,
                        'content_type': db_file.content_type,
                        'file_size': file_size
                    }
                })
            else:
                return jsonify({'success': False, 'message': 'Nom de fichier vide'})
        else:
            return jsonify({'success': False, 'message': 'Aucun fichier db_file trouvé'})
            
    except Exception as e:
        print(f"❌ [TEST_UPLOAD] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/fast_import_database/<project_name>', methods=['POST'])
def fast_import_database(project_name):
    """Import ultra-rapide de base de données avec FastImportService"""
    try:
        print(f"🚀 [FAST_IMPORT] Début import ultra-rapide pour le projet: {project_name}")
        print(f"🔍 [FAST_IMPORT] Request method: {request.method}")
        print(f"🔍 [FAST_IMPORT] Content-Type: {request.content_type}")
        print(f"🔍 [FAST_IMPORT] Files in request: {list(request.files.keys())}")
        
        # Vérifier que le projet existe
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            print(f"❌ [FAST_IMPORT] Projet non trouvé: {project_path}")
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier le fichier uploadé
        if 'db_file' not in request.files:
            print(f"❌ [FAST_IMPORT] Aucun fichier db_file dans la requête")
            return jsonify({'success': False, 'message': 'Aucun fichier de base de données fourni'})
        
        db_file = request.files['db_file']
        print(f"📁 [FAST_IMPORT] Fichier reçu: {db_file.filename}")
        print(f"📊 [FAST_IMPORT] Content-Type du fichier: {db_file.content_type}")
        
        if db_file.filename == '':
            print(f"❌ [FAST_IMPORT] Nom de fichier vide")
            return jsonify({'success': False, 'message': 'Aucun fichier sélectionné'})
        
        if not allowed_file(db_file.filename):
            print(f"❌ [FAST_IMPORT] Type de fichier non autorisé: {db_file.filename}")
            return jsonify({'success': False, 'message': 'Type de fichier non autorisé'})
        
        print(f"✅ [FAST_IMPORT] Fichier validé: {db_file.filename}")
        
        # Sauvegarder le fichier temporairement
        if not db_file.filename:
            return jsonify({'success': False, 'message': 'Nom de fichier manquant'})
        db_filename = secure_filename(db_file.filename)
        db_path = os.path.join(app.config['UPLOAD_FOLDER'], f"fast_import_{db_filename}")
        print(f"💾 [FAST_IMPORT] Sauvegarde du fichier vers: {db_path}")
        
        # Créer le dossier upload s'il n'existe pas
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        
        # Sauvegarder le fichier
        db_file.save(db_path)
        
        # Vérifier que le fichier a été sauvegardé
        if os.path.exists(db_path):
            file_size = os.path.getsize(db_path)
            print(f"✅ [FAST_IMPORT] Fichier sauvegardé avec succès: {db_path} ({file_size} bytes)")
        else:
            print(f"❌ [FAST_IMPORT] Échec de la sauvegarde du fichier")
            return jsonify({'success': False, 'message': 'Erreur lors de la sauvegarde du fichier'})
        
        # Vérifier que le conteneur MySQL est actif
        mysql_container = f"{project_name}_mysql_1"
        result = subprocess.run([
            'docker', 'ps', '--format', '{{.Names}}'
        ], capture_output=True, text=True)
        
        if mysql_container not in result.stdout:
            print(f"❌ [FAST_IMPORT] Conteneur MySQL non actif: {mysql_container}")
            # Nettoyer le fichier temporaire
            try:
                os.remove(db_path)
            except:
                pass
            return jsonify({'success': False, 'message': 'Le conteneur MySQL n\'est pas actif. Veuillez d\'abord démarrer le projet.'})
        
        print(f"✅ [FAST_IMPORT] Conteneur MySQL actif: {mysql_container}")
        
        # Lancer l'import ultra-rapide avec FastImportService
        print("🚀 [FAST_IMPORT] Démarrage de l'import avec FastImportService...")
        
        try:
            import_result = fast_import_service.import_database(project_name, db_path)
            
            # Nettoyer le fichier temporaire
            try:
                os.remove(db_path)
                print(f"🧹 [FAST_IMPORT] Fichier temporaire nettoyé: {db_path}")
            except Exception as e:
                print(f"⚠️ [FAST_IMPORT] Erreur lors du nettoyage: {e}")
            
            if import_result.get('success', False):
                print("✅ [FAST_IMPORT] Import ultra-rapide terminé avec succès")
                return jsonify({
                    'success': True, 
                    'message': 'Import ultra-rapide terminé avec succès',
                    'details': {
                        'method': import_result.get('method', 'FastImport'),
                        'speed': import_result.get('speed', 'N/A'),
                        'duration': import_result.get('duration', 'N/A'),
                        'file_size': import_result.get('file_size', 'N/A'),
                        'tables_imported': import_result.get('tables_imported', 'N/A')
                    }
                })
            else:
                error_message = import_result.get('error', 'Erreur lors de l\'import ultra-rapide')
                print(f"❌ [FAST_IMPORT] Erreur import: {error_message}")
                return jsonify({'success': False, 'message': error_message})
                
        except Exception as import_error:
            print(f"❌ [FAST_IMPORT] Exception lors de l'import: {import_error}")
            import traceback
            traceback.print_exc()
            
            # Nettoyer le fichier temporaire même en cas d'erreur
            try:
                os.remove(db_path)
            except:
                pass
                
            return jsonify({
                'success': False, 
                'message': f'Erreur lors de l\'import ultra-rapide: {str(import_error)}'
            })
        
    except Exception as e:
        print(f"❌ [FAST_IMPORT] Exception générale: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/update_database/<project_name>', methods=['POST'])
def update_database(project_name):
    """Met à jour la base de données d'un projet existant"""
    try:
        print(f"🔄 [UPDATE_DB] Début mise à jour DB pour le projet: {project_name}")
        print(f"🔍 [UPDATE_DB] Request method: {request.method}")
        print(f"🔍 [UPDATE_DB] Content-Type: {request.content_type}")
        print(f"🔍 [UPDATE_DB] Files in request: {list(request.files.keys())}")
        
        # Vérifier que le projet existe
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            print(f"❌ [UPDATE_DB] Projet non trouvé: {project_path}")
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier le fichier uploadé
        if 'db_file' not in request.files:
            print(f"❌ [UPDATE_DB] Aucun fichier db_file dans la requête")
            return jsonify({'success': False, 'message': 'Aucun fichier de base de données fourni'})
        
        db_file = request.files['db_file']
        print(f"📁 [UPDATE_DB] Fichier reçu: {db_file.filename}")
        print(f"📊 [UPDATE_DB] Content-Type du fichier: {db_file.content_type}")
        print(f"📊 [UPDATE_DB] Taille du fichier: {db_file.content_length if hasattr(db_file, 'content_length') else 'N/A'} bytes")
        
        if db_file.filename == '':
            print(f"❌ [UPDATE_DB] Nom de fichier vide")
            return jsonify({'success': False, 'message': 'Aucun fichier sélectionné'})
        
        if not allowed_file(db_file.filename):
            print(f"❌ [UPDATE_DB] Type de fichier non autorisé: {db_file.filename}")
            return jsonify({'success': False, 'message': 'Type de fichier non autorisé'})
        
        print(f"✅ [UPDATE_DB] Fichier validé: {db_file.filename}")
        
        # Sauvegarder le fichier temporairement
        if db_file.filename:
            db_filename = secure_filename(db_file.filename)
            db_path = os.path.join(app.config['UPLOAD_FOLDER'], f"update_{db_filename}")
            print(f"💾 [UPDATE_DB] Sauvegarde du fichier vers: {db_path}")
            
            # Créer le dossier upload s'il n'existe pas
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            
            # Sauvegarder le fichier
            db_file.save(db_path)
            
            # Vérifier que le fichier a été sauvegardé
            if os.path.exists(db_path):
                file_size = os.path.getsize(db_path)
                print(f"✅ [UPDATE_DB] Fichier sauvegardé avec succès: {db_path} ({file_size} bytes)")
            else:
                print(f"❌ [UPDATE_DB] Échec de la sauvegarde du fichier")
                return jsonify({'success': False, 'message': 'Erreur lors de la sauvegarde du fichier'})
        else:
            print(f"❌ [UPDATE_DB] Nom de fichier invalide")
            return jsonify({'success': False, 'message': 'Nom de fichier invalide'})
        
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
        
        # Importer la nouvelle base de données avec le service ultra-rapide
        print("📥 Import de la nouvelle base de données avec FastImportService...")
        
        try:
            import_result = fast_import_service.import_database(project_name, db_path)
            
            # Nettoyer le fichier temporaire
            try:
                os.remove(db_path)
            except Exception as e:
                print(f"⚠️ Erreur lors du nettoyage: {e}")
            
            if import_result.get('success', False):
                print("✅ Base de données mise à jour avec succès")
                return jsonify({
                    'success': True, 
                    'message': 'Base de données mise à jour avec succès',
                    'details': {
                        'method': import_result.get('method', 'FastImport'),
                        'speed': import_result.get('speed', 'N/A'),
                        'duration': import_result.get('duration', 'N/A'),
                        'file_size': import_result.get('file_size', 'N/A'),
                        'tables_imported': import_result.get('tables_imported', 'N/A')
                    }
                })
            else:
                error_message = import_result.get('error', 'Erreur lors de l\'import de la nouvelle base de données')
                print(f"❌ Erreur import: {error_message}")
                return jsonify({'success': False, 'message': error_message})
                
        except Exception as import_error:
            print(f"❌ Exception lors de l'import: {import_error}")
            print(f"📊 Taille du fichier SQL: {os.path.getsize(db_path) if os.path.exists(db_path) else 'N/A'} bytes")
            
            # Nettoyer le fichier temporaire même en cas d'erreur
            try:
                os.remove(db_path)
            except:
                pass
                
            return jsonify({
                'success': False, 
                'message': f'Erreur lors de l\'import: {str(import_error)}'
            })
        
    except Exception as e:
        print(f"❌ [UPDATE_DB] Exception générale: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/export_database/<project_name>', methods=['POST'])
def export_database(project_name):
    """Exporte la base de données d'un projet"""
    try:
        print(f"📤 Début export DB pour le projet: {project_name}")
        
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier que le projet est actif
        project_status = check_project_status(project_name)
        if project_status != 'active':
            return jsonify({'success': False, 'message': 'Le projet doit être démarré pour exporter la base de données'})
        
        # Créer le dossier d'export s'il n'existe pas
        export_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'exports')
        os.makedirs(export_dir, exist_ok=True)
        
        # Générer le nom du fichier d'export avec timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_filename = f"{project_name}_export_{timestamp}.sql"
        export_path = os.path.join(export_dir, export_filename)
        
        # Utiliser le service de base de données pour l'export
        success, error = database_service.export_database(project_name, export_path)
        
        if success:
            # Créer l'URL de téléchargement
            download_url = f"/download_export/{export_filename}"
            
            print(f"✅ Base de données exportée avec succès: {export_filename}")
            return jsonify({
                'success': True, 
                'message': 'Base de données exportée avec succès',
                'filename': export_filename,
                'download_url': download_url
            })
        else:
            print(f"❌ Erreur lors de l'export: {error}")
            return jsonify({'success': False, 'message': f'Erreur lors de l\'export: {error}'})
        
    except Exception as e:
        print(f"❌ Erreur lors de l'export de la base de données: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/download_export/<filename>')
def download_export(filename):
    """Télécharge un fichier d'export de base de données"""
    try:
        export_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'exports')
        file_path = os.path.join(export_dir, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'Fichier non trouvé'}), 404
        
        # Vérifier que le fichier a un nom sécurisé
        if not filename.endswith('.sql') or '..' in filename:
            return jsonify({'error': 'Nom de fichier invalide'}), 400
        
        return send_file(file_path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        print(f"❌ Erreur lors du téléchargement: {e}")
        return jsonify({'error': 'Erreur lors du téléchargement'}), 500

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
                        deleted_projects_file = os.path.join(PROJECTS_FOLDER, '.deleted_projects')
                        with open(deleted_projects_file, 'a') as f:
                            f.write(f"{project_name}\n")
                        print("✅ Projet marqué comme supprimé (fichier global avec sudo)")
                    except Exception as e4:
                        print(f"⚠️ Erreur finale: {e4}")
                        print("❌ Impossible de marquer le projet comme supprimé")
        
        # ÉTAPE 7: Nettoyage final des ressources Docker
        print("🧹 Nettoyage final des ressources Docker...")
        try:
            docker_service.cleanup_unused_resources()
        except Exception as e:
            print(f"⚠️ Erreur nettoyage final: {e}")
        
        # ÉTAPE 7.5: Attente pour stabilisation complète (NOUVEAU)
        print("⏳ Attente de 10 secondes pour stabilisation complète des processus Docker...")
        import time
        time.sleep(10)
        print("✅ Stabilisation terminée, début suppression physique")

        # ÉTAPE 8: Suppression physique des fichiers (OBLIGATOIRE)
        print("📁 Suppression physique des fichiers...")
        project_deleted = False
        
        try:
            # Utiliser le script de suppression robuste
            script_path = os.path.join(os.path.dirname(__file__), 'delete_project_robust.sh')
            
            if os.path.exists(script_path):
                print("🔧 Utilisation du script de suppression robuste...")
                
                # Augmenter le timeout à 5 minutes et capturer toutes les sorties
                result = subprocess.run([
                    'bash', script_path, project_name
                ], capture_output=True, text=True, timeout=300)  # 5 minutes au lieu de 2 minutes
                
                # Vérifier si le dossier a été supprimé (peu importe le code de retour)
                project_deleted = not os.path.exists(project.path)
                
                if project_deleted:
                    print("✅ Dossier supprimé avec le script robuste")
                    print(f"📝 Sortie du script: {result.stdout[-500:] if result.stdout else 'Aucune sortie'}")  # Dernières 500 caractères
                else:
                    print(f"⚠️ Script robuste terminé mais dossier existe encore")
                    print(f"📝 Code de retour: {result.returncode}")
                    print(f"📝 Sortie du script: {result.stdout[-1000:] if result.stdout else 'Aucune sortie'}")
                    print(f"📝 Erreurs du script: {result.stderr[-1000:] if result.stderr else 'Aucune erreur'}")
                    
                    # Même si le script "échoue", tenter une dernière vérification
                    import time
                    time.sleep(2)  # Attendre 2 secondes supplémentaires
                    project_deleted = not os.path.exists(project.path)
                    if project_deleted:
                        print("✅ Dossier finalement supprimé après attente supplémentaire")
                    else:
                        # MÉTHODE DE FALLBACK FORCÉE (NOUVEAU)
                        print("🔧 Méthode de fallback : suppression forcée avec sudo...")
                        try:
                            # Utiliser la même méthode que le script robuste utilise
                            print("🔑 Correction des permissions forcée...")
                            subprocess.run(['sudo', 'chown', '-R', 'dev-server:dev-server', project.path], 
                                         capture_output=True, text=True, timeout=30)
                            subprocess.run(['sudo', 'chmod', '-R', '777', project.path], 
                                         capture_output=True, text=True, timeout=30)
                            
                            print("🗑️ Suppression forcée...")
                            result = subprocess.run(['sudo', 'rm', '-rf', project.path], 
                                                   capture_output=True, text=True, timeout=60)
                            
                            # Vérifier le résultat final
                            project_deleted = not os.path.exists(project.path)
                            if project_deleted:
                                print("✅ Suppression forcée réussie !")
                            else:
                                print(f"❌ Suppression forcée échouée: {result.stderr}")
                        except Exception as fallback_error:
                            print(f"❌ Erreur méthode de fallback: {fallback_error}")
                    
            else:
                print("⚠️ Script robuste non trouvé, utilisation de la méthode de base...")
                
                # Méthode de fallback - correction des permissions puis suppression
                print("🔧 Correction des permissions...")
                subprocess.run(['sudo', 'chown', '-R', 'dev-server:dev-server', project.path], 
                             capture_output=True, text=True, timeout=30)
                subprocess.run(['sudo', 'chmod', '-R', '777', project.path], 
                             capture_output=True, text=True, timeout=30)
                
                print("🗑️ Suppression avec sudo rm...")
                result = subprocess.run([
                    'sudo', 'rm', '-rf', project.path
                ], capture_output=True, text=True, timeout=60)
                
                project_deleted = not os.path.exists(project.path)
                
                if project_deleted:
                    print("✅ Dossier supprimé avec la méthode de base")
                else:
                    print(f"⚠️ Suppression de base échouée: {result.stderr}")
                    
        except subprocess.TimeoutExpired:
            print("⚠️ Timeout lors de la suppression (plus de 5 minutes)")
            # Vérifier quand même si le dossier a été supprimé malgré le timeout
            project_deleted = not os.path.exists(project.path)
            if project_deleted:
                print("✅ Dossier supprimé malgré le timeout")
        except Exception as e:
            print(f"⚠️ Erreur suppression physique: {e}")
            project_deleted = not os.path.exists(project.path)
            if project_deleted:
                print("✅ Dossier supprimé malgré l'erreur")
        
        # ÉTAPE 9: Vérification finale et retour du résultat
        if project_deleted:
            print(f"✅ Suppression du projet {project_name} terminée avec succès")
            return jsonify({
                'success': True,
                'message': 'Projet supprimé avec succès',
                'details': 'Conteneurs Docker supprimés, volumes nettoyés, dossier physique supprimé'
            })
        else:
            print(f"⚠️ Suppression du projet {project_name} incomplète - dossier non supprimé")
            return jsonify({
                'success': False,
                'message': 'Suppression partiellement échouée',
                'details': 'Les conteneurs Docker ont été supprimés mais le dossier existe encore. Le projet est marqué comme supprimé et n\'apparaîtra plus dans l\'interface.'
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
        
        # Utiliser la nouvelle architecture Project
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.is_valid:
            return jsonify({'success': False, 'message': 'Projet invalide (pas de docker-compose.yml)'})
        
        project_path = project.path  # Dossier projets/
        compose_path = project.container_path  # Dossier containers/
        
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
        
        # Si pas de domaine, ajouter .akdigital.fr par défaut
        if '.' not in new_hostname:
            new_hostname = f"{new_hostname}.akdigital.fr"
        
        print(f"🌐 Nouveau hostname: {new_hostname}")
        
        # Lire l'ancien hostname
        hostname_file = os.path.join(compose_path, '.hostname')
        old_hostname = f"{project_name}.akdigital.fr"  # Valeur par défaut
        
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
        
        # Mettre à jour le fichier docker-compose.yml dans containers/
        compose_file = os.path.join(compose_path, 'docker-compose.yml')
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
        wp_config_file = os.path.join(project_path, 'wp-config.php')
        print(f"⚙️ Mise à jour WordPress config: {wp_config_file}")
        if os.path.exists(wp_config_file):
            with open(wp_config_file, 'r') as f:
                wp_content = f.read()
            # Remplacer les URLs avec l'ancien hostname par le nouveau
            wp_content = wp_content.replace(f'http://{old_hostname}', f'http://{new_hostname}')
            with open(wp_config_file, 'w') as f:
                f.write(wp_content)
            print("✅ WordPress config mis à jour avec le nouveau hostname")
        else:
            print("⚠️ Fichier wp-config.php non trouvé")
        
        # Obtenir le port du projet
        port_file = os.path.join(compose_path, '.port')
        if not os.path.exists(port_file):
            return jsonify({'success': False, 'message': 'Port du projet non trouvé'})
        
        with open(port_file, 'r') as f:
            project_port = f.read().strip()
        
        # Obtenir le port Next.js si activé
        nextjs_port = None
        if project.has_nextjs:
            nextjs_port_file = os.path.join(compose_path, '.nextjs_port')
            if os.path.exists(nextjs_port_file):
                with open(nextjs_port_file, 'r') as f:
                    nextjs_port = f.read().strip()
        
        # Configuration de domaine supprimée - utilisation des IP:port directs
        print(f"🌐 Hostname mis à jour dans les fichiers de configuration")
        print(f"   Accès direct: http://192.168.1.21:{project_port}")
        if project.has_nextjs and nextjs_port:
            print(f"   Next.js direct: http://192.168.1.21:{nextjs_port}")
        print("💡 Utilisez les IP:port directs pour accéder au site")
        
        # Redémarrer les conteneurs pour appliquer les changements
        print("🔄 Redémarrage des conteneurs...")
        try:
            # Utiliser le DockerService pour redémarrer depuis containers/
            docker_service.stop_containers(compose_path)
            success, error = docker_service.start_containers(compose_path)
            
            if not success:
                print(f"⚠️ Erreur lors du redémarrage: {error}")
                return jsonify({'success': False, 'message': f'Erreur lors du redémarrage des conteneurs: {error}'})
            
            print("✅ Conteneurs redémarrés")
                
        except Exception as e:
            print(f"⚠️ Erreur lors du redémarrage: {e}")
            return jsonify({'success': False, 'message': 'Erreur lors du redémarrage des conteneurs'})
        
        print(f"✅ Hostname du projet {project_name} mis à jour avec succès")
        return jsonify({'success': True, 'message': f'Hostname mis à jour vers {new_hostname} avec succès !'})
        
    except Exception as e:
        print(f"❌ Erreur lors de l'édition de l'hostname: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/start_project/<project_name>', methods=['POST'])
def start_project(project_name):
    """Démarre un projet WordPress"""
    try:
        print(f"🚀 Démarrage du projet: {project_name}")
        
        # Utiliser le modèle Project avec la nouvelle architecture
        project = Project(project_name, PROJECTS_FOLDER, 'containers')
        
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.is_valid:
            return jsonify({'success': False, 'message': 'Projet invalide (pas de docker-compose.yml)'})
        
        # Utiliser le DockerService pour démarrer les conteneurs depuis containers/
        success, error = docker_service.start_containers(project.container_path)
        
        if success:
            print(f"✅ Projet {project_name} démarré avec succès")
            return jsonify({'success': True, 'message': f'Projet {project_name} démarré avec succès'})
        else:
            print(f"❌ Erreur lors du démarrage: {error}")
            return jsonify({'success': False, 'message': f'Erreur lors du démarrage: {error}'})
            
    except Exception as e:
        print(f"❌ Erreur lors du démarrage du projet: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/stop_project/<project_name>', methods=['POST'])
def stop_project(project_name):
    """Arrête un projet WordPress"""
    try:
        print(f"🛑 Arrêt du projet: {project_name}")
        
        # Utiliser le modèle Project avec la nouvelle architecture
        project = Project(project_name, PROJECTS_FOLDER, 'containers')
        
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.is_valid:
            return jsonify({'success': False, 'message': 'Projet invalide (pas de docker-compose.yml)'})
        
        # Utiliser le DockerService pour arrêter les conteneurs depuis containers/
        success, error = docker_service.stop_containers(project.container_path)
        
        if success:
            print(f"✅ Projet {project_name} arrêté avec succès")
            return jsonify({'success': True, 'message': f'Projet {project_name} arrêté avec succès'})
        else:
            print(f"❌ Erreur lors de l'arrêt: {error}")
            return jsonify({'success': False, 'message': f'Erreur lors de l\'arrêt: {error}'})
            
    except Exception as e:
        print(f"❌ Erreur lors de l'arrêt du projet: {e}")
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
                "react": "latest",
                "react-dom": "latest"
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
        <link rel="icon" href="/favicon.png" />
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

@app.route('/get_wordpress_urls/<project_name>')
def get_wordpress_urls(project_name):
    """Récupère les URLs WordPress depuis la base de données"""
    try:
        mysql_container = f"{project_name}_mysql_1"
        
        # Vérifier que le conteneur MySQL fonctionne
        result = subprocess.run([
            'docker', 'ps', '--filter', f'name={mysql_container}', '--filter', 'status=running', '--format', '{{.Names}}'
        ], capture_output=True, text=True)
        
        if mysql_container not in result.stdout:
            return jsonify({'success': False, 'message': 'Conteneur MySQL non accessible'})
        
        # Récupérer les URLs depuis la base de données
        query_result = subprocess.run([
            'docker', 'exec', mysql_container, 'mysql', 
            '-u', 'wordpress', '-pwordpress', 'wordpress',
            '-e', "SELECT option_name, option_value FROM wp_options WHERE option_name IN ('home', 'siteurl', 'admin_email');"
        ], capture_output=True, text=True, timeout=10)
        
        if query_result.returncode != 0:
            return jsonify({'success': False, 'message': 'Erreur lors de la requête SQL'})
        
        # Parser les résultats
        lines = query_result.stdout.strip().split('\n')
        urls = {}
        
        for line in lines[1:]:  # Skip header
            if '\t' in line:
                parts = line.split('\t')
                if len(parts) >= 2:
                    option_name = parts[0]
                    option_value = parts[1]
                    urls[option_name] = option_value
        
        # URLs par défaut si pas trouvées
        if not urls.get('home'):
            urls['home'] = f"http://192.168.1.21:8080"
        if not urls.get('siteurl'):
            urls['siteurl'] = urls['home']
            
        # Construire les URLs proprement
        frontend_url = urls.get('home', f"http://192.168.1.21:8080")
        siteurl = urls.get('siteurl', f"http://192.168.1.21:8080")
        
        # Supprimer le slash final s'il existe pour éviter les doubles slashes
        if siteurl.endswith('/'):
            siteurl = siteurl.rstrip('/')
            
        return jsonify({
            'success': True,
            'urls': {
                'frontend': frontend_url,
                'admin': siteurl + '/wp-admin',
                'admin_email': urls.get('admin_email', '')
            }
        })
        
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des URLs: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/nextjs_npm/<project_name>/<command>', methods=['POST'])
def nextjs_npm(project_name, command):
    """Exécute les commandes npm pour Next.js"""
    try:
        print(f"🎯 Commande npm {command} pour {project_name}")
        
        # Utiliser la nouvelle architecture
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier que Next.js est configuré
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Next.js n\'est pas configuré pour ce projet. Utilisez "Ajouter Next.js" d\'abord.'})
        
        nextjs_path = os.path.join(project.path, 'nextjs')
        if not os.path.exists(nextjs_path):
            return jsonify({'success': False, 'message': 'Dossier Next.js non trouvé dans projets/'})
        
        nextjs_container = f"{project_name}_nextjs_1"
        
        # Vérification plus détaillée du conteneur Next.js
        print(f"🔍 Vérification du conteneur: {nextjs_container}")
        
        # 1. Vérifier si le conteneur existe (running ou pas)
        result_all = subprocess.run([
            'docker', 'ps', '-a', '--filter', f'name={nextjs_container}', '--format', '{{.Names}} {{.Status}}'
        ], capture_output=True, text=True)
        
        if nextjs_container not in result_all.stdout:
            return jsonify({'success': False, 'message': f'Conteneur Next.js non trouvé. Le projet "{project_name}" doit être redémarré pour créer le conteneur Next.js.'})
        
        # 2. Vérifier si le conteneur est running
        result_running = subprocess.run([
            'docker', 'ps', '--filter', f'name={nextjs_container}', '--filter', 'status=running', '--format', '{{.Names}}'
        ], capture_output=True, text=True)
        
        if nextjs_container not in result_running.stdout:
            # Le conteneur existe mais n'est pas running - essayer de le démarrer
            print(f"🔄 Conteneur {nextjs_container} existe mais n'est pas running. Tentative de démarrage...")
            
            start_result = subprocess.run([
                'docker', 'start', nextjs_container
            ], capture_output=True, text=True, timeout=30)
            
            if start_result.returncode == 0:
                print(f"✅ Conteneur {nextjs_container} démarré avec succès")
                # Attendre 3 secondes que le conteneur soit prêt
                import time
                time.sleep(3)
            else:
                print(f"❌ Impossible de démarrer le conteneur: {start_result.stderr}")
                return jsonify({'success': False, 'message': f'Conteneur Next.js arrêté et impossible à démarrer. Erreur: {start_result.stderr}'})
        
        print(f"✅ Conteneur {nextjs_container} est actif")
        
        # Vérifier si npm run dev est déjà en cours
        if command == 'dev':
            dev_check = subprocess.run([
                'docker', 'exec', nextjs_container, 'pgrep', '-f', 'npm.*dev'
            ], capture_output=True, text=True)
            
            if dev_check.returncode == 0:
                return jsonify({'success': False, 'message': 'npm run dev est déjà en cours d\'exécution'})
        
        # Commandes autorisées
        allowed_commands = {
            'install': ['npm', 'install'],
            'dev': ['npm', 'run', 'dev'],
            'build': ['npm', 'run', 'build'],
            'start': ['npm', 'start']
        }
        
        if command not in allowed_commands:
            return jsonify({'success': False, 'message': 'Commande non autorisée'})
        
        npm_command = allowed_commands[command]
        
        # Pour 'dev', il faut d'abord arrêter le processus existant
        if command == 'dev':
            print(f"🔄 Arrêt du processus npm dev existant...")
            # Arrêter le processus npm dev existant
            subprocess.run([
                'docker', 'exec', nextjs_container, 'pkill', '-f', 'npm.*dev'
            ], capture_output=True)
            
            # Exécuter npm run dev en arrière-plan
            result = subprocess.run([
                'docker', 'exec', '-d', nextjs_container, 'sh', '-c', 
                f"cd /app && {' '.join(npm_command)}"
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                message = f"npm run dev démarré en arrière-plan sur le port {project.nextjs_port}"
            else:
                return jsonify({'success': False, 'message': f'Erreur lors du démarrage: {result.stderr}'})
            
        elif command == 'install':
            print(f"📦 Installation des dépendances npm...")
            # npm install - attendre la fin
            result = subprocess.run([
                'docker', 'exec', nextjs_container, 'sh', '-c', 
                f"cd /app && {' '.join(npm_command)}"
            ], capture_output=True, text=True, timeout=300)  # 5 minutes max
            
            if result.returncode == 0:
                message = "Dépendances npm installées avec succès"
            else:
                return jsonify({'success': False, 'message': f'Erreur npm install: {result.stderr}'})
                
        elif command == 'build':
            print(f"🏗️ Construction du projet Next.js...")
            # npm run build - attendre la fin
            result = subprocess.run([
                'docker', 'exec', nextjs_container, 'sh', '-c', 
                f"cd /app && {' '.join(npm_command)}"
            ], capture_output=True, text=True, timeout=600)  # 10 minutes max
            
            if result.returncode == 0:
                message = f"Projet Next.js construit avec succès sur le port {project.nextjs_port}"
            else:
                return jsonify({'success': False, 'message': f'Erreur npm build: {result.stderr}'})
        
        print(f"✅ {message}")
        return jsonify({'success': True, 'message': message})
        
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'message': f'Timeout lors de l\'exécution de npm {command}'})
    except Exception as e:
        print(f"❌ Erreur npm {command}: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/check_nextjs_status/<project_name>')
def check_nextjs_status(project_name):
    """Vérifie le statut de npm run dev pour un projet (conteneur en priorité)"""
    try:
        # Utiliser la nouvelle architecture
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        
        if not project.exists:
            return jsonify({'success': False, 'dev_running': False})
        
        dev_running = False
        container_running = False
        
        # 1. Vérifier d'abord le conteneur Next.js (priorité)
        if project.has_nextjs:
            nextjs_container = f"{project_name}_nextjs_1"
            
            # Vérifier si le conteneur est en cours d'exécution
            result = subprocess.run([
                'docker', 'ps', '--filter', f'name={nextjs_container}', '--filter', 'status=running', '--format', '{{.Names}}'
            ], capture_output=True, text=True)
            
            if nextjs_container in result.stdout:
                container_running = True
                
                # Si le conteneur tourne, npm dev est probablement en cours (sauf si on vient de le démarrer)
                # Vérifier explicitement si npm run dev est en cours dans le conteneur
                dev_check = subprocess.run([
                    'docker', 'exec', nextjs_container, 'pgrep', '-f', 'npm.*dev'
                ], capture_output=True, text=True)
                
                if dev_check.returncode == 0:
                    dev_running = True
                    print(f"✅ npm run dev détecté dans le conteneur {nextjs_container}")
                else:
                    # Le conteneur tourne mais npm dev n'est pas encore démarré
                    print(f"ℹ️ Conteneur {nextjs_container} en cours mais npm dev pas encore démarré")
            else:
                print(f"ℹ️ Conteneur {nextjs_container} arrêté")
        
        # 2. Vérifier sur l'hôte seulement si le conteneur n'a pas npm dev
        if not dev_running:
            # Chercher des processus npm dev orphelins sur l'hôte
            host_check = subprocess.run([
                'pgrep', '-f', 'npm.*dev'
            ], capture_output=True, text=True)
            
            if host_check.returncode == 0 and host_check.stdout.strip():
                dev_running = True
                print(f"⚠️ Processus npm dev orphelins détectés sur l'hôte: {host_check.stdout.strip()}")
        
        # 3. Vérifier les processus sudo npm dev (cas particulier)
        if not dev_running:
            sudo_check = subprocess.run([
                'pgrep', '-f', 'sudo.*npm.*dev'
            ], capture_output=True, text=True)
            
            if sudo_check.returncode == 0 and sudo_check.stdout.strip():
                dev_running = True
                print(f"⚠️ Processus sudo npm dev détectés: {sudo_check.stdout.strip()}")
        
        print(f"📊 Statut {project_name}: conteneur_actif={container_running}, npm_dev_actif={dev_running}")
        
        return jsonify({
            'success': True, 
            'dev_running': dev_running,
            'container_running': container_running
        })
        
    except Exception as e:
        print(f"❌ Erreur vérification statut Next.js: {e}")
        return jsonify({'success': False, 'dev_running': False})

@app.route('/stop_nextjs_dev/<project_name>', methods=['POST'])
def stop_nextjs_dev(project_name):
    """Arrête npm run dev pour un projet Next.js (arrêt du conteneur)"""
    try:
        print(f"🛑 Arrêt de npm run dev pour {project_name}")
        
        # Utiliser la nouvelle architecture
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        stopped_processes = []
        errors = []
        
        # 1. Arrêter complètement le conteneur Next.js (plus efficace que de tuer le processus)
        if project.has_nextjs:
            nextjs_container = f"{project_name}_nextjs_1"
            
            print(f"🔄 Arrêt du conteneur Next.js...")
            result = subprocess.run([
                'docker', 'stop', nextjs_container
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                stopped_processes.append("conteneur Next.js arrêté")
                print(f"✅ Conteneur {nextjs_container} arrêté avec succès")
            else:
                # Vérifier si le conteneur existe/était déjà arrêté
                check_result = subprocess.run([
                    'docker', 'ps', '-a', '--filter', f'name={nextjs_container}', '--format', '{{.Names}}'
                ], capture_output=True, text=True)
                
                if nextjs_container in check_result.stdout:
                    stopped_processes.append("conteneur Next.js (déjà arrêté)")
                else:
                    errors.append("Conteneur Next.js non trouvé")
        
        # 2. Arrêter TOUS les processus npm dev sur l'hôte (au cas où il y en aurait)
        print(f"🔄 Nettoyage des processus npm run dev sur l'hôte...")
        
        try:
            result = subprocess.run([
                'pgrep', '-f', 'npm.*dev'
            ], capture_output=True, text=True)
            
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                print(f"📋 Processus npm dev trouvés sur l'hôte: {pids}")
                
                for pid in pids:
                    if pid.strip():
                        try:
                            kill_result = subprocess.run([
                                'sudo', 'kill', '-KILL', pid.strip()
                            ], capture_output=True, text=True, timeout=5)
                            
                            if kill_result.returncode == 0:
                                stopped_processes.append(f"processus hôte PID {pid.strip()}")
                            else:
                                errors.append(f"Impossible d'arrêter PID {pid.strip()}")
                        except Exception as e:
                            errors.append(f"Erreur PID {pid.strip()}: {str(e)}")
            else:
                print(f"ℹ️ Aucun processus npm dev trouvé sur l'hôte")
        
        except Exception as e:
            errors.append(f"Erreur recherche processus: {str(e)}")
        
        # 3. Nettoyer les processus sudo npm dev
        try:
            result = subprocess.run([
                'pgrep', '-f', 'sudo.*npm.*dev'
            ], capture_output=True, text=True)
            
            if result.returncode == 0 and result.stdout.strip():
                sudo_pids = result.stdout.strip().split('\n')
                print(f"📋 Processus sudo npm dev trouvés: {sudo_pids}")
                
                for pid in sudo_pids:
                    if pid.strip():
                        try:
                            kill_result = subprocess.run([
                                'sudo', 'kill', '-KILL', pid.strip()
                            ], capture_output=True, text=True, timeout=5)
                            
                            if kill_result.returncode == 0:
                                stopped_processes.append(f"sudo PID {pid.strip()}")
                        except Exception:
                            pass  # Ignorer les erreurs pour les processus sudo
        except Exception:
            pass  # Ignorer les erreurs de recherche sudo
        
        # Construire le message de retour
        if stopped_processes:
            message = f"npm run dev arrêté: {', '.join(stopped_processes)}"
            if errors:
                message += f" (avertissements: {', '.join(errors)})"
            print(f"✅ {message}")
            return jsonify({'success': True, 'message': message})
        elif errors:
            message = f"Erreurs lors de l'arrêt: {', '.join(errors)}"
            print(f"⚠️ {message}")
            return jsonify({'success': False, 'message': message})
        else:
            message = "npm run dev n'était pas en cours d'exécution"
            print(f"ℹ️ {message}")
            return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        print(f"❌ Erreur arrêt npm dev: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})



@app.route('/start_nextjs_container/<project_name>', methods=['POST'])
def start_nextjs_container(project_name):
    """Redémarre le conteneur Next.js pour un projet"""
    try:
        print(f"🚀 Démarrage du conteneur Next.js pour {project_name}")
        
        # Utiliser la nouvelle architecture
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        
        if not project.exists or not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Projet Next.js non trouvé'})
        
        nextjs_container = f"{project_name}_nextjs_1"
        
        # Vérifier l'état actuel du conteneur
        result = subprocess.run([
            'docker', 'ps', '-a', '--filter', f'name={nextjs_container}', '--format', '{{.Names}} {{.Status}}'
        ], capture_output=True, text=True)
        
        if nextjs_container not in result.stdout:
            return jsonify({'success': False, 'message': 'Conteneur Next.js non trouvé'})
        
        # Démarrer le conteneur (il se redémarrera automatiquement avec npm run dev)
        print(f"🔄 Démarrage du conteneur {nextjs_container}...")
        result = subprocess.run([
            'docker', 'start', nextjs_container
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            message = f"Conteneur Next.js démarré - npm run dev va s'initialiser automatiquement"
            print(f"✅ {message}")
            return jsonify({'success': True, 'message': message})
        else:
            # Si start échoue, essayer restart
            print(f"🔄 Tentative de restart du conteneur...")
            result = subprocess.run([
                'docker', 'restart', nextjs_container
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                message = f"Conteneur Next.js redémarré - npm run dev va s'initialiser automatiquement"
                print(f"✅ {message}")
                return jsonify({'success': True, 'message': message})
            else:
                error_msg = f"Impossible de démarrer le conteneur: {result.stderr}"
                print(f"❌ {error_msg}")
                return jsonify({'success': False, 'message': error_msg})
        
    except Exception as e:
        print(f"❌ Erreur démarrage conteneur Next.js: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

# Fonctions nginx supprimées - utilisation des IP:port directs uniquement

if __name__ == '__main__':
    # Créer les dossiers nécessaires
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(PROJECTS_FOLDER, exist_ok=True)
    
    # Démarrer l'application
    print("🚀 Démarrage de WordPress Launcher...")
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True) 