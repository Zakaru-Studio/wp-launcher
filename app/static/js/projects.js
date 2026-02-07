/**
 * Fonctions spécifiques pour les projets WordPress
 * Complémente project-management.js avec des fonctions spécialisées
 */




/**
 * Fonction pour ajouter Next.js à un projet
 * @param {string} projectName - Nom du projet
 */
async function addNextjs(projectName) {
    try {
        if (!confirm(`Ajouter Next.js au projet ${projectName} ?`)) {
            return;
        }
        
        const response = await makeRequest(`/add_nextjs/${projectName}`, { method: 'POST' });
        
        if (response.success) {
            if (typeof showSuccess === 'function') {
                showSuccess(`Next.js ajouté au projet ${projectName} sur le port ${response.nextjs_port}`);
            }
            if (typeof loadProjects === 'function') {
                loadProjects(); // Recharger la liste
            }
        } else {
            if (typeof showError === 'function') {
                showError(response.message || 'Erreur lors de l\'ajout de Next.js');
            }
        }
    } catch (error) {
        if (typeof showError === 'function') {
            showError('Erreur lors de l\'ajout de Next.js');
        }
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
        
        const response = await makeRequest(`/remove_nextjs/${projectName}`, { method: 'POST' });
        
        if (response.success) {
            if (typeof showSuccess === 'function') {
                showSuccess(`Next.js supprimé du projet ${projectName}`);
            }
            if (typeof loadProjects === 'function') {
                loadProjects(); // Recharger la liste
            }
        } else {
            if (typeof showError === 'function') {
                showError(response.message || 'Erreur lors de la suppression de Next.js');
            }
        }
    } catch (error) {
        if (typeof showError === 'function') {
            showError('Erreur lors de la suppression de Next.js');
        }
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
        
        if (typeof showLoader === 'function') {
            showLoader('Import du fichier SQL local en cours...');
        }
        
        const response = await fetch(`/import_local_sql/${projectName}`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (typeof showSuccess === 'function') {
                showSuccess(`Fichier SQL local importé avec succès: ${result.file_imported}`);
            }
            // Rafraîchir la liste des projets
            if (typeof loadProjects === 'function') {
                setTimeout(loadProjects, 2000);
            }
        } else {
            if (typeof showError === 'function') {
                showError(result.message || 'Erreur lors de l\'import du fichier SQL local');
            }
        }
    } catch (error) {
        if (typeof showError === 'function') {
            showError('Erreur lors de l\'import du fichier SQL local');
        }
    } finally {
        if (typeof hideLoader === 'function') {
            hideLoader();
        }
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
            return result.files;
        } else {
            return [];
        }
    } catch (error) {
        return [];
    }
}


// Fonction d'import ultra-rapide - appelée par l'event listener du formulaire
function doFastImportDatabase(projectName) {
    // Créer une tâche dans le gestionnaire
    const task = startDatabaseTask(projectName, 'import_db');
    if (!task) return; // Tâche déjà en cours
    
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
        taskManager.completeTask(task.id, 'Aucun fichier sélectionné', false);
        return;
    }
    
    formData.append('db_file', file);
    
    // Mettre à jour la tâche
    taskManager.updateTask(task.id, { 
        message: `Import de la base de données en cours...`,
        details: `Fichier: ${file.name}`,
        progress: 10
    });
    
    // Définir le projet en cours d'import pour la modale
    window.currentImportProject = projectName;
    
    // Bloquer l'accès au site pendant l'import
    if (typeof projectsImporting !== 'undefined') {
        projectsImporting.add(projectName);
        console.log('🔒 Import démarré, accès bloqué pour:', projectName);
        // Recharger les projets pour mettre à jour les boutons
        if (typeof loadProjects === 'function') {
            loadProjects();
        }
    }
    
    // Réinitialiser le buffer de logs
    if (window.importLogsBuffer) {
        window.importLogsBuffer.length = 0;
    } else {
        window.importLogsBuffer = [];
    }
    
    // Ajouter le premier log
    if (typeof window.addImportLog === 'function') {
        window.addImportLog(`🚀 Démarrage de l'import pour ${projectName}`, 0, 'starting');
        window.addImportLog(`📁 Fichier: ${file.name}`, 0, 'info');
    }
    
    // OUVRIR LA MODALE IMMÉDIATEMENT
    console.log('🔔 Ouverture de la modale de logs pour:', projectName);
    if (typeof window.showImportLogsModal === 'function') {
        try {
            window.showImportLogsModal();
            console.log('✅ Modale ouverte avec succès');
        } catch (error) {
            console.error('❌ Erreur ouverture modale:', error);
        }
    } else {
        console.error('❌ window.showImportLogsModal n\'est pas définie');
    }
    
    // Envoyer la requête d'import
    fetch(`/fast_import_database/${projectName}`, {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Ne pas compléter la tâche ici, les événements Socket.IO le feront
            console.log('📡 Import démarré, en attente des événements Socket.IO...');
            if (typeof window.addImportLog === 'function') {
                window.addImportLog('📡 Requête envoyée, import en cours...', 5, 'importing');
            }
        } else {
            taskManager.completeTask(task.id, data.message || 'Erreur lors de l\'import', false);
            if (typeof window.addImportLog === 'function') {
                window.addImportLog(`❌ Erreur: ${data.message || 'Erreur inconnue'}`, 0, 'error');
            }
        }
    })
    .catch(error => {
        taskManager.completeTask(task.id, 'Erreur lors de l\'import: ' + error.message, false);
        if (typeof window.addImportLog === 'function') {
            window.addImportLog(`❌ Erreur réseau: ${error.message}`, 0, 'error');
        }
    });
}

