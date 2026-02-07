/**
 * Gestionnaire de configuration WP Debug - Sous-menu flottant
 */

let currentWPDebugProject = null;
let currentWPDebugConfig = {};

// Exposer globalement pour la gestion de fermeture
if (typeof window !== 'undefined') {
    window.wpDebugSubmenuElement = null;
}

/**
 * Crée le sous-menu WP Debug s'il n'existe pas
 */
function createWPDebugSubmenu() {
    if (window.wpDebugSubmenuElement) return window.wpDebugSubmenuElement;
    
    const submenu = document.createElement('div');
    submenu.id = 'wpdebug-floating-submenu';
    submenu.className = 'dropdown-menu dropdown-menu-dark show';
    submenu.style.cssText = 'position: fixed; z-index: 99999; min-width: 280px; display: none; padding: 15px;';
    
    submenu.innerHTML = `
        <div class="wpdebug-header mb-2 pb-2" style="border-bottom: 1px solid rgba(255,255,255,0.1);">
            <h6 class="text-light mb-0"><i class="fas fa-bug me-2"></i>WP Debug</h6>
        </div>
        <div id="wpdebug-loading" class="text-center py-2">
            <span class="spinner-border spinner-border-sm text-light"></span>
            <small class="text-light ms-2">Chargement...</small>
        </div>
        <div id="wpdebug-switches" style="display: none;">
            <div class="wpdebug-item">
                <div class="form-check form-switch">
                    <input class="form-check-input wpdebug-toggle" type="checkbox" id="toggle-WP_DEBUG" data-constant="WP_DEBUG">
                    <label class="form-check-label text-light small" for="toggle-WP_DEBUG">WP_DEBUG</label>
                </div>
            </div>
            <div class="wpdebug-item">
                <div class="form-check form-switch">
                    <input class="form-check-input wpdebug-toggle" type="checkbox" id="toggle-WP_DEBUG_LOG" data-constant="WP_DEBUG_LOG">
                    <label class="form-check-label text-light small" for="toggle-WP_DEBUG_LOG">WP_DEBUG_LOG</label>
                </div>
            </div>
            <div class="wpdebug-item">
                <div class="form-check form-switch">
                    <input class="form-check-input wpdebug-toggle" type="checkbox" id="toggle-WP_DEBUG_DISPLAY" data-constant="WP_DEBUG_DISPLAY">
                    <label class="form-check-label text-light small" for="toggle-WP_DEBUG_DISPLAY">WP_DEBUG_DISPLAY</label>
                </div>
            </div>
            <div class="wpdebug-item">
                <div class="form-check form-switch">
                    <input class="form-check-input wpdebug-toggle" type="checkbox" id="toggle-SCRIPT_DEBUG" data-constant="SCRIPT_DEBUG">
                    <label class="form-check-label text-light small" for="toggle-SCRIPT_DEBUG">SCRIPT_DEBUG</label>
                </div>
            </div>
            <div class="wpdebug-item">
                <div class="form-check form-switch">
                    <input class="form-check-input wpdebug-toggle" type="checkbox" id="toggle-SAVEQUERIES" data-constant="SAVEQUERIES">
                    <label class="form-check-label text-light small" for="toggle-SAVEQUERIES">SAVEQUERIES</label>
                </div>
            </div>
        </div>
    `;
    
    document.body.appendChild(submenu);
    
    // Event listeners pour les toggles
    submenu.addEventListener('change', async function(e) {
        if (e.target.classList.contains('wpdebug-toggle')) {
            const constant = e.target.dataset.constant;
            const value = e.target.checked;
            await toggleWPDebugConstant(constant, value, e.target);
        }
    });
    
    window.wpDebugSubmenuElement = submenu;
    return submenu;
}

/**
 * Ouvre le sous-menu WP Debug
 */
async function openWPDebugSubmenu(event, projectName) {
    
    event.preventDefault();
    event.stopPropagation();
    
    currentWPDebugProject = projectName;
    
    // Fermer le sous-menu WP-CLI s'il est ouvert
    if (typeof wpcliSubmenuElement !== 'undefined' && wpcliSubmenuElement && wpcliSubmenuElement.style.display === 'block') {
        wpcliSubmenuElement.style.display = 'none';
    }
    
    // Créer ou récupérer le sous-menu
    const submenu = createWPDebugSubmenu();
    
    // Récupérer le trigger
    const trigger = event.target.closest('a') || event.target;
    const rect = trigger.getBoundingClientRect();
    
    // Calculer la position
    let left = rect.right + 10;
    let top = rect.top + window.scrollY;
    
    // Ajuster si pas assez d'espace à droite
    if (window.innerWidth - rect.right < 300) {
        left = rect.left - 290;
    }
    
    // Ajuster si pas assez d'espace en bas
    if (rect.top + 300 > window.innerHeight) {
        top = window.innerHeight + window.scrollY - 310;
    }
    
    // Positionner et afficher
    submenu.style.left = `${left}px`;
    submenu.style.top = `${top}px`;
    submenu.style.display = 'block';
    
    
    // Charger la configuration
    await loadWPDebugConfig();
}

/**
 * Charge la configuration WP Debug actuelle
 */
async function loadWPDebugConfig() {
    const loadingDiv = document.getElementById('wpdebug-loading');
    const switchesDiv = document.getElementById('wpdebug-switches');
    
    if (!loadingDiv || !switchesDiv) return;
    
    loadingDiv.style.display = 'block';
    switchesDiv.style.display = 'none';
    
    try {
        const response = await fetch(`/wp-debug/get/${currentWPDebugProject}`);
        const result = await response.json();
        
        if (result.success) {
            
            // Sauvegarder la config
            currentWPDebugConfig = result.config;
            
            // Mettre à jour l'état des switches
            updateDebugSwitches(result.config);
            
            // Afficher le contenu
            loadingDiv.style.display = 'none';
            switchesDiv.style.display = 'block';
        } else {
            console.error('[WP Debug] Error:', result.message);
            if (wpDebugSubmenuElement) {
                wpDebugSubmenuElement.style.display = 'none';
            }
            showToast(result.message, 'error');
        }
    } catch (error) {
        console.error('[WP Debug] Error loading config:', error);
        if (wpDebugSubmenuElement) {
            wpDebugSubmenuElement.style.display = 'none';
        }
        showToast('Erreur de chargement', 'error');
    }
}

/**
 * Met à jour l'état visuel des switches
 */
function updateDebugSwitches(config) {
    const constants = ['WP_DEBUG', 'WP_DEBUG_LOG', 'WP_DEBUG_DISPLAY', 'SCRIPT_DEBUG', 'SAVEQUERIES'];
    
    constants.forEach(constant => {
        const checkbox = document.getElementById(`toggle-${constant}`);
        if (checkbox) {
            checkbox.checked = config[constant] === true;
        }
    });
}

/**
 * Toggle une constante WP Debug
 */
async function toggleWPDebugConstant(constant, value, checkbox) {
    
    // Désactiver tous les switches pendant la requête
    const allSwitches = document.querySelectorAll('.wpdebug-toggle');
    allSwitches.forEach(sw => sw.disabled = true);
    
    try {
        const response = await fetch(`/wp-debug/set/${currentWPDebugProject}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                constant: constant,
                value: value
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            
            // Mettre à jour la config locale
            currentWPDebugConfig = result.config;
            
            // Afficher un feedback discret
            showToast(`${constant} ${value ? 'ON' : 'OFF'}`, 'success');
        } else {
            console.error('[WP Debug] Error:', result.message);
            // Restaurer l'état précédent
            checkbox.checked = !value;
            showToast(result.message, 'error');
        }
    } catch (error) {
        console.error('[WP Debug] Error setting constant:', error);
        // Restaurer l'état précédent
        checkbox.checked = !value;
        showToast('Erreur de connexion', 'error');
    } finally {
        // Réactiver tous les switches
        allSwitches.forEach(sw => sw.disabled = false);
    }
}

// Exposer globalement
window.openWPDebugSubmenu = openWPDebugSubmenu;
window.wpDebugSubmenuElement = wpDebugSubmenuElement;

