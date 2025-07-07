/**
 * Gestion des projets WordPress - Interface Ultra Moderne
 * Chargement, affichage, contrôles start/stop avec animations
 */

// Variables globales pour les projets (projects est défini dans le template principal)
// refreshInterval et currentFilter sont définis dans search-filter.js

/**
 * Fonction pour démarrer un projet
 * @param {string} projectName - Nom du projet
 */
async function startProject(projectName) {
    try {
        const button = document.querySelector(`button[onclick="startProject('${projectName}')"]`);
        if (button) {
            button.classList.add('loading');
            button.innerHTML = '';
        }

        const response = await makeRequest(`/start_project/${projectName}`, 'POST');
        
        if (response.success) {
            showSuccess(`Projet ${projectName} démarré avec succès`);
            setTimeout(() => loadProjects(), 2000); // Recharger après 2 secondes
        } else {
            showError(response.message || 'Erreur lors du démarrage');
        }
    } catch (error) {
        console.error('Erreur démarrage:', error);
        showError('Erreur lors du démarrage du projet');
    }
}

/**
 * Fonction pour arrêter un projet
 * @param {string} projectName - Nom du projet
 */
async function stopProject(projectName) {
    try {
        const button = document.querySelector(`button[onclick="stopProject('${projectName}')"]`);
        if (button) {
            button.classList.add('loading');
            button.innerHTML = '';
        }

        const response = await makeRequest(`/stop_project/${projectName}`, 'POST');
        
        if (response.success) {
            showSuccess(`Projet ${projectName} arrêté avec succès`);
            setTimeout(() => loadProjects(), 2000); // Recharger après 2 secondes
        } else {
            showError(response.message || 'Erreur lors de l\'arrêt');
        }
    } catch (error) {
        console.error('Erreur arrêt:', error);
        showError('Erreur lors de l\'arrêt du projet');
    }
}

/**
 * Fonction pour supprimer un projet
 * @param {string} projectName - Nom du projet
 */
function deleteProject(projectName) {
    const modal = new bootstrap.Modal(document.getElementById('deleteModal'));
    document.getElementById('delete-project-name').textContent = projectName;
    
    // Gérer la confirmation
    const confirmButton = document.getElementById('confirm-delete');
    confirmButton.onclick = () => confirmDeleteProject(projectName);
    
    modal.show();
}

/**
 * Confirme et execute la suppression d'un projet
 * @param {string} projectName - Nom du projet à supprimer
 */
async function confirmDeleteProject(projectName) {
    try {
        // Fermer le modal de confirmation
        bootstrap.Modal.getInstance(document.getElementById('deleteModal')).hide();
        
        // Trouver et désactiver visuellement le projet
        const projectElement = document.querySelector(`[data-project="${projectName}"]`);
        if (projectElement) {
            // Effet visuel de suppression en cours
            projectElement.style.opacity = '0.5';
            projectElement.style.pointerEvents = 'none';
            projectElement.style.transition = 'all 0.3s ease';
            
            // Ajouter un overlay de suppression en cours
            const overlay = document.createElement('div');
            overlay.style.cssText = `
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: var(--border-radius);
                z-index: 10;
            `;
            overlay.innerHTML = `
                <div style="color: white; text-align: center;">
                    <i class="fas fa-spinner fa-spin" style="font-size: 2rem; margin-bottom: 0.5rem;"></i>
                    <div>Suppression en cours...</div>
                </div>
            `;
            
            if (projectElement.style.position !== 'relative') {
                projectElement.style.position = 'relative';
            }
            projectElement.appendChild(overlay);
        }
        
        // Appel API pour supprimer le projet
        const response = await makeRequest(`/delete_project/${projectName}`, 'DELETE');
        
        if (response.success) {
            showSuccess(`Projet ${projectName} supprimé avec succès`);
            
            // Animation de disparition du projet
            if (projectElement) {
                projectElement.style.transform = 'scale(0.8)';
                projectElement.style.opacity = '0';
                
                // Supprimer l'élément après l'animation
                setTimeout(() => {
                    if (projectElement.parentNode) {
                        projectElement.parentNode.removeChild(projectElement);
                    }
                    // Recharger la liste complète pour être sûr
                    loadProjects();
                }, 300);
            } else {
                // Recharger immédiatement si l'élément n'est pas trouvé
                loadProjects();
            }
        } else {
            // Erreur - restaurer l'état visuel
            if (projectElement) {
                projectElement.style.opacity = '1';
                projectElement.style.pointerEvents = 'auto';
                const overlay = projectElement.querySelector('[style*="position: absolute"]');
                if (overlay) {
                    overlay.remove();
                }
            }
            showError(response.message || 'Erreur lors de la suppression');
        }
    } catch (error) {
        console.error('Erreur suppression:', error);
        showError('Erreur lors de la suppression du projet');
        
        // Restaurer l'état visuel en cas d'erreur
        const projectElement = document.querySelector(`[data-project="${projectName}"]`);
        if (projectElement) {
            projectElement.style.opacity = '1';
            projectElement.style.pointerEvents = 'auto';
            const overlay = projectElement.querySelector('[style*="position: absolute"]');
            if (overlay) {
                overlay.remove();
            }
        }
        
        // Recharger la liste en cas d'erreur pour être sûr
        loadProjects();
    }
}

