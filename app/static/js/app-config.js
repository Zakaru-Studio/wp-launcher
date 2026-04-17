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

// Load config on startup
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadAppConfig);
} else {
    loadAppConfig();
}