// Fonction pour ouvrir le modal d'import
function openImportModal(projectName) {
    // Stocker le nom du projet dans le dataset du formulaire
    document.getElementById('update-db-form').dataset.projectName = projectName;
    
    // Réinitialiser le champ de fichier
    const fileInput = document.getElementById('db-file');
    if (fileInput) {
        fileInput.value = '';
    }
    
    // Ouvrir le modal
    const modal = new bootstrap.Modal(document.getElementById('updateDbModal'));
    modal.show();
}

// Modifier la fonction updateDatabase pour utiliser le nouveau système
function updateDatabase(projectName) {
    openImportModal(projectName);
}

/**
 * Fonction pour exporter la base de données d'un projet
 * @param {string} projectName - Nom du projet
 */
async function exportDatabase(projectName) {
    // Créer une tâche dans le gestionnaire
    const task = startDatabaseTask(projectName, 'export_db');
    if (!task) return; // Tâche déjà en cours

    try {
        // Mettre à jour la tâche
        taskManager.updateTask(task.id, { 
            message: `Préparation de l'export de la base de données...`,
            progress: 25
        });
        
        const response = await fetch(`/export_database/${projectName}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        }).then(res => res.json());
        
        if (response.success) {
            // Mettre à jour la progression
            taskManager.updateTask(task.id, { 
                message: `Génération du fichier d'export...`,
                progress: 75
            });

            // Créer un lien de téléchargement temporaire
            const downloadUrl = response.download_url;
            const fileName = response.filename || `${projectName}_export.sql`;
            
            // Créer un élément de téléchargement
            const downloadLink = document.createElement('a');
            downloadLink.href = downloadUrl;
            downloadLink.download = fileName;
            downloadLink.style.display = 'none';
            
            // Ajouter au DOM, cliquer et supprimer
            document.body.appendChild(downloadLink);
            downloadLink.click();
            document.body.removeChild(downloadLink);
            
            taskManager.completeTask(task.id, `Base de données exportée : ${fileName}`, true);
        } else {
            taskManager.completeTask(task.id, response.message || 'Erreur lors de l\'export de la base de données', false);
        }
    } catch (error) {
        taskManager.completeTask(task.id, 'Erreur lors de l\'export de la base de données', false);
    }
}

// Gestionnaire du formulaire d'import
document.getElementById('update-db-form').addEventListener('submit', function(e) {
    e.preventDefault();
    
    const projectName = this.dataset.projectName;
    if (!projectName) {
        console.error('❌ Pas de projectName dans le dataset du formulaire');
        return;
    }
    
    console.log('📤 Soumission du formulaire d\'import pour:', projectName);
    
    // Lancer l'import ultra-rapide avec ouverture de la modale
    doFastImportDatabase(projectName);
});

// La gestion du formulaire de création est maintenant dans project-management.js

// Les fonctions de rafraîchissement sont maintenant dans project-management.js 

// Initialiser le suivi du progrès au chargement de la page
// Gestion du modal de progrès d'import
document.addEventListener('DOMContentLoaded', function() {
    const progressModal = document.getElementById('importProgressModal');
    if (progressModal) {
        progressModal.addEventListener('hidden.bs.modal', function() {
            if (typeof currentImportProject !== 'undefined') {
                currentImportProject = null;
            }
            if (typeof importedTablesSet !== 'undefined') {
                importedTablesSet.clear();
            }
        });
    }
}); 