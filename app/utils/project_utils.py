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


def copy_docker_template(project_path, project_name, ports, enable_nextjs=False, resource_limits=None):
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
                _copy_file_robust(src, dst, project_name, ports, resource_limits)
                    
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
            # Utiliser la logique de suppression robuste de routes/projects.py si nécessaire
            print(f"❌ Échec de suppression robuste pour {dst}")
    
    print(f"📁 Copie du dossier: {src} → {dst}")
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _copy_file_robust(src, dst, project_name=None, ports=None, resource_limits=None):
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
    if project_name:
        content = content.replace('PROJECT_NAME', project_name)
        content = content.replace('{project_name}', project_name)
        print(f"🔄 Placeholders remplacés: {project_name}")
    
    # Remplacer les placeholders de ports si fournis
    if ports:
        content = content.replace('{wordpress_port}', str(ports.get('wordpress', '8080')))
        content = content.replace('{phpmyadmin_port}', str(ports.get('phpmyadmin', '8081')))
        content = content.replace('{mailpit_port}', str(ports.get('mailpit', '8082')))
        content = content.replace('{smtp_port}', str(ports.get('smtp', '8083')))
        if 'nextjs' in ports:
            content = content.replace('{nextjs_port}', str(ports['nextjs']))
        if 'api' in ports:
            content = content.replace('{api_port}', str(ports['api']))
        if 'mongodb' in ports:
            content = content.replace('{mongodb_port}', str(ports['mongodb']))
        if 'mysql' in ports:
            content = content.replace('{mysql_port}', str(ports['mysql']))
        if 'mongo_express' in ports:
            content = content.replace('{mongo_express_port}', str(ports['mongo_express']))
        print(f"🔄 Ports remplacés: {ports}")
    
    # Remplacer les placeholders de ressources si fournis
    if resource_limits:
        content = content.replace('{wordpress_memory}', resource_limits.get('wordpress_memory', '384m'))
        content = content.replace('{mysql_memory}', resource_limits.get('mysql_memory', '384m'))
        content = content.replace('{wordpress_cpu}', resource_limits.get('wordpress_cpu', '0.75'))
        content = content.replace('{mysql_cpu}', resource_limits.get('mysql_cpu', '0.75'))
        print(f"🔄 Limites ressources remplacées: {resource_limits}")
    
    # Écrire le contenu modifié dans le fichier destination
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(content)
    
    try:
        os.chmod(dst, 0o664)
    except Exception:
        pass


def copy_docker_template_nextjs_mongo(project_path, project_name, ports):
    """Copie le template docker-compose pour Next.js + MongoDB"""
    template_path = 'docker-template'
    if not os.path.exists(template_path):
        raise Exception(f"Template Docker non trouvé: {template_path}")
    
    try:
        # Copier le docker-compose spécifique Next.js + MongoDB
        src_compose = os.path.join(template_path, 'docker-compose-nextjs-mongo.yml')
        dst_compose = os.path.join(project_path, 'docker-compose.yml')
        
        if os.path.exists(src_compose):
            _copy_file_robust(src_compose, dst_compose, project_name, ports)
            print(f"✅ docker-compose-nextjs-mongo.yml → docker-compose.yml")
        else:
            raise Exception(f"Template Next.js-MongoDB non trouvé: {src_compose}")
        
        # Copier les scripts utiles (pas de dossiers spécifiques WordPress)
        for item in ['init-permissions.sh']:
            src = os.path.join(template_path, item)
            dst = os.path.join(project_path, item)
            
            if os.path.exists(src):
                _copy_file_robust(src, dst, project_name, ports)
                print(f"✅ {item} copié")
        
        print("✅ Template Next.js + MongoDB copié avec succès")
        
    except Exception as e:
        print(f"❌ Erreur lors de la copie du template Next.js + MongoDB:")
        print(f"   Source: {template_path}")
        print(f"   Destination: {project_path}")
        print(f"   Erreur: {e}")
        raise Exception(f"Échec de la copie du template Next.js + MongoDB: {e}")


