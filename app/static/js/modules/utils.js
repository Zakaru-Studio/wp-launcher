/**
 * Utilitaires JavaScript communs
 * Factorisation du code dupliqué entre les fichiers JS
 */

// Variables globales - vérifier si déjà déclarées
if (typeof window.isLoading === 'undefined') {
    window.isLoading = false;
}

/**
 * Gestion du loader global
 */
function showLoader(message = 'Traitement en cours...') {
    if (window.isLoading) return;
    
    window.isLoading = true;
    
    // Supprimer l'ancien loader s'il existe
    const existingLoader = document.getElementById('global-loader');
    if (existingLoader) {
        existingLoader.remove();
    }
    
    const loader = document.createElement('div');
    loader.id = 'global-loader';
    loader.className = 'global-loader';
    loader.innerHTML = `
        <div class="spinner"></div>
        <div class="loader-message">${message}</div>
    `;
    document.body.appendChild(loader);
    
}

function hideLoader() {
    if (!window.isLoading) return;
    
    window.isLoading = false;
    const loader = document.getElementById('global-loader');
    if (loader) {
        loader.remove();
    }
    
}


/**
 * Requête HTTP standardisée avec gestion d'erreurs
 */
async function makeRequest(url, options = {}) {
    const defaultOptions = {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
        },
        ...options
    };
    
    try {
        const response = await fetch(url, defaultOptions);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            return await response.json();
        } else {
            return await response.text();
        }
    } catch (error) {
        throw error;
    }
}

/**
 * Utilitaires de formatage
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDuration(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    
    if (hours > 0) {
        return `${hours}h ${minutes}m ${secs}s`;
    } else if (minutes > 0) {
        return `${minutes}m ${secs}s`;
    } else {
        return `${secs}s`;
    }
}

function formatElapsedTime(startTime) {
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    return formatDuration(elapsed);
}

/**
 * Validation des données
 */
function validateHostname(hostname) {
    if (!hostname || hostname.trim() === '') {
        return true; // Vide autorisé
    }
    
    const hostnameRegex = /^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)*$/i;
    return hostnameRegex.test(hostname.trim());
}

function validateProjectName(name) {
    if (!name || name.trim() === '') {
        return false;
    }
    
    // Nom de projet: lettres, chiffres, tirets et underscores
    const nameRegex = /^[a-zA-Z0-9_-]+$/;
    return nameRegex.test(name.trim());
}

/**
 * Utilitaires DOM
 */
function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function throttle(func, limit) {
    let inThrottle;
    return function() {
        const args = arguments;
        const context = this;
        if (!inThrottle) {
            func.apply(context, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    }
}

/**
 * Gestion des événements globaux
 */
function setupGlobalEvents() {
    // Fermer les alertes automatiquement
    document.addEventListener('DOMContentLoaded', function() {
        const alerts = document.querySelectorAll('.alert:not(.alert-persistent)');
        alerts.forEach(alert => {
            setTimeout(() => {
                if (alert && alert.parentNode) {
                    alert.style.opacity = '0';
                    alert.style.transform = 'translateY(-10px)';
                    setTimeout(() => {
                        if (alert.parentNode) {
                            alert.parentNode.removeChild(alert);
                        }
                    }, 300);
                }
            }, 5000);
        });
    });
    
    // Gestion des erreurs globales
    window.addEventListener('error', function(e) {
        // Gestion d'erreur en production
    });
    
    // Gestion des erreurs de promesses non capturées
    window.addEventListener('unhandledrejection', function(e) {
        e.preventDefault(); // Empêche l'affichage dans la console
    });
}

/**
 * Configuration SocketIO standardisée
 */
function setupSocketIO() {
    if (typeof io === 'undefined') {
        return null;
    }
    
    const socket = io();
    
    socket.on('connect', function() {
        // WebSocket connecté
    });
    
    socket.on('disconnect', function() {
        // WebSocket déconnecté
    });
    
    socket.on('error', function(error) {
        // Erreur WebSocket
    });
    
    return socket;
}

/**
 * Fonctions utilitaires supplémentaires
 */

/**
 * Copie du texte dans le presse-papiers
 * @param {string} text - Texte à copier
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (error) {
        return false;
    }
}

/**
 * Génère un ID unique général (non-lié aux tâches)
 * @returns {string} ID unique
 */
function generateUniqueId() {
    const timestamp = Date.now();
    const random = Math.random().toString(36).substring(2, 9);
    return `id_${timestamp}_${random}`;
}

/**
 * Initialisation automatique
 */
document.addEventListener('DOMContentLoaded', function() {
    setupGlobalEvents();
});

// Exporter les fonctions pour utilisation dans d'autres modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        showLoader,
        hideLoader,
        makeRequest,
        formatFileSize,
        formatDuration,
        formatElapsedTime,
        validateHostname,
        validateProjectName,
        escapeHtml,
        debounce,
        throttle,
        setupSocketIO,
        copyToClipboard,
        generateUniqueId
    };
}