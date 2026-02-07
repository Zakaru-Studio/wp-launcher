/**
 * Instances UI Manager
 * Gestion de l'interface utilisateur pour les instances de développement
 */

class InstancesUIManager {
    constructor() {
        this.currentUser = document.body.dataset.currentUser || '';
        this.currentRole = document.body.dataset.currentRole || '';
        this.instancesCache = {}; // Cache par projet
    }
    
    // Charger et afficher les instances d'un projet
    async loadProjectInstances(projectName, dropdownElement) {
        try {
            const response = await fetch(`/api/dev-instances/by-project/${projectName}`);
            const data = await response.json();
            
            if (data.success) {
                this.instancesCache[projectName] = data.instances;
                this.renderInstancesDropdown(projectName, data.instances, dropdownElement);
            }
        } catch (error) {
            console.error('Erreur chargement instances:', error);
            dropdownElement.innerHTML = '<li class="dropdown-item text-danger"><small>Erreur de chargement</small></li>';
        }
    }
    
    // Afficher le contenu du dropdown
    renderInstancesDropdown(projectName, instances, dropdownElement) {
        const userInstances = instances.filter(i => i.owner_username === this.currentUser);
        const hasUserInstance = userInstances.length > 0;
        
        let html = '';
        
        // En-tête
        html += `<li class="dropdown-header"><strong>Instances de développement</strong></li>`;
        html += `<li><hr class="dropdown-divider"></li>`;
        
        // Instance principale (toujours affichée)
        html += `<li><a class="dropdown-item instance-item" href="#" 
            onclick="event.preventDefault(); switchToMainInstance('${projectName}');">
            <i class="fas fa-home me-2 text-success"></i>
            <span>Instance principale</span>
        </a></li>`;
        
        // Instances dev de l'utilisateur
        if (userInstances.length > 0) {
            userInstances.forEach(instance => {
                const instanceData = JSON.stringify(instance).replace(/'/g, "\\'");
                html += `<li><a class="dropdown-item instance-item" href="#"
                    onclick="event.preventDefault(); switchToDevInstance('${projectName}', '${instanceData.replace(/"/g, '&quot;')}');">
                    <i class="fas fa-laptop-code me-2 text-info"></i>
                    <span>Mon instance dev</span>
                    <span class="badge bg-info ms-2">${instance.port}</span>
                </a></li>`;
            });
        }
        
        // Autres instances (admin seulement)
        if (this.currentRole === 'admin') {
            const otherInstances = instances.filter(i => i.owner_username !== this.currentUser);
            if (otherInstances.length > 0) {
                html += `<li><hr class="dropdown-divider"></li>`;
                html += `<li class="dropdown-header"><small>Autres développeurs</small></li>`;
                otherInstances.forEach(instance => {
                    const instanceData = JSON.stringify(instance).replace(/'/g, "\\'");
                    html += `<li><a class="dropdown-item instance-item" href="#"
                        onclick="event.preventDefault(); switchToDevInstance('${projectName}', '${instanceData.replace(/"/g, '&quot;')}');">
                        <i class="fas fa-user me-2"></i>
                        <span>${instance.owner_username}</span>
                        <span class="badge bg-secondary ms-2">${instance.port}</span>
                    </a></li>`;
                });
            }
        }
        
        // Lien créer instance
        html += `<li><hr class="dropdown-divider"></li>`;
        
        if (this.currentRole === 'admin') {
            // Admin : toujours disponible
            html += `<li><a class="dropdown-item create-instance-btn" href="#" 
                onclick="event.preventDefault(); openCreateInstanceModal('${projectName}');">
                <i class="fas fa-plus-circle me-2"></i>Créer une instance
            </a></li>`;
        } else {
            // Dev : uniquement si pas d'instance existante
            if (!hasUserInstance) {
                html += `<li><a class="dropdown-item create-instance-btn" href="#" 
                    onclick="event.preventDefault(); createDevInstanceForSelf('${projectName}');">
                    <i class="fas fa-plus-circle me-2"></i>Créer mon instance
                </a></li>`;
            } else {
                html += `<li class="dropdown-item text-muted disabled">
                    <i class="fas fa-info-circle me-2"></i>
                    <small>Vous avez déjà une instance</small>
                </li>`;
            }
        }
        
        dropdownElement.innerHTML = html;
        
        // Mettre à jour le label du bouton
        this.updateInstanceButtonLabel(projectName, hasUserInstance);
    }
    
    // Mettre à jour le label du bouton
    updateInstanceButtonLabel(projectName, hasUserInstance) {
        const button = document.querySelector(`#instances-dropdown-${projectName}`);
        if (button) {
            const label = button.querySelector('.instance-label');
            if (label) {
                if (hasUserInstance) {
                    label.textContent = 'Mon instance dev';
                    button.classList.add('has-dev-instance');
                } else {
                    label.textContent = 'Instance principale';
                    button.classList.remove('has-dev-instance');
                }
            }
        }
    }
}

// Instance globale
window.instancesUIManager = new InstancesUIManager();

// Event delegation pour charger les instances au clic sur le dropdown
document.addEventListener('DOMContentLoaded', function() {
    // Utiliser l'événement show.bs.dropdown sur le document
    document.addEventListener('show.bs.dropdown', function(event) {
        // Vérifier si c'est un dropdown d'instances
        const button = event.target;
        if (button.classList.contains('instance-dropdown-btn')) {
            const dropdownMenu = button.nextElementSibling;
            if (dropdownMenu && dropdownMenu.classList.contains('instances-dropdown')) {
                const projectName = dropdownMenu.dataset.project;
                if (projectName && window.instancesUIManager) {
                    console.log('Chargement des instances pour:', projectName);
                    window.instancesUIManager.loadProjectInstances(projectName, dropdownMenu);
                }
            }
        }
    });
    
    console.log('✅ Instances UI Manager initialisé');
});

// Créer une instance pour soi-même (développeur)
async function createDevInstanceForSelf(projectName) {
    if (!confirm(`Créer votre instance de développement pour "${projectName}" ?\n\nCela va copier les fichiers et la base de données du projet parent.`)) {
        return;
    }
    
    try {
        const response = await fetch('/api/dev-instances/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ parent_project: projectName })
        });
        
        const data = await response.json();
        if (data.success) {
            alert(`Instance créée avec succès!\nURL: ${getProjectUrl(data.instance.port)}`);
            // Recharger les instances
            const dropdown = document.querySelector(`.instances-dropdown[data-project="${projectName}"]`);
            if (dropdown) {
                window.instancesUIManager.loadProjectInstances(projectName, dropdown);
            }
        } else {
            alert(`Erreur: ${data.error}`);
        }
    } catch (error) {
        alert(`Erreur: ${error.message}`);
    }
}

// Ouvrir la modale de création (admin)
function openCreateInstanceModal(projectName) {
    // Charger la liste des utilisateurs
    fetch('/admin/api/users/list')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const users = data.users || [];
                const select = document.getElementById('create-instance-user');
                select.innerHTML = users.map(u => 
                    `<option value="${u.username}">${u.username} (${u.email})</option>`
                ).join('');
                
                document.getElementById('create-instance-project').value = projectName;
                const modal = new bootstrap.Modal(document.getElementById('createInstanceModal'));
                modal.show();
            } else {
                alert('Erreur lors du chargement des utilisateurs');
            }
        })
        .catch(error => {
            alert('Erreur: ' + error.message);
        });
}