def copy_docker_template_nextjs_mysql(project_path, project_name, ports):
    """Copie le template docker-compose pour Next.js + MySQL"""
    template_path = 'docker-template'
    if not os.path.exists(template_path):
        raise Exception(f"Template Docker non trouvé: {template_path}")
    
    try:
        # Copier le docker-compose spécifique Next.js + MySQL
        src_compose = os.path.join(template_path, 'docker-compose-nextjs-mysql.yml')
        dst_compose = os.path.join(project_path, 'docker-compose.yml')
        
        if os.path.exists(src_compose):
            _copy_file_robust(src_compose, dst_compose, project_name, ports)
            print(f"✅ docker-compose-nextjs-mysql.yml → docker-compose.yml")
        else:
            raise Exception(f"Template Next.js-MySQL non trouvé: {src_compose}")
        
        # Copier les scripts utiles (pas de dossiers spécifiques WordPress)
        for item in ['init-permissions.sh']:
            src = os.path.join(template_path, item)
            dst = os.path.join(project_path, item)
            
            if os.path.exists(src):
                _copy_file_robust(src, dst, project_name, ports)
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
    
    # S'assurer que le dossier wp-content existe
    os.makedirs(wp_content_dest, exist_ok=True)
    
    # Appliquer les bonnes permissions au dossier wp-content AVANT de créer les fichiers
    try:
        import subprocess
        current_user = os.getenv('USER', 'dev-server')
        
        # Changer le propriétaire du dossier wp-content
        subprocess.run(['sudo', 'chown', '-R', f'{current_user}:{current_user}', wp_content_dest], 
                      check=True, capture_output=True)
        
        # Définir les permissions appropriées
        subprocess.run(['chmod', '-R', '755', wp_content_dest], 
                      check=True, capture_output=True)
        
        print(f"✅ Permissions wp-content configurées pour {current_user}")
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Erreur lors de la configuration des permissions wp-content: {e}")
    except Exception as e:
        print(f"⚠️ Erreur inattendue lors de la configuration des permissions: {e}")
    
    # Créer les dossiers de base
    try:
        os.makedirs(os.path.join(wp_content_dest, 'themes'), exist_ok=True)
        os.makedirs(os.path.join(wp_content_dest, 'plugins'), exist_ok=True)
        os.makedirs(os.path.join(wp_content_dest, 'uploads'), exist_ok=True)
        os.makedirs(os.path.join(wp_content_dest, 'mu-plugins'), exist_ok=True)
        
        # Copier le contenu complet du template wp-content
        template_wp_content = os.path.join('docker-template', 'wordpress', 'wp-content')
        if os.path.exists(template_wp_content):
            import shutil
            
            # Copier les mu-plugins du template
            template_mu_plugins = os.path.join(template_wp_content, 'mu-plugins')
            if os.path.exists(template_mu_plugins):
                mu_plugins_dest = os.path.join(wp_content_dest, 'mu-plugins')
                try:
                    for item in os.listdir(template_mu_plugins):
                        src_item = os.path.join(template_mu_plugins, item)
                        dst_item = os.path.join(mu_plugins_dest, item)
                        if os.path.isfile(src_item):
                            shutil.copy2(src_item, dst_item)
                            print(f"✅ mu-plugin copié: {item}")
                    print("✅ mu-plugins du template copiés")
                except Exception as e:
                    print(f"⚠️ Erreur lors de la copie des mu-plugins: {e}")
            
            # Copier les plugins du template
            template_plugins = os.path.join(template_wp_content, 'plugins')
            if os.path.exists(template_plugins):
                plugins_dest = os.path.join(wp_content_dest, 'plugins')
                try:
                    for item in os.listdir(template_plugins):
                        src_item = os.path.join(template_plugins, item)
                        dst_item = os.path.join(plugins_dest, item)
                        if os.path.isdir(src_item):
                            shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                            print(f"✅ Plugin copié: {item}")
                        elif os.path.isfile(src_item):
                            shutil.copy2(src_item, dst_item)
                            print(f"✅ Fichier plugin copié: {item}")
                    print("✅ Plugins du template copiés")
                except Exception as e:
                    print(f"⚠️ Erreur lors de la copie des plugins: {e}")
            
            # Copier les thèmes du template
            template_themes = os.path.join(template_wp_content, 'themes')
            if os.path.exists(template_themes):
                themes_dest = os.path.join(wp_content_dest, 'themes')
                try:
                    for item in os.listdir(template_themes):
                        src_item = os.path.join(template_themes, item)
                        dst_item = os.path.join(themes_dest, item)
                        if os.path.isdir(src_item):
                            shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                            print(f"✅ Thème copié: {item}")
                        elif os.path.isfile(src_item):
                            shutil.copy2(src_item, dst_item)
                            print(f"✅ Fichier thème copié: {item}")
                    print("✅ Thèmes du template copiés")
                except Exception as e:
                    print(f"⚠️ Erreur lors de la copie des thèmes: {e}")
        else:
            print("⚠️ Template wp-content non trouvé dans docker-template/wordpress/wp-content")
        
        # Créer un fichier index.php de sécurité
        index_content = "<?php\n// Silence is golden.\n"
        
        # Créer les fichiers index.php avec gestion d'erreurs
        index_files = [
            os.path.join(wp_content_dest, 'index.php'),
            os.path.join(wp_content_dest, 'themes', 'index.php'),
            os.path.join(wp_content_dest, 'plugins', 'index.php'),
            os.path.join(wp_content_dest, 'uploads', 'index.php'),
            os.path.join(wp_content_dest, 'mu-plugins', 'index.php')
        ]
        
        for index_file in index_files:
            try:
                with open(index_file, 'w') as f:
                    f.write(index_content)
                print(f"✅ Fichier créé: {index_file}")
            except PermissionError as e:
                print(f"❌ Erreur de permissions pour {index_file}: {e}")
                # Essayer de corriger les permissions et réessayer
                try:
                    subprocess.run(['sudo', 'chown', current_user, os.path.dirname(index_file)], 
                                  check=True, capture_output=True)
                    subprocess.run(['chmod', '755', os.path.dirname(index_file)], 
                                  check=True, capture_output=True)
                    with open(index_file, 'w') as f:
                        f.write(index_content)
                    print(f"✅ Fichier créé après correction des permissions: {index_file}")
                except Exception as e2:
                    print(f"❌ Impossible de créer {index_file} même après correction: {e2}")
            except Exception as e:
                print(f"❌ Erreur lors de la création de {index_file}: {e}")
        
        # Appliquer les permissions finales avec stratégie de groupe partagé
        try:
            # S'assurer que dev-server et www-data font partie du groupe www-data
            try:
                subprocess.run(['sudo', 'usermod', '-a', '-G', 'www-data', current_user], 
                              check=True, capture_output=True)
                print(f"✅ {current_user} ajouté au groupe www-data")
            except subprocess.CalledProcessError:
                print(f"⚠️ Impossible d'ajouter {current_user} au groupe www-data")
            
            # www-data propriétaire, groupe www-data pour accès partagé
            subprocess.run(['sudo', 'chown', '-R', '33:www-data', wp_content_dest], 
                          check=True, capture_output=True)
            
            # Permissions: propriétaire (www-data) et groupe (www-data) ont lecture/écriture
            subprocess.run(['find', wp_content_dest, '-type', 'd', '-exec', 'chmod', '775', '{}', ';'], 
                          check=True, capture_output=True)
            subprocess.run(['find', wp_content_dest, '-type', 'f', '-exec', 'chmod', '664', '{}', ';'], 
                          check=True, capture_output=True)
            
            # Permissions spéciales pour uploads
            uploads_dir = os.path.join(wp_content_dest, 'uploads')
            if os.path.exists(uploads_dir):
                subprocess.run(['chmod', '-R', '775', uploads_dir], 
                              check=True, capture_output=True)
            
            # Mettre le sticky bit sur les dossiers pour préserver le groupe
            subprocess.run(['find', wp_content_dest, '-type', 'd', '-exec', 'chmod', 'g+s', '{}', ';'], 
                          check=True, capture_output=True)
            
            # Ajouter des ACL pour renforcer l'accès dev-server
            try:
                subprocess.run(['which', 'setfacl'], check=True, capture_output=True)
                
                # ACL pour dev-server : lecture/écriture/exécution
                subprocess.run(['sudo', 'setfacl', '-R', '-m', f'u:{current_user}:rwx', wp_content_dest], 
                              check=True, capture_output=True)
                # ACL par défaut pour les nouveaux fichiers
                subprocess.run(['sudo', 'setfacl', '-R', '-d', '-m', f'u:{current_user}:rwx', wp_content_dest], 
                              check=True, capture_output=True)
                subprocess.run(['sudo', 'setfacl', '-R', '-d', '-m', 'g:www-data:rwx', wp_content_dest], 
                              check=True, capture_output=True)
                print(f"✅ ACL avancées configurées pour {current_user} et www-data")
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("⚠️ setfacl non disponible, utilisation des permissions de groupe uniquement")
            
            print("✅ Permissions partagées appliquées (www-data propriétaire, groupe www-data pour dev-server)")
        except Exception as e:
            print(f"⚠️ Erreur lors de l'application des permissions finales: {e}")
        
        print("✅ wp-content vierge créé avec succès")
        
    except Exception as e:
        print(f"❌ Erreur lors de la création du wp-content: {e}")
        raise