/**
 * Fonction pour éditer l'hostname d'un projet
 * @param {string} projectName - Nom du projet
 * @param {string} currentHostname - Hostname actuel
 */
function editHostname(projectName, currentHostname) {
    const modal = new bootstrap.Modal(document.getElementById('hostnameModal'));
    const input = document.getElementById('new-hostname');
    
    input.value = currentHostname;
    
    // Gérer la soumission du formulaire
    const form = document.getElementById('hostname-form');
    form.onsubmit = (e) => {
        e.preventDefault();
        saveHostname(projectName, input.value);
    };
    
    modal.show();
}

/**
 * Sauvegarde le nouvel hostname et met à jour le reverse proxy
 * @param {string} projectName - Nom du projet
 * @param {string} newHostname - Nouvel hostname
 */
async function saveHostname(projectName, newHostname) {
    try {
        const submitButton = document.querySelector('#hostname-form button[type="submit"]');
        submitButton.classList.add('loading');
        
        const response = await makeRequest(`/edit_hostname/${projectName}`, 'POST', {
            'Content-Type': 'application/json'
        }, JSON.stringify({ new_hostname: newHostname }));
        
        if (response.success) {
            showSuccess('Hostname mis à jour avec succès');
            bootstrap.Modal.getInstance(document.getElementById('hostnameModal')).hide();
            loadProjects(); // Recharger la liste
        } else {
            showError(response.message || 'Erreur lors de la mise à jour');
        }
    } catch (error) {
        console.error('Erreur mise à jour hostname:', error);
        showError('Erreur lors de la mise à jour de l\'hostname');
    } finally {
        const submitButton = document.querySelector('#hostname-form button[type="submit"]');
        submitButton.classList.remove('loading');
    }
}

/**
 * Fonction pour importer une base de données avec le système ultra-rapide
 * @param {string} projectName - Nom du projet
 */
function fastImportDatabase(projectName) {
    const modal = new bootstrap.Modal(document.getElementById('updateDbModal'));
    
    // Gérer la soumission du formulaire
    const form = document.getElementById('update-db-form');
    form.onsubmit = (e) => {
        e.preventDefault();
        fastUploadDatabase(projectName, new FormData(form));
    };
    
    modal.show();
}

/**
 * Upload et import ultra-rapide de la base de données
 * @param {string} projectName - Nom du projet
 * @param {FormData} formData - Données du formulaire
 */