// Basculer vers l'instance principale (fonction globale)
window.switchToMainInstance = function(projectName) {
    console.log('Switch to main instance:', projectName);
    
    // Supprimer l'instance sélectionnée du sessionStorage
    sessionStorage.removeItem(`selected_instance_${projectName}`);
    
    // Recharger la page pour mettre à jour tous les composants
    window.location.reload();
}

// Basculer vers une instance dev (fonction globale)
window.switchToDevInstance = function(projectName, instanceDataStr) {
    console.log('Switch to dev instance:', projectName, instanceDataStr);
    
    // Parser les données de l'instance
    const instance = typeof instanceDataStr === 'string' ? 
        JSON.parse(instanceDataStr.replace(/&quot;/g, '"')) : instanceDataStr;
    
    console.log('Parsed instance:', instance);
    
    // Stocker dans sessionStorage pour persister après rechargement
    sessionStorage.setItem(`selected_instance_${projectName}`, JSON.stringify(instance));
    
    // Recharger la page pour mettre à jour tous les composants
    window.location.reload();
}

// Fetch le statut de l'instance et mettre à jour l'UI (fonction globale)
window.fetchInstanceStatusAndUpdate = async function(projectName, instance) {
    console.log('Fetching status for instance:', instance.name);
    try {
        // Récupérer le statut actuel de l'instance
        const response = await fetch(`/api/dev-instances/${instance.name}/status`);
        const data = await response.json();
        
        console.log('Instance status response:', data);
        
        if (data.success) {
            // Mettre à jour l'UI avec les vraies données
            if (typeof window.updateProjectCardForInstance === 'function') {
                console.log('Calling updateProjectCardForInstance with status:', data.status);
                window.updateProjectCardForInstance(projectName, instance, data.status);
            } else {
                console.error('updateProjectCardForInstance not found');
            }
        } else {
            console.error('Failed to get instance status:', data.error);
            // Fallback: mettre à jour avec statut 'stopped' par défaut
            if (typeof window.updateProjectCardForInstance === 'function') {
                window.updateProjectCardForInstance(projectName, instance, 'stopped');
            }
        }
    } catch (error) {
        console.error('Erreur fetch statut instance:', error);
        // En cas d'erreur, utiliser le statut par défaut
        if (typeof window.updateProjectCardForInstance === 'function') {
            window.updateProjectCardForInstance(projectName, instance, 'stopped');
        }
    }
}