def create_wordpress_base_files(project_path):
    """Crée les fichiers de base WordPress (.htaccess et wp-config.php)"""
    print("📝 Création des fichiers de base WordPress...")
    
    # S'assurer que le dossier du projet existe et a les bonnes permissions
    try:
        import subprocess
        current_user = os.getenv('USER', 'dev-server')
        
        # Créer le dossier du projet s'il n'existe pas
        os.makedirs(project_path, exist_ok=True)
        
        # Appliquer les bonnes permissions au dossier du projet
        subprocess.run(['sudo', 'chown', '-R', f'{current_user}:{current_user}', project_path], 
                      check=True, capture_output=True)
        subprocess.run(['chmod', '755', project_path], 
                      check=True, capture_output=True)
        
        print(f"✅ Permissions du dossier projet configurées pour {current_user}")
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Erreur lors de la configuration des permissions du projet: {e}")
    except Exception as e:
        print(f"⚠️ Erreur inattendue lors de la configuration des permissions: {e}")
    
    # Créer le fichier .htaccess
    htaccess_content = r"""# BEGIN WordPress
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
    
    try:
        with open(htaccess_path, 'w') as f:
            f.write(htaccess_content)
        print(f"✅ Fichier .htaccess créé: {htaccess_path}")
    except PermissionError as e:
        print(f"❌ Erreur de permissions pour .htaccess: {e}")
        try:
            subprocess.run(['sudo', 'chown', current_user, project_path], 
                          check=True, capture_output=True)
            with open(htaccess_path, 'w') as f:
                f.write(htaccess_content)
            print(f"✅ Fichier .htaccess créé après correction des permissions: {htaccess_path}")
        except Exception as e2:
            print(f"❌ Impossible de créer .htaccess même après correction: {e2}")
            return False
    except Exception as e:
        print(f"❌ Erreur lors de la création de .htaccess: {e}")
        return False
    
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

// Configuration des URLs - Accès local uniquement
define('WP_HOME', 'http://192.168.1.21:PROJECT_PORT');
define('WP_SITEURL', 'http://192.168.1.21:PROJECT_PORT');

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

// Configuration des cookies
define('COOKIEPATH', '/');
define('SITECOOKIEPATH', '/');

// Augmenter les limites d'upload
ini_set('upload_max_filesize', '1024M');
ini_set('post_max_size', '1024M');
ini_set('max_execution_time', '0');
ini_set('max_input_time', '7200');
ini_set('memory_limit', '1024M');

// Définir les constantes WordPress
define('WP_MEMORY_LIMIT', '1024M');
define('UPLOAD_MAX_FILESIZE', '1024M');
define('POST_MAX_SIZE', '1024M');

// Configuration des langues
define('WPLANG', 'fr_FR');

// Configuration du chemin absolu vers WordPress
if (!defined('ABSPATH')) {
    define('ABSPATH', __DIR__ . '/');
}

// Protection WP-CLI : définir les variables SERVER manquantes
if (defined('WP_CLI') && WP_CLI) {
    $_SERVER['SERVER_NAME'] = '192.168.1.21';
    $_SERVER['SERVER_PORT'] = 'PROJECT_PORT';
    $_SERVER['HTTP_HOST'] = '192.168.1.21:PROJECT_PORT';
    $_SERVER['REQUEST_URI'] = '/';
    $_SERVER['REQUEST_METHOD'] = 'GET';
}

// Configuration des chemins - Accès local uniquement
define('WP_CONTENT_DIR', ABSPATH . 'wp-content');
define('WP_CONTENT_URL', 'http://192.168.1.21:PROJECT_PORT/wp-content');

// Chargement des réglages WordPress
require_once ABSPATH . 'wp-settings.php';
"""
    
    wp_config_path = os.path.join(project_path, 'wp-config.php')
    
    # Vérification de sécurité : supprimer wp-config.php s'il existe comme dossier
    if os.path.exists(wp_config_path) and os.path.isdir(wp_config_path):
        print(f"⚠️ wp-config.php existe comme dossier, suppression...")
        try:
            import shutil
            shutil.rmtree(wp_config_path)
        except Exception as e:
            print(f"❌ Impossible de supprimer le dossier wp-config.php: {e}")
            return False
    
    # Créer le fichier wp-config.php
    try:
        with open(wp_config_path, 'w') as f:
            f.write(wp_config_content)
        print(f"✅ Fichier wp-config.php créé: {wp_config_path}")
        
        # Vérifier que c'est bien un fichier
        if not os.path.isfile(wp_config_path):
            print(f"❌ Erreur: wp-config.php n'est pas un fichier valide")
            return False
            
    except PermissionError as e:
        print(f"❌ Erreur de permissions pour wp-config.php: {e}")
        try:
            subprocess.run(['sudo', 'chown', current_user, project_path], 
                          check=True, capture_output=True)
            with open(wp_config_path, 'w') as f:
                f.write(wp_config_content)
            print(f"✅ Fichier wp-config.php créé après correction des permissions: {wp_config_path}")
            
            # Vérifier que c'est bien un fichier
            if not os.path.isfile(wp_config_path):
                print(f"❌ Erreur: wp-config.php n'est pas un fichier valide")
                return False
        except Exception as e2:
            print(f"❌ Impossible de créer wp-config.php même après correction: {e2}")
            return False
    except Exception as e:
        print(f"❌ Erreur lors de la création de wp-config.php: {e}")
        return False
    
    # Appliquer les permissions finales sur tous les fichiers créés
    try:
        subprocess.run(['sudo', 'chown', '-R', f'{current_user}:{current_user}', project_path], 
                      check=True, capture_output=True)
        subprocess.run(['find', project_path, '-type', 'f', '-exec', 'chmod', '644', '{}', ';'], 
                      check=True, capture_output=True)
        print("✅ Permissions finales appliquées aux fichiers de base WordPress")
    except Exception as e:
        print(f"⚠️ Erreur lors de l'application des permissions finales: {e}")
    
    print("✅ Fichiers de base WordPress créés avec succès")
    return True


