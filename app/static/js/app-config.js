/**
 * Application configuration loaded from server
 */

// ---------------------------------------------------------------------------
// Debug flag: enable via ?debug=1 or localStorage 'wp-launcher-debug'='true'.
// Silences console.log in production but preserves console.error / console.warn.
// ---------------------------------------------------------------------------
(function() {
    try {
        window.APP_DEBUG = new URLSearchParams(location.search).has('debug') ||
                          localStorage.getItem('wp-launcher-debug') === 'true';
    } catch (e) {
        window.APP_DEBUG = false;
    }
    const _origLog = console.log.bind(console);
    console.log = function() {
        if (window.APP_DEBUG) {
            _origLog.apply(console, arguments);
        }
    };
})();

// ---------------------------------------------------------------------------
// Socket.IO singleton factory. All modules should use getSocketIO() instead
// of calling io() directly, so we only ever maintain one connection and
// avoid duplicated event handlers.
// ---------------------------------------------------------------------------
window.getSocketIO = function() {
    if (!window._socket) {
        if (typeof io === 'undefined') {
            console.warn('Socket.IO not loaded yet');
            return null;
        }
        window._socket = io();
    }
    return window._socket;
};

// Global app configuration with safe defaults
window.APP_CONFIG = {
    host: window.location.hostname,
    port: '5000',
    url: `http://${window.location.hostname}:5000`,
    wp_admin_user: 'admin',
    wp_admin_password: 'admin',
    // Rempli par le serveur : voir getVscodeUri(). `remote` vaut true quand
    // le navigateur n'est pas sur la machine qui héberge les fichiers.
    vscode: { scheme: 'vscode', ssh_host: '', remote: false },
    loaded: false
};

/**
 * Load configuration from server
 */
async function loadAppConfig() {
    try {
        const response = await fetch('/api/config/app');
        if (response.ok) {
            const config = await response.json();
            window.APP_CONFIG = {
                host: config.app_host,
                port: config.app_port,
                url: config.app_url,
                wp_admin_user: config.wp_admin_user || 'admin',
                wp_admin_password: config.wp_admin_password || 'admin',
                vscode: config.vscode || { scheme: 'vscode', ssh_host: '', remote: false },
                loaded: true
            };
            console.log('✅ App config loaded:', window.APP_CONFIG.host);
        }
    } catch (error) {
        console.error('❌ Failed to load app config:', error);
    }
}

/**
 * Generate a URL for a project
 */
function getProjectUrl(port, path = '') {
    const baseUrl = `http://${window.APP_CONFIG.host}:${port}`;
    return path ? `${baseUrl}/${path}` : baseUrl;
}

/**
 * Returns the app base URL
 */
function getAppUrl() {
    return window.APP_CONFIG.url;
}

/**
 * Construit l'URI vscode:// qui ouvre un dossier de projet.
 *
 * En local : vscode://file/chemin/absolu
 * À distance : vscode://vscode-remote/ssh-remote+hote/chemin/absolu — VS Code
 * ouvre alors une fenêtre Remote-SSH connectée à l'hôte, sans quoi il tenterait
 * d'ouvrir un chemin qui n'existe pas sur le poste client.
 *
 * Retourne null si le chemin est inconnu, ou si l'hôte SSH n'est pas
 * configuré alors qu'on est à distance (mieux vaut ne rien faire qu'ouvrir
 * une fenêtre vide).
 */
function getVscodeUri(absolutePath) {
    if (!absolutePath) return null;

    const cfg = (window.APP_CONFIG && window.APP_CONFIG.vscode) || {};
    const scheme = cfg.scheme || 'vscode';

    // Encodage segment par segment : les / structurels sont conservés, les
    // espaces et caractères exotiques d'un nom de dossier sont échappés.
    // Le chemin est absolu, on garde son / initial — d'où le `vscode://file` nu.
    const raw = absolutePath.startsWith('/') ? absolutePath : '/' + absolutePath;
    const path = raw.split('/').map(encodeURIComponent).join('/');

    if (cfg.remote) {
        if (!cfg.ssh_host) return null;
        // Le @ de user@hote est légal tel quel dans un segment d'URI : on le
        // laisse en clair, VS Code résolvant l'hôte que sa lecture de l'URI
        // décode le pourcent-encodage ou non.
        const host = encodeURIComponent(cfg.ssh_host).replace(/%40/g, '@');
        return `${scheme}://vscode-remote/ssh-remote+${host}${path}`;
    }
    return `${scheme}://file${path}`;
}
window.getVscodeUri = getVscodeUri;

// Load config on startup
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadAppConfig);
} else {
    loadAppConfig();
}
