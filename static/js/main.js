/**
 * JavaScript principal - WordPress Launcher
 * Fonctions communes et utilitaires
 */

// Variables globales
let isLoading = false;

/**
 * Initialisation de l'application
 */
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 WordPress Launcher initialisé');
    
    // Charger les projets au démarrage
    if (typeof refreshProjects === 'function') {
        refreshProjects();
    }
    
    // Configurer les événements globaux
    setupGlobalEvents();
    
    // Configurer Socket.IO si disponible
    if (typeof io !== 'undefined') {
        setupSocketIO();
    }
});

/**
 * Configuration des événements globaux
 */
function setupGlobalEvents() {
    // Gestion des erreurs JavaScript
    window.addEventListener('error', function(e) {
        console.error('Erreur JavaScript:', e.error);
        showToast('Une erreur inattendue s\'est produite', 'error');
    });
    
    // Confirmation avant fermeture de page si en cours de traitement
    window.addEventListener('beforeunload', function(e) {
        if (isLoading) {
            e.preventDefault();
            e.returnValue = 'Une opération est en cours. Êtes-vous sûr de vouloir quitter ?';
        }
    });
    
    // Gestion des raccourcis clavier
    document.addEventListener('keydown', function(e) {
        // Echap pour fermer les loaders/modales
        if (e.key === 'Escape') {
            hideLoader();
        }
        
        // Ctrl+R pour actualiser les projets
        if (e.ctrlKey && e.key === 'r') {
            e.preventDefault();
            if (typeof refreshProjects === 'function') {
                refreshProjects();
            }
        }
    });
}

/**
 * Configuration de Socket.IO
 */
function setupSocketIO() {
    if (typeof socket === 'undefined') return;
    
    socket.on('connect', function() {
        console.log('✅ Connexion Socket.IO établie');
    });
    
    socket.on('disconnect', function() {
        console.log('❌ Connexion Socket.IO perdue');
        showToast('Connexion perdue avec le serveur', 'warning');
    });
    
    socket.on('error', function(error) {
        console.error('Erreur Socket.IO:', error);
        showToast('Erreur de connexion temps réel', 'error');
    });
}

/**
 * Affiche un loader
 * @param {string} message - Message à afficher
 */
function showLoader(message = 'Chargement...') {
    isLoading = true;
    
    // Créer le loader s'il n'existe pas
    let loader = document.getElementById('global-loader');
    if (!loader) {
        loader = document.createElement('div');
        loader.id = 'global-loader';
        loader.className = 'global-loader';
        loader.innerHTML = `
            <div class="loader-content">
                <div class="spinner"></div>
                <p class="loader-message">${message}</p>
            </div>
        `;
        document.body.appendChild(loader);
    }
    
    // Mettre à jour le message
    const messageEl = loader.querySelector('.loader-message');
    if (messageEl) {
        messageEl.textContent = message;
    }
    
    // Afficher le loader
    loader.style.display = 'flex';
    setTimeout(() => {
        loader.classList.add('visible');
    }, 10);
}

/**
 * Masque le loader
 */
function hideLoader() {
    isLoading = false;
    
    const loader = document.getElementById('global-loader');
    if (loader) {
        loader.classList.remove('visible');
        setTimeout(() => {
            loader.style.display = 'none';
        }, 300);
    }
}

/**
 * Affiche un toast/notification
 * @param {string} title - Titre du toast
 * @param {string} message - Message du toast
 * @param {string} type - Type de toast (success, error, warning, info)
 * @param {number} duration - Durée d'affichage en ms (0 = permanent)
 */
function showToast(title, message = '', type = 'info', duration = 5000) {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        const container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '11';
        document.body.appendChild(container);
    }
    
    const toastId = generateUniqueId();
    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = `toast align-items-center text-white bg-${type} border-0`;
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <strong>${title}</strong>
                ${message ? `<div class="mt-1">${message}</div>` : ''}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    // Initialiser le toast Bootstrap
    const bsToast = new bootstrap.Toast(toast, {
        autohide: duration > 0,
        delay: duration
    });
    
    bsToast.show();
    
    // Nettoyer après fermeture
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
    
    return toastId;
}

/**
 * Effectue une requête HTTP avec gestion d'erreurs
 * @param {string} url - URL de la requête
 * @param {string} method - Méthode HTTP
 * @param {Object} headers - Headers de la requête
 * @param {*} body - Corps de la requête
 * @returns {Promise} - Promesse de réponse
 */
async function makeRequest(url, method = 'GET', headers = {}, body = null) {
    try {
        const config = {
            method,
            headers: {
                'Content-Type': 'application/json',
                ...headers
            }
        };
        
        if (body && method !== 'GET') {
            config.body = typeof body === 'string' ? body : JSON.stringify(body);
        }
        
        const response = await fetch(url, config);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('Erreur requête:', error);
        throw error;
    }
}

/**
 * Formate une taille de fichier
 * @param {number} bytes - Taille en bytes
 * @returns {string} - Taille formatée
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Formate une durée
 * @param {number} seconds - Durée en secondes
 * @returns {string} - Durée formatée
 */
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

/**
 * Valide un nom de projet
 * @param {string} name - Nom du projet
 * @returns {boolean} - Validité du nom
 */
function validateProjectName(name) {
    if (!name || name.trim().length === 0) {
        return false;
    }
    
    // Regex pour lettres, chiffres, tirets et underscores
    const regex = /^[a-zA-Z0-9_-]+$/;
    return regex.test(name.trim());
}

/**
 * Valide un hostname
 * @param {string} hostname - Hostname à valider
 * @returns {boolean} - Validité de l'hostname
 */
function validateHostname(hostname) {
    if (!hostname || hostname.trim().length === 0) {
        return true; // Optionnel
    }
    
    // Format basique pour hostname local
    const regex = /^[a-zA-Z0-9.-]+\.(local|dev)$/;
    return regex.test(hostname.trim());
}

/**
 * Copie du texte dans le presse-papiers
 * @param {string} text - Texte à copier
 * @returns {Promise<boolean>} - Succès de la copie
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copié !', 'Texte copié dans le presse-papiers', 'success', 2000);
        return true;
    } catch (error) {
        console.error('Erreur copie presse-papiers:', error);
        showToast('Erreur', 'Impossible de copier dans le presse-papiers', 'error');
        return false;
    }
}

/**
 * Debounce une fonction
 * @param {Function} func - Fonction à debouncer
 * @param {number} wait - Délai en ms
 * @returns {Function} - Fonction debouncée
 */
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

/**
 * Throttle une fonction
 * @param {Function} func - Fonction à throttler
 * @param {number} limit - Limite en ms
 * @returns {Function} - Fonction throttlée
 */
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * Escape HTML pour éviter les injections XSS
 * @param {string} text - Texte à échapper
 * @returns {string} - Texte échappé
 */
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

/**
 * Génère un ID unique
 * @returns {string} - ID unique
 */
function generateUniqueId() {
    return 'id_' + Math.random().toString(36).substr(2, 9);
}

// Export des fonctions si module ES6
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        showLoader,
        hideLoader,
        showToast,
        makeRequest,
        formatFileSize,
        formatDuration,
        validateProjectName,
        validateHostname,
        copyToClipboard,
        debounce,
        throttle,
        escapeHtml,
        generateUniqueId
    };
} 