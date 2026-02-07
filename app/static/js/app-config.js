/**
 * Application configuration loaded from server
 */

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