async function fastUploadDatabase(projectName, formData) {
    try {
        const submitButton = document.querySelector('#update-db-form button[type="submit"]');
        submitButton.classList.add('loading');
        
        // Utiliser la nouvelle route ultra-rapide
        const response = await fetch(`/fast_import_database/${projectName}`, {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success) {
            showSuccess('Import ultra-rapide de base de données démarré');
            bootstrap.Modal.getInstance(document.getElementById('updateDbModal')).hide();
            
            // Afficher des informations sur les performances
            if (result.estimated_speed) {
                showToast(
                    'Import optimisé',
                    `Méthode sélectionnée: ${result.method}<br>Vitesse estimée: ${result.estimated_speed}`,
                    'info',
                    5000
                );
            }
        } else {
            showError(result.message || 'Erreur lors de l\'import ultra-rapide');
        }
    } catch (error) {
        console.error('Erreur import DB ultra-rapide:', error);
        showError('Erreur lors de l\'import ultra-rapide de la base de données');
    } finally {
        const submitButton = document.querySelector('#update-db-form button[type="submit"]');
        submitButton.classList.remove('loading');
    }
}

/**
 * Fonction pour ajouter Next.js à un projet
 * @param {string} projectName - Nom du projet
 */
async function addNextjs(projectName) {
    try {
        if (!confirm(`Ajouter Next.js au projet ${projectName} ?`)) {
            return;
        }
        
        const response = await makeRequest(`/add_nextjs/${projectName}`, 'POST');
        
        if (response.success) {
            showSuccess(`Next.js ajouté au projet ${projectName} sur le port ${response.nextjs_port}`);
            loadProjects(); // Recharger la liste
        } else {
            showError(response.message || 'Erreur lors de l\'ajout de Next.js');
        }
    } catch (error) {
        console.error('Erreur ajout Next.js:', error);
        showError('Erreur lors de l\'ajout de Next.js');
    }
}

/**
 * Fonction pour supprimer Next.js d'un projet
 * @param {string} projectName - Nom du projet
 */
async function removeNextjs(projectName) {
    try {
        if (!confirm(`Supprimer Next.js du projet ${projectName} ?`)) {
            return;
        }
        
        const response = await makeRequest(`/remove_nextjs/${projectName}`, 'POST');
        
        if (response.success) {
            showSuccess(`Next.js supprimé du projet ${projectName}`);
            loadProjects(); // Recharger la liste
        } else {
            showError(response.message || 'Erreur lors de la suppression de Next.js');
        }
    } catch (error) {
        console.error('Erreur suppression Next.js:', error);
        showError('Erreur lors de la suppression de Next.js');
    }
}

/**
 * Utilitaire pour les requêtes AJAX
 * @param {string} url - URL de la requête
 * @param {string} method - Méthode HTTP
 * @param {Object} headers - En-têtes supplémentaires
 * @param {string} body - Corps de la requête
 */
async function makeRequest(url, method = 'GET', headers = {}, body = null) {
    const options = {
        method: method,
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            ...headers
        }
    };
    
    if (body) {
        options.body = body;
    }
    
    const response = await fetch(url, options);
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    
    const text = await response.text();
    
    try {
        return JSON.parse(text);
    } catch (e) {
        // Si ce n'est pas du JSON, retourner le texte
        return { success: true, data: text };
    }
}

/**
 * Utilitaire pour échapper le HTML
 * @param {string} text - Texte à échapper
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Copie du texte dans le presse-papiers
 * @param {string} text - Texte à copier
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showSuccess('Copié dans le presse-papiers');
    } catch (error) {
        console.error('Erreur copie presse-papiers:', error);
        showError('Erreur lors de la copie');
    }
}

/**
 * Import d'un fichier SQL local trouvé dans les uploads
 * @param {string} projectName - Nom du projet
 */
async function importLocalSql(projectName) {
    try {
        // Confirmer l'action
        if (!confirm(`Importer le fichier SQL local le plus récent pour le projet ${projectName} ?`)) {
            return;
        }
        
        showLoader('Import du fichier SQL local en cours...');
        
        const response = await fetch(`/import_local_sql/${projectName}`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showSuccess(`Fichier SQL local importé avec succès: ${result.file_imported}`);
            // Rafraîchir la liste des projets
            setTimeout(loadProjects, 2000);
        } else {
            showError(result.message || 'Erreur lors de l\'import du fichier SQL local');
        }
    } catch (error) {
        console.error('Erreur import SQL local:', error);
        showError('Erreur lors de l\'import du fichier SQL local');
    } finally {
        hideLoader();
    }
}

/**
 * Lister les fichiers SQL locaux disponibles
 */
async function listLocalSqlFiles() {
    try {
        const response = await fetch('/list_local_sql');
        const result = await response.json();
        
        if (result.success) {
            console.log('Fichiers SQL locaux:', result.files);
            return result.files;
        } else {
            console.error('Erreur lors de la liste des fichiers SQL:', result.message);
            return [];
        }
    } catch (error) {
        console.error('Erreur liste SQL local:', error);
        return [];
    }
}

// Variables globales pour le suivi du progrès
let currentImportProject = null;
let importProgressModal = null;
let importedTablesSet = new Set();

// Initialisation du suivi du progrès
function initProgressTracking() {
    // Écouter les événements de progrès d'import
    socket.on('fast_import_progress', function(data) {
        updateImportProgress(data);
    });
    
    // Référence au modal de progrès
    importProgressModal = new bootstrap.Modal(document.getElementById('importProgressModal'));
}

