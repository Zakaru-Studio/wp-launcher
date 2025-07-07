<?php
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

// Configuration des URLs
define('WP_HOME', 'http://192.168.1.21:PROJECT_PORT');
define('WP_SITEURL', 'http://192.168.1.21:PROJECT_PORT');

// Configuration des fichiers
define('DISALLOW_FILE_EDIT', false);
define('DISALLOW_FILE_MODS', false);

// Configuration du cache
define('WP_CACHE', false);

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
define('FORCE_SSL_ADMIN', false);

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

// Configuration des chemins
define('WP_CONTENT_DIR', ABSPATH . 'wp-content');
define('WP_CONTENT_URL', 'http://192.168.1.21:PROJECT_PORT/wp-content');

// Chargement des réglages WordPress
require_once ABSPATH . 'wp-settings.php';