/**
 * Gestion du clonage de projets
 */

let currentCloneSource = null;

/**
 * Ouvre la modale de clonage
 */
function openCloneModal(projectName) {
    // Détecter si c'est une instance dev
    const projectCard = document.querySelector(`[data-project-name="${projectName}"]`);
    const isDevInstance = projectCard && projectCard.dataset.isDevInstance === 'true';
    const currentInstance = projectCard ? projectCard.dataset.currentInstance : '';
    
    // Si instance dev sélectionnée, cloner depuis le projet parent
    let sourceProjectName = projectName;
    let showDevWarning = false;
    
    if (isDevInstance && currentInstance) {
        // C'est une instance dev, on va cloner le projet parent
        sourceProjectName = projectName;
        showDevWarning = true;
        console.log(`[Clone] Instance dev détectée (${currentInstance}), clonage depuis le projet parent: ${sourceProjectName}`);
    }
    
    currentCloneSource = sourceProjectName;
    
    // Mettre à jour le titre
    document.getElementById('clone-source-name').textContent = sourceProjectName;
    
    // Reset du formulaire
    document.getElementById('clone-project-form').reset();
    
    // Titre par défaut
    const defaultName = `${sourceProjectName}-clone`;
    document.getElementById('clone-target-name').value = defaultName;
    
    // Options par défaut
    document.getElementById('clone-database').checked = true;
    document.getElementById('clone-plugins').checked = true;
    document.getElementById('clone-themes').checked = true;
    document.getElementById('clone-uploads').checked = false;
    document.getElementById('clone-progress').style.display = 'none';
    
    // Afficher/masquer le message d'avertissement pour les instances dev
    let warningDiv = document.getElementById('clone-dev-warning');
    if (!warningDiv) {
        // Créer le div d'avertissement s'il n'existe pas
        warningDiv = document.createElement('div');
        warningDiv.id = 'clone-dev-warning';
        warningDiv.className = 'alert alert-info mb-3';
        warningDiv.style.display = 'none';
        
        // Insérer avant le formulaire
        const form = document.getElementById('clone-project-form');
        if (form) {
            form.parentNode.insertBefore(warningDiv, form);
        }
    }
    
    if (showDevWarning) {
        warningDiv.replaceChildren();
        const icon = document.createElement('i');
        icon.className = 'fas fa-info-circle me-2';
        warningDiv.appendChild(icon);
        const strongTitle = document.createElement('strong');
        strongTitle.textContent = 'Instance de développement détectée';
        warningDiv.appendChild(strongTitle);
        warningDiv.appendChild(document.createElement('br'));
        warningDiv.appendChild(document.createTextNode("Le clonage se fera depuis l'instance principale "));
        const strongSource = document.createElement('strong');
        strongSource.textContent = sourceProjectName;
        warningDiv.appendChild(strongSource);
        warningDiv.appendChild(document.createTextNode(", pas depuis l'instance dev "));
        const strongInstance = document.createElement('strong');
        strongInstance.textContent = currentInstance;
        warningDiv.appendChild(strongInstance);
        warningDiv.appendChild(document.createTextNode('.'));
        warningDiv.style.display = 'block';
    } else {
        warningDiv.style.display = 'none';
    }
    
    // Valider le nom par défaut
    validateCloneName(defaultName);
    
    // Afficher la modale
    const modal = new bootstrap.Modal(document.getElementById('cloneModal'));
    modal.show();
    
    // Focus sur l'input
    setTimeout(() => {
        document.getElementById('clone-target-name').select();
    }, 500);
}

/**
 * Valide le nom du projet en temps réel
 */
