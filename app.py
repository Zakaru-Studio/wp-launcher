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

app = Flask(__name__)
app.secret_key = 'wp-launcher-secret-key-2024'

# Configuration SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

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

def copy_docker_template(project_path, enable_nextjs=False):
    """Copie le template docker-compose dans le projet"""
    template_path = 'docker-template'
    if os.path.exists(template_path):
        for item in os.listdir(template_path):
            # Ignorer le fichier docker-compose.yml principal si on ne veut pas Next.js
            if item == 'docker-compose.yml' and not enable_nextjs:
                continue
            # Ignorer le fichier sans Next.js si on veut Next.js
            if item == 'docker-compose-no-nextjs.yml' and enable_nextjs:
                continue
                
            src = os.path.join(template_path, item)
            dst = os.path.join(project_path, item)
            
            # Cas spécial: renommer docker-compose-no-nextjs.yml en docker-compose.yml
            if item == 'docker-compose-no-nextjs.yml' and not enable_nextjs:
                dst = os.path.join(project_path, 'docker-compose.yml')
            
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
        
        # Attendre que MySQL soit prêt SANS aucun événement SocketIO
        print("🧠 Attente silencieuse de la disponibilité MySQL...")
        
        # Attente simple sans émission d'événements SocketIO
        max_attempts = 60
        attempt = 0
        while attempt < max_attempts:
            if smart_mysql_check(container_name, timeout=1):
                print(f"✅ MySQL prêt après {attempt + 1} tentatives")
                break
            attempt += 1
            print(f"⏳ Tentative {attempt}/{max_attempts} - attente MySQL...")
            time.sleep(2)
        
        if attempt >= max_attempts:
            print("❌ MySQL n'est pas prêt après 60 tentatives")
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

def intelligent_mysql_wait(container_name, project_name, max_wait_time=60, emit_progress=True):
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
            
            # Emmettre le progrès pour l'interface seulement pour les imports
            if emit_progress:
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

