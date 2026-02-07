/**
 * Configuration de l'application chargée depuis le serveur
 */

// Configuration globale de l'application
window.APP_CONFIG = {
    host: '192.168.1.21',  // Valeur par défaut
    port: '5000',
    url: 'http://192.168.1.21:5000',
    loaded: false
};

/**
 * Charge la configuration depuis le serveur
 */
async function loadAppConfig() {
    try {
        const response = await fetch('/api/config');
        if (response.ok) {
            const config = await response.json();
            window.APP_CONFIG = {
                host: config.app_host,
                port: config.app_port,
                url: config.app_url,
                loaded: true
            };
            console.log('✅ Configuration chargée:', window.APP_CONFIG);
        }
    } catch (error) {
        console.error('❌ Erreur lors du chargement de la configuration:', error);
        // Utiliser les valeurs par défaut
    }
}

/**
 * Génère une URL pour un projet
 */
function getProjectUrl(port, path = '') {
    const baseUrl = `http://${window.APP_CONFIG.host}:${port}`;
    return path ? `${baseUrl}/${path}` : baseUrl;
}

/**
 * Retourne l'URL de base de l'application
 */
function getAppUrl() {
    return window.APP_CONFIG.url;
}

// Charger la config au démarrage
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadAppConfig);
} else {
    loadAppConfig();
}