async function validateCloneName(name) {
    const validationDiv = document.getElementById('clone-name-validation');

    // Helper: build <span class="..."><i class="icon"></i> <text> <strong>?</strong></span>
    function buildMessage(spanClass, iconClass, text, strongText) {
        const span = document.createElement('span');
        span.className = spanClass;
        if (iconClass) {
            const i = document.createElement('i');
            i.className = iconClass;
            span.appendChild(i);
            span.appendChild(document.createTextNode(' '));
        }
        span.appendChild(document.createTextNode(text));
        if (strongText) {
            span.appendChild(document.createTextNode(' '));
            const strong = document.createElement('strong');
            strong.textContent = strongText;
            span.appendChild(strong);
        }
        validationDiv.replaceChildren(span);
    }

    if (!name || name.length < 2) {
        buildMessage('text-muted', null, 'Entrez un nom (min. 2 caractères)');
        return false;
    }

    try {
        const response = await fetch(`/validate-name/${encodeURIComponent(name)}`);
        const result = await response.json();

        if (result.valid) {
            buildMessage('text-success', 'fas fa-check-circle', 'Nom disponible:', result.safe_name);
            return true;
        } else {
            buildMessage('text-danger', 'fas fa-times-circle', result.message || '');
            return false;
        }
    } catch (error) {
        buildMessage('text-danger', null, 'Erreur de validation');
        return false;
    }
}

/**
 * Soumet le formulaire de clonage
 */
async function submitCloneForm(event) {
    event.preventDefault();
    
    const targetName = document.getElementById('clone-target-name').value.trim();
    const cloneDatabase = document.getElementById('clone-database').checked;
    const clonePlugins = document.getElementById('clone-plugins').checked;
    const cloneThemes = document.getElementById('clone-themes').checked;
    const cloneUploads = document.getElementById('clone-uploads').checked;
    
    if (!targetName) {
        showToast('Veuillez entrer un nom pour le nouveau projet', 'warning');
        return;
    }
    
    // Valider le nom
    const isValid = await validateCloneName(targetName);
    if (!isValid) {
        return;
    }
    
    // Désactiver le bouton et afficher la progress
    const submitBtn = document.getElementById('clone-submit-btn');
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Clonage...';
    document.getElementById('clone-progress').style.display = 'block';
    
    try {
        const response = await fetch(`/clone/${currentCloneSource}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                target_name: targetName,
                clone_database: cloneDatabase,
                clone_plugins: clonePlugins,
                clone_themes: cloneThemes,
                clone_uploads: cloneUploads
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            // Fermer la modale
            const modal = bootstrap.Modal.getInstance(document.getElementById('cloneModal'));
            modal.hide();
            
            // Afficher notification de succès (toujours via taskManager, pas d'alerte)
            if (window.taskManager && typeof window.taskManager.createTask === 'function') {
                window.taskManager.createTask({
                    name: `Clonage ${currentCloneSource} → ${result.project_info.name}`,
                    description: 'Projet cloné avec succès',
                    projectName: result.project_info.name,
                    status: 'completed',
                    autoRemove: false
                });
            }
            
            // Recharger la liste des projets
            setTimeout(() => {
                if (typeof window.loadProjects === 'function') {
                    window.loadProjects();
                } else if (typeof loadProjects === 'function') {
                    loadProjects();
                } else {
                    location.reload();
                }
            }, 1000);
        } else {
            showToast(`Erreur lors du clonage: ${result.message}`, 'error');
        }
        
    } catch (error) {
        console.error('Erreur clonage:', error);
        showToast(`Erreur: ${error.message}`, 'error');
    } finally {
        // Réactiver le bouton
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-clone me-2"></i>Cloner le projet';
        document.getElementById('clone-progress').style.display = 'none';
    }
}

/**
 * Initialisation
 */
document.addEventListener('DOMContentLoaded', function() {
    // Validation en temps réel
    const targetNameInput = document.getElementById('clone-target-name');
    if (targetNameInput) {
        let validateTimeout;
        targetNameInput.addEventListener('input', function() {
            clearTimeout(validateTimeout);
            validateTimeout = setTimeout(() => {
                validateCloneName(this.value);
            }, 500);
        });
    }
    
    // Soumission du formulaire
    const cloneForm = document.getElementById('clone-project-form');
    if (cloneForm) {
        cloneForm.addEventListener('submit', submitCloneForm);
    }
});