@app.route('/create_project', methods=['POST'])
def create_project():
    try:
        print("🚀 Début de création du projet")
        
        # Récupérer les données du formulaire
        project_name = request.form['project_name'].strip()
        project_hostname = request.form.get('project_hostname', '').strip()
        
        if not project_name:
            flash('Le nom du projet est requis', 'error')
            return redirect(url_for('index'))
        
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
        
        # Vérifier le fichier archive WP Migrate Pro (optionnel)
        wp_migrate_archive = request.files.get('wp_migrate_archive')
        
        # Valider l'archive si fournie
        if wp_migrate_archive and wp_migrate_archive.filename:
            if not allowed_file(wp_migrate_archive.filename):
                flash('Type de fichier archive non autorisé', 'error')
                return redirect(url_for('index'))
            print(f"📦 Archive WP Migrate Pro: {wp_migrate_archive.filename}")
        else:
            wp_migrate_archive = None
            print("📦 Aucune archive WP Migrate Pro - site WordPress vierge")
        
        # Créer le dossier du projet
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if os.path.exists(project_path):
            flash(f'Le projet {project_name} existe déjà', 'error')
            return redirect(url_for('index'))
        
        print(f"📂 Création du dossier: {project_path}")
        os.makedirs(project_path, exist_ok=True)
        
        # Vérifier si Next.js est demandé
        enable_nextjs = request.form.get('enable_nextjs') == 'on'
        print(f"⚡ Next.js demandé: {enable_nextjs}")
        
        # Copier le template Docker
        print("📋 Copie du template Docker...")
        copy_docker_template(project_path, enable_nextjs)
        
        # Sauvegarder l'archive WP Migrate Pro (si fournie)
        wp_migrate_path = None
        wp_content_path = None
        db_path = None
        
        if wp_migrate_archive:
            wp_migrate_filename = secure_filename(wp_migrate_archive.filename)
            wp_migrate_path = os.path.join(app.config['UPLOAD_FOLDER'], wp_migrate_filename)
            print(f"💾 Sauvegarde de l'archive WP Migrate Pro: {wp_migrate_path}")
            wp_migrate_archive.save(wp_migrate_path)
            
            if not os.path.exists(wp_migrate_path):
                raise Exception(f"Erreur: archive WP Migrate Pro non sauvegardée: {wp_migrate_path}")
            print(f"✅ Archive WP Migrate Pro sauvegardée")
            
            # Extraire l'archive WP Migrate Pro
            temp_extract_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_extract_' + project_name)
            print(f"📦 Extraction de l'archive WP Migrate Pro vers: {temp_extract_path}")
            os.makedirs(temp_extract_path, exist_ok=True)
            extract_zip(wp_migrate_path, temp_extract_path)
            
            # Vérifier la structure WP Migrate Pro
            expected_wp_content = os.path.join(temp_extract_path, 'app', 'public', 'wp-content')
            expected_sql = os.path.join(temp_extract_path, 'app', 'sql', 'local.sql')
            
            if os.path.exists(expected_wp_content):
                print(f"✅ wp-content trouvé dans l'archive: {expected_wp_content}")
                wp_content_path = expected_wp_content
            else:
                print(f"⚠️ wp-content non trouvé dans l'archive à l'emplacement attendu: {expected_wp_content}")
                
            if os.path.exists(expected_sql):
                print(f"✅ Fichier SQL trouvé dans l'archive: {expected_sql}")
                db_path = expected_sql
            else:
                print(f"⚠️ Fichier SQL non trouvé dans l'archive à l'emplacement attendu: {expected_sql}")
        
        # Extraire wp-content ou utiliser celui par défaut
        wp_content_dest = os.path.join(project_path, 'wordpress', 'wp-content')
        print(f"📦 Configuration wp-content: {wp_content_dest}")
        os.makedirs(wp_content_dest, exist_ok=True)
        
        if wp_content_path:
            # Copier le wp-content depuis l'archive WP Migrate Pro
            print(f"📦 Copie wp-content depuis l'archive WP Migrate Pro: {wp_content_path}")
            import shutil
            if os.path.exists(wp_content_path):
                # Copier récursivement tout le contenu
                shutil.copytree(wp_content_path, wp_content_dest, dirs_exist_ok=True)
                print("✅ wp-content copié depuis l'archive WP Migrate Pro")
            else:
                print("⚠️ wp-content introuvable dans l'archive, création d'un wp-content vierge")
                create_default_wp_content(wp_content_dest)
        else:
            # Utiliser un wp-content vierge avec les thèmes par défaut
            print("📦 Création d'un wp-content vierge avec thèmes par défaut")
            create_default_wp_content(wp_content_dest)
        
        # Trouver les ports libres automatiquement
        print("🔍 Recherche de ports libres...")
        project_port = find_free_port_for_project()
        pma_port = find_free_port_for_project(project_port + 1)
        mailpit_port = find_free_port_for_project(pma_port + 1)
        smtp_port = find_free_port_for_project(mailpit_port + 1)
        nextjs_port = find_free_port_for_project(smtp_port + 1) if enable_nextjs else None
        
        print(f"🌐 Port WordPress: {project_port}")
        print(f"🔧 Port phpMyAdmin: {pma_port}")
        print(f"📧 Port Mailpit: {mailpit_port}")
        print(f"📨 Port SMTP: {smtp_port}")
        if enable_nextjs:
            print(f"⚡ Port Next.js: {nextjs_port}")
        
        # Modifier le docker-compose.yml avec le bon nom de projet, hostname et port
        compose_file = os.path.join(project_path, 'docker-compose.yml')
        print(f"⚙️ Configuration Docker Compose: {compose_file}")
        if os.path.exists(compose_file):
            with open(compose_file, 'r') as f:
                content = f.read()
            content = content.replace('PROJECT_NAME', project_name)
            content = content.replace('PROJECT_PORT', str(project_port))
            content = content.replace('PROJECT_PMA_PORT', str(pma_port))
            content = content.replace('PROJECT_MAILPIT_PORT', str(mailpit_port))
            content = content.replace('PROJECT_SMTP_PORT', str(smtp_port))
            
            if enable_nextjs:
                content = content.replace('PROJECT_NEXTJS_PORT', str(nextjs_port))
                
            with open(compose_file, 'w') as f:
                f.write(content)
            print("✅ Docker Compose configuré")
        else:
            raise Exception("Fichier docker-compose.yml manquant")
        
        # Sauvegarder les ports attribués
        port_file = os.path.join(project_path, '.port')
        pma_port_file = os.path.join(project_path, '.pma_port')
        mailpit_port_file = os.path.join(project_path, '.mailpit_port')
        smtp_port_file = os.path.join(project_path, '.smtp_port')
        with open(port_file, 'w') as f:
            f.write(str(project_port))
        with open(pma_port_file, 'w') as f:
            f.write(str(pma_port))
        with open(mailpit_port_file, 'w') as f:
            f.write(str(mailpit_port))
        with open(smtp_port_file, 'w') as f:
            f.write(str(smtp_port))
        print(f"✅ Port WordPress {project_port} sauvegardé")
        print(f"✅ Port phpMyAdmin {pma_port} sauvegardé")
        print(f"✅ Port Mailpit {mailpit_port} sauvegardé")
        print(f"✅ Port SMTP {smtp_port} sauvegardé")
        
        # Gérer Next.js si demandé
        if enable_nextjs:
            nextjs_port_file = os.path.join(project_path, '.nextjs_port')
            with open(nextjs_port_file, 'w') as f:
                f.write(str(nextjs_port))
            print(f"✅ Port Next.js {nextjs_port} sauvegardé")
            
            # Créer le dossier nextjs avec un exemple de base
            nextjs_path = os.path.join(project_path, 'nextjs')
            os.makedirs(nextjs_path, exist_ok=True)
            
            # Créer un package.json basique pour Next.js
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
            
            # Créer un README pour Next.js
            readme_content = f"""# {project_name} Frontend (Next.js)

Ce dossier contient le frontend Next.js pour le projet {project_name}.

## Démarrage rapide

1. Le conteneur Next.js va automatiquement installer les dépendances
2. Votre application sera disponible sur http://192.168.1.21:{nextjs_port}
3. Modifiez les fichiers dans ce dossier pour développer votre frontend

## Structure recommandée

```
nextjs/
├── pages/
│   ├── index.js      # Page d'accueil
│   └── api/          # API routes
├── components/       # Composants React
├── styles/           # Fichiers CSS
└── public/          # Assets statiques
```

## Configuration WordPress Headless

Pour connecter Next.js à WordPress, utilisez l'API REST WordPress :
- URL de l'API: http://wordpress:80/wp-json/wp/v2/
- Accessible depuis le conteneur Next.js via le réseau Docker

## Développement

Le mode développement Next.js est activé par défaut avec hot-reload.
"""
            
            with open(os.path.join(nextjs_path, 'README.md'), 'w') as f:
                f.write(readme_content)
            
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
          <p>Votre WordPress est accessible à l'adresse : <strong>http://wordpress</strong> (dans Docker) ou <strong>http://192.168.1.21:{project_port}</strong> (depuis l'extérieur)</p>
          
          <h3>API WordPress</h3>
          <p>L'API REST WordPress est disponible à :</p>
          <ul>
            <li>Depuis Next.js : <code>http://wordpress/wp-json/wp/v2/</code></li>
            <li>Depuis l'extérieur : <code>http://192.168.1.21:{project_port}/wp-json/wp/v2/</code></li>
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
            
            print(f"✅ Dossier Next.js créé avec configuration de base")
        
        # Modifier le wp-config.php avec le bon port
        wp_config_file = os.path.join(project_path, 'wordpress', 'wp-config.php')
        print(f"⚙️ Configuration WordPress: {wp_config_file}")
        if os.path.exists(wp_config_file):
            with open(wp_config_file, 'r') as f:
                wp_content = f.read()
            wp_content = wp_content.replace('PROJECT_PORT', str(project_port))
            with open(wp_config_file, 'w') as f:
                f.write(wp_content)
            print("✅ WordPress configuré avec le port")
        else:
            print("⚠️ Fichier wp-config.php manquant, création automatique par WordPress")
        
        # Sauvegarder l'hostname dans un fichier de configuration
        hostname_file = os.path.join(project_path, '.hostname')
        with open(hostname_file, 'w') as f:
            f.write(project_hostname)
        print(f"✅ Hostname sauvegardé: {project_hostname}")
        
        # Lancer Docker Compose
        print("🐳 Lancement de Docker Compose...")
        result = subprocess.run([
            'docker-compose', 'up', '-d'
        ], capture_output=True, text=True, cwd=project_path)
        
        if result.returncode != 0:
            raise Exception(f"Erreur Docker Compose: {result.stderr}")
        
        print("✅ Conteneurs Docker lancés")
        
        # Attendre un peu que les conteneurs se lancent
        print("⏳ Attente du démarrage des conteneurs...")
        time.sleep(45)
        
        # Importer la base de données ou créer une base vierge
        if db_path:
            print("🗃️ Début import de la base de données...")
            if not import_database(project_path, db_path, project_name):
                flash('Projet créé mais erreur lors de l\'import de la base de données', 'warning')
            else:
                flash(f'Projet {project_name} créé avec succès !', 'success')
        else:
            print("🗃️ Création d'une base de données WordPress vierge...")
            if not create_clean_wordpress_database(project_path, project_name):
                flash('Projet créé mais erreur lors de la création de la base de données', 'warning')
            else:
                flash(f'Projet {project_name} créé avec succès ! Rendez-vous sur le site pour terminer l\'installation WordPress.', 'success')
        
        # Note: Plus besoin d'ajouter l'hostname aux /etc/hosts car nous utilisons l'IP directe
        print(f"🌐 Configuration terminée - Site accessible via http://192.168.1.21:{project_port}")
        
        # Nettoyer les fichiers temporaires
        print("🧹 Nettoyage des fichiers temporaires...")
        try:
            if wp_migrate_path and os.path.exists(wp_migrate_path):
                os.remove(wp_migrate_path)
                print("✅ Archive WP Migrate Pro temporaire supprimée")
            
            # Nettoyer le dossier d'extraction temporaire
            temp_extract_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_extract_' + project_name)
            if os.path.exists(temp_extract_path):
                import shutil
                shutil.rmtree(temp_extract_path)
                print("✅ Dossier d'extraction temporaire supprimé")
        except Exception as e:
            print(f"⚠️ Erreur lors du nettoyage: {e}")
        
        return redirect(url_for('index'))
        
    except Exception as e:
        print(f"❌ Erreur lors de la création du projet: {str(e)}")
        flash(f'Erreur lors de la création du projet: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/projects')