def create_nextjs_app_structure(base_path, project_name, database_type='mysql'):
    """Crée la structure complète d'une app Next.js avec client et API séparés"""
    print("📁 Création de la structure Next.js App avec client/api séparés...")
    
    # Créer les dossiers client et api
    client_dir = os.path.join(base_path, 'client')
    api_dir = os.path.join(base_path, 'api')
    
    os.makedirs(client_dir, exist_ok=True)
    os.makedirs(api_dir, exist_ok=True)
    
    # Créer la structure du client Next.js
    _create_nextjs_client_structure(client_dir, project_name)
    
    # Créer l'API Express.js
    _create_express_api_structure(api_dir, project_name, database_type)
    
    print("✅ Structure Next.js App avec client/api créée avec succès")


def _create_nextjs_client_structure(client_dir, project_name):
    """Crée la structure du client Next.js"""
    print("📦 Création du client Next.js...")
    
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
            "js-cookie": "^3.0.5",
            "tailwindcss": "^3.3.0"
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
            "typescript": "^5"
        }
    }
    
    with open(os.path.join(client_dir, 'package.json'), 'w') as f:
        json.dump(client_package_json, f, indent=2)
    
    # Créer les dossiers de base
    for folder in ['pages', 'components', 'styles', 'lib', 'public']:
        os.makedirs(os.path.join(client_dir, folder), exist_ok=True)
    
    # Créer next.config.js avec configuration API
    next_config_content = '''/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3001',
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.API_URL || 'http://api:3001'}/:path*`,
      },
    ];
  },
}

module.exports = nextConfig
'''
    
    with open(os.path.join(client_dir, 'next.config.js'), 'w') as f:
        f.write(next_config_content)
    
    # Créer pages/_app.js
    app_content = '''import '../styles/globals.css'

function MyApp({ Component, pageProps }) {
  return <Component {...pageProps} />
}

export default MyApp
'''
    
    with open(os.path.join(client_dir, 'pages', '_app.js'), 'w') as f:
        f.write(app_content)
    
    # Créer pages/index.js avec appel API
    index_content = f'''import Head from 'next/head'
import {{ useState, useEffect }} from 'react'
import styles from '../styles/Home.module.css'

export default function Home() {{
  const [apiStatus, setApiStatus] = useState('Connecting...')
  const [data, setData] = useState(null)

  useEffect(() => {{
    // Test de connexion à l'API
    fetch(process.env.NEXT_PUBLIC_API_URL + '/health')
      .then(res => res.json())
      .then(data => {{
        setApiStatus('Connected ✅')
        setData(data)
      }})
      .catch(err => {{
        setApiStatus('Connection failed ❌')
        console.error(err)
      }})
  }}, [])

  return (
    <div className={{styles.container}}>
      <Head>
        <title>{project_name} - Next.js Client</title>
        <meta name="description" content="Client Next.js pour {project_name}" />
        <link rel="icon" href="/favicon.png" />
      </Head>

      <main className={{styles.main}}>
        <h1 className={{styles.title}}>
          Bienvenue sur <a>{project_name}</a>
        </h1>

        <p className={{styles.description}}>
          Client Next.js connecté à l'API Express.js
        </p>

        <div className={{styles.grid}}>
          <div className={{styles.card}}>
            <h2>API Status</h2>
            <p>{{apiStatus}}</p>
            {{data && (
              <pre>{{JSON.stringify(data, null, 2)}}</pre>
            )}}
          </div>

          <div className={{styles.card}}>
            <h2>Documentation &rarr;</h2>
            <p>Découvrez les fonctionnalités de votre application.</p>
          </div>

          <div className={{styles.card}}>
            <h2>API Routes &rarr;</h2>
            <p>Testez vos endpoints API.</p>
          </div>

          <div className={{styles.card}}>
            <h2>Deploy &rarr;</h2>
            <p>Déployez votre application instantanément.</p>
          </div>
        </div>
      </main>

      <footer className={{styles.footer}}>
        <p>Powered by WP Launcher & Next.js</p>
      </footer>
    </div>
  )
}}
'''
    
    with open(os.path.join(client_dir, 'pages', 'index.js'), 'w') as f:
        f.write(index_content)
    
    # Créer lib/api.js pour les appels API
    api_lib_content = f'''const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3001'

class ApiClient {{
  constructor() {{
    this.baseURL = API_URL
  }}

  async request(endpoint, options = {{}}) {{
    const url = `${{this.baseURL}}${{endpoint}}`
    const config = {{
      headers: {{
        'Content-Type': 'application/json',
        ...options.headers,
      }},
      ...options,
    }}

    try {{
      const response = await fetch(url, config)
      const data = await response.json()
      
      if (!response.ok) {{
        throw new Error(data.message || 'API request failed')
      }}
      
      return data
    }} catch (error) {{
      console.error('API Error:', error)
      throw error
    }}
  }}

  // Méthodes utilitaires
  get(endpoint) {{
    return this.request(endpoint)
  }}

  post(endpoint, data) {{
    return this.request(endpoint, {{
      method: 'POST',
      body: JSON.stringify(data),
    }})
  }}

  put(endpoint, data) {{
    return this.request(endpoint, {{
      method: 'PUT',
      body: JSON.stringify(data),
    }})
  }}

  delete(endpoint) {{
    return this.request(endpoint, {{
      method: 'DELETE',
    }})
  }}
}}

export const api = new ApiClient()
export default api
'''
    
    with open(os.path.join(client_dir, 'lib', 'api.js'), 'w') as f:
        f.write(api_lib_content)
    
    # Créer styles/globals.css
    global_css_content = '''html,
body {
  padding: 0;
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Oxygen,
    Ubuntu, Cantarell, Fira Sans, Droid Sans, Helvetica Neue, sans-serif;
}

a {
  color: inherit;
  text-decoration: none;
}

* {
  box-sizing: border-box;
}

@media (prefers-color-scheme: dark) {
  html {
    color-scheme: dark;
  }
  body {
    color: white;
    background: black;
  }
}
'''
    
    with open(os.path.join(client_dir, 'styles', 'globals.css'), 'w') as f:
        f.write(global_css_content)
    
    # Créer styles/Home.module.css
    home_css_content = '''.container {
  padding: 0 2rem;
}

.main {
  min-height: 100vh;
  padding: 4rem 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}

.footer {
  display: flex;
  flex: 1;
  padding: 2rem 0;
  border-top: 1px solid #eaeaea;
  justify-content: center;
  align-items: center;
}

.title a {
  color: #0070f3;
  text-decoration: none;
}

.title a:hover,
.title a:focus,
.title a:active {
  text-decoration: underline;
}

.title {
  margin: 0;
  line-height: 1.15;
  font-size: 4rem;
  text-align: center;
}

.description {
  margin: 4rem 0;
  line-height: 1.5;
  font-size: 1.5rem;
  text-align: center;
}

.grid {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  max-width: 800px;
}

.card {
  margin: 1rem;
  padding: 1.5rem;
  text-align: left;
  color: inherit;
  text-decoration: none;
  border: 1px solid #eaeaea;
  border-radius: 10px;
  transition: color 0.15s ease, border-color 0.15s ease;
  max-width: 300px;
}

.card:hover,
.card:focus,
.card:active {
  color: #0070f3;
  border-color: #0070f3;
}

.card h2 {
  margin: 0 0 1rem 0;
  font-size: 1.5rem;
}

.card p {
  margin: 0;
  font-size: 1.25rem;
  line-height: 1.5;
}
'''
    
    with open(os.path.join(client_dir, 'styles', 'Home.module.css'), 'w') as f:
        f.write(home_css_content)

    print("✅ Client Next.js créé")


