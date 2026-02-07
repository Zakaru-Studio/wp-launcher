/**
 * Gestion des snapshots de projets
 */

let currentSnapshotProject = null;
let currentSnapshotInstance = null; // Instance sélectionnée pour les snapshots
let currentSnapshotParentProject = null; // Nom du projet parent
let rollbackLogsBuffer = [];
let currentRollbackProject = null;
let rollbackLogsModalInstance = null;

/**
 * Ouvre la modale de gestion des snapshots
 */
function openSnapshotsModal(projectName) {
    console.log('[Snapshots] Opening modal for project:', projectName);
    
    try {
        // Détecter si une instance dev est actuellement sélectionnée
        const projectCard = document.querySelector(`[data-project-name="${projectName}"]`);
        const isDevInstance = projectCard && projectCard.dataset.isDevInstance === 'true';
        const currentInstance = projectCard ? projectCard.dataset.currentInstance : '';
        
        // Déterminer le nom du parent et l'instance actuelle
        if (isDevInstance && currentInstance) {
            currentSnapshotProject = currentInstance;
            currentSnapshotInstance = currentInstance;
            currentSnapshotParentProject = projectName;
        } else {
            currentSnapshotProject = projectName;
            currentSnapshotInstance = null;
            currentSnapshotParentProject = projectName;
        }
        
        console.log('[Snapshots] Target:', {
            project: currentSnapshotProject,
            instance: currentSnapshotInstance,
            parent: currentSnapshotParentProject,
            isDevInstance
        });
        
        // Vérifier que Bootstrap est chargé
        if (typeof bootstrap === 'undefined') {
            console.error('[Snapshots] Bootstrap non chargé, tentative de réessai...');
            setTimeout(() => openSnapshotsModal(projectName), 100);
            return;
        }
        
        // Mettre à jour le titre
        const titleElement = document.getElementById('snapshots-project-name');
        if (titleElement) {
            titleElement.textContent = currentSnapshotProject;
        }
        
        // Réinitialiser l'affichage
        const createForm = document.getElementById('create-snapshot-form');
        const snapshotsList = document.getElementById('snapshots-list');
        const btnCreate = document.getElementById('btn-create-snapshot');
        
        if (createForm) createForm.style.display = 'none';
        if (snapshotsList) snapshotsList.style.display = 'block';
        if (btnCreate) btnCreate.style.display = 'inline-block';
        
        // Afficher la modale
        const modalElement = document.getElementById('snapshotsModal');
        if (modalElement) {
            const modal = new bootstrap.Modal(modalElement);
            modal.show();
        } else {
            console.error('[Snapshots] Element #snapshotsModal non trouvé');
            return;
        }
        
        // Charger le sélecteur d'instances et la liste des snapshots
        loadInstanceSelector();
        loadSnapshotsList();
    } catch (error) {
        console.error('[Snapshots] Erreur:', error);
    }
}

/**
 * Charge et affiche le sélecteur d'instances
 */
