/**
 * Fonctionnalités de recherche et filtrage pour WordPress Launcher
 */

// Variables globales pour le filtrage avec persistance localStorage
if (typeof currentFilter === 'undefined') {
    var currentFilter = localStorage.getItem('wp-launcher-filter') || 'all';
}
if (typeof currentSearchTerm === 'undefined') {
    var currentSearchTerm = localStorage.getItem('wp-launcher-search') || '';
}

// Fonction pour initialiser la recherche en temps réel
function initSearchFunctionality() {
    const searchInput = document.getElementById('search-input');
    const clearButton = document.getElementById('clear-search');
    
    if (!searchInput || !clearButton) return;
    
    searchInput.addEventListener('input', function(e) {
        currentSearchTerm = e.target.value.toLowerCase();
        
        // Sauvegarder dans localStorage
        if (currentSearchTerm) {
            localStorage.setItem('wp-launcher-search', currentSearchTerm);
        } else {
            localStorage.removeItem('wp-launcher-search');
        }
        
        // Montrer/cacher le bouton clear
        if (currentSearchTerm) {
            clearButton.style.display = 'flex';
        } else {
            clearButton.style.display = 'none';
        }
        
        // Filtrer les projets
        filterAndRenderProjects();
    });
    
    // Permettre la recherche avec Enter
    searchInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            filterAndRenderProjects();
        }
    });
}

// Fonction pour effacer la recherche
function clearSearch() {
    const searchInput = document.getElementById('search-input');
    const clearButton = document.getElementById('clear-search');
    
    if (searchInput) searchInput.value = '';
    currentSearchTerm = '';
    localStorage.removeItem('wp-launcher-search');
    if (clearButton) clearButton.style.display = 'none';
    
    filterAndRenderProjects();
}

// Fonction pour filtrer les projets par catégorie
function filterProjects(filterType) {
    // Mettre à jour le filtre actuel
    currentFilter = filterType;
    
    // Sauvegarder dans localStorage
    if (filterType === 'all') {
        localStorage.removeItem('wp-launcher-filter');
    } else {
        localStorage.setItem('wp-launcher-filter', filterType);
    }
    
    // Mettre à jour l'interface
    updateActiveStatCard(filterType);
    
    // Filtrer et afficher les projets
    filterAndRenderProjects();
}

// Fonction pour mettre à jour la carte stat active
function updateActiveStatCard(filterType) {
    // Retirer la classe active de toutes les cartes
    document.querySelectorAll('.stat-card').forEach(card => {
        card.classList.remove('active');
    });
    
    // Ajouter la classe active à la carte sélectionnée
    const activeCard = document.querySelector(`[data-filter="${filterType}"]`);
    if (activeCard) {
        activeCard.classList.add('active');
    }
}

// Fonction pour effacer le filtre
function clearFilter() {
    currentFilter = 'all';
    localStorage.removeItem('wp-launcher-filter');
    updateActiveStatCard('all');
    filterAndRenderProjects();
}

// Fonction pour filtrer et afficher les projets
function filterAndRenderProjects() {
    // Utiliser la variable projects globale définie dans project-management.js
    if (typeof projects === 'undefined' || !projects) {
        //console.warn('Variable projects non définie, impossible de filtrer. Attente du chargement...');
        
        // Afficher un état de chargement au lieu du message d'erreur
        const container = document.getElementById('projects-grid');
        if (container) {
            container.innerHTML = `
                <div class="project-item fade-in">
                    <div class="empty-state">
                        <i class="fas fa-spinner fa-spin"></i>
                        <h3>Chargement des projets...</h3>
                        <p>Veuillez patienter</p>
                    </div>
                </div>
            `;
        }
        
        // Réessayer après un court délai si les projets ne sont pas encore chargés
        setTimeout(() => {
            if (typeof projects !== 'undefined' && projects) {
                filterAndRenderProjects();
            }
        }, 100);
        return;
    }
    
    let filteredProjects = projects;
    
    // Filtre par catégorie
    if (currentFilter !== 'all') {
        filteredProjects = filteredProjects.filter(project => {
            switch(currentFilter) {
                case 'active':
                    return project.status === 'active';
                case 'inactive':
                    return project.status === 'inactive';
                case 'wordpress':
                    // Projets WordPress classiques (sans Next.js ajouté)
                    return project.type === 'wordpress' && !project.nextjs_enabled;
                case 'nextjs':
                    // Inclure les projets Next.js purs ET les projets WordPress avec Next.js ajouté
                    return project.type === 'nextjs' || project.nextjs_enabled;
                default:
                    return true;
            }
        });
    }
    
    // Filtre par recherche
    if (currentSearchTerm) {
        filteredProjects = filteredProjects.filter(project => {
            return project.name.toLowerCase().includes(currentSearchTerm) ||
                   (project.hostname && project.hostname.toLowerCase().includes(currentSearchTerm));
        });
    }
    
    // Afficher les projets filtrés
    renderFilteredProjects(filteredProjects);
}