def _create_express_api_structure(api_dir, project_name, database_type):
    """Crée la structure de l'API Express.js avec configuration de base de données"""
    print(f"🚀 Création de l'API Express.js avec {database_type}...")
    
    # Package.json pour l'API
    dependencies = {
        "express": "^4.18.2",
        "cors": "^2.8.5",
        "helmet": "^7.1.0",
        "morgan": "^1.10.0",
        "dotenv": "^16.3.1",
        "bcryptjs": "^2.4.3",
        "jsonwebtoken": "^9.0.2",
        "express-validator": "^7.0.1",
        "compression": "^1.7.4"
    }
    
    # Ajouter les dépendances selon le type de base de données
    if database_type == 'mongodb':
        dependencies.update({
            "mongoose": "^8.0.0",
            "mongodb": "^6.3.0"
        })
    else:  # mysql
        dependencies.update({
            "mysql2": "^3.6.5",
            "sequelize": "^6.35.1"
        })
    
    api_package_json = {
        "name": f"{project_name}-api",
        "version": "1.0.0",
        "description": f"API Express.js pour {project_name}",
        "main": "server.js",
        "scripts": {
            "dev": "nodemon server.js",
            "start": "node server.js",
            "test": "echo \"Error: no test specified\" && exit 1"
        },
        "dependencies": dependencies,
        "devDependencies": {
            "nodemon": "^3.0.2"
        }
    }
    
    with open(os.path.join(api_dir, 'package.json'), 'w') as f:
        json.dump(api_package_json, f, indent=2)
    
    # Créer les dossiers de base
    for folder in ['routes', 'models', 'middleware', 'config', 'controllers']:
        os.makedirs(os.path.join(api_dir, folder), exist_ok=True)
    
    # Créer server.js principal
    server_content = f'''const express = require('express')
const cors = require('cors')
const helmet = require('helmet')
const morgan = require('morgan')
const compression = require('compression')
require('dotenv').config()

const app = express()
const PORT = process.env.API_PORT || 3001

// Configuration de la base de données
require('./config/database')

// Middlewares
app.use(helmet())
app.use(compression())
app.use(morgan('combined'))
app.use(cors({{
  origin: [
    process.env.CLIENT_URL || 'http://localhost:3000',
    process.env.CORS_ORIGIN || 'http://localhost:3000'
  ],
  credentials: true
}}))
app.use(express.json())
app.use(express.urlencoded({{ extended: true }}))

// Routes
app.get('/health', (req, res) => {{
  res.json({{ 
    status: 'OK', 
    message: 'API {project_name} is running',
    timestamp: new Date().toISOString(),
    database: '{database_type.upper()}',
    environment: process.env.NODE_ENV || 'development'
  }})
}})

// API Routes
app.use('/api/auth', require('./routes/auth'))
app.use('/api/users', require('./routes/users'))

// Route de test de base de données
app.get('/api/db-test', require('./controllers/dbTest'))

// 404 handler
app.use('*', (req, res) => {{
  res.status(404).json({{ message: 'Route not found' }})
}})

// Error handler
app.use((err, req, res, next) => {{
  console.error('Error:', err)
  res.status(500).json({{ message: 'Internal server error' }})
}})

app.listen(PORT, '0.0.0.0', () => {{
  console.log(`🚀 API Server running on port ${{PORT}}`)
  console.log(`🔗 Health check: http://localhost:${{PORT}}/health`)
}})
'''
    
    with open(os.path.join(api_dir, 'server.js'), 'w') as f:
        f.write(server_content)
    
    # Créer la configuration de base de données
    if database_type == 'mongodb':
        _create_mongodb_config(api_dir, project_name)
    else:
        _create_mysql_config(api_dir, project_name)
    
    # Créer les routes de base
    _create_base_routes(api_dir, database_type)
    
    # Créer les contrôleurs
    _create_controllers(api_dir, database_type)
    
    # Créer .env
    env_content = f'''# Configuration de l'API {project_name}
NODE_ENV=development
API_PORT=3001

# Base de données
'''
    
    if database_type == 'mongodb':
        env_content += f'''MONGODB_URI=mongodb://admin:adminpassword@mongodb:27017/{project_name}?authSource=admin
DB_HOST=mongodb
DB_PORT=27017
DB_NAME={project_name}
DB_USER=admin
DB_PASSWORD=adminpassword
'''
    else:
        env_content += f'''DATABASE_URL=mysql://{project_name}:projectpassword@mysql:3306/{project_name}
DB_HOST=mysql
DB_PORT=3306
DB_NAME={project_name}
DB_USER={project_name}
DB_PASSWORD=projectpassword
'''
    
    env_content += f'''
# JWT
JWT_SECRET=your-jwt-secret-key-here-{project_name}

# CORS
CLIENT_URL=http://192.168.1.21:3000
CORS_ORIGIN=http://192.168.1.21:3000

# Email (Mailpit)
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_USER=noreply@{project_name}.test
SMTP_PASS=
'''
    
    with open(os.path.join(api_dir, '.env'), 'w') as f:
        f.write(env_content)
    
    print("✅ API Express.js créée")