async function loadInstanceSelector() {
    // Trouver ou créer le conteneur du sélecteur
    let selectorContainer = document.getElementById('snapshot-instance-selector');
    
    if (!selectorContainer) {
        // Créer le conteneur avant la liste des snapshots
        const listDiv = document.getElementById('snapshots-list');
        if (listDiv) {
            selectorContainer = document.createElement('div');
            selectorContainer.id = 'snapshot-instance-selector';
            selectorContainer.className = 'mb-3';
            listDiv.parentNode.insertBefore(selectorContainer, listDiv);
        }
    }
    
    if (!selectorContainer) {
        console.error('[Snapshots] Impossible de créer le sélecteur d\'instances');
        return;
    }
    
    try {
        // Charger la liste des instances
        const response = await fetch(`/api/dev-instances/by-project/${currentSnapshotParentProject}`);
        const result = await response.json();
        
        if (!result.success || !result.instances || result.instances.length === 0) {
            // Pas d'instances, afficher juste l'instance principale
            selectorContainer.innerHTML = `
                <div class="alert alert-info">
                    <i class="fas fa-info-circle me-2"></i>
                    Snapshots pour l'instance principale <strong>${currentSnapshotParentProject}</strong>
                </div>
            `;
            return;
        }
        
        // Construire le sélecteur avec instance principale + instances dev
        const instances = [
            { name: currentSnapshotParentProject, label: 'Instance principale', isMain: true },
            ...result.instances.map(inst => ({
                name: inst.name,
                label: `Instance de ${inst.owner_username}`,
                isMain: false
            }))
        ];
        
        const currentSelected = currentSnapshotProject;
        
        selectorContainer.innerHTML = `
            <div class="snapshot-instance-selector-wrapper">
                <label class="form-label text-light">
                    <i class="fas fa-server me-2"></i>
                    Instance cible pour les snapshots
                </label>
                <select class="form-select bg-secondary text-light border-secondary" id="snapshot-instance-select">
                    ${instances.map(inst => `
                        <option value="${inst.name}" ${inst.name === currentSelected ? 'selected' : ''}>
                            ${inst.label} ${inst.isMain ? '' : `(${inst.name})`}
                        </option>
                    `).join('')}
                </select>
            </div>
        `;
        
        // Ajouter un event listener pour changer d'instance
        const selectElement = document.getElementById('snapshot-instance-select');
        if (selectElement) {
            selectElement.addEventListener('change', function() {
                const newInstance = this.value;
                console.log('[Snapshots] Changement d\'instance:', newInstance);
                
                // Mettre à jour les variables globales
                currentSnapshotProject = newInstance;
                if (newInstance === currentSnapshotParentProject) {
                    currentSnapshotInstance = null;
                } else {
                    currentSnapshotInstance = newInstance;
                }
                
                // Mettre à jour le titre
                const titleElement = document.getElementById('snapshots-project-name');
                if (titleElement) {
                    titleElement.textContent = newInstance;
                }
                
                // Recharger la liste des snapshots
                loadSnapshotsList();
            });
        }
        
    } catch (error) {
        console.error('[Snapshots] Erreur chargement instances:', error);
        selectorContainer.innerHTML = `
            <div class="alert alert-warning">
                <i class="fas fa-exclamation-triangle me-2"></i>
                Impossible de charger les instances
            </div>
        `;
    }
}

/**
 * Charge la liste des snapshots d'un projet
 */