// Fonction pour afficher les projets filtrés
function renderFilteredProjects(filteredProjects) {
    const container = document.getElementById('projects-grid');
    
    if (!container) return;
    
    if (filteredProjects.length === 0) {
        // Vérifier s'il y a des tâches en cours avant d'afficher "Aucun projet trouvé"
        const hasRunningTasks = typeof taskManager !== 'undefined' && taskManager && taskManager.hasRunningTasks();
        
        if (hasRunningTasks) {
            // Si des tâches sont en cours, afficher un message de chargement
            container.innerHTML = `
                <div class="project-item fade-in">
                    <div class="empty-state">
                        <i class="fas fa-spinner fa-spin"></i>
                        <h3>Opération en cours...</h3>
                        <p>Veuillez patienter pendant le traitement</p>
                    </div>
                </div>
            `;
            return;
        }
        
        let emptyMessage = 'Aucun projet trouvé';
        if (currentSearchTerm) {
            emptyMessage += ` pour "${currentSearchTerm}"`;
        }
        if (currentFilter !== 'all') {
            const filterNames = {
                'active': 'actifs',
                'inactive': 'arrêtés',
                'wordpress': 'WordPress classiques',
                'nextjs': 'avec Next.js'
            };
            emptyMessage += ` dans les projets ${filterNames[currentFilter]}`;
        }
        
        container.innerHTML = `
            <div class="project-item fade-in">
                <div class="empty-state">
                    <i class="fas fa-search"></i>
                    <h3>${emptyMessage}</h3>
                    <p>Essayez de modifier vos critères de recherche</p>
                </div>
            </div>
        `;
        return;
    }
    
    // Utiliser la fonction createProjectHTML définie dans le template
    if (typeof createProjectHTML === 'function') {
        container.innerHTML = filteredProjects.map(project => createProjectHTML(project)).join('');
    } else {
        //console.error('Fonction createProjectHTML non trouvée');
        return;
    }
    
    // Ajouter les animations
    const items = container.querySelectorAll('.project-item');
    items.forEach((item, index) => {
        item.style.animationDelay = `${index * 0.1}s`;
    });
}

// Fonction pour mettre à jour la liste des projets (appelée depuis project-management.js)
function updateProjectsList(projectsList) {
    // Mettre à jour la variable projects globale
    if (typeof projects !== 'undefined') {
        // La variable projects est déjà mise à jour dans project-management.js
        // On déclenche juste le filtrage avec les données actuelles
        filterAndRenderProjects();
    } else {
        //console.warn('Variable projects non disponible dans updateProjectsList');
    }
}

// Fonction pour restaurer l'état depuis localStorage
function restoreFilterState() {
    // Restaurer le terme de recherche
    const searchInput = document.getElementById('search-input');
    const clearButton = document.getElementById('clear-search');
    
    if (searchInput && currentSearchTerm) {
        searchInput.value = currentSearchTerm;
        if (clearButton) clearButton.style.display = 'flex';
    }
    
    // Restaurer le filtre actif
    if (currentFilter !== 'all') {
        updateActiveStatCard(currentFilter);
    }
}

// Initialiser les fonctionnalités au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
    initSearchFunctionality();
    restoreFilterState();
});