def list_projects():
    """Liste les projets existants (ancienne route pour compatibilité)"""
    projects = []
    if os.path.exists(PROJECTS_FOLDER):
        for project in os.listdir(PROJECTS_FOLDER):
            project_path = os.path.join(PROJECTS_FOLDER, project)
            if os.path.isdir(project_path):
                projects.append(project)
    return jsonify(projects)

@app.route('/projects_with_status')
def list_projects_with_status():
    """Liste les projets existants avec leur statut et hostname"""
    projects = []
    projects_to_cleanup = []
    
    if os.path.exists(PROJECTS_FOLDER):
        for project in os.listdir(PROJECTS_FOLDER):
            project_path = os.path.join(PROJECTS_FOLDER, project)
            
            try:
                # Vérifier que c'est un dossier et qu'on peut y accéder
                if not os.path.isdir(project_path):
                    continue
                
                # Test d'accès en lecture au dossier
                try:
                    dir_contents = os.listdir(project_path)
                except PermissionError:
                    print(f"⚠️ Dossier {project} inaccessible, marqué pour nettoyage...")
                    projects_to_cleanup.append(project_path)
                    continue
                
                # Vérifier que c'est un projet valide (doit avoir docker-compose.yml)
                docker_compose_file = os.path.join(project_path, 'docker-compose.yml')
                if not os.path.exists(docker_compose_file):
                    print(f"⚠️ Projet {project} invalide (pas de docker-compose.yml), marqué pour nettoyage...")
                    projects_to_cleanup.append(project_path)
                    continue
                
                # Vérifier que le docker-compose.yml est valide
                try:
                    with open(docker_compose_file, 'r') as f:
                        compose_content = f.read()
                    if not compose_content.strip() or project not in compose_content:
                        print(f"⚠️ Projet {project} corrompu (docker-compose.yml invalide), marqué pour nettoyage...")
                        projects_to_cleanup.append(project_path)
                        continue
                except Exception as e:
                    print(f"⚠️ Erreur lecture docker-compose.yml pour {project}: {e}, marqué pour nettoyage...")
                    projects_to_cleanup.append(project_path)
                    continue
                
                # Vérifier le statut des conteneurs
                status = check_project_status(project)
                
                # Lire l'hostname depuis le fichier .hostname
                hostname_file = os.path.join(project_path, '.hostname')
                hostname = None
                if os.path.exists(hostname_file):
                    try:
                        with open(hostname_file, 'r') as f:
                            hostname = f.read().strip()
                    except Exception:
                        hostname = f"{project}.local"
                else:
                    hostname = f"{project}.local"
                
                # Lire le port depuis le fichier .port
                port_file = os.path.join(project_path, '.port')
                port = 8080  # Port par défaut
                if os.path.exists(port_file):
                    try:
                        with open(port_file, 'r') as f:
                            port = int(f.read().strip())
                    except Exception:
                        port = 8080
                
                # Lire le port phpMyAdmin depuis le fichier .pma_port
                pma_port_file = os.path.join(project_path, '.pma_port')
                pma_port = None
                if os.path.exists(pma_port_file):
                    try:
                        with open(pma_port_file, 'r') as f:
                            pma_port = int(f.read().strip())
                    except Exception:
                        pma_port = None
                
                # Lire le port Mailpit depuis le fichier .mailpit_port
                mailpit_port_file = os.path.join(project_path, '.mailpit_port')
                mailpit_port = None
                if os.path.exists(mailpit_port_file):
                    try:
                        with open(mailpit_port_file, 'r') as f:
                            mailpit_port = int(f.read().strip())
                    except Exception:
                        mailpit_port = None
                
                # Lire le port Next.js depuis le fichier .nextjs_port
                nextjs_port_file = os.path.join(project_path, '.nextjs_port')
                nextjs_port = None
                if os.path.exists(nextjs_port_file):
                    try:
                        with open(nextjs_port_file, 'r') as f:
                            nextjs_port = int(f.read().strip())
                    except Exception:
                        nextjs_port = None
                
                projects.append({
                    'name': project,
                    'status': status,
                    'hostname': hostname,
                    'port': port,
                    'pma_port': pma_port,
                    'mailpit_port': mailpit_port,
                    'nextjs_port': nextjs_port
                })
                
            except Exception as e:
                print(f"⚠️ Erreur lors du traitement du projet {project}: {e}")
                projects_to_cleanup.append(project_path)
                continue
    
    # Nettoyer les projets invalides ou corrompus
    if projects_to_cleanup:
        print(f"🧹 Nettoyage automatique de {len(projects_to_cleanup)} projet(s) invalide(s)...")
        for cleanup_path in projects_to_cleanup:
            cleanup_project_name = os.path.basename(cleanup_path)
            print(f"🗑️ Suppression du projet corrompu: {cleanup_project_name}")
            
            try:
                # Tenter d'arrêter les conteneurs Docker associés
                original_cwd = os.getcwd()
                if os.path.exists(cleanup_path):
                    try:
                        os.chdir(cleanup_path)
                        subprocess.run(['docker-compose', 'down', '-v', '--remove-orphans'], 
                                     capture_output=True, text=True, timeout=30)
                    except Exception:
                        pass
                    finally:
                        os.chdir(original_cwd)
                
                # Forcer la suppression avec sudo
                result = subprocess.run(['sudo', 'rm', '-rf', cleanup_path], 
                                      capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    print(f"✅ Projet corrompu {cleanup_project_name} supprimé automatiquement")
                else:
                    print(f"⚠️ Impossible de supprimer automatiquement {cleanup_project_name}: {result.stderr}")
                    
            except Exception as cleanup_error:
                print(f"⚠️ Erreur lors du nettoyage automatique de {cleanup_project_name}: {cleanup_error}")
                
    return jsonify(projects)

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
        db_filename = secure_filename(db_file.filename)
        db_path = os.path.join(app.config['UPLOAD_FOLDER'], f"update_{db_filename}")
        db_file.save(db_path)
        
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
        
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Aller dans le dossier du projet
        original_cwd = os.getcwd()
        os.chdir(project_path)
        
        try:
            # Arrêter et supprimer les conteneurs avec leurs volumes
            print("🛑 Arrêt des conteneurs...")
            result = subprocess.run([
                'docker-compose', 'down', '-v', '--remove-orphans'
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"⚠️ Erreur lors de l'arrêt: {result.stderr}")
            else:
                print("✅ Conteneurs arrêtés")
            
            # Supprimer tous les conteneurs contenant le nom du projet (même arrêtés)
            print("🗑️ Suppression de tous les conteneurs liés au projet...")
            all_containers_result = subprocess.run([
                'docker', 'ps', '-a', '--format', '{{.Names}}'
            ], capture_output=True, text=True)
            
            if all_containers_result.stdout.strip():
                for container in all_containers_result.stdout.strip().split('\n'):
                    if container and project_name in container:
                        # Arrêter le conteneur
                        subprocess.run(['docker', 'stop', container], capture_output=True, text=True)
                        # Supprimer le conteneur
                        subprocess.run(['docker', 'rm', '-f', container], capture_output=True, text=True)
                        print(f"🗑️ Conteneur supprimé: {container}")
            
            # Supprimer toutes les images contenant le nom du projet
            print("🗑️ Suppression des images...")
            images_result = subprocess.run([
                'docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'
            ], capture_output=True, text=True)
            
            if images_result.stdout.strip():
                for image in images_result.stdout.strip().split('\n'):
                    if image and project_name in image:
                        subprocess.run(['docker', 'rmi', '-f', image], capture_output=True, text=True)
                        print(f"🗑️ Image supprimée: {image}")
            
            # Supprimer tous les volumes contenant le nom du projet
            print("💾 Suppression des volumes...")
            volumes_result = subprocess.run([
                'docker', 'volume', 'ls', '--format', '{{.Name}}'
            ], capture_output=True, text=True)
            
            if volumes_result.stdout.strip():
                for volume in volumes_result.stdout.strip().split('\n'):
                    if volume and project_name in volume:
                        subprocess.run(['docker', 'volume', 'rm', '-f', volume], capture_output=True, text=True)
                        print(f"💾 Volume supprimé: {volume}")
            
        finally:
            # Revenir au dossier original
            os.chdir(original_cwd)
        
        # Supprimer l'hostname du fichier /etc/hosts
        print(f"🌐 Suppression de l'hostname du fichier /etc/hosts...")
        try:
            # Lire l'hostname depuis le fichier .hostname
            hostname_file = os.path.join(project_path, '.hostname')
            if os.path.exists(hostname_file):
                with open(hostname_file, 'r') as f:
                    hostname = f.read().strip()
            else:
                hostname = f"{project_name}.local"
            
            script_path = os.path.join(os.path.dirname(__file__), 'manage_hosts.sh')
            subprocess.run(['sudo', script_path, 'remove', hostname], check=True)
            print(f"✅ Hostname {hostname} supprimé des hosts")
        except Exception as e:
            print(f"⚠️ Erreur lors de la suppression de l'hostname: {e}")
        
        # Supprimer le dossier du projet - Méthode simplifiée et robuste
        print("📁 Suppression des fichiers du projet...")
        project_deleted = False
        
        # Méthode 1: Suppression directe avec sudo (plus fiable)
        try:
            print("🔐 Suppression avec sudo...")
            result = subprocess.run([
                'sudo', 'rm', '-rf', project_path
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print("✅ Fichiers supprimés avec sudo")
                project_deleted = True
            else:
                print(f"⚠️ Erreur sudo rm: {result.stderr}")
                
        except Exception as sudo_error:
            print(f"⚠️ Erreur suppression sudo: {sudo_error}")
        
        # Méthode 2: Fallback avec correction des permissions puis shutil
        if not project_deleted and os.path.exists(project_path):
            try:
                print("🔧 Tentative avec correction des permissions...")
                # Forcer les permissions en écriture
                subprocess.run(['sudo', 'chmod', '-R', '777', project_path], 
                             capture_output=True, text=True, timeout=30)
                
                import shutil
                shutil.rmtree(project_path)
                print("✅ Fichiers supprimés avec shutil")
                project_deleted = True
                
            except Exception as shutil_error:
                print(f"⚠️ Erreur suppression shutil: {shutil_error}")
        
        # Vérification finale
        if os.path.exists(project_path):
            print(f"⚠️ ATTENTION: Le dossier {project_path} existe encore")
            print(f"⚠️ Suppression manuelle requise: sudo rm -rf {project_path}")
        else:
            print("✅ Dossier projet complètement supprimé")
        
        print(f"✅ Projet {project_name} supprimé complètement")
        return jsonify({'success': True, 'message': 'Projet supprimé avec succès'})
        
    except Exception as e:
        print(f"❌ Erreur lors de la suppression du projet: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/start_project/<project_name>', methods=['POST'])
def start_project(project_name):
    """Démarre tous les conteneurs d'un projet"""
    try:
        print(f"▶️ Démarrage du projet: {project_name}")
        
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Aller dans le dossier du projet et démarrer
        original_cwd = os.getcwd()
        os.chdir(project_path)
        
        try:
            result = subprocess.run([
                'docker-compose', 'up', '-d'
            ], capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0:
                print(f"✅ Projet {project_name} démarré")
                return jsonify({'success': True, 'message': 'Projet démarré avec succès'})
            else:
                print(f"❌ Erreur démarrage: {result.stderr}")
                return jsonify({'success': False, 'message': f'Erreur: {result.stderr}'})
                
        finally:
            os.chdir(original_cwd)
            
    except Exception as e:
        print(f"❌ Erreur lors du démarrage: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/stop_project/<project_name>', methods=['POST'])
def stop_project(project_name):
    """Arrête tous les conteneurs d'un projet"""
    try:
        print(f"⏹️ Arrêt du projet: {project_name}")
        
        project_path = os.path.join(PROJECTS_FOLDER, project_name)
        if not os.path.exists(project_path):
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Aller dans le dossier du projet et arrêter
        original_cwd = os.getcwd()
        os.chdir(project_path)
        
        try:
            result = subprocess.run([
                'docker-compose', 'stop'
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print(f"✅ Projet {project_name} arrêté")
                return jsonify({'success': True, 'message': 'Projet arrêté avec succès'})
            else:
                print(f"❌ Erreur arrêt: {result.stderr}")
                return jsonify({'success': False, 'message': f'Erreur: {result.stderr}'})
                
        finally:
            os.chdir(original_cwd)
            
    except Exception as e:
        print(f"❌ Erreur lors de l'arrêt: {e}")
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
      - apparmor:unconfined
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

if __name__ == '__main__':
    # Créer les dossiers nécessaires
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(PROJECTS_FOLDER, exist_ok=True)
    
    # Démarrer l'application avec SocketIO
    # Mode debug désactivé pour la production/systemd
    debug_mode = os.getenv('FLASK_ENV') != 'production'
    socketio.run(app, host='0.0.0.0', port=5000, debug=debug_mode, allow_unsafe_werkzeug=True) 