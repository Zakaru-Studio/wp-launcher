#!/usr/bin/env python3
"""
Utilitaires pour la gestion et création des projets
"""
import os
import shutil
import subprocess
import json
from werkzeug.utils import secure_filename


def secure_project_name(project_name):
    """Sécurise un nom de projet"""
    return secure_filename(project_name.replace(' ', '-').lower())


def copy_docker_template(project_path, project_name, project_hostname, ports, enable_nextjs=False):
    """Copie le template docker-compose dans le projet selon la configuration (version robuste)"""
    template_path = 'docker-template'
    if not os.path.exists(template_path):
        raise Exception(f"Template Docker non trouvé: {template_path}")
    
    try:
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
            
            # Gestion robuste de la copie
            if os.path.isdir(src):
                _copy_directory_robust(src, dst)
            else:
                _copy_file_robust(src, dst, project_name, project_hostname, ports)
                    
    except Exception as e:
        print(f"❌ Erreur lors de la copie du template Docker:")
        print(f"   Source: {template_path}")
        print(f"   Destination: {project_path}")
        print(f"   Erreur: {e}")
        raise Exception(f"Échec de la copie du template Docker: {e}")


def _copy_directory_robust(src, dst):
    """Copie un répertoire de manière robuste"""
    if os.path.exists(dst):
        print(f"🗑️ Suppression du dossier existant: {dst}")
        try:
            shutil.rmtree(dst)
        except (PermissionError, OSError) as e:
            print(f"⚠️ Suppression normale échouée: {e}")
            _force_remove_directory(dst)
    
    print(f"📁 Copie du dossier: {src} → {dst}")
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _copy_file_robust(src, dst, project_name=None, project_hostname=None, ports=None):
    """Copie un fichier de manière robuste et remplace les placeholders"""
    print(f"📄 Copie du fichier: {src} → {dst}")
    
    if os.path.exists(dst):
        try:
            os.chmod(dst, 0o666)
        except Exception:
            pass
    
    # Lire le contenu du fichier source
    with open(src, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Remplacer les placeholders si les paramètres sont fournis
    if project_name and project_hostname:
        content = content.replace('PROJECT_NAME', project_name)
        content = content.replace('{project_name}', project_name)
        content = content.replace('{project_hostname}', project_hostname)
        print(f"🔄 Placeholders remplacés: {project_name}, {project_hostname}")
    
    # Remplacer les placeholders de ports si fournis
    if ports:
        content = content.replace('{wordpress_port}', str(ports.get('wordpress', '8080')))
        content = content.replace('{phpmyadmin_port}', str(ports.get('phpmyadmin', '8081')))
        content = content.replace('{mailpit_port}', str(ports.get('mailpit', '8082')))
        content = content.replace('{smtp_port}', str(ports.get('smtp', '8083')))
        if 'nextjs' in ports:
            content = content.replace('{nextjs_port}', str(ports['nextjs']))
        print(f"🔄 Ports remplacés: {ports}")
    
    # Écrire le contenu modifié dans le fichier destination
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(content)
    
    try:
        os.chmod(dst, 0o664)
    except Exception:
        pass


def _force_remove_directory(dst):
    """Supprime un répertoire de force"""
    try:
        # Changer les permissions récursivement
        for root, dirs, files in os.walk(dst):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o777)
            for f in files:
                os.chmod(os.path.join(root, f), 0o666)
        shutil.rmtree(dst)
    except Exception as e2:
        print(f"⚠️ Suppression avec permissions échouée: {e2}")
        # Dernière tentative avec sudo
        result = subprocess.run(['sudo', 'rm', '-rf', dst], 
                              capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Impossible de supprimer {dst}: {result.stderr}")
        print(f"✅ Suppression avec sudo réussie")


def copy_docker_template_nextjs_mongo(project_path, project_name, project_hostname):
    """Copie le template docker-compose pour Next.js + MongoDB"""
    template_path = 'docker-template'
    if not os.path.exists(template_path):
        raise Exception(f"Template Docker non trouvé: {template_path}")
    
    try:
        # Copier le docker-compose spécifique Next.js + MongoDB
        src_compose = os.path.join(template_path, 'docker-compose-nextjs-mongo.yml')
        dst_compose = os.path.join(project_path, 'docker-compose.yml')
        
        if os.path.exists(src_compose):
            _copy_file_robust(src_compose, dst_compose, project_name, project_hostname)
            print(f"✅ docker-compose-nextjs-mongo.yml → docker-compose.yml")
        else:
            raise Exception(f"Template Next.js-MongoDB non trouvé: {src_compose}")
        
        # Copier les scripts utiles (pas de dossiers spécifiques WordPress)
        for item in ['init-permissions.sh']:
            src = os.path.join(template_path, item)
            dst = os.path.join(project_path, item)
            
            if os.path.exists(src):
                _copy_file_robust(src, dst, project_name, project_hostname)
                print(f"✅ {item} copié")
        
        print("✅ Template Next.js + MongoDB copié avec succès")
        
    except Exception as e:
        print(f"❌ Erreur lors de la copie du template Next.js + MongoDB:")
        print(f"   Source: {template_path}")
        print(f"   Destination: {project_path}")
        print(f"   Erreur: {e}")
        raise Exception(f"Échec de la copie du template Next.js + MongoDB: {e}")


def copy_docker_template_nextjs_mysql(project_path, project_name, project_hostname):
    """Copie le template docker-compose pour Next.js + MySQL"""
    template_path = 'docker-template'
    if not os.path.exists(template_path):
        raise Exception(f"Template Docker non trouvé: {template_path}")
    
    try:
        # Copier le docker-compose spécifique Next.js + MySQL
        src_compose = os.path.join(template_path, 'docker-compose-nextjs-mysql.yml')
        dst_compose = os.path.join(project_path, 'docker-compose.yml')
        
        if os.path.exists(src_compose):
            _copy_file_robust(src_compose, dst_compose, project_name, project_hostname)
            print(f"✅ docker-compose-nextjs-mysql.yml → docker-compose.yml")
        else:
            raise Exception(f"Template Next.js-MySQL non trouvé: {src_compose}")
        
        # Copier les scripts utiles (pas de dossiers spécifiques WordPress)
        for item in ['init-permissions.sh']:
            src = os.path.join(template_path, item)
            dst = os.path.join(project_path, item)
            
            if os.path.exists(src):
                _copy_file_robust(src, dst, project_name, project_hostname)
                print(f"✅ {item} copié")
        
        print("✅ Template Next.js + MySQL copié avec succès")
        
    except Exception as e:
        print(f"❌ Erreur lors de la copie du template Next.js + MySQL:")
        print(f"   Source: {template_path}")
        print(f"   Destination: {project_path}")
        print(f"   Erreur: {e}")
        raise Exception(f"Échec de la copie du template Next.js + MySQL: {e}")


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


def create_wordpress_base_files(project_path):
    """Crée les fichiers de base WordPress (.htaccess et wp-config.php)"""
    print("📝 Création des fichiers de base WordPress...")
    
    # Créer le fichier .htaccess
    htaccess_content = """# BEGIN WordPress
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]
RewriteBase /
RewriteRule ^index\.php$ - [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule . /index.php [L]
</IfModule>
# END WordPress"""
    
    htaccess_path = os.path.join(project_path, '.htaccess')
    with open(htaccess_path, 'w') as f:
        f.write(htaccess_content)
    print(f"✅ Fichier .htaccess créé: {htaccess_path}")
    
    # Créer le fichier wp-config.php avec placeholders
    wp_config_content = """<?php
/**
 * Configuration WordPress générée par WP Launcher
 */

// Configuration MySQL
define('DB_NAME', 'wordpress');
define('DB_USER', 'wordpress');
define('DB_PASSWORD', 'wordpress');
define('DB_HOST', 'mysql:3306');
define('DB_CHARSET', 'utf8mb4');
define('DB_COLLATE', '');

// Clés de sécurité WordPress
define('AUTH_KEY', 'put your unique phrase here');
define('SECURE_AUTH_KEY', 'put your unique phrase here');
define('LOGGED_IN_KEY', 'put your unique phrase here');
define('NONCE_KEY', 'put your unique phrase here');
define('AUTH_SALT', 'put your unique phrase here');
define('SECURE_AUTH_SALT', 'put your unique phrase here');
define('LOGGED_IN_SALT', 'put your unique phrase here');
define('NONCE_SALT', 'put your unique phrase here');

// Préfixe des tables WordPress
$table_prefix = 'wp_';

// Mode debug (désactivé par défaut)
define('WP_DEBUG', false);

// Configuration des URLs - Utilise l'URL SSL lors de l'exposition
define('WP_HOME', 'https://{project_hostname}.dev.akdigital.fr');
define('WP_SITEURL', 'https://{project_hostname}.dev.akdigital.fr');

// Configuration des fichiers
define('DISALLOW_FILE_EDIT', false);
define('DISALLOW_FILE_MODS', false);

// Configuration du cache
define( 'WP_CACHE', false ); // Added by WP Rocket

// Configuration multisite (désactivé par défaut)
define('WP_ALLOW_MULTISITE', false);

// Configuration des révisions
define('WP_POST_REVISIONS', 3);

// Configuration de la corbeille
define('EMPTY_TRASH_DAYS', 30);

// Configuration des mises à jour automatiques
define('WP_AUTO_UPDATE_CORE', false);

// Configuration du système de fichiers
define('FS_METHOD', 'direct');

// Configuration SSL
define('FORCE_SSL_ADMIN', true);

// Configuration des cookies
define('COOKIEPATH', '/');
define('SITECOOKIEPATH', '/');

// Augmenter les limites d'upload
ini_set('upload_max_filesize', '10240M');
ini_set('post_max_size', '10240M');
ini_set('max_execution_time', '0');
ini_set('max_input_time', '7200');
ini_set('memory_limit', '10240M');

// Définir les constantes WordPress
define('WP_MEMORY_LIMIT', '10240M');
define('UPLOAD_MAX_FILESIZE', '10240M');
define('POST_MAX_SIZE', '10240M');

// Configuration des langues
define('WPLANG', 'fr_FR');

// Configuration du chemin absolu vers WordPress
if (!defined('ABSPATH')) {
    define('ABSPATH', __DIR__ . '/');
}

// Configuration des chemins - Utilise l'URL SSL
define('WP_CONTENT_DIR', ABSPATH . 'wp-content');
define('WP_CONTENT_URL', 'https://{project_hostname}.dev.akdigital.fr/wp-content');

// Configuration pour proxy HTTPS (Traefik)
if (isset($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https') {
    $_SERVER['HTTPS'] = 'on';
    $_SERVER['SERVER_PORT'] = 443;
}

// Force HTTPS detection
if (isset($_SERVER['HTTP_X_FORWARDED_FOR'])) {
    $_SERVER['HTTPS'] = 'on';
    $_SERVER['SERVER_PORT'] = 443;
}

// Configuration pour reverse proxy
define('WP_HOME_SSL', true);
define('WP_SITEURL_SSL', true);

// Chargement des réglages WordPress
require_once ABSPATH . 'wp-settings.php';
"""
    
    wp_config_path = os.path.join(project_path, 'wp-config.php')
    with open(wp_config_path, 'w') as f:
        f.write(wp_config_content)
    print(f"✅ Fichier wp-config.php créé: {wp_config_path}")
    
    print("✅ Fichiers de base WordPress créés avec succès")


def create_nextjs_app_structure(base_path, project_name):
    """Crée la structure complète d'une app Next.js avec client et API"""
    print("📁 Création de la structure Next.js App...")
    
    # Créer le dossier nextjs principal
    nextjs_dir = os.path.join(base_path, 'nextjs')
    os.makedirs(nextjs_dir, exist_ok=True)
    
    # Créer les structures client et API
    _create_nextjs_client_structure(nextjs_dir, project_name)
    _create_nextjs_api_structure(nextjs_dir, project_name)
    
    print("✅ Structure Next.js App créée avec succès")


def _create_nextjs_client_structure(nextjs_dir, project_name):
    """Crée la structure du client Next.js"""
    client_dir = os.path.join(nextjs_dir, 'client')
    os.makedirs(client_dir, exist_ok=True)
    
    # Package.json pour le client
    client_package_json = {
        "name": f"{project_name}-client",
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
            "react-dom": "latest",
            "@headlessui/react": "^1.7.17",
            "@heroicons/react": "^2.0.18",
            "axios": "^1.6.0",
            "js-cookie": "^3.0.5"
        },
        "devDependencies": {
            "@types/node": "^20",
            "@types/react": "^18",
            "@types/react-dom": "^18",
            "@types/js-cookie": "^3.0.6",
            "autoprefixer": "^10",
            "eslint": "^8",
            "eslint-config-next": "14.0.0",
            "postcss": "^8",
            "tailwindcss": "^3.3.0",
            "typescript": "^5"
        }
    }
    
    with open(os.path.join(client_dir, 'package.json'), 'w') as f:
        json.dump(client_package_json, f, indent=2)
    
    # Créer les dossiers de base
    for folder in ['pages', 'components', 'styles', 'lib']:
        os.makedirs(os.path.join(client_dir, folder), exist_ok=True)
    
    print(f"✅ Structure client Next.js créée: {client_dir}")