def _create_mongodb_config(api_dir, project_name):
    """Crée la configuration MongoDB"""
    config_content = f'''const mongoose = require('mongoose')

const connectDB = async () => {{
  try {{
    const conn = await mongoose.connect(process.env.MONGODB_URI, {{
      useNewUrlParser: true,
      useUnifiedTopology: true,
    }})
    
    console.log(`📦 MongoDB Connected: ${{conn.connection.host}}`)
  }} catch (error) {{
    console.error('❌ MongoDB connection error:', error)
    process.exit(1)
  }}
}}

connectDB()

module.exports = mongoose
'''
    
    with open(os.path.join(api_dir, 'config', 'database.js'), 'w') as f:
        f.write(config_content)


def _create_mysql_config(api_dir, project_name):
    """Crée la configuration MySQL avec Sequelize"""
    config_content = f'''const {{ Sequelize }} = require('sequelize')

const sequelize = new Sequelize(
  process.env.DB_NAME,
  process.env.DB_USER,
  process.env.DB_PASSWORD,
  {{
    host: process.env.DB_HOST,
    port: process.env.DB_PORT || 3306,
    dialect: 'mysql',
    logging: process.env.NODE_ENV === 'development' ? console.log : false,
    pool: {{
      max: 5,
      min: 0,
      acquire: 30000,
      idle: 10000
    }}
  }}
)

// Test de connexion
const testConnection = async () => {{
  try {{
    await sequelize.authenticate()
    console.log('📦 MySQL connection established successfully.')
  }} catch (error) {{
    console.error('❌ Unable to connect to MySQL:', error)
  }}
}}

testConnection()

module.exports = sequelize
'''
    
    with open(os.path.join(api_dir, 'config', 'database.js'), 'w') as f:
        f.write(config_content)


def _create_base_routes(api_dir, database_type):
    """Crée les routes de base"""
    # Route auth
    auth_route_content = '''const express = require('express')
const bcrypt = require('bcryptjs')
const jwt = require('jsonwebtoken')
const { body, validationResult } = require('express-validator')
const router = express.Router()

// POST /api/auth/register
router.post('/register', [
  body('email').isEmail().normalizeEmail(),
  body('password').isLength({ min: 6 }),
  body('name').trim().isLength({ min: 1 })
], async (req, res) => {
  try {
    const errors = validationResult(req)
    if (!errors.isEmpty()) {
      return res.status(400).json({ errors: errors.array() })
    }

    const { email, password, name } = req.body

    // TODO: Vérifier si l'utilisateur existe déjà
    // TODO: Créer l'utilisateur dans la base de données
    
    res.status(201).json({ 
      message: 'User registered successfully',
      user: { email, name }
    })
  } catch (error) {
    console.error('Registration error:', error)
    res.status(500).json({ message: 'Server error' })
  }
})

// POST /api/auth/login
router.post('/login', [
  body('email').isEmail().normalizeEmail(),
  body('password').exists()
], async (req, res) => {
  try {
    const errors = validationResult(req)
    if (!errors.isEmpty()) {
      return res.status(400).json({ errors: errors.array() })
    }

    const { email, password } = req.body

    // TODO: Vérifier les credentials
    // TODO: Générer un JWT token
    
    const token = jwt.sign(
      { userId: 1, email }, 
      process.env.JWT_SECRET,
      { expiresIn: '7d' }
    )

    res.json({ 
      message: 'Login successful',
      token,
      user: { email }
    })
  } catch (error) {
    console.error('Login error:', error)
    res.status(500).json({ message: 'Server error' })
  }
})

module.exports = router
'''
    
    with open(os.path.join(api_dir, 'routes', 'auth.js'), 'w') as f:
        f.write(auth_route_content)
    
    # Route users
    users_route_content = '''const express = require('express')
const router = express.Router()

// GET /api/users
router.get('/', async (req, res) => {
  try {
    // TODO: Récupérer les utilisateurs depuis la base de données
    res.json({ 
      message: 'Users list',
      users: []
    })
  } catch (error) {
    console.error('Users fetch error:', error)
    res.status(500).json({ message: 'Server error' })
  }
})

// GET /api/users/:id
router.get('/:id', async (req, res) => {
  try {
    const { id } = req.params
    // TODO: Récupérer l'utilisateur par ID
    res.json({ 
      message: 'User details',
      user: { id }
    })
  } catch (error) {
    console.error('User fetch error:', error)
    res.status(500).json({ message: 'Server error' })
  }
})

module.exports = router
'''
    
    with open(os.path.join(api_dir, 'routes', 'users.js'), 'w') as f:
        f.write(users_route_content)


