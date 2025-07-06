/**
 * Fonctionnalités de recherche et filtrage pour WordPress Launcher
 */

// Variables globales pour le filtrage
let currentFilter = 'all';
let currentSearchTerm = '';

// Fonction pour initialiser la recherche en temps réel
function initSearchFunctionality() {
    const searchInput = document.getElementById('search-input');
    const clearButton = document.getElementById('clear-search');
    
    if (!searchInput || !clearButton) return;
    
    searchInput.addEventListener('input', function(e) {
        currentSearchTerm = e.target.value.toLowerCase();
        
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
    if (clearButton) clearButton.style.display = 'none';
    
    filterAndRenderProjects();
}

// Fonction pour filtrer les projets par catégorie
function filterProjects(filterType) {
    // Mettre à jour le filtre actuel
    currentFilter = filterType;
    
    // Mettre à jour l'interface
    updateActiveStatCard(filterType);
    showFilterIndicator(filterType);
    
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

// Fonction pour afficher l'indicateur de filtre
function showFilterIndicator(filterType) {
    const indicator = document.getElementById('filter-indicator');
    const filterText = document.getElementById('current-filter');
    
    if (!indicator || !filterText) return;
    
    const filterNames = {
        'all': 'Tous les projets',
        'active': 'Projets actifs',
        'inactive': 'Projets arrêtés',
        'nextjs': 'Projets Next.js'
    };
    
    if (filterType !== 'all') {
        filterText.textContent = filterNames[filterType];
        indicator.style.display = 'flex';
    } else {
        indicator.style.display = 'none';
    }
}

// Fonction pour effacer le filtre
function clearFilter() {
    currentFilter = 'all';
    updateActiveStatCard('all');
    const indicator = document.getElementById('filter-indicator');
    if (indicator) indicator.style.display = 'none';
    filterAndRenderProjects();
}

// Fonction pour filtrer et afficher les projets
function filterAndRenderProjects() {
    // Utiliser la variable projects globale définie dans le template
    if (typeof projects === 'undefined' || !projects) {
        console.warn('Variable projects non définie, impossible de filtrer');
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
                case 'nextjs':
                    return project.nextjs_enabled;
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
        let emptyMessage = 'Aucun projet trouvé';
        if (currentSearchTerm) {
            emptyMessage += ` pour "${currentSearchTerm}"`;
        }
        if (currentFilter !== 'all') {
            const filterNames = {
                'active': 'actifs',
                'inactive': 'arrêtés',
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
        console.error('Fonction createProjectHTML non trouvée');
        return;
    }
    
    // Ajouter les animations
    const items = container.querySelectorAll('.project-item');
    items.forEach((item, index) => {
        item.style.animationDelay = `${index * 0.1}s`;
        item.classList.add('slide-in');
    });
}

// Fonction pour mettre à jour la liste des projets (appelée depuis index.html)
function updateProjectsList(projectsList) {
    // Cette fonction n'est plus nécessaire car nous utilisons directement la variable projects
    // Mais on la garde pour la compatibilité
    filterAndRenderProjects();
}

// Initialiser les fonctionnalités au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
    initSearchFunctionality();
}); 