async function loadSnapshotsList() {
    const listDiv = document.getElementById('snapshots-list');
    
    listDiv.innerHTML = `
        <div class="text-center py-4">
            <span class="spinner-border" role="status"></span>
            <p class="mt-2">Chargement des snapshots...</p>
        </div>
    `;
    
    try {
        const response = await fetch(`/snapshots/list/${currentSnapshotProject}`);
        const result = await response.json();
        
        if (result.success) {
            if (result.snapshots.length === 0) {
                listDiv.innerHTML = `
                    <div class="alert alert-info">
                        <i class="fas fa-info-circle me-2"></i>
                        Aucun snapshot pour ce projet. Créez-en un pour sauvegarder l'état actuel.
                    </div>
                `;
            } else {
                listDiv.innerHTML = result.snapshots.map(snapshot => renderSnapshotCard(snapshot)).join('');
            }
        } else {
            listDiv.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    Erreur: ${result.message}
                </div>
            `;
        }
    } catch (error) {
        console.error('Erreur chargement snapshots:', error);
        listDiv.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle me-2"></i>
                Erreur de chargement: ${error.message}
            </div>
        `;
    }
}

/**
 * Génère le HTML pour une carte de snapshot
 */
function renderSnapshotCard(snapshot) {
    const date = new Date(snapshot.created_at).toLocaleString('fr-FR');
    const content = snapshot.content_summary || {};
    const totalSize = snapshot.total_size_mb || snapshot.archive_size_mb || 0;
    
    return `
        <div class="snapshot-card">
            <div class="snapshot-header">
                <div>
                    <h6 class="mb-1">
                        <i class="fas fa-camera me-2"></i>
                        ${snapshot.description || 'Snapshot sans description'}
                    </h6>
                    <div class="snapshot-meta">
                        <i class="fas fa-clock me-1"></i>${date} | 
                        <i class="fas fa-hdd me-1"></i>${totalSize} MB
                        ${snapshot.includes_database ? '<i class="fas fa-database ms-2 text-success" title="Inclut la base de données"></i>' : ''}
                    </div>
                </div>
                <div>
                    <button class="btn btn-sm btn-warning" onclick="rollbackSnapshot('${snapshot.snapshot_id}')" 
                            title="Restaurer ce snapshot">
                        <i class="fas fa-undo"></i> Rollback
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="deleteSnapshot('${snapshot.snapshot_id}')" 
                            title="Supprimer ce snapshot">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
            
            <div class="mt-2">
                <small class="text-light"><strong>Contenu:</strong></small><br>
                ${content.themes && content.themes.length > 0 ? `<span class="badge bg-info me-1"><i class="fas fa-palette me-1"></i>${content.themes.length} thème(s)</span>` : ''}
                ${content.plugins && content.plugins.length > 0 ? `<span class="badge bg-primary me-1"><i class="fas fa-plug me-1"></i>${content.plugins.length} plugin(s)</span>` : ''}
                ${content.git_directories && content.git_directories.length > 0 ? `<span class="badge bg-warning me-1"><i class="fab fa-git-alt me-1"></i>${content.git_directories.length} dossier(s) Git</span>` : ''}
                ${content.has_database ? '<span class="badge bg-success me-1"><i class="fas fa-database me-1"></i>Base de données</span>' : ''}
                ${content.config_files && content.config_files.length > 0 ? `<span class="badge bg-secondary me-1"><i class="fas fa-cog me-1"></i>Config</span>` : ''}
            </div>
        </div>
    `;
}

/**
 * Affiche le formulaire de création de snapshot
 */
async function showCreateSnapshotForm() {
    console.log('[Snapshots] showCreateSnapshotForm called');
    
    try {
        // Générer une description par défaut
        const now = new Date();
        const dateStr = now.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
        const timeStr = now.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
        const defaultDescription = `Snapshot du ${dateStr} à ${timeStr}`;
        
        // Récupérer les éléments
        const createForm = document.getElementById('create-snapshot-form');
        const snapshotsList = document.getElementById('snapshots-list');
        const btnCreate = document.getElementById('btn-create-snapshot');
        const descriptionInput = document.getElementById('snapshot-description');
        
        console.log('[Snapshots] Elements found:', {
            createForm: !!createForm,
            snapshotsList: !!snapshotsList,
            btnCreate: !!btnCreate,
            descriptionInput: !!descriptionInput
        });
        
        // Masquer la liste et le bouton, afficher le formulaire
        if (snapshotsList) snapshotsList.style.display = 'none';
        if (btnCreate) btnCreate.style.display = 'none';
        if (createForm) {
            createForm.style.display = 'block';
            console.log('[Snapshots] Form displayed');
        }
        
        // Remplir la description
        if (descriptionInput) {
            descriptionInput.value = defaultDescription;
            descriptionInput.select();
        }
        
        // Charger le preview
        await loadSnapshotFilesPreview();
        
        console.log('[Snapshots] Form setup complete');
    } catch (error) {
        console.error('[Snapshots] Error:', error);
    }
}

/**
 * Charge la prévisualisation des fichiers qui seront inclus dans le snapshot
 */
async function loadSnapshotFilesPreview() {
    const previewDiv = document.getElementById('snapshot-files-preview');
    
    previewDiv.innerHTML = `
        <div class="text-center">
            <span class="spinner-border spinner-border-sm text-light" role="status"></span>
            <span class="text-light ms-2">Analyse du projet...</span>
        </div>
    `;
    
    try {
        // Appeler l'API pour obtenir les fichiers qui seront inclus
        const response = await fetch(`/snapshots/preview/${currentSnapshotProject}`);
        const result = await response.json();
        
        if (result.success) {
            let html = '';
            
            // Section Base de données (toujours incluse)
            html += `
                <div class="snapshot-info-section">
                    <div class="d-flex align-items-center mb-2">
                        <i class="fas fa-database text-success fs-4 me-3"></i>
                        <div>
                            <h6 class="mb-0 text-light">Base de données</h6>
                        </div>
                        <i class="fas fa-check-circle text-success ms-auto"></i>
                    </div>
                </div>
            `;
            
            // Dossiers Git si présents
            if (result.git_directories && result.git_directories.length > 0) {
                html += `
                    <div class="snapshot-info-section">
                        <div class="d-flex align-items-center mb-2">
                            <i class="fab fa-git-alt text-warning fs-4 me-3"></i>
                            <div>
                                <h6 class="mb-0 text-light">Dossiers Git (${result.git_directories.length})</h6>
                                <small class="text-muted">Repositories versionnés</small>
                            </div>
                            <i class="fas fa-check-circle text-success ms-auto"></i>
                        </div>
                    </div>
                `;
            }
            
            // Options de snapshot (checkboxes)
            html += `
                <div class="snapshot-options">
                    <h6 class="text-light mb-3"><i class="fas fa-sliders-h me-2"></i>Options du snapshot</h6>
                    
                    <div class="snapshot-option-item">
                        <input type="checkbox" id="include-themes" checked>
                        <label for="include-themes">
                            <i class="fas fa-palette me-2"></i>
                            <span>Inclure les thèmes ${result.themes && result.themes.length > 0 ? `(${result.themes.length})` : ''}</span>
                        </label>
                    </div>
                    
                    <div class="snapshot-option-item">
                        <input type="checkbox" id="include-plugins" checked>
                        <label for="include-plugins">
                            <i class="fas fa-plug me-2"></i>
                            <span>Inclure les plugins ${result.plugins && result.plugins.length > 0 ? `(${result.plugins.length})` : ''}</span>
                        </label>
                    </div>
                    
                    <div class="snapshot-option-item">
                        <input type="checkbox" id="include-languages" checked>
                        <label for="include-languages">
                            <i class="fas fa-language me-2"></i>
                            <span>Inclure les fichiers de langue</span>
                        </label>
                    </div>
                    
                    <div class="snapshot-option-item">
                        <input type="checkbox" id="include-uploads" ${result.uploads_status === 'available' ? 'checked' : ''}>
                        <label for="include-uploads">
                            <i class="fas fa-images me-2"></i>
                            <span>Inclure les uploads ${result.uploads_status === 'empty' ? '(dossier vide)' : result.uploads_status === 'too_large' ? `(trop volumineux: ${result.uploads_size_mb} MB)` : result.uploads_status === 'unavailable' ? '(non disponible)' : ''}</span>
                        </label>
                    </div>
                </div>
            `;
            
            previewDiv.innerHTML = html;
            
        } else {
            // Afficher un message d'information même en cas d'erreur API
            previewDiv.innerHTML = `
                <div class="alert alert-info mb-2">
                    <i class="fas fa-info-circle me-2"></i>
                    <strong>Le snapshot incluera :</strong>
                </div>
                <div class="snapshot-section">
                    <h6><i class="fas fa-palette me-2 text-info"></i>Tous les thèmes WordPress</h6>
                    <h6><i class="fas fa-plug me-2 text-primary"></i>Tous les plugins WordPress</h6>
                    <h6><i class="fas fa-database me-2 text-success"></i>Export de la base de données</h6>
                    <h6><i class="fas fa-cog me-2 text-secondary"></i>Fichiers de configuration</h6>
                </div>
                <div class="alert alert-warning mb-0 mt-2">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    Impossible d'obtenir les détails (${result.message || 'Erreur inconnue'}), mais le snapshot sera créé avec tous les éléments ci-dessus.
                </div>
            `;
        }
    } catch (error) {
        console.error('Erreur chargement preview:', error);
        // Afficher un message générique mais ne pas empêcher la création
        previewDiv.innerHTML = `
            <div class="alert alert-info mb-2">
                <i class="fas fa-info-circle me-2"></i>
                <strong>Le snapshot incluera :</strong>
            </div>
            <div class="snapshot-section">
                <ul class="list-unstyled mb-0">
                    <li><i class="fas fa-palette me-2 text-info"></i>Tous les thèmes WordPress</li>
                    <li><i class="fas fa-plug me-2 text-primary"></i>Tous les plugins WordPress</li>
                    <li><i class="fas fa-database me-2 text-success"></i>Export de la base de données</li>
                    <li><i class="fas fa-cog me-2 text-secondary"></i>Fichiers de configuration</li>
                </ul>
            </div>
        `;
    }
}

/**
 * Cache le formulaire de création de snapshot
 */
function hideCreateSnapshotForm() {
    const createForm = document.getElementById('create-snapshot-form');
    const snapshotsList = document.getElementById('snapshots-list');
    const btnCreate = document.getElementById('btn-create-snapshot');
    
    if (createForm) createForm.style.display = 'none';
    if (snapshotsList) snapshotsList.style.display = 'block';
    if (btnCreate) btnCreate.style.display = 'inline-block';
}

/**
 * Crée un nouveau snapshot
 */
async function createSnapshot() {
    const description = document.getElementById('snapshot-description').value.trim();
    
    // Récupérer les options cochées
    const includeThemes = document.getElementById('include-themes')?.checked ?? true;
    const includePlugins = document.getElementById('include-plugins')?.checked ?? true;
    const includeLanguages = document.getElementById('include-languages')?.checked ?? true;
    const includeUploads = document.getElementById('include-uploads')?.checked ?? false;
    
    try {
        const response = await fetch(`/snapshots/create/${currentSnapshotProject}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                description,
                options: {
                    include_themes: includeThemes,
                    include_plugins: includePlugins,
                    include_languages: includeLanguages,
                    include_uploads: includeUploads
                }
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast(`Snapshot créé avec succès! ID: ${result.snapshot_id} - Taille: ${result.metadata.archive_size_mb} MB`, 'success');
            hideCreateSnapshotForm();
            loadSnapshotsList();
        } else {
            showToast(`Erreur: ${result.message}`, 'error');
        }
        
    } catch (error) {
        console.error('Erreur création snapshot:', error);
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

/**
 * Restaure un snapshot
 */
async function rollbackSnapshot(snapshotId) {
    const confirmed = confirm(
        '⚠️ ATTENTION: Cette action va restaurer les fichiers à leur état au moment du snapshot.\n\n' +
        'Les modifications non sauvegardées seront perdues.\n\n' +
        'Continuer ?'
    );
    
    if (!confirmed) {
        return;
    }
    
    try {
        // Fermer la modale des snapshots
        const snapshotsModal = bootstrap.Modal.getInstance(document.getElementById('snapshotsModal'));
        if (snapshotsModal) {
            snapshotsModal.hide();
        }
        
        // Ouvrir la modale des logs de rollback
        setTimeout(() => {
            if (typeof showRollbackLogsModal === 'function') {
                showRollbackLogsModal();
            }
        }, 300);
        
        const response = await fetch(`/snapshots/rollback/${snapshotId}`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showSuccess(`Snapshot restauré avec succès! ${result.files_restored.length} fichiers restaurés`, 6000);
            loadSnapshotsList();
        } else {
            showError(`Erreur: ${result.message}`);
        }
        
    } catch (error) {
        console.error('Erreur rollback:', error);
        showError(`Erreur: ${error.message}`);
    }
}

/**
 * Supprime un snapshot
 */
async function deleteSnapshot(snapshotId) {
    const confirmed = confirm(
        '⚠️ Supprimer ce snapshot définitivement ?\n\n' +
        'Cette action est irréversible.'
    );
    
    if (!confirmed) {
        return;
    }
    
    try {
        const response = await fetch(`/snapshots/delete/${snapshotId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast('Snapshot supprimé avec succès', 'success');
            loadSnapshotsList();
        } else {
            showToast(`Erreur: ${result.message}`, 'error');
        }
        
    } catch (error) {
        console.error('Erreur suppression:', error);
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

// Exposer les fonctions globalement pour qu'elles soient accessibles depuis les onclick
window.openSnapshotsModal = openSnapshotsModal;
window.showCreateSnapshotForm = showCreateSnapshotForm;
window.hideCreateSnapshotForm = hideCreateSnapshotForm;
window.createSnapshot = createSnapshot;
window.rollbackSnapshot = rollbackSnapshot;
window.deleteSnapshot = deleteSnapshot;

// Log de confirmation du chargement
console.log('[Snapshots] snapshot-manager.js loaded, functions exported:', {
    openSnapshotsModal: typeof window.openSnapshotsModal,
    showCreateSnapshotForm: typeof window.showCreateSnapshotForm,
    hideCreateSnapshotForm: typeof window.hideCreateSnapshotForm,
    createSnapshot: typeof window.createSnapshot,
    rollbackSnapshot: typeof window.rollbackSnapshot,
    deleteSnapshot: typeof window.deleteSnapshot
});

// Initialiser les event listeners quand le DOM est prêt
document.addEventListener('DOMContentLoaded', function() {
    console.log('[Snapshots] Initializing event listeners...');
    
    // Event listener pour le bouton "Créer un nouveau snapshot"
    const btnCreateSnapshot = document.getElementById('btn-create-snapshot');
    if (btnCreateSnapshot) {
        btnCreateSnapshot.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('[Snapshots] Button "Créer un nouveau snapshot" clicked');
            showCreateSnapshotForm();
        });
        console.log('[Snapshots] Event listener attached to #btn-create-snapshot');
    } else {
        console.warn('[Snapshots] Button #btn-create-snapshot not found in DOM');
    }
    
    // Event listener pour le bouton "Annuler"
    const btnCancelSnapshot = document.getElementById('btn-cancel-snapshot');
    if (btnCancelSnapshot) {
        btnCancelSnapshot.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('[Snapshots] Button "Annuler" clicked');
            hideCreateSnapshotForm();
        });
        console.log('[Snapshots] Event listener attached to #btn-cancel-snapshot');
    }
    
    // Event listener pour le bouton "Créer le snapshot"
    const btnSaveSnapshot = document.getElementById('btn-save-snapshot');
    if (btnSaveSnapshot) {
        btnSaveSnapshot.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('[Snapshots] Button "Créer le snapshot" clicked');
            createSnapshot();
        });
        console.log('[Snapshots] Event listener attached to #btn-save-snapshot');
    }
    
    // Écouter les événements de rollback via socket.io
    if (typeof socket !== 'undefined' && socket) {
        socket.on('rollback_progress', function(data) {
            console.log('[Rollback] Progress event:', data);
            
            if (data.project) {
                currentRollbackProject = data.project;
            }
            
            if (data.message) {
                addRollbackLog(data.message, data.progress, data.status);
            }
            
            // Ouvrir automatiquement la modale au début
            if (!rollbackLogsModalInstance && data.progress <= 10) {
                setTimeout(() => {
                    try {
                        showRollbackLogsModal();
                    } catch (error) {
                        console.error('[Rollback] Erreur ouverture modale:', error);
                    }
                }, 500);
            }
        });
    }
});