// Mettre à jour toute l'UI du projet/instance
function updateProjectUI(projectName, data) {
    const projectCard = document.querySelector(`[data-project-name="${projectName}"]`);
    if (!projectCard) return;
    
    const isDevInstance = data.isDevInstance;

    // 1. Mettre à jour le port affiché dans le header
    const portLink = projectCard.querySelector('.project-ip-port a');
    if (portLink) {
        portLink.href = getProjectUrl(data.port);
        portLink.innerHTML = `<i class="fas fa-external-link-alt me-1"></i>${window.APP_CONFIG.host}:${data.port}`;
    }
    
    // 2. Mettre à jour les liens des services
    const wpLink = projectCard.querySelector('.btn-primary[title*="WordPress"]');
    if (wpLink) {
        wpLink.href = getProjectUrl(data.port);
    }
    
    // 3. phpMyAdmin et Mailpit (désactivés pour les instances dev)
    const pmaLink = projectCard.querySelector('.btn-info[title*="phpMyAdmin"]');
    if (pmaLink) {
        if (isDevInstance) {
            pmaLink.style.opacity = '0.5';
            pmaLink.style.pointerEvents = 'none';
            pmaLink.title = 'phpMyAdmin non disponible pour les instances dev';
        } else {
            pmaLink.href = getProjectUrl(data.ports.phpmyadmin);
            pmaLink.style.opacity = '1';
            pmaLink.style.pointerEvents = 'auto';
            pmaLink.title = 'Ouvrir phpMyAdmin';
        }
    }
    
    const mailpitLink = projectCard.querySelector('.btn-warning[title*="Mailpit"]');
    if (mailpitLink) {
        if (isDevInstance) {
            mailpitLink.style.opacity = '0.5';
            mailpitLink.style.pointerEvents = 'none';
            mailpitLink.title = 'Mailpit non disponible pour les instances dev';
        } else {
            mailpitLink.href = getProjectUrl(data.ports.mailpit);
            mailpitLink.style.opacity = '1';
            mailpitLink.style.pointerEvents = 'auto';
            mailpitLink.title = 'Ouvrir Mailpit';
        }
    }
    
    // 4. Mettre à jour le menu des commandes pour utiliser le bon nom de projet/instance
    updateCommandsMenu(projectCard, isDevInstance ? data.name : projectName, isDevInstance);
}