def _create_nextjs_api_structure(nextjs_dir, project_name):
    """Crée la structure de l'API Express"""
    api_dir = os.path.join(nextjs_dir, 'api')
    os.makedirs(api_dir, exist_ok=True)
    
    # Package.json pour l'API
    api_package_json = {
        "name": f"{project_name}-api",
        "version": "1.0.0",
        "description": f"API Express pour {project_name}",
        "main": "server.js",
        "scripts": {
            "start": "node server.js",
            "dev": "nodemon server.js",
            "test": "jest"
        },
        "dependencies": {
            "express": "^4.18.2",
            "mongoose": "^7.6.0",
            "cors": "^2.8.5",
            "helmet": "^7.0.0",
            "express-rate-limit": "^6.10.0",
            "compression": "^1.7.4",
            "jsonwebtoken": "^9.0.2",
            "bcryptjs": "^2.4.3",
            "zod": "^3.22.4",
            "dotenv": "^16.3.1",
            "nodemailer": "^6.9.7"
        },
        "devDependencies": {
            "nodemon": "^3.0.1",
            "jest": "^29.7.0"
        }
    }
    
    with open(os.path.join(api_dir, 'package.json'), 'w') as f:
        json.dump(api_package_json, f, indent=2)
    
    # Créer les dossiers de base
    for folder in ['routes', 'models', 'middleware', 'utils']:
        os.makedirs(os.path.join(api_dir, folder), exist_ok=True)
    
    print(f"✅ Structure API Express créée: {api_dir}")