def _create_controllers(api_dir, database_type):
    """Crée les contrôleurs de base"""
    if database_type == 'mongodb':
        db_test_content = '''const mongoose = require('mongoose')

const dbTest = async (req, res) => {
  try {
    // Test de connexion MongoDB
    const dbState = mongoose.connection.readyState
    const states = {
      0: 'disconnected',
      1: 'connected',
      2: 'connecting',
      3: 'disconnecting'
    }
    
    // Test d'écriture/lecture simple
    const testData = {
      timestamp: new Date(),
      test: 'MongoDB connection test'
    }
    
    res.json({
      database: 'MongoDB',
      status: states[dbState] || 'unknown',
      host: process.env.DB_HOST,
      port: process.env.DB_PORT,
      database: process.env.DB_NAME,
      testData
    })
  } catch (error) {
    console.error('Database test error:', error)
    res.status(500).json({ 
      database: 'MongoDB',
      status: 'error', 
      error: error.message 
    })
  }
}

module.exports = dbTest
'''
    else:
        db_test_content = '''const sequelize = require('../config/database')

const dbTest = async (req, res) => {
  try {
    // Test de connexion MySQL
    await sequelize.authenticate()
    
    // Test de query simple
    const [results] = await sequelize.query('SELECT NOW() as current_time')
    
    res.json({
      database: 'MySQL',
      status: 'connected',
      host: process.env.DB_HOST,
      port: process.env.DB_PORT,
      database: process.env.DB_NAME,
      currentTime: results[0].current_time
    })
  } catch (error) {
    console.error('Database test error:', error)
    res.status(500).json({ 
      database: 'MySQL',
      status: 'error', 
      error: error.message 
    })
  }
}

module.exports = dbTest
'''
    
    with open(os.path.join(api_dir, 'controllers', 'dbTest.js'), 'w') as f:
        f.write(db_test_content)


def get_project_type(project_path):
    """Détermine le type d'un projet"""
    if os.path.exists(os.path.join(project_path, 'client')):
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


def update_project_wordpress_urls_in_files(project_path, port=None):
    """Met à jour les URLs dans les fichiers du projet WordPress après création"""
    try:
        print(f"🔧 Mise à jour des URLs dans les fichiers pour l'accès local")
        
        # Mettre à jour wp-config.php
        wp_config_path = os.path.join(project_path, 'wp-config.php')
        if os.path.exists(wp_config_path):
            with open(wp_config_path, 'r') as f:
                content = f.read()
            
            # Remplacer les placeholders par des URLs locales
            if port:
                content = content.replace('PROJECT_PORT', str(port))
                print(f"✅ wp-config.php mis à jour avec le port {port}")
            
            with open(wp_config_path, 'w') as f:
                f.write(content)
        
        return True
    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour des fichiers: {e}")
        return False


def create_nextjs_package_json(nextjs_path, project_name):
    """Crée un package.json minimal pour Next.js"""
    try:
        print(f"📦 Création du package.json pour Next.js dans: {nextjs_path}")
        
        # S'assurer que le dossier existe
        os.makedirs(nextjs_path, exist_ok=True)
        
        # Package.json minimal mais complet
        package_json = {
            "name": f"{project_name}-nextjs",
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
                "@types/node": "^20",
                "@types/react": "^18",
                "@types/react-dom": "^18",
                "eslint": "^8",
                "eslint-config-next": "14.0.0",
                "typescript": "^5"
            }
        }
        
        package_json_path = os.path.join(nextjs_path, 'package.json')
        with open(package_json_path, 'w') as f:
            json.dump(package_json, f, indent=2)
        
        print(f"✅ package.json créé avec succès: {package_json_path}")
        
        # Créer également une page d'index simple
        pages_dir = os.path.join(nextjs_path, 'pages')
        os.makedirs(pages_dir, exist_ok=True)
        
        index_content = f'''export default function Home() {{
  return (
    <div style={{{{ padding: '2rem', textAlign: 'center' }}}}>
      <h1>Bienvenue sur {project_name}</h1>
      <p>Application Next.js prête à être développée !</p>
    </div>
  )
}}'''
        
        with open(os.path.join(pages_dir, 'index.js'), 'w') as f:
            f.write(index_content)
        
        print(f"✅ Page d'index créée")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la création du package.json: {e}")
        return False


