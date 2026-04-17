#!/usr/bin/env python3
"""
Utilitaires pour la gestion des bases de données
"""
import os
import re
import subprocess
import time
import secrets
import string
import tempfile
from app.utils.file_utils import extract_zip
from app.config.docker_config import DockerConfig


# Regex stricte pour valider les identifiants (nom de DB, de conteneur, etc.)
_SAFE_IDENT = re.compile(r'^[a-zA-Z0-9_-]+$')


def _safe_ident(name):
    """Valide un identifiant avant de l'interpoler dans une commande docker/SQL.

    N'autorise que [a-zA-Z0-9_-]. Lève ValueError si invalide.
    """
    if not name or not _SAFE_IDENT.match(str(name)):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def _escape_sql_string(value):
    """Échappe une valeur destinée à être interpolée entre quotes simples en SQL."""
    if value is None:
        return ''
    return str(value).replace("\\", "\\\\").replace("'", "''")


def generate_wordpress_security_keys():
    """Génère les clés de sécurité WordPress"""
    def generate_key():
        chars = string.ascii_letters + string.digits + '!@#$%^&*(-_=+)'
        return ''.join(secrets.choice(chars) for _ in range(64))
    
    return {
        'AUTH_KEY': generate_key(),
        'SECURE_AUTH_KEY': generate_key(),
        'LOGGED_IN_KEY': generate_key(),
        'NONCE_KEY': generate_key(),
        'AUTH_SALT': generate_key(),
        'SECURE_AUTH_SALT': generate_key(),
        'LOGGED_IN_SALT': generate_key(),
        'NONCE_SALT': generate_key()
    }


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