def get_project_type(project_path):
    """Détermine le type d'un projet"""
    if os.path.exists(os.path.join(project_path, 'nextjs')):
        return 'nextjs'
    elif os.path.exists(os.path.join(project_path, 'wp-content')):
        return 'wordpress'
    else:
        return 'unknown'


def project_exists(project_name, projects_folder):
    """Vérifie si un projet existe déjà"""
    project_path = os.path.join(projects_folder, project_name)
    return os.path.exists(project_path)


def create_project_marker(project_path, project_type):
    """Crée un marqueur pour identifier le type de projet"""
    marker_file = os.path.join(project_path, '.project_type')
    with open(marker_file, 'w') as f:
        f.write(project_type) 


def update_project_wordpress_urls_in_files(project_path, project_hostname):
    """Met à jour les URLs dans les fichiers du projet WordPress après création"""
    try:
        print(f"🔧 Mise à jour des URLs dans les fichiers pour {project_hostname}")
        
        # Mettre à jour wp-config.php
        wp_config_path = os.path.join(project_path, 'wp-config.php')
        if os.path.exists(wp_config_path):
            with open(wp_config_path, 'r') as f:
                content = f.read()
            
            content = content.replace('{project_hostname}', project_hostname)
            
            with open(wp_config_path, 'w') as f:
                f.write(content)
            print(f"✅ wp-config.php mis à jour avec {project_hostname}")
        
        return True
    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour des fichiers: {e}")
        return False 