def set_project_permissions(project_path, current_user=None):
    """Applique les bonnes permissions à un projet WordPress (version améliorée)"""
    try:
        if not current_user:
            current_user = os.getenv('USER', 'dev-server')
        
        print(f"🔧 Application des permissions automatiques pour: {project_path}")
        print(f"👤 Utilisateur: {current_user}")
        
        # Vérifier que le projet existe
        if not os.path.exists(project_path):
            print(f"❌ Le projet n'existe pas: {project_path}")
            return False
        
        # Changer le propriétaire vers dev-server:www-data
        print(f"🔧 Changement propriétaire: {current_user}:www-data")
        result = subprocess.run([
            'sudo', 'chown', '-R', f'{current_user}:www-data', project_path
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            print(f"⚠️ Erreur lors du changement de propriétaire: {result.stderr}")
            return False
        
        # Permissions des dossiers (775 - lecture/écriture pour owner et group)
        print(f"📁 Application permissions dossiers (775)...")
        result = subprocess.run([
            'find', project_path, '-type', 'd', '-exec', 'chmod', '775', '{}', '+'
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            print(f"⚠️ Erreur lors des permissions dossiers: {result.stderr}")
            return False
        
        # Permissions des fichiers (664 - lecture/écriture pour owner et group)
        print(f"📄 Application permissions fichiers (664)...")
        result = subprocess.run([
            'find', project_path, '-type', 'f', '-exec', 'chmod', '664', '{}', '+'
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            print(f"⚠️ Erreur lors des permissions fichiers: {result.stderr}")
            return False
        
        # Permissions spéciales pour wp-content/uploads si c'est un projet WordPress
        uploads_path = os.path.join(project_path, 'wp-content', 'uploads')
        if os.path.exists(uploads_path):
            print(f"📷 Permissions spéciales uploads (775)...")
            subprocess.run(['chmod', '-R', '775', uploads_path], 
                         capture_output=True, text=True, timeout=10)
            print(f"✅ Permissions uploads spéciales appliquées")
        
        # Vérification finale
        test_file = os.path.join(project_path, '.permission_test')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            print(f"✅ Test d'écriture réussi")
        except Exception as e:
            print(f"⚠️ Test d'écriture échoué: {e}")
            return False
        
        print(f"✅ Permissions automatiques appliquées avec succès!")
        print(f"📋 Résumé:")
        print(f"   - Propriétaire: {current_user}:www-data")
        print(f"   - Dossiers: 775 (rwxrwxr-x)")
        print(f"   - Fichiers: 664 (rw-rw-r--)")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de l'application des permissions: {e}")
        return False


def apply_automatic_project_permissions(project_path, project_type='wordpress'):
    """Fonction principale pour appliquer automatiquement les permissions après création d'un projet"""
    try:
        print(f"🚀 PERMISSIONS AUTOMATIQUES - {project_type.upper()}")
        print(f"=" * 50)
        
        current_user = os.getenv('USER', 'dev-server')
        
        # Appliquer les permissions selon le type de projet
        success = set_project_permissions(project_path, current_user)
        
        # Pour WordPress, s'assurer que www-data peut écrire depuis le conteneur Docker
        if success and project_type == 'wordpress':
            print(f"🐳 Configuration spéciale WordPress pour Docker...")
            success = _ensure_wordpress_docker_permissions(project_path, current_user)
        
        if success:
            print(f"🎉 Permissions automatiques configurées avec succès!")
            print(f"✅ L'utilisateur {current_user} ET WordPress peuvent maintenant écrire dans le projet")
            return True
        else:
            print(f"❌ Échec de l'application des permissions automatiques")
            print(f"💡 Vous devrez exécuter manuellement:")
            print(f"   sudo chown -R {current_user}:www-data {project_path}")
            print(f"   find {project_path} -type d -exec chmod 775 {{}} \\;")
            print(f"   find {project_path} -type f -exec chmod 664 {{}} \\;")
            return False
            
    except Exception as e:
        print(f"❌ Erreur dans apply_automatic_project_permissions: {e}")
        return False


def _ensure_wordpress_docker_permissions(project_path, current_user):
    """S'assure que WordPress dans Docker peut écrire (www-data)"""
    try:
        print(f"🔧 Configuration permissions Docker WordPress...")
        
        # S'assurer que www-data est dans le groupe
        subprocess.run(['sudo', 'usermod', '-a', '-G', 'www-data', current_user], 
                      capture_output=True, text=True, timeout=10)
        
        # Forcer le groupe www-data sur tout le projet
        result = subprocess.run([
            'sudo', 'chgrp', '-R', 'www-data', project_path
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            print(f"⚠️ Erreur lors du changement de groupe: {result.stderr}")
            return False
        
        # Permissions spéciales pour les dossiers critiques WordPress
        wp_critical_dirs = [
            os.path.join(project_path, 'wp-content'),
            os.path.join(project_path, 'wp-content', 'themes'),
            os.path.join(project_path, 'wp-content', 'plugins'),
            os.path.join(project_path, 'wp-content', 'uploads'),
            os.path.join(project_path, 'wp-content', 'mu-plugins')
        ]
        
        for dir_path in wp_critical_dirs:
            if os.path.exists(dir_path):
                # Permissions 775 pour permettre l'écriture par le groupe
                subprocess.run(['chmod', '775', dir_path], 
                             capture_output=True, text=True, timeout=5)
                # S'assurer du bon groupe
                subprocess.run(['sudo', 'chgrp', 'www-data', dir_path], 
                             capture_output=True, text=True, timeout=5)
                
                # IMPORTANT: Forcer les permissions sur TOUS les sous-fichiers et dossiers
                # Car le wp-content de référence peut être copié après les permissions initiales
                subprocess.run(['sudo', 'chgrp', '-R', 'www-data', dir_path], 
                             capture_output=True, text=True, timeout=10)
                subprocess.run(['find', dir_path, '-type', 'd', '-exec', 'chmod', '775', '{}', '+'], 
                             capture_output=True, text=True, timeout=10)
                subprocess.run(['find', dir_path, '-type', 'f', '-exec', 'chmod', '664', '{}', '+'], 
                             capture_output=True, text=True, timeout=10)
                
                print(f"✅ Permissions WordPress configurées (récursif): {dir_path}")
        
        # Test final : vérifier qu'on peut créer un fichier
        test_file = os.path.join(project_path, 'wp-content', '.write_test_wp')
        try:
            with open(test_file, 'w') as f:
                f.write('test write permission')
            os.remove(test_file)
            print(f"✅ Test d'écriture WordPress réussi")
        except Exception as e:
            print(f"⚠️ Test d'écriture WordPress échoué: {e}")
            return False
        
        print(f"✅ Permissions Docker WordPress configurées!")
        print(f"📋 Configuration finale:")
        print(f"   - Utilisateur: {current_user}")
        print(f"   - Groupe: www-data")
        print(f"   - Dossiers critiques: 775")
        print(f"   - Compatible Docker: ✅")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la configuration Docker WordPress: {e}")
        return False 