// Mettre à jour le menu des commandes (fonction globale)
window.updateCommandsMenu = function(projectCard, targetName, isDevInstance) {
    console.log(`Mise à jour du menu commandes pour: ${targetName}, isDevInstance: ${isDevInstance}`);
    
    // Mettre à jour tous les liens du menu Commandes
    const commandLinks = projectCard.querySelectorAll('.project-commands-dropdown a');
    commandLinks.forEach(link => {
        const onclick = link.getAttribute('onclick');
        if (onclick) {
            // Remplacer le nom du projet par le nom de l'instance si nécessaire
            const originalProjectName = projectCard.dataset.projectName;
            const newOnclick = onclick.replace(
                new RegExp(`'${originalProjectName}'`, 'g'),
                `'${targetName}'`
            );
            link.setAttribute('onclick', newOnclick);
        }
        
        // Mettre à jour les data attributes pour WP-CLI
        if (link.dataset.project) {
            link.dataset.project = targetName;
        }
    });
    
    // Ajouter un indicateur visuel si c'est une instance dev
    const deleteLink = projectCard.querySelector('.text-danger[onclick*="deleteProject"]');
    if (deleteLink) {
        if (isDevInstance) {
            deleteLink.innerHTML = '<i class="fas fa-trash me-2"></i>Supprimer l\'instance';
        } else {
            deleteLink.innerHTML = '<i class="fas fa-trash me-2"></i>Supprimer le site';
        }
    }
}

// Supprimer une instance (fonction globale)
window.deleteDevInstance = async function(instanceName) {
    console.log('deleteDevInstance called with:', instanceName);
    
    if (!confirm(`Supprimer l'instance "${instanceName}" ?\n\nCette action supprimera uniquement le conteneur Docker.\nLes fichiers et la base de données seront conservés.`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/dev-instances/${encodeURIComponent(instanceName)}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        console.log('Delete response:', data);
        
        if (data.success || response.ok) {
            alert('Instance supprimée avec succès');
            // Recharger les projets
            if (typeof loadProjects === 'function') {
                loadProjects();
            }
        } else {
            alert(`Erreur: ${data.error || 'Erreur inconnue'}`);
        }
    } catch (error) {
        console.error('Delete error:', error);
        alert(`Erreur: ${error.message}`);
    }
}

// Soumettre la création d'instance (admin)
async function submitCreateInstance() {
    const projectName = document.getElementById('create-instance-project').value;
    const username = document.getElementById('create-instance-user').value;
    
    if (!username) {
        alert('Veuillez sélectionner un utilisateur');
        return;
    }
    
    try {
        const response = await fetch('/api/dev-instances/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ 
                parent_project: projectName,
                owner_username: username // Admin peut spécifier le propriétaire
            })
        });
        
        const data = await response.json();
        if (data.success) {
            alert(`Instance créée avec succès pour ${username}!\nURL: ${getProjectUrl(data.instance.port)}`);
            bootstrap.Modal.getInstance(document.getElementById('createInstanceModal')).hide();
            // Recharger les projets
            if (typeof loadProjects === 'function') {
                loadProjects();
            }
        } else {
            alert(`Erreur: ${data.error}`);
        }
    } catch (error) {
        alert(`Erreur: ${error.message}`);
    }
}

