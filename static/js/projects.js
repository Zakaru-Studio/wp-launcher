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
 * Confirme et exécute la suppression d'un projet
 * @param {string} projectName - Nom du projet
 */
async function confirmDeleteProject(projectName) {
    try {
        const confirmButton = document.getElementById('confirm-delete');
        confirmButton.classList.add('loading');
        
        // Trouver et marquer visuellement l'élément comme étant supprimé
        const projectElements = document.querySelectorAll('.project-item');
        let projectElement = null;
        
        for (const element of projectElements) {
            const title = element.querySelector('.project-title');
            if (title && title.textContent.trim() === projectName) {
                projectElement = element;
                break;
            }
        }
        
        // Marquer visuellement l'élément comme étant supprimé
        if (projectElement) {
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
        
        const response = await makeRequest(`/delete_project/${projectName}`, 'DELETE');
        
        if (response.success) {
            showSuccess(`Projet ${projectName} supprimé avec succès`);
            bootstrap.Modal.getInstance(document.getElementById('deleteModal')).hide();
            
            // Animation de suppression de l'élément
            if (projectElement) {
                projectElement.style.transform = 'scale(0.8)';
                projectElement.style.opacity = '0';
                
                setTimeout(() => {
                    // Supprimer l'élément du DOM
                    if (projectElement.parentNode) {
                        projectElement.parentNode.removeChild(projectElement);
                    }
                    
                    // Recharger la liste complète pour s'assurer de la cohérence
                    loadProjects();
                }, 300);
            } else {
                // Si l'élément n'a pas été trouvé, recharger directement
                loadProjects();
            }
        } else {
            showError(response.message || 'Erreur lors de la suppression');
            
            // Restaurer l'élément en cas d'erreur
            if (projectElement) {
                projectElement.style.opacity = '1';
                projectElement.style.pointerEvents = 'auto';
                const overlay = projectElement.querySelector('div[style*="position: absolute"]');
                if (overlay) {
                    overlay.remove();
                }
            }
        }
    } catch (error) {
        console.error('Erreur suppression:', error);
        showError('Erreur lors de la suppression du projet');
        
        // Restaurer l'élément en cas d'erreur
        const projectElements = document.querySelectorAll('.project-item');
        for (const element of projectElements) {
            const title = element.querySelector('.project-title');
            if (title && title.textContent.trim() === projectName) {
                element.style.opacity = '1';
                element.style.pointerEvents = 'auto';
                const overlay = element.querySelector('div[style*="position: absolute"]');
                if (overlay) {
                    overlay.remove();
                }
                break;
            }
        }
    } finally {
        const confirmButton = document.getElementById('confirm-delete');
        confirmButton.classList.remove('loading');
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
 * Sauvegarde le nouvel hostname
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
 * Fonction pour mettre à jour la base de données
 * @param {string} projectName - Nom du projet
 */
function updateDatabase(projectName) {
    const modal = new bootstrap.Modal(document.getElementById('updateDbModal'));
    
    // Gérer la soumission du formulaire
    const form = document.getElementById('update-db-form');
    form.onsubmit = (e) => {
        e.preventDefault();
        uploadDatabase(projectName, new FormData(form));
    };
    
    modal.show();
}

/**
 * Upload et import de la base de données
 * @param {string} projectName - Nom du projet
 * @param {FormData} formData - Données du formulaire
 */
async function uploadDatabase(projectName, formData) {
    try {
        const submitButton = document.querySelector('#update-db-form button[type="submit"]');
        submitButton.classList.add('loading');
        
        const response = await fetch(`/update_database/${projectName}`, {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success) {
            showSuccess('Import de base de données démarré');
            bootstrap.Modal.getInstance(document.getElementById('updateDbModal')).hide();
        } else {
            showError(result.message || 'Erreur lors de l\'import');
        }
    } catch (error) {
        console.error('Erreur import DB:', error);
        showError('Erreur lors de l\'import de la base de données');
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
        const button = document.querySelector(`button[onclick="addNextjs('${projectName}')"]`);
        if (button) {
            button.classList.add('loading');
            button.innerHTML = '';
        }

        const response = await makeRequest(`/add_nextjs/${projectName}`, 'POST');
        
        if (response.success) {
            showSuccess(`Next.js ajouté au projet ${projectName}`);
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
        const button = document.querySelector(`button[onclick="removeNextjs('${projectName}')"]`);
        if (button) {
            button.classList.add('loading');
            button.innerHTML = '';
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