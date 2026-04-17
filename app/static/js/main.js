/**
 * JavaScript principal - WordPress Launcher (Optimisé)
 * Utilise le module utils.js pour éviter la duplication
 */

// Socket.IO global - déclaré uniquement si pas déjà défini
if (typeof socket === 'undefined') {
    var socket = null;
}

/**
 * Initialisation de l'application
 */
document.addEventListener('DOMContentLoaded', function() {
    
    // Attendre que utils.js soit chargé
    initializeApp();
    
    // Charger les projets au démarrage
    if (typeof refreshProjects === 'function') {
        refreshProjects();
    }
    
    // Gestion des raccourcis clavier
    setupKeyboardShortcuts();
    
    // Confirmation avant fermeture si en cours de traitement
    setupBeforeUnload();
});

/**
 * Initialisation principale — utilise le singleton Socket.IO (getSocketIO).
 * Si io n'est pas encore chargé, on réessaie une seule fois après 100ms.
 */
function initializeApp() {
    function attach() {
        if (typeof window.getSocketIO === 'function') {
            socket = window.getSocketIO();
        }
        if (socket) {
            setupProjectSocketEvents();
            return true;
        }
        return false;
    }

    if (!attach()) {
        setTimeout(attach, 100);
    }
}

/**
 * Configuration des raccourcis clavier
 */
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
        // Echap pour fermer les loaders/modales
        if (e.key === 'Escape') {
            if (typeof hideLoader === 'function') {
                hideLoader();
            }
            
            // Fermer les modales Bootstrap ouvertes
            const openModals = document.querySelectorAll('.modal.show');
            openModals.forEach(modal => {
                const modalInstance = bootstrap.Modal.getInstance(modal);
                if (modalInstance) {
                    modalInstance.hide();
                }
            });
        }
        
        // F5 ou Ctrl+R pour recharger les projets
        if (e.key === 'F5' || (e.ctrlKey && e.key === 'r')) {
            if (typeof refreshProjects === 'function') {
                e.preventDefault();
                refreshProjects();
            }
        }
        
        // Ctrl+N pour nouveau projet
        if (e.ctrlKey && e.key === 'n') {
            e.preventDefault();
            const createBtn = document.querySelector('[data-bs-target="#createProjectModal"]');
            if (createBtn) {
                createBtn.click();
            }
        }
    });
}

/**
 * Confirmation avant fermeture de page
 */
function setupBeforeUnload() {
    window.addEventListener('beforeunload', function(e) {
        if (typeof isLoading !== 'undefined' && isLoading) {
            e.preventDefault();
            e.returnValue = 'Une opération est en cours. Êtes-vous sûr de vouloir quitter ?';
        }
    });
}

/**
 * Gestion des opérations projet avec feedback visuel
 */
async function executeProjectOperation(operation, projectName, showLoaderGlobal = true) {
    try {
        if (showLoaderGlobal && typeof showLoader === 'function') {
            showLoader();
        }
        
        const result = await makeRequest(`/${operation}/${projectName}`, {
            method: 'POST'
        });
        
        if (result.success) {
            // Recharger les projets après l'opération
            setTimeout(() => {
                refreshProjects();
            }, 1000);
        }
        
        return result;
        
    } catch (error) {
        return { success: false, message: error.message };
    } finally {
        if (showLoaderGlobal && typeof hideLoader === 'function') {
            hideLoader();
        }
    }
}


/**
 * Gestion des événements Socket.IO spécifiques
 */
let _reloadPending = null;
function debouncedRefreshProjects() {
    if (_reloadPending) clearTimeout(_reloadPending);
    _reloadPending = setTimeout(() => {
        _reloadPending = null;
        refreshProjects();
    }, 500);
}

function setupProjectSocketEvents() {
    if (!socket) return;

    // Événements de progression de tâches
    socket.on('task_progress', function(data) {

        // Mettre à jour l'interface si nécessaire
        if (typeof updateTaskProgress === 'function') {
            updateTaskProgress(data);
        }
    });

    // Événements de statut de projet — debounce pour éviter les rechargements
    // en rafale (3+ requêtes/seconde) lorsque plusieurs events arrivent ensemble.
    socket.on('project_status_changed', debouncedRefreshProjects);
}

/**
 * Utilitaires d'URL pour les projets
 */
function openProjectUrl(url, newTab = true) {
    if (!url) {
        return;
    }
    
    if (newTab) {
        window.open(url, '_blank');
    } else {
        window.location.href = url;
    }
}

/**
 * Gestion des paramètres d'affichage
 */
function toggleProjectView(viewType) {
    const container = document.querySelector('.projects-grid');
    if (!container) return;
    
    // Sauvegarder la préférence
    localStorage.setItem('projectViewType', viewType);
    
    // Appliquer la vue
    container.className = `projects-grid projects-${viewType}`;
    
    // Mettre à jour les boutons de vue
    document.querySelectorAll('.view-toggle').forEach(btn => {
        btn.classList.remove('active');
    });
    
    const activeBtn = document.querySelector(`[data-view="${viewType}"]`);
    if (activeBtn) {
        activeBtn.classList.add('active');
    }
}

/**
 * Fonctions d'assistance pour les projets
 */
function refreshProjects() {
    if (typeof loadProjects === 'function') {
        loadProjects();
    }
}

/**
 * Restaurer les préférences utilisateur
 */
document.addEventListener('DOMContentLoaded', function() {
    // Restaurer la vue des projets
    const savedView = localStorage.getItem('projectViewType');
    if (savedView) {
        toggleProjectView(savedView);
    }
});

/**
 * Redémarre l'application gracefully
 */
async function restartApp() {
    if (!confirm('Redémarrer l\'application ? Cela prendra quelques secondes.')) {
        return;
    }
    
    const btn = document.querySelector('.btn-restart-app');
    if (btn) {
        btn.classList.add('restarting');
        btn.disabled = true;
    }
    
    try {
        const response = await fetch('/api/system/restart', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Afficher message de succès
            if (typeof showToast === 'function') {
                showToast('Redémarrage en cours... La page va se recharger.', 'info');
            }
            
            // Attendre 5 secondes puis essayer de recharger la page
            // On va essayer de recharger toutes les 2 secondes jusqu'à ce que ça marche
            let attempts = 0;
            const maxAttempts = 15;
            
            const tryReload = () => {
                attempts++;
                
                // Essayer de faire une requête simple pour voir si le serveur répond
                fetch('/', { method: 'HEAD' })
                    .then(() => {
                        // Le serveur répond, on peut recharger
                        if (typeof showToast === 'function') {
                            showToast('Serveur prêt, rechargement...', 'success');
                        }
                        setTimeout(() => window.location.reload(), 500);
                    })
                    .catch(() => {
                        // Le serveur ne répond pas encore
                        if (attempts < maxAttempts) {
                            setTimeout(tryReload, 2000);
                        } else {
                            if (typeof showToast === 'function') {
                                showToast('Le serveur met du temps à redémarrer. Rechargez manuellement.', 'warning');
                            }
                            if (btn) {
                                btn.classList.remove('restarting');
                                btn.disabled = false;
                            }
                        }
                    });
            };
            
            // Attendre 5 secondes avant de commencer à essayer
            setTimeout(tryReload, 5000);
            
        } else {
            throw new Error(data.error || 'Erreur lors du redémarrage');
        }
    } catch (error) {
        console.error('Erreur redémarrage:', error);
        showToast('Erreur lors du redémarrage', 'error');
        if (btn) {
            btn.classList.remove('restarting');
            btn.disabled = false;
        }
    }
}