/**
 * Ajouter un log à la modale de rollback
 */
function addRollbackLog(message, progress, status) {
    const timestamp = new Date().toLocaleTimeString('fr-FR');
    const logEntry = {
        timestamp,
        message,
        progress,
        status
    };
    
    rollbackLogsBuffer.push(logEntry);
    console.log('[Rollback] Log ajouté:', message);
    
    // Si la modale est ouverte, mettre à jour l'affichage
    const logsModal = document.getElementById('rollbackLogsModal');
    if (logsModal && logsModal.classList.contains('show')) {
        updateRollbackLogsDisplay();
    }
}

/**
 * Mettre à jour l'affichage des logs de rollback
 */
function updateRollbackLogsDisplay() {
    const logsContent = document.getElementById('rollback-logs-content');
    if (!logsContent) {
        console.warn('[Rollback] Élément rollback-logs-content non trouvé');
        return;
    }
    
    let html = '';
    rollbackLogsBuffer.forEach(log => {
        let color = '#d4d4d4';
        let icon = '📊';
        
        if (log.status === 'complete') {
            color = '#4ec9b0';
            icon = '✅';
        } else if (log.status === 'error') {
            color = '#f48771';
            icon = '❌';
        } else if (log.status === 'warning') {
            color = '#ce9178';
            icon = '⚠️';
        } else if (log.status === 'processing') {
            color = '#6a9fb5';
            icon = '🔄';
        }
        
        const progressBar = log.progress ? ` [${log.progress}%]` : '';
        html += `<div style="color: ${color}; margin-bottom: 4px;">[${log.timestamp}]${progressBar} ${icon} ${log.message}</div>`;
    });
    
    logsContent.innerHTML = html || '<div style="color: #6a9fb5;">📡 Aucun log disponible</div>';
    logsContent.scrollTop = logsContent.scrollHeight;
}

