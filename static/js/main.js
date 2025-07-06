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
 * Affiche un loader global avec message
 * @param {string} message - Message à afficher
 */
function showLoader(message = 'Traitement en cours...') {
    const loader = document.getElementById('global-loader');
    const loaderMessage = document.getElementById('loader-message');
    
    if (loader && loaderMessage) {
        loaderMessage.textContent = message;
        loader.classList.remove('d-none');
        isLoading = true;
        
        // Empêcher le scroll de la page
        document.body.style.overflow = 'hidden';
    }
}

/**
 * Cache le loader global
 */
function hideLoader() {
    const loader = document.getElementById('global-loader');
    
    if (loader) {
        loader.classList.add('d-none');
        isLoading = false;
        
        // Restaurer le scroll de la page
        document.body.style.overflow = '';
    }
}

/**
 * Affiche un toast/notification
 * @param {string} message - Message à afficher
 * @param {string} type - Type: success, error, warning, info
 */
function showToast(message, type = 'success') {
    const toastContainer = document.getElementById('toast-container') || createToastContainer();
    
    const toastId = 'toast-' + Date.now();
    const icons = {
        success: 'check-circle',
        error: 'exclamation-triangle',
        warning: 'exclamation-circle',
        info: 'info-circle'
    };
    
    const bgClasses = {
        success: 'bg-success',
        error: 'bg-danger',
        warning: 'bg-warning',
        info: 'bg-info'
    };
    
    const icon = icons[type] || icons.info;
    const bgClass = bgClasses[type] || bgClasses.info;
    
    const toastHtml = `
        <div id="${toastId}" class="toast align-items-center text-white ${bgClass} border-0 fade-in" role="alert">
            <div class="d-flex">
                <div class="toast-body">
                    <i class="fas fa-${icon} me-2"></i>
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;
    
    toastContainer.insertAdjacentHTML('beforeend', toastHtml);
    
    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement, { 
        delay: type === 'error' ? 8000 : 4000 
    });
    
    toast.show();
    
    // Supprimer l'élément après fermeture
    toastElement.addEventListener('hidden.bs.toast', function() {
        toastElement.remove();
    });
}

/**
 * Crée le conteneur de toasts s'il n'existe pas
 */
function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    container.style.zIndex = '11';
    document.body.appendChild(container);
    return container;
}

/**
 * Ajoute un loader sur un bouton
 * @param {Element} button - Élément bouton
 */
function addButtonLoader(button) {
    if (!button) return;
    
    button.disabled = true;
    button.classList.add('loading');
    button.dataset.originalText = button.innerHTML;
}

/**
 * Retire le loader d'un bouton
 * @param {Element} button - Élément bouton
 */
function removeButtonLoader(button) {
    if (!button) return;
    
    button.disabled = false;
    button.classList.remove('loading');
    if (button.dataset.originalText) {
        button.innerHTML = button.dataset.originalText;
        delete button.dataset.originalText;
    }
}

/**
 * Effectue une requête AJAX avec gestion d'erreurs
 * @param {string} url - URL de la requête
 * @param {object} options - Options de la requête
 * @returns {Promise} - Promesse de la réponse
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
            throw new Error(`Erreur HTTP: ${response.status}`);
        }
        
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            return await response.json();
        } else {
            return await response.text();
        }
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
    if (bytes === 0) return '0 B';
    
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Formate une durée en texte lisible
 * @param {number} seconds - Durée en secondes
 * @returns {string} - Durée formatée
 */
function formatDuration(seconds) {
    if (seconds < 60) {
        return Math.round(seconds) + 's';
    } else if (seconds < 3600) {
        return Math.floor(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's';
    } else {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return hours + 'h ' + minutes + 'm';
    }
}

/**
 * Valide un nom de projet
 * @param {string} name - Nom à valider
 * @returns {boolean} - Validité du nom
 */
function validateProjectName(name) {
    if (!name || name.trim().length === 0) {
        return false;
    }
    
    // Lettres, chiffres, tirets et underscores uniquement
    const regex = /^[a-zA-Z0-9-_]+$/;
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
 * @returns {Promise<boolean>} - Succès de l'opération
 */
async function copyToClipboard(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return true;
        } else {
            // Fallback pour les navigateurs plus anciens
            const textArea = document.createElement('textarea');
            textArea.value = text;
            textArea.style.position = 'fixed';
            textArea.style.left = '-999999px';
            textArea.style.top = '-999999px';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            const result = document.execCommand('copy');
            textArea.remove();
            return result;
        }
    } catch (error) {
        console.error('Erreur copie presse-papiers:', error);
        return false;
    }
}

/**
 * Débounce une fonction
 * @param {Function} func - Fonction à débouncer
 * @param {number} wait - Délai d'attente en ms
 * @returns {Function} - Fonction débouncée
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
    return 'id-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
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