// Mettre à jour le progrès d'import
function updateImportProgress(data) {
    if (data.project !== currentImportProject) {
        return; // Ignorer si ce n'est pas le bon projet
    }
    
    const progressBar = document.getElementById('import-progress-bar');
    const progressPercentage = document.getElementById('progress-percentage');
    const progressMessage = document.getElementById('progress-message');
    const progressSpinner = document.getElementById('progress-spinner');
    const progressSuccessIcon = document.getElementById('progress-success-icon');
    const progressErrorIcon = document.getElementById('progress-error-icon');
    const progressCloseBtn = document.getElementById('progress-close-btn');
    const progressFooter = document.getElementById('progress-footer');
    const tablesContainer = document.getElementById('tables-container');
    const importedTablesDiv = document.getElementById('imported-tables');
    const importStats = document.getElementById('import-stats');
    
    // Mettre à jour la barre de progrès
    progressBar.style.width = data.progress + '%';
    progressPercentage.textContent = data.progress + '%';
    progressMessage.textContent = data.message;
    
    // Gérer les différents états
    switch (data.status) {
        case 'starting':
        case 'analyzing':
        case 'analyzed':
        case 'connecting':
        case 'dropping':
        case 'optimizing':
        case 'copying':
            progressSpinner.style.display = 'block';
            progressSuccessIcon.style.display = 'none';
            progressErrorIcon.style.display = 'none';
            break;
            
        case 'importing':
            progressSpinner.style.display = 'block';
            progressSuccessIcon.style.display = 'none';
            progressErrorIcon.style.display = 'none';
            
            // Afficher les tables importées
            if (data.table && !importedTablesSet.has(data.table)) {
                importedTablesSet.add(data.table);
                addImportedTable(data.table);
                tablesContainer.style.display = 'block';
            }
            break;
            
        case 'finalizing':
            progressSpinner.style.display = 'block';
            progressSuccessIcon.style.display = 'none';
            progressErrorIcon.style.display = 'none';
            break;
            
        case 'completed':
            progressSpinner.style.display = 'none';
            progressSuccessIcon.style.display = 'block';
            progressErrorIcon.style.display = 'none';
            progressCloseBtn.style.display = 'block';
            progressFooter.style.display = 'block';
            
            // Arrêter l'animation de la barre de progrès
            progressBar.classList.remove('progress-bar-animated');
            break;
            
        case 'error':
            progressSpinner.style.display = 'none';
            progressSuccessIcon.style.display = 'none';
            progressErrorIcon.style.display = 'block';
            progressCloseBtn.style.display = 'block';
            progressFooter.style.display = 'block';
            
            // Changer la couleur de la barre de progrès en rouge
            progressBar.classList.remove('progress-bar-animated');
            progressBar.style.background = '#dc3545';
            break;
    }
    
    console.log('📊 Progrès import:', data);
}

// Ajouter une table importée à l'affichage
function addImportedTable(tableName) {
    const importedTablesDiv = document.getElementById('imported-tables');
    const tableElement = document.createElement('div');
    tableElement.className = 'col-auto';
    tableElement.innerHTML = `
        <div class="table-imported">
            <div class="table-name">${tableName}</div>
        </div>
    `;
    importedTablesDiv.appendChild(tableElement);
}

// Afficher les statistiques finales
function showImportStats(details) {
    const importStats = document.getElementById('import-stats');
    const statDuration = document.getElementById('stat-duration');
    const statSpeed = document.getElementById('stat-speed');
    const statSize = document.getElementById('stat-size');
    const statTables = document.getElementById('stat-tables');
    
    if (details) {
        statDuration.textContent = details.duration || '-';
        statSpeed.textContent = details.speed || '-';
        statSize.textContent = details.file_size || '-';
        statTables.textContent = details.tables_imported || '-';
        
        importStats.style.display = 'block';
    }
}

// Réinitialiser le modal de progrès
function resetProgressModal() {
    const progressBar = document.getElementById('import-progress-bar');
    const progressPercentage = document.getElementById('progress-percentage');
    const progressMessage = document.getElementById('progress-message');
    const progressSpinner = document.getElementById('progress-spinner');
    const progressSuccessIcon = document.getElementById('progress-success-icon');
    const progressErrorIcon = document.getElementById('progress-error-icon');
    const progressCloseBtn = document.getElementById('progress-close-btn');
    const progressFooter = document.getElementById('progress-footer');
    const tablesContainer = document.getElementById('tables-container');
    const importedTablesDiv = document.getElementById('imported-tables');
    const importStats = document.getElementById('import-stats');
    
    // Réinitialiser les éléments
    progressBar.style.width = '0%';
    progressBar.style.background = '';
    progressBar.classList.add('progress-bar-animated');
    progressPercentage.textContent = '0%';
    progressMessage.textContent = 'Initialisation...';
    
    // Réinitialiser les icônes
    progressSpinner.style.display = 'block';
    progressSuccessIcon.style.display = 'none';
    progressErrorIcon.style.display = 'none';
    progressCloseBtn.style.display = 'none';
    progressFooter.style.display = 'none';
    
    // Réinitialiser les tables
    tablesContainer.style.display = 'none';
    importedTablesDiv.innerHTML = '';
    importedTablesSet.clear();
    
    // Réinitialiser les statistiques
    importStats.style.display = 'none';
}

