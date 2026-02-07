/**
 * Gestionnaire des configurations PHP et MySQL
 */

// Variables globales pour les configurations
let currentConfigProject = null;
let currentConfigType = null;

/**
 * Ouvre la modal de configuration PHP
 */
function openPhpConfigModal(projectName) {
    currentConfigProject = projectName;
    currentConfigType = 'php';
    
    
    // Charger la configuration actuelle et le type WordPress
    Promise.all([
        loadConfigData(projectName, 'php'),
        loadWordPressType(projectName)
    ]).then(([configData, wpTypeData]) => {
        if (configData.success) {
            showConfigModal('Configuration PHP', configData.config, configData.schema, 'php', wpTypeData);
        } else {
            showErrorMessage('Erreur lors du chargement de la configuration PHP: ' + configData.error);
        }
    }).catch(error => {
        showErrorMessage('Erreur lors du chargement de la configuration PHP');
    });
}

/**
 * Ouvre la modal de configuration MySQL
 */
function openMysqlConfigModal(projectName) {
    currentConfigProject = projectName;
    currentConfigType = 'mysql';
    
    
    // Charger la configuration actuelle
    loadConfigData(projectName, 'mysql')
        .then(data => {
            if (data.success) {
                showConfigModal('Configuration MySQL', data.config, data.schema, 'mysql');
            } else {
                showErrorMessage('Erreur lors du chargement de la configuration MySQL: ' + data.error);
            }
        })
        .catch(error => {
            showErrorMessage('Erreur lors du chargement de la configuration MySQL');
        });
}

/**
 * Charge les données de configuration depuis l'API
 */
async function loadConfigData(projectName, configType) {
    try {
        const response = await fetch(`/api/config/${configType}/${projectName}`);
        return await response.json();
    } catch (error) {
        throw error;
    }
}

/**
 * Charge le type WordPress d'un projet
 */
async function loadWordPressType(projectName) {
    try {
        const response = await fetch(`/api/config/wordpress-type/${projectName}`);
        const data = await response.json();
        return data.success ? data : { success: false };
    } catch (error) {
        return { success: false };
    }
}

/**
 * Affiche la modal de configuration
 */