def intelligent_mysql_wait(container_name, project_name, max_wait_time=60, socketio=None):
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
            if socketio:
                socketio.emit('import_progress', {
                    'type': 'database_import',
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


def detect_file_encoding(file_path):
    """Détecte l'encodage d'un fichier et retourne son contenu"""
    encodings_to_try = ['utf-8', 'latin-1', 'windows-1252', 'iso-8859-1']
    
    for encoding in encodings_to_try:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
                print(f"✅ Encodage détecté: {encoding}")
                return encoding, content
        except UnicodeDecodeError:
            print(f"⚠️ Échec avec encodage {encoding}")
            continue
    
    print("❌ Impossible de décoder le fichier avec les encodages supportés")
    return None, None


def prepare_sql_file(db_file_path):
    """Prépare un fichier SQL pour l'import (extraction si ZIP, détection d'encodage)"""
    # Si c'est un fichier ZIP, l'extraire d'abord
    if db_file_path.endswith('.zip'):
        print("📦 Extraction de l'archive ZIP...")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            extract_zip(db_file_path, temp_dir)
            # Chercher le fichier .sql dans l'extraction
            sql_files = [f for f in os.listdir(temp_dir) if f.endswith('.sql')]
            if not sql_files:
                raise Exception("Aucun fichier .sql trouvé dans l'archive")
            sql_file = os.path.join(temp_dir, sql_files[0])
            print(f"📄 Fichier SQL trouvé: {sql_files[0]}")
            
            # Détecter l'encodage du fichier SQL extrait
            print("🔍 Détection de l'encodage du fichier SQL...")
            encoding, content = detect_file_encoding(sql_file)
            
            if content is None:
                raise Exception("Impossible de lire le fichier SQL avec les encodages supportés")
            
            return encoding, content
    else:
        sql_file = db_file_path
        print(f"📄 Utilisation du fichier SQL: {os.path.basename(sql_file)}")
        
        # Détecter l'encodage du fichier SQL
        print("🔍 Détection de l'encodage du fichier SQL...")
        encoding, content = detect_file_encoding(sql_file)
        
        if content is None:
            raise Exception("Impossible de lire le fichier SQL avec les encodages supportés")
        
        return encoding, content


def execute_mysql_command(container_name, command, timeout=30):
    """Execute une commande MySQL dans un conteneur Docker"""
    try:
        result = subprocess.run([
            'docker', 'exec', container_name, 'mysql', 
            '-u', 'wordpress', '-pwordpress', 
            '-e', command
        ], capture_output=True, text=True, timeout=timeout)
        
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Timeout lors de l'exécution de la commande MySQL"
    except Exception as e:
        return False, "", str(e)


def check_database_exists(container_name, database_name):
    """Vérifie si une base de données existe"""
    # Valider les identifiants avant interpolation dans la requête SQL
    _safe_ident(container_name)
    _safe_ident(database_name)
    escaped_db = _escape_sql_string(database_name)
    success, stdout, stderr = execute_mysql_command(
        container_name,
        f"SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = '{escaped_db}'"
    )

    if success:
        return database_name in stdout
    else:
        print(f"❌ Erreur vérification base de données: {stderr}")
        return False


def get_database_size(container_name, database_name):
    """Récupère la taille d'une base de données"""
    # Valider les identifiants avant interpolation dans la requête SQL
    _safe_ident(container_name)
    _safe_ident(database_name)
    escaped_db = _escape_sql_string(database_name)
    success, stdout, stderr = execute_mysql_command(
        container_name,
        f"SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 1) AS 'DB Size in MB' FROM information_schema.tables WHERE table_schema='{escaped_db}'"
    )
    
    if success and stdout.strip():
        try:
            # Extraire la taille depuis la sortie
            lines = stdout.strip().split('\n')
            if len(lines) > 1:
                size_str = lines[1].strip()
                return float(size_str) if size_str and size_str != 'NULL' else 0.0
        except (ValueError, IndexError):
            pass
    
    return 0.0


def backup_database(container_name, database_name, backup_path):
    """Crée une sauvegarde d'une base de données"""
    try:
        # Utiliser mysqldump pour créer la sauvegarde
        result = subprocess.run([
            'docker', 'exec', container_name, 'mysqldump',
            '-u', 'wordpress', '-pwordpress',
            '--single-transaction', '--routines', '--triggers',
            database_name
        ], capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(result.stdout)
            print(f"✅ Sauvegarde créée: {backup_path}")
            return True
        else:
            print(f"❌ Erreur lors de la sauvegarde: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde: {e}")
        return False 


def update_wordpress_urls(container_path, project_name, new_url):
    """Met à jour les URLs WordPress dans la base de données lors de l'exposition"""
    try:
        # Valider le nom de projet (utilisé dans les noms de conteneurs docker)
        _safe_ident(project_name)
        # new_url est interpolé dans du SQL : on échappe les quotes et les antislashs
        safe_new_url = _escape_sql_string(new_url)

        print(f"🔄 Mise à jour complète des URLs WordPress pour {project_name} vers {new_url}")

        # Attendre que MySQL soit prêt
        if not intelligent_mysql_wait(container_path, project_name):
            print("❌ MySQL n'est pas prêt pour la mise à jour des URLs")
            return False

        # Détecter l'ancienne URL en lisant la base de données
        old_urls = []
        
        # Récupérer l'ancienne URL depuis la base
        check_cmd = [
            'docker', 'exec', f'{project_name}_mysql_1',
            'mysql', '-u', 'wordpress', '-pwordpress', 'wordpress',
            '-se', "SELECT option_value FROM wp_options WHERE option_name = 'home' LIMIT 1;"
        ]
        
        try:
            result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                current_url = result.stdout.strip()
                if current_url and current_url != new_url:
                    old_urls.append(current_url)
                    print(f"📍 URL actuelle détectée: {current_url}")
        except Exception as e:
            print(f"⚠️ Impossible de détecter l'URL actuelle: {e}")
        
        # Ajouter les URLs communes à remplacer (accès local uniquement)
        local_ip = DockerConfig.LOCAL_IP
        old_urls.extend([
            'http://localhost',
            f'http://{local_ip}:8087',
            f'http://{local_ip}:8090',
            f'http://{local_ip}:8091',
            f'http://{local_ip}:8081',
            f'http://{local_ip}:8082',
            f'http://{local_ip}:8083'
        ])
        
        # Nettoyer les doublons
        old_urls = list(set(old_urls))
        
        print(f"🎯 URLs à remplacer: {old_urls}")
        
        # Commandes SQL pour mettre à jour les URLs principales
        # safe_new_url est déjà échappé (quotes + antislashs)
        base_commands = [
            f"UPDATE wp_options SET option_value = '{safe_new_url}' WHERE option_name = 'home';",
            f"UPDATE wp_options SET option_value = '{safe_new_url}' WHERE option_name = 'siteurl';"
        ]

        # Commandes pour chaque ancienne URL détectée
        update_commands = []
        for old_url in old_urls:
            if old_url and old_url != new_url:
                # Mise à jour complète avec et sans slash final
                old_url_slash = old_url.rstrip('/') + '/'
                old_url_no_slash = old_url.rstrip('/')

                # Échapper chaque ancienne URL avant interpolation
                safe_old_url = _escape_sql_string(old_url)
                safe_old_slash = _escape_sql_string(old_url_slash)
                safe_old_no_slash = _escape_sql_string(old_url_no_slash)

                update_commands.extend([
                    # Options WordPress (plugins, thèmes, widgets)
                    f"UPDATE wp_options SET option_value = REPLACE(option_value, '{safe_old_slash}', '{safe_new_url}/') WHERE option_value LIKE '%{safe_old_url}%';",
                    f"UPDATE wp_options SET option_value = REPLACE(option_value, '{safe_old_no_slash}', '{safe_new_url}') WHERE option_value LIKE '%{safe_old_url}%';",

                    # Contenu des posts
                    f"UPDATE wp_posts SET post_content = REPLACE(post_content, '{safe_old_slash}', '{safe_new_url}/');",
                    f"UPDATE wp_posts SET post_content = REPLACE(post_content, '{safe_old_no_slash}', '{safe_new_url}');",
                    f"UPDATE wp_posts SET post_excerpt = REPLACE(post_excerpt, '{safe_old_slash}', '{safe_new_url}/');",
                    f"UPDATE wp_posts SET post_excerpt = REPLACE(post_excerpt, '{safe_old_no_slash}', '{safe_new_url}');",

                    # Commentaires
                    f"UPDATE wp_comments SET comment_content = REPLACE(comment_content, '{safe_old_slash}', '{safe_new_url}/');",
                    f"UPDATE wp_comments SET comment_content = REPLACE(comment_content, '{safe_old_no_slash}', '{safe_new_url}');",

                    # Métadonnées des posts
                    f"UPDATE wp_postmeta SET meta_value = REPLACE(meta_value, '{safe_old_slash}', '{safe_new_url}/') WHERE meta_value LIKE '%{safe_old_url}%';",
                    f"UPDATE wp_postmeta SET meta_value = REPLACE(meta_value, '{safe_old_no_slash}', '{safe_new_url}') WHERE meta_value LIKE '%{safe_old_url}%';",

                    # Métadonnées des commentaires
                    f"UPDATE wp_commentmeta SET meta_value = REPLACE(meta_value, '{safe_old_slash}', '{safe_new_url}/') WHERE meta_value LIKE '%{safe_old_url}%';",
                    f"UPDATE wp_commentmeta SET meta_value = REPLACE(meta_value, '{safe_old_no_slash}', '{safe_new_url}') WHERE meta_value LIKE '%{safe_old_url}%';",

                    # Métadonnées des utilisateurs
                    f"UPDATE wp_usermeta SET meta_value = REPLACE(meta_value, '{safe_old_slash}', '{safe_new_url}/') WHERE meta_value LIKE '%{safe_old_url}%';",
                    f"UPDATE wp_usermeta SET meta_value = REPLACE(meta_value, '{safe_old_no_slash}', '{safe_new_url}') WHERE meta_value LIKE '%{safe_old_url}%';"
                ])
        
        # Combiner toutes les commandes
        all_commands = base_commands + update_commands
        
        # Commandes de nettoyage du cache
        cache_commands = [
            "DELETE FROM wp_options WHERE option_name LIKE '%_transient_%';",
            "DELETE FROM wp_options WHERE option_name LIKE '%_site_transient_%';",
            "UPDATE wp_options SET option_value = '' WHERE option_name = 'rewrite_rules';"
        ]
        
        all_commands.extend(cache_commands)
        
        print(f"🔧 Exécution de {len(all_commands)} commandes de mise à jour...")
        
        # Exécuter les commandes SQL
        success_count = 0
        for i, command in enumerate(all_commands, 1):
            try:
                mysql_cmd = [
                    'docker', 'exec', f'{project_name}_mysql_1',
                    'mysql', '-u', 'wordpress', '-pwordpress', 'wordpress',
                    '-e', command
                ]
                
                result = subprocess.run(
                    mysql_cmd, 
                    capture_output=True, 
                    text=True, 
                    timeout=30
                )
                
                if result.returncode != 0:
                    print(f"⚠️ Erreur commande {i}/{len(all_commands)}: {result.stderr}")
                else:
                    success_count += 1
                    if i <= len(base_commands):
                        print(f"✅ Commande principale {i}/{len(base_commands)} exécutée")
                    elif i % 10 == 0:  # Afficher le progrès tous les 10 commandes
                        print(f"⏳ Progression: {i}/{len(all_commands)} commandes...")
                    
            except subprocess.TimeoutExpired:
                print(f"⏱️ Timeout commande {i}")
                continue
            except Exception as e:
                print(f"❌ Erreur commande {i}: {e}")
                continue
        
        print(f"✅ Mise à jour terminée: {success_count}/{len(all_commands)} commandes réussies")
        
        # Forcer le rechargement des permaliens
        try:
            flush_cmd = [
                'docker', 'exec', f'{project_name}_mysql_1',
                'mysql', '-u', 'wordpress', '-pwordpress', 'wordpress',
                '-e', "UPDATE wp_options SET option_value = '/%postname%/' WHERE option_name = 'permalink_structure';"
            ]
            subprocess.run(flush_cmd, capture_output=True, text=True, timeout=15)
            print("🔄 Permaliens rechargés")
        except Exception as e:
            print(f"⚠️ Erreur rechargement permaliens: {e}")
        
        print(f"✅ URLs WordPress mises à jour avec succès pour {project_name}")
        print(f"💡 Conseil: Videz le cache de vos plugins (si applicable) depuis l'admin WordPress")
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour des URLs WordPress: {e}")
        return False 


def update_wordpress_urls_simple(container_path, project_name, new_url):
    """Version simplifiée de mise à jour des URLs WordPress (contourne intelligent_mysql_wait)"""
    try:
        # Valider le nom de projet (utilisé dans le nom du conteneur docker)
        _safe_ident(project_name)
        # Échapper l'URL avant interpolation dans le SQL
        safe_new_url = _escape_sql_string(new_url)
        new_url = safe_new_url  # Le reste du SQL plus bas utilise {new_url}

        print(f"🔄 Mise à jour simplifiée des URLs WordPress pour {project_name} vers {new_url}")

        # Préparer la commande SQL complète
        local_ip = DockerConfig.LOCAL_IP
        sql_commands = f"""
-- Mise à jour des URLs principales
UPDATE wp_options SET option_value = '{new_url}' WHERE option_name = 'home';
UPDATE wp_options SET option_value = '{new_url}' WHERE option_name = 'siteurl';

-- Nettoyage des options contenant les anciennes URLs
UPDATE wp_options SET option_value = REPLACE(option_value, 'http://{local_ip}:8087', '{new_url}') WHERE option_value LIKE '%http://{local_ip}:8087%';
UPDATE wp_options SET option_value = REPLACE(option_value, 'http://{local_ip}:8090', '{new_url}') WHERE option_value LIKE '%http://{local_ip}:8090%';
UPDATE wp_options SET option_value = REPLACE(option_value, 'http://{local_ip}:8091', '{new_url}') WHERE option_value LIKE '%http://{local_ip}:8091%';
UPDATE wp_options SET option_value = REPLACE(option_value, 'http://{local_ip}:8081', '{new_url}') WHERE option_value LIKE '%http://{local_ip}:8081%';
UPDATE wp_options SET option_value = REPLACE(option_value, 'http://{local_ip}:8082', '{new_url}') WHERE option_value LIKE '%http://{local_ip}:8082%';
UPDATE wp_options SET option_value = REPLACE(option_value, 'http://{local_ip}:8083', '{new_url}') WHERE option_value LIKE '%http://{local_ip}:8083%';
UPDATE wp_options SET option_value = REPLACE(option_value, 'http://localhost', '{new_url}') WHERE option_value LIKE '%http://localhost%';


-- Nettoyage du contenu des posts
UPDATE wp_posts SET post_content = REPLACE(post_content, 'http://{local_ip}:8087', '{new_url}');
UPDATE wp_posts SET post_content = REPLACE(post_content, 'http://{local_ip}:8090', '{new_url}');
UPDATE wp_posts SET post_content = REPLACE(post_content, 'http://{local_ip}:8091', '{new_url}');
UPDATE wp_posts SET post_content = REPLACE(post_content, 'http://{local_ip}:8081', '{new_url}');
UPDATE wp_posts SET post_content = REPLACE(post_content, 'http://{local_ip}:8082', '{new_url}');
UPDATE wp_posts SET post_content = REPLACE(post_content, 'http://{local_ip}:8083', '{new_url}');
UPDATE wp_posts SET post_content = REPLACE(post_content, 'http://localhost', '{new_url}');
UPDATE wp_posts SET post_excerpt = REPLACE(post_excerpt, 'http://{local_ip}:8087', '{new_url}');
UPDATE wp_posts SET post_excerpt = REPLACE(post_excerpt, 'http://localhost', '{new_url}');

-- Nettoyage des métadonnées
UPDATE wp_postmeta SET meta_value = REPLACE(meta_value, 'http://{local_ip}:8087', '{new_url}') WHERE meta_value LIKE '%http://{local_ip}:8087%';
UPDATE wp_postmeta SET meta_value = REPLACE(meta_value, 'http://{local_ip}:8090', '{new_url}') WHERE meta_value LIKE '%http://{local_ip}:8090%';
UPDATE wp_postmeta SET meta_value = REPLACE(meta_value, 'http://{local_ip}:8091', '{new_url}') WHERE meta_value LIKE '%http://{local_ip}:8091%';
UPDATE wp_postmeta SET meta_value = REPLACE(meta_value, 'http://localhost', '{new_url}') WHERE meta_value LIKE '%http://localhost%';
UPDATE wp_commentmeta SET meta_value = REPLACE(meta_value, 'http://{local_ip}:8087', '{new_url}') WHERE meta_value LIKE '%http://{local_ip}:8087%';
UPDATE wp_commentmeta SET meta_value = REPLACE(meta_value, 'http://localhost', '{new_url}') WHERE meta_value LIKE '%http://localhost%';

UPDATE wp_usermeta SET meta_value = REPLACE(meta_value, 'http://{local_ip}:8087', '{new_url}') WHERE meta_value LIKE '%http://{local_ip}:8087%';
UPDATE wp_usermeta SET meta_value = REPLACE(meta_value, 'http://localhost', '{new_url}') WHERE meta_value LIKE '%http://localhost%';

-- Nettoyage du cache
DELETE FROM wp_options WHERE option_name LIKE '%_transient_%';
DELETE FROM wp_options WHERE option_name LIKE '%_site_transient_%';

-- Forcer le rechargement des règles de réécriture
UPDATE wp_options SET option_value = '' WHERE option_name = 'rewrite_rules';

SELECT 'Mise à jour terminée' as result;
"""
        
        # Exécuter la commande SQL
        mysql_cmd = [
            'docker', 'exec', f'{project_name}_mysql_1',
            'mysql', '-u', 'wordpress', '-pwordpress', 'wordpress',
            '-e', sql_commands
        ]
        
        result = subprocess.run(
            mysql_cmd, 
            capture_output=True, 
            text=True, 
            timeout=60
        )
        
        if result.returncode == 0:
            print(f"✅ URLs WordPress mises à jour avec succès pour {project_name}")
            print(f"💡 Conseil: Videz le cache de vos plugins (si applicable) depuis l'admin WordPress")
            return True
        else:
            print(f"❌ Erreur lors de la mise à jour: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour des URLs WordPress: {e}")
        return False 