// Fonction d'import ultra-rapide
function fastImportDatabase(projectName) {
    currentImportProject = projectName;
    
    // Réinitialiser et afficher le modal de progrès
    resetProgressModal();
    importProgressModal.show();
    
    // Cacher le modal d'import de fichier
    const updateModal = bootstrap.Modal.getInstance(document.getElementById('updateDbModal'));
    if (updateModal) {
        updateModal.hide();
    }
    
    // Préparer les données du formulaire
    const formData = new FormData();
    const fileInput = document.getElementById('db-file');
    const file = fileInput.files[0];
    
    if (!file) {
        showToast('Veuillez sélectionner un fichier', 'error');
        importProgressModal.hide();
        return;
    }
    
    formData.append('db_file', file);
    
    // Envoyer la requête d'import
    fetch(`/fast_import_database/${projectName}`, {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log('✅ Import réussi:', data);
            
            // Afficher les statistiques finales
            if (data.details) {
                showImportStats(data.details);
            }
            
            // Recharger la liste des projets après un délai
            setTimeout(() => {
                loadProjects();
            }, 2000);
            
        } else {
            console.error('❌ Erreur import:', data.message);
            showToast(data.message, 'error');
        }
    })
    .catch(error => {
        console.error('❌ Erreur réseau:', error);
        showToast('Erreur lors de l\'import: ' + error.message, 'error');
    });
}

// Fonction pour ouvrir le modal d'import
function openImportModal(projectName) {
    document.getElementById('update-db-form').dataset.projectName = projectName;
    const modal = new bootstrap.Modal(document.getElementById('updateDbModal'));
    modal.show();
}

// Modifier la fonction updateDatabase pour utiliser le nouveau système
function updateDatabase(projectName) {
    console.log('📋 Ouverture du modal d\'import pour:', projectName);
    openImportModal(projectName);
}

// Gestionnaire du formulaire d'import
document.getElementById('update-db-form').addEventListener('submit', function(e) {
    e.preventDefault();
    
    const projectName = this.dataset.projectName;
    if (!projectName) {
        showToast('Erreur: nom du projet manquant', 'error');
        return;
    }
    
    // Lancer l'import ultra-rapide
    fastImportDatabase(projectName);
});

/**
 * Gestion de la soumission du formulaire de création
 */
document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('createProjectForm');
    if (form) {
        form.addEventListener('submit', function(e) {
            const projectName = document.getElementById('project_name').value;
            if (!projectName || !/^[a-zA-Z0-9-_]+$/.test(projectName)) {
                e.preventDefault();
                showError('Le nom du projet doit contenir uniquement des lettres, chiffres, tirets et underscores.');
                return;
            }
            
            // Ajouter un loader au bouton de soumission
            const submitButton = form.querySelector('button[type="submit"]');
            if (submitButton) {
                submitButton.classList.add('loading');
                setTimeout(() => {
                    // Cacher le modal après soumission
                    const modal = bootstrap.Modal.getInstance(document.getElementById('createProjectModal'));
                    if (modal) modal.hide();
                }, 1000);
            }
        });
    }
});

// Rafraîchissement automatique des projets (fonction globale utilisée dans index.html)
if (typeof refreshProjects === 'undefined') {
    window.refreshProjects = function() {
        if (typeof loadProjects === 'function') {
            loadProjects();
        }
    };
} 

// Initialiser le suivi du progrès au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Initialisation du suivi du progrès...');
    
    // Attendre que SocketIO soit prêt
    if (typeof socket !== 'undefined') {
        initProgressTracking();
    } else {
        // Réessayer après un délai si socket n'est pas encore défini
        setTimeout(() => {
            if (typeof socket !== 'undefined') {
                initProgressTracking();
            }
        }, 1000);
    }
    
    // Gérer la fermeture du modal de progrès
    const progressModal = document.getElementById('importProgressModal');
    if (progressModal) {
        progressModal.addEventListener('hidden.bs.modal', function() {
            currentImportProject = null;
            importedTablesSet.clear();
        });
    }
}); 