/**
 * Afficher la modale des logs de rollback
 */
function showRollbackLogsModal() {
    console.log('[Rollback] showRollbackLogsModal appelée');
    
    if (typeof bootstrap === 'undefined' || !bootstrap.Modal) {
        console.error('[Rollback] Bootstrap non disponible');
        setTimeout(() => {
            if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
                showRollbackLogsModal();
            }
        }, 500);
        return;
    }
    
    const modalElement = document.getElementById('rollbackLogsModal');
    if (!modalElement) {
        console.error('[Rollback] Element rollbackLogsModal non trouvé');
        return;
    }
    
    // Si la modale est déjà ouverte, juste mettre à jour
    if (modalElement.classList.contains('show')) {
        updateRollbackLogsDisplay();
        return;
    }
    
    try {
        if (rollbackLogsModalInstance) {
            try {
                rollbackLogsModalInstance.dispose();
            } catch (e) {}
            rollbackLogsModalInstance = null;
        }
        
        const existingInstance = bootstrap.Modal.getInstance(modalElement);
        if (existingInstance) {
            rollbackLogsModalInstance = existingInstance;
        } else {
            rollbackLogsModalInstance = new bootstrap.Modal(modalElement, {
                backdrop: 'static',
                keyboard: true
            });
        }
        
        modalElement.removeEventListener('hidden.bs.modal', onRollbackModalHidden);
        modalElement.addEventListener('hidden.bs.modal', onRollbackModalHidden);
        
        const projectNameSpan = document.getElementById('rollback-logs-project-name');
        if (projectNameSpan) {
            projectNameSpan.textContent = currentRollbackProject || '-';
        }
        
        updateRollbackLogsDisplay();
        rollbackLogsModalInstance.show();
        console.log('[Rollback] Modale affichée');
        
    } catch (error) {
        console.error('[Rollback] Erreur lors de l\'affichage de la modale:', error);
    }
}

function onRollbackModalHidden() {
    console.log('[Rollback] Modale fermée');
    rollbackLogsModalInstance = null;
}

/**
 * Effacer les logs de rollback
 */
function clearRollbackLogs() {
    if (confirm('Êtes-vous sûr de vouloir effacer tous les logs ?')) {
        rollbackLogsBuffer = [];
        updateRollbackLogsDisplay();
    }
}

// Exposer les fonctions globalement
window.showRollbackLogsModal = showRollbackLogsModal;
window.clearRollbackLogs = clearRollbackLogs;
window.addRollbackLog = addRollbackLog;