function showConfigModal(title, config, schema, configType, wpTypeData = null) {
    // Générer la section du type WordPress si c'est une config PHP
    let wpTypeSectionHtml = '';
    if (configType === 'php' && wpTypeData && wpTypeData.success) {
        const currentType = wpTypeData.type || 'showcase';
        const types = wpTypeData.types || {};
        
        wpTypeSectionHtml = `
            <div class="wordpress-type-selector mb-4">
                <h6 class="text-light mb-3">
                    <i class="fas fa-server me-2"></i>Type de site WordPress
                </h6>
                <div class="row g-3">
                    ${Object.keys(types).map(typeKey => {
                        const typeInfo = types[typeKey];
                        const isChecked = currentType === typeKey ? 'checked' : '';
                        return `
                            <div class="col-md-6">
                                <div class="form-check">
                                    <input class="form-check-input" type="radio" name="wordpress_type" 
                                           id="wp_type_${typeKey}" value="${typeKey}" ${isChecked}>
                                    <label class="form-check-label text-light" for="wp_type_${typeKey}">
                                        <div style="font-size: 1.15em; margin-bottom: 5px;">
                                            <i class="${typeInfo.icon}"></i>
                                        </div>
                                        ${typeInfo.label}
                                        <br>
                                        <small class="text-info" style="font-size: 0.95em;">${typeInfo.memory} • ${typeInfo.cpu}</small>
                                    </label>
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
            <hr class="border-secondary mb-4">
        `;
    }
    
    // Créer la modal
    const modalHtml = `
        <div class="modal fade" id="configModal" tabindex="-1" aria-labelledby="configModalLabel" aria-hidden="true">
            <div class="modal-dialog modal-lg">
                <div class="modal-content bg-dark">
                    <div class="modal-header border-secondary">
                        <h5 class="modal-title text-light" id="configModalLabel">
                            <i class="fas fa-cog me-2"></i>${title} - ${currentConfigProject}
                        </h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        ${wpTypeSectionHtml}
                        <form id="configForm">
                            <div class="row">
                                ${generateConfigFields(config, schema)}
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer border-secondary">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                            <i class="fas fa-times me-2"></i>Annuler
                        </button>
                        <button type="button" class="btn btn-primary" onclick="saveConfiguration()">
                            <i class="fas fa-save me-2"></i>Enregistrer et redémarrer
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Supprimer la modal existante si elle existe
    const existingModal = document.getElementById('configModal');
    if (existingModal) {
        existingModal.remove();
    }
    
    // Ajouter la nouvelle modal au DOM
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // Afficher la modal
    const modal = new bootstrap.Modal(document.getElementById('configModal'));
    modal.show();
    
    // Ajouter les event listeners pour les switches (mais pas les radios WordPress)
    const switches = document.querySelectorAll('#configModal .form-check-input[type="checkbox"]');
    switches.forEach(switchInput => {
        switchInput.addEventListener('change', function() {
            const label = this.nextElementSibling;
            const checkedValue = this.getAttribute('data-checked-value') || 'true';
            const uncheckedValue = this.getAttribute('data-unchecked-value') || 'false';
            const checkedLabel = this.getAttribute('data-checked-label') || 'Activé';
            const uncheckedLabel = this.getAttribute('data-unchecked-label') || 'Désactivé';
            
            if (this.checked) {
                this.value = checkedValue;
                if (label && label.classList.contains('form-check-label')) {
                    label.textContent = checkedLabel;
                }
            } else {
                this.value = uncheckedValue;
                if (label && label.classList.contains('form-check-label')) {
                    label.textContent = uncheckedLabel;
                }
            }
        });
    });
    
    // Nettoyer après fermeture
    document.getElementById('configModal').addEventListener('hidden.bs.modal', function () {
        this.remove();
    });
}

/**
 * Génère les champs de configuration basés sur le schéma
 */
function generateConfigFields(config, schema) {
    let fieldsHtml = '';
    
    for (const [key, fieldSchema] of Object.entries(schema)) {
        // Filtrer les options WP_DEBUG (gérées dans le menu Commandes)
        if (key.toLowerCase().includes('wp_debug')) {
            continue;
        }
        
        const currentValue = config[key] || fieldSchema.default || '';
        
        fieldsHtml += `
            <div class="col-md-6 mb-3">
                <label for="config_${key}" class="form-label text-light">
                    ${fieldSchema.label}
                    ${fieldSchema.description ? `<i class="fas fa-info-circle ms-1" title="${fieldSchema.description}"></i>` : ''}
                </label>
                ${generateFieldInput(key, fieldSchema, currentValue)}
            </div>
        `;
    }
    
    return fieldsHtml;
}

/**
 * Génère un champ d'entrée basé sur le type
 */
function generateFieldInput(key, fieldSchema, currentValue) {
    const baseClasses = 'form-control bg-secondary text-light border-secondary';
    
    switch (fieldSchema.type) {
        case 'select':
            let optionsHtml = '';
            for (const option of fieldSchema.options) {
                const selected = currentValue === option ? 'selected' : '';
                optionsHtml += `<option value="${option}" ${selected}>${option}</option>`;
            }
            return `<select id="config_${key}" name="${key}" class="${baseClasses}">${optionsHtml}</select>`;
            
        case 'switch':
            // Pour display_errors, on utilise 'On'/'Off' au lieu de 'true'/'false'
            let isChecked, checkedValue, uncheckedValue, checkedLabel, uncheckedLabel;
            if (key === 'display_errors') {
                isChecked = currentValue === 'On';
                checkedValue = 'On';
                uncheckedValue = 'Off';
                checkedLabel = 'Activé (On)';
                uncheckedLabel = 'Désactivé (Off)';
            } else {
                // Pour wp_debug, wp_debug_log, wp_debug_display
                isChecked = currentValue === 'true' || currentValue === true;
                checkedValue = 'true';
                uncheckedValue = 'false';
                checkedLabel = 'Activé';
                uncheckedLabel = 'Désactivé';
            }
            
            return `
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="config_${key}" name="${key}" 
                           ${isChecked ? 'checked' : ''} 
                           data-checked-value="${checkedValue}" 
                           data-unchecked-value="${uncheckedValue}"
                           data-checked-label="${checkedLabel}"
                           data-unchecked-label="${uncheckedLabel}"
                           value="${isChecked ? checkedValue : uncheckedValue}">
                    <label class="form-check-label text-light" for="config_${key}">
                        ${isChecked ? checkedLabel : uncheckedLabel}
                    </label>
                </div>
            `;
            
        case 'number':
            return `<input type="number" id="config_${key}" name="${key}" class="${baseClasses}" value="${currentValue}" min="0">`;
            
        case 'text':
        default:
            return `<input type="text" id="config_${key}" name="${key}" class="${baseClasses}" value="${currentValue}" placeholder="${fieldSchema.default || ''}">`;
    }
}

/**
 * Sauvegarde la configuration
 */
async function saveConfiguration() {
    if (!currentConfigProject || !currentConfigType) {
        showToast('Erreur: projet ou type de configuration non défini', 'error');
        return;
    }
    
    let infoAlert = null; // Déclarer ici pour être accessible dans catch
    let taskId = null; // ID de la tâche pour le TaskManager
    
    try {
        // Collecter les données du formulaire AVANT de fermer la modale
        const formData = new FormData(document.getElementById('configForm'));
        const configData = {};
        
        for (const [key, value] of formData.entries()) {
            configData[key] = value;
        }
        
        // Gérer les switches (checkboxes) non cochées
        const form = document.getElementById('configForm');
        const switches = form.querySelectorAll('input[type="checkbox"]');
        switches.forEach(switchInput => {
            const name = switchInput.getAttribute('name');
            if (name && !configData.hasOwnProperty(name)) {
                const uncheckedValue = switchInput.getAttribute('data-unchecked-value') || 'false';
                configData[name] = uncheckedValue;
            }
        });
        
        // Récupérer le type WordPress si applicable AVANT de fermer la modale
        let wpTypeRadioValue = null;
        if (currentConfigType === 'php') {
            // Chercher dans la modale spécifiquement
            const modal = document.getElementById('configModal');
            const wpTypeRadio = modal ? modal.querySelector('input[name="wordpress_type"]:checked') : null;
            if (wpTypeRadio) {
                wpTypeRadioValue = wpTypeRadio.value;
                console.log('[Config] Type WordPress sélectionné:', wpTypeRadioValue);
            } else {
                console.warn('[Config] Aucun type WordPress sélectionné');
            }
        }
        
        // Fermer la modale immédiatement
        const modal = bootstrap.Modal.getInstance(document.getElementById('configModal'));
        if (modal) {
            modal.hide();
        }
        
        // Créer une tâche dans le TaskManager
        if (taskManager) {
            taskId = taskManager.generateTaskId('config_update', currentConfigProject);
            const taskName = currentConfigType === 'php' ? 'Configuration PHP' : 'Configuration MySQL';
            
            taskManager.createTask(taskId, taskName, 'config_update', currentConfigProject, {
                details: 'Sauvegarde de la configuration en cours...'
            });
        }
        
        // Vérifier si le type WordPress a changé (pour config PHP uniquement)
        let wpTypeChanged = false;
        if (currentConfigType === 'php' && wpTypeRadioValue) {
            // Charger le type actuel pour comparer
            const currentWpTypeData = await loadWordPressType(currentConfigProject);
            const currentType = currentWpTypeData.type || 'showcase';
            
            if (wpTypeRadioValue !== currentType) {
                wpTypeChanged = true;
                
                // Mettre à jour la tâche
                if (taskManager && taskId) {
                    taskManager.updateTask(taskId, {
                        message: 'Changement de type WordPress...',
                        details: 'Mise à jour des limites de ressources Docker'
                    });
                }
                
                // Afficher un message d'information
                infoAlert = document.createElement('div');
                infoAlert.className = 'alert alert-info alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3';
                infoAlert.style.zIndex = '9999';
                infoAlert.innerHTML = `
                    <i class="fas fa-info-circle me-2"></i>
                    Changement de type WordPress... Redémarrage des containers...
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                `;
                document.body.appendChild(infoAlert);
                
                // Sauvegarder le nouveau type
                const wpTypeResponse = await fetch(`/api/config/wordpress-type/${currentConfigProject}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ type: wpTypeRadioValue })
                });
                
                const wpTypeResult = await wpTypeResponse.json();
                
                if (!wpTypeResult.success) {
                    throw new Error(wpTypeResult.error || 'Erreur lors du changement de type WordPress');
                }
            }
        }
        
        // Mettre à jour la progression de la tâche
        if (taskManager && taskId) {
            taskManager.updateTask(taskId, {
                message: wpTypeChanged ? 'Configuration en cours...' : 'Sauvegarde de la configuration...',
                details: 'Envoi des données à l\'API'
            });
        }
        
        console.log('Configuration à envoyer:', configData);
        
        // Afficher un message d'information pour MySQL
        if (currentConfigType === 'mysql') {
            infoAlert = document.createElement('div');
            infoAlert.className = 'alert alert-info alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3';
            infoAlert.style.zIndex = '9999';
            infoAlert.innerHTML = `
                <i class="fas fa-info-circle me-2"></i>
                Redémarrage de MySQL en cours... Cela peut prendre 30-60 secondes.
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            document.body.appendChild(infoAlert);
            
            // Mettre à jour la tâche
            if (taskManager && taskId) {
                taskManager.updateTask(taskId, {
                    message: 'Redémarrage de MySQL...',
                    details: 'Cette opération peut prendre 30-60 secondes'
                });
            }
        }
        
        // Envoyer à l'API
        if (taskManager && taskId) {
            taskManager.updateTask(taskId, {
                message: 'Envoi de la configuration...',
                details: currentConfigType === 'mysql' ? 'Redémarrage du service...' : 'Application des modifications...'
            });
        }
        
        const response = await fetch(`/api/config/${currentConfigType}/${currentConfigProject}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(configData)
        });
        
        const result = await response.json();
        
        // Supprimer le message d'information s'il existe
        if (infoAlert) {
            infoAlert.remove();
        }
        
        if (result.success) {
            // Afficher un message de succès
            let successMessage = '';
            let reloadDelay = 1000;
            
            if (wpTypeChanged) {
                successMessage = 'Type WordPress et configuration mis à jour avec succès! Les containers ont été redémarrés.';
                reloadDelay = 3000;
            } else if (result.php_version_changed) {
                successMessage = 'Configuration PHP et version mises à jour! Le conteneur a été recréé.';
                reloadDelay = 3000;
            } else if (currentConfigType === 'mysql' && result.services_restarted) {
                successMessage = 'Configuration MySQL mise à jour avec succès! Le service MySQL a été redémarré.';
                reloadDelay = 2000;
            } else {
                successMessage = `Configuration ${currentConfigType.toUpperCase()} mise à jour avec succès!`;
                if (result.services_restarted) {
                    successMessage += ' Les services ont été redémarrés.';
                    reloadDelay = 2000;
                }
            }
            
            // Terminer la tâche avec succès
            if (taskManager && taskId) {
                taskManager.completeTask(taskId, successMessage, true);
            }
            
            // Créer une alerte de succès
            const alertDiv = document.createElement('div');
            alertDiv.className = 'alert alert-success alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3';
            alertDiv.style.zIndex = '9999';
            alertDiv.innerHTML = `
                <i class="fas fa-check-circle me-2"></i>
                ${successMessage}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            document.body.appendChild(alertDiv);
            
            // Auto-dismiss après 5 secondes
            setTimeout(() => {
                alertDiv.remove();
            }, 5000);
            
            // Rafraîchir la liste des projets pour refléter les changements
            setTimeout(() => {
                if (typeof loadProjects === 'function') {
                    loadProjects();
                }
            }, reloadDelay);
            
        } else {
            // Supprimer le message d'information s'il existe (en cas d'erreur aussi)
            if (infoAlert) {
                infoAlert.remove();
            }
            
            // Terminer la tâche avec erreur
            if (taskManager && taskId) {
                taskManager.completeTask(taskId, `Erreur: ${result.error}`, false);
            }
            
            // Afficher l'erreur
            const errorDiv = document.createElement('div');
            errorDiv.className = 'alert alert-danger alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3';
            errorDiv.style.zIndex = '9999';
            errorDiv.innerHTML = `
                <i class="fas fa-exclamation-triangle me-2"></i>
                Erreur: ${result.error}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            document.body.appendChild(errorDiv);
            
            setTimeout(() => {
                errorDiv.remove();
            }, 5000);
        }
        
    } catch (error) {
        console.error('Erreur lors de la sauvegarde:', error);
        
        // Supprimer le message d'information s'il existe
        if (infoAlert) {
            infoAlert.remove();
        }
        
        // Terminer la tâche avec erreur
        if (taskManager && taskId) {
            taskManager.completeTask(taskId, 'Erreur lors de la sauvegarde de la configuration', false);
        }
        
        // Afficher l'erreur
        const errorDiv = document.createElement('div');
        errorDiv.className = 'alert alert-danger alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3';
        errorDiv.style.zIndex = '9999';
        errorDiv.innerHTML = `
            <i class="fas fa-exclamation-triangle me-2"></i>
            Erreur lors de la sauvegarde de la configuration
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        document.body.appendChild(errorDiv);
        
        setTimeout(() => {
            errorDiv.remove();
        }, 5000);
    }
}

/**
 * Affiche un message de succès
 */
function showSuccessMessage(message) {
    const alertDiv = document.createElement('div');
    alertDiv.className = 'alert alert-success alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3';
    alertDiv.style.zIndex = '9999';
    alertDiv.innerHTML = `
        <i class="fas fa-check-circle me-2"></i>
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.body.appendChild(alertDiv);
    
    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

/**
 * Affiche un message d'erreur
 */
function showErrorMessage(message) {
    const alertDiv = document.createElement('div');
    alertDiv.className = 'alert alert-danger alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3';
    alertDiv.style.zIndex = '9999';
    alertDiv.innerHTML = `
        <i class="fas fa-exclamation-triangle me-2"></i>
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.body.appendChild(alertDiv);
    
    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

// Rendre les fonctions disponibles globalement
window.openPhpConfigModal = openPhpConfigModal;
window.openMysqlConfigModal = openMysqlConfigModal;
window.saveConfiguration = saveConfiguration;

// Config Manager chargé
