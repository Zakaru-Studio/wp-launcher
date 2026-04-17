/**
 * Gestion des projets - Toutes les fonctions liées aux projets
 * Extrait du template pour éviter les conflits
 */

// Variables globales
if (typeof projects === 'undefined') {
    var projects = [];
}
if (typeof socket === 'undefined') {
    var socket = null;
}
if (typeof importLogsBuffer === 'undefined') {
    var importLogsBuffer = [];
}
if (typeof currentImportProject === 'undefined') {
    var currentImportProject = null;
}
if (typeof currentImportTaskId === 'undefined') {
    var currentImportTaskId = null;
}
if (typeof importLogsModalInstance === 'undefined') {
    var importLogsModalInstance = null;
}
// Projets en cours d'import (bloquer l'accès au site pendant l'import)
if (typeof projectsImporting === 'undefined') {
    var projectsImporting = new Set();
}
// Timestamps des dernières mises à jour d'import (pour timeout automatique)
if (typeof importLastUpdate === 'undefined') {
    var importLastUpdate = {};
}
// Timeout en ms pour débloquer automatiquement les boutons (5 minutes)
const IMPORT_TIMEOUT_MS = 5 * 60 * 1000;

/**
 * Initialisation SocketIO pour les progress bars
 */
function initProgressTracking() {

    // Utiliser le singleton pour partager UNE SEULE instance Socket.IO entre
    // main.js, task-manager.js et project-management.js (évite les events doublés).
    if (typeof window.getSocketIO !== 'function') {
        console.error('getSocketIO non disponible');
        return;
    }
    const sharedSocket = window.getSocketIO();
    if (!sharedSocket) {
        console.error('Socket.IO non disponible');
        return;
    }
    socket = sharedSocket;

    // IMPORTANT: Attacher les listeners au socket existant (même s'il a été créé ailleurs)
    // Écouter les événements de création de projet
    socket.on('project_creation', function (data) {

            // Trouver la tâche correspondante dans le gestionnaire
            let currentTask = null;
            if (typeof taskManager !== 'undefined' && taskManager) {
                for (const [taskId, task] of taskManager.tasks.entries()) {
                    if (task.type === 'create_project' && task.status === 'running') {
                        currentTask = task;
                        break;
                    }
                }
            }

            if (data.status === 'error') {
                if (currentTask && typeof taskManager !== 'undefined' && taskManager) {
                    taskManager.completeTask(currentTask.id, data.message, false);
                }
                // Afficher l'erreur dans la console
                console.error('Erreur création projet:', data.message);
            } else if (data.status === 'warning') {
                if (currentTask && typeof taskManager !== 'undefined' && taskManager) {
                    taskManager.completeTask(currentTask.id, data.message, false);
                }
                // Afficher l'avertissement dans la console
                loadProjects(); // Recharger la liste des projets
            } else if (data.status === 'completed') {
                if (currentTask && typeof taskManager !== 'undefined' && taskManager) {
                    taskManager.completeTask(currentTask.id, data.message, true);
                }

                loadProjects(); // Recharger la liste des projets

                // Afficher le succès dans la console
            } else {
                // Mettre à jour la tâche en cours
                if (currentTask && data.step && data.total_steps && typeof taskManager !== 'undefined' && taskManager) {
                    const progress = Math.round((data.step / data.total_steps) * 100);
                    taskManager.updateTask(currentTask.id, {
                        message: data.message,
                        details: data.details ? JSON.stringify(data.details) : '',
                        progress: progress
                    });
                }
            }
        });

        // Gestion des progress bars SocketIO (uniquement pour import DB)
        socket.on('import_progress', function (data) {
            // Vérifier que c'est bien un import de base de données
            if (!data.type || data.type !== 'database_import') {
                return; // Ignorer les autres types d'événements
            }

            // Stocker le projet en cours d'import
            if (data.project) {
                currentImportProject = data.project;
                
                // Mettre à jour le timestamp de dernière activité
                importLastUpdate[data.project] = Date.now();
                
                // Ajouter le projet à la liste des imports en cours (bloque les boutons Site/Admin)
                if (data.status !== 'complete' && data.status !== 'error' && data.status !== 'completed') {
                    if (!projectsImporting.has(data.project)) {
                        projectsImporting.add(data.project);
                        // Mettre à jour l'affichage des boutons
                        updateProjectButtonsState(data.project, true);
                    }
                } else {
                    // Import terminé - débloquer
                    projectsImporting.delete(data.project);
                    delete importLastUpdate[data.project];
                    updateProjectButtonsState(data.project, false);
                    loadProjects(); // Recharger les projets pour s'assurer que les boutons sont mis à jour
                }
                
                // Ouvrir automatiquement la modale au début d'un nouvel import
                if (!importLogsModalInstance && data.progress <= 10) {
                    console.log('🔔 Ouverture automatique de la modale de logs pour:', data.project);
                    setTimeout(() => {
                        try {
                            showImportLogsModal();
                        } catch (error) {
                            console.error('Erreur lors de l\'ouverture de la modale:', error);
                        }
                    }, 500);
                }
            }

            // Ajouter le message aux logs
            if (data.message) {
                addImportLog(data.message, data.progress, data.status);
            }

            // Trouver la tâche correspondante dans le gestionnaire
            let currentTask = null;
            if (typeof taskManager !== 'undefined' && taskManager && data.project) {
                for (const [taskId, task] of taskManager.tasks.entries()) {
                    if (task.type === 'import_db' && task.projectName === data.project && task.status === 'running') {
                        currentTask = task;
                        break;
                    }
                }
            }

            // Mettre à jour la tâche si elle existe
            if (currentTask && typeof taskManager !== 'undefined' && taskManager) {
                if (data.status === 'complete' || data.status === 'completed') {
                    taskManager.completeTask(currentTask.id, data.message || 'Import terminé', true);
                    // Débloquer l'accès au site
                    projectsImporting.delete(data.project);
                    updateProjectButtonsState(data.project, false);
                } else if (data.status === 'error') {
                    taskManager.completeTask(currentTask.id, data.message || 'Erreur lors de l\'import', false);
                    // Débloquer l'accès au site en cas d'erreur
                    projectsImporting.delete(data.project);
                    updateProjectButtonsState(data.project, false);
                } else {
                    taskManager.updateTask(currentTask.id, {
                        message: data.message,
                        progress: data.progress || 0
                    });
                }
            }

            // Conserver l'affichage existant pour compatibilité
            const progressDiv = document.getElementById('import-progress');
            const progressBar = document.getElementById('progress-bar');
            const progressMessage = document.getElementById('progress-message');
            const progressProject = document.getElementById('progress-project-name');

            if (progressDiv && progressBar && progressMessage && progressProject) {
                showImportProgress();
                progressBar.style.width = data.progress + '%';
                progressMessage.textContent = data.message;
                progressProject.textContent = data.project;

                if (data.status === 'complete' || data.status === 'completed' || data.status === 'error') {
                    setTimeout(() => {
                        hideImportProgress();
                        loadProjects(); // Recharger les projets
                    }, 3000);
                }
            }
        });
}

/**
 * Met à jour l'état des boutons Site/Admin d'un projet (désactivé pendant l'import)
 */
function updateProjectButtonsState(projectName, isImporting) {
    const projectCard = document.querySelector(`[data-project-name="${projectName}"]`);
    if (!projectCard) return;
    
    // Chercher les boutons Site et Admin dans le service WordPress
    const wordpressService = projectCard.querySelector('.service-wordpress, [data-service-type="wordpress"]');
    if (!wordpressService) return;
    
    const buttons = wordpressService.querySelectorAll('.service-btn');
    buttons.forEach(btn => {
        const btnText = btn.textContent.trim().toLowerCase();
        if (btnText.includes('site') || btnText.includes('admin')) {
            if (isImporting) {
                btn.disabled = true;
                btn.classList.add('btn-disabled-import');
                btn.setAttribute('data-original-onclick', btn.getAttribute('onclick') || '');
                btn.setAttribute('onclick', 'showImportInProgressAlert()');
                btn.title = 'Import en cours - Accès temporairement bloqué';
            } else {
                btn.disabled = false;
                btn.classList.remove('btn-disabled-import');
                const originalOnclick = btn.getAttribute('data-original-onclick');
                if (originalOnclick) {
                    btn.setAttribute('onclick', originalOnclick);
                }
                btn.removeAttribute('data-original-onclick');
                btn.title = '';
            }
        }
    });
}

/**
 * Affiche une alerte quand on essaie d'accéder au site pendant l'import
 */
function showImportInProgressAlert() {
    if (typeof showImportLogsModal === 'function') {
        showImportLogsModal();
    } else {
        showToast('Import de base de données en cours. Veuillez patienter...', 'info');
    }
}

/**
 * Vérifie et débloque les projets dont l'import est inactif depuis trop longtemps
 */
function checkImportTimeouts() {
    const now = Date.now();
    const projectsToUnblock = [];
    
    for (const projectName of projectsImporting) {
        const lastUpdate = importLastUpdate[projectName];
        if (!lastUpdate || (now - lastUpdate) > IMPORT_TIMEOUT_MS) {
            projectsToUnblock.push(projectName);
        }
    }
    
    for (const projectName of projectsToUnblock) {
        console.log('⏰ Timeout import, déblocage automatique pour:', projectName);
        projectsImporting.delete(projectName);
        delete importLastUpdate[projectName];
        updateProjectButtonsState(projectName, false);
    }
    
    if (projectsToUnblock.length > 0) {
        loadProjects();
    }
}

/**
 * Débloque manuellement tous les projets en cours d'import
 */
function unlockAllImports() {
    for (const projectName of projectsImporting) {
        updateProjectButtonsState(projectName, false);
    }
    projectsImporting.clear();
    importLastUpdate = {};
    loadProjects();
}

// Vérifier les timeouts toutes les 30 secondes
setInterval(checkImportTimeouts, 30000);

// Au chargement de la page, nettoyer les imports bloqués
window.addEventListener('load', () => {
    // Les imports ne persistent pas entre les rechargements de page
    projectsImporting.clear();
    importLastUpdate = {};
});

/**
 * Fonction pour gérer l'interface selon le type de projet sélectionné
 */
function updateProjectTypeInterface() {
    const wordpressSelected = document.getElementById('project_type_wordpress')?.checked;
    const nextjsSelected = document.getElementById('project_type_nextjs')?.checked;

    // Éléments à montrer/cacher
    const wordpressTypeOption = document.getElementById('wordpress_type_option');
    const wordpressNextjsOption = document.getElementById('wordpress_nextjs_option');
    const wordpressArchiveSection = document.getElementById('wordpress_archive_section');
    const nextjsInfoSection = document.getElementById('nextjs_info_section');
    const nextjsDatabaseSection = document.getElementById('nextjs_database_section');

    if (wordpressSelected) {
        // Afficher les options WordPress uniquement
        if (wordpressTypeOption) wordpressTypeOption.style.display = 'block';
        if (wordpressNextjsOption) wordpressNextjsOption.style.display = 'block';
        if (wordpressArchiveSection) wordpressArchiveSection.style.display = 'block';
        if (nextjsInfoSection) nextjsInfoSection.style.display = 'none';
        if (nextjsDatabaseSection) nextjsDatabaseSection.style.display = 'none';

        // Désactiver les champs database_type pour WordPress (ne pas les inclure dans FormData)
        const dbTypeInputs = document.querySelectorAll('input[name="database_type"]');
        dbTypeInputs.forEach(input => input.disabled = true);
    } else if (nextjsSelected) {
        // Afficher les options Next.js App uniquement
        if (wordpressTypeOption) wordpressTypeOption.style.display = 'none';
        if (wordpressNextjsOption) wordpressNextjsOption.style.display = 'none';
        if (wordpressArchiveSection) wordpressArchiveSection.style.display = 'none';
        if (nextjsInfoSection) nextjsInfoSection.style.display = 'block';
        if (nextjsDatabaseSection) nextjsDatabaseSection.style.display = 'block';

        // Réactiver les champs database_type pour Next.js
        const dbTypeInputs = document.querySelectorAll('input[name="database_type"]');
        dbTypeInputs.forEach(input => input.disabled = false);

        // Décocher l'option Next.js pour WordPress si elle était cochée
        const enableNextjsCheckbox = document.getElementById('enable_nextjs');
        if (enableNextjsCheckbox) enableNextjsCheckbox.checked = false;

        // Mettre à jour l'affichage selon la base de données sélectionnée
        updateDatabaseChoice();
    }
}

/**
 * Fonction pour gérer le choix de base de données pour Next.js
 */
function updateDatabaseChoice() {
    const mongoSelected = document.getElementById('db_type_mongodb')?.checked;
    const mysqlSelected = document.getElementById('db_type_mysql')?.checked;

    // Mettre à jour les tech badges
    const techStack = document.getElementById('nextjs_tech_stack');
    const dbInfo = document.getElementById('nextjs_db_info');

    if (mongoSelected) {
        if (techStack) {
            techStack.innerHTML = `
                <span class="tech-badge">Next.js</span>
                <span class="tech-badge">MongoDB</span>
                <span class="tech-badge">Express</span>
            `;
        }
        if (dbInfo) {
            dbInfo.textContent = 'MongoDB avec Mongo Express';
        }
    } else if (mysqlSelected) {
        if (techStack) {
            techStack.innerHTML = `
                <span class="tech-badge">Next.js</span>
                <span class="tech-badge">MySQL</span>
                <span class="tech-badge">Express</span>
            `;
        }
        if (dbInfo) {
            dbInfo.textContent = 'MySQL avec phpMyAdmin';
        }
    }
}

/**
 * Fonction pour afficher le modal de création
 */
function showCreateProjectModal() {
    const modal = new bootstrap.Modal(document.getElementById('createProjectModal'));
    modal.show();

    // S'assurer que l'interface est correctement initialisée
    updateProjectTypeInterface();
}

/**
 * Fonction pour charger les projets
 */
async function loadProjects() {
    try {
        const response = await fetch('/projects_with_status');
        const data = await response.json();
        projects = data.projects || [];

        // Trier les projets par ordre alphabétique croissant
        projects.sort((a, b) => a.name.localeCompare(b.name));

        // Mettre à jour les données pour le filtrage
        if (typeof updateProjectsList === 'function') {
            updateProjectsList(projects);
        }

        updateStats();

        // Si le système de filtrage n'est pas disponible, utiliser le rendu classique
        if (typeof filterAndRenderProjects === 'function') {
            filterAndRenderProjects();
            // Restaurer l'état des projets après le filtrage
            setTimeout(() => restoreProjectStates(), 100);
        } else {
            console.warn('filterAndRenderProjects non disponible, utilisation du rendu classique');
            renderProjects();
        }

        // Vérifier le statut des boutons npm run dev après le rendu
        setTimeout(() => checkNextjsDevStatus(), 1500);
        
        // NOUVEAU : Restaurer les instances sélectionnées après le rendu
        setTimeout(() => {
            restoreSelectedInstances();
        }, 200);

    } catch (error) {
        console.error('Erreur lors du chargement des projets:', error);
        if (typeof showError === 'function') {
            showError('Erreur lors du chargement des projets');
        }
    }
}

/**
 * Restaurer les instances sélectionnées depuis sessionStorage
 */
function restoreSelectedInstances() {
    // Parcourir tous les projets pour restaurer leur instance sélectionnée
    projects.forEach(project => {
        const selectedInstance = sessionStorage.getItem(`selected_instance_${project.name}`);
        if (selectedInstance) {
            try {
                const instance = JSON.parse(selectedInstance);
                console.log(`Restauration de l'instance ${instance.name} pour le projet ${project.name}`);
                // Réappliquer l'instance sans recharger
                if (typeof fetchInstanceStatusAndUpdate === 'function') {
                    fetchInstanceStatusAndUpdate(project.name, instance);
                }
            } catch (error) {
                console.error(`Erreur lors de la restauration de l'instance pour ${project.name}:`, error);
                // En cas d'erreur, supprimer l'entrée corrompue
                sessionStorage.removeItem(`selected_instance_${project.name}`);
            }
        }
    });
}

/**
 * Fonction pour mettre à jour les statistiques
 */
function updateStats() {
    const totalProjects = projects.length;
    const activeProjects = projects.filter(p => p.status === 'active').length;
    const inactiveProjects = projects.filter(p => p.status === 'inactive').length;
    // Compter les projets WordPress classiques (sans Next.js ajouté)
    const wordpressProjects = projects.filter(p => p.type === 'wordpress' && !p.nextjs_enabled).length;
    // Compter les projets Next.js purs ET les projets WordPress avec Next.js ajouté
    const nextjsProjects = projects.filter(p => p.type === 'nextjs' || p.type === 'wordpress_nextjs' || p.nextjs_enabled || p.has_nextjs).length;

    document.getElementById('total-projects').textContent = totalProjects;
    document.getElementById('active-projects').textContent = activeProjects;
    document.getElementById('inactive-projects').textContent = inactiveProjects;
    document.getElementById('wordpress-projects').textContent = wordpressProjects;
    document.getElementById('nextjs-projects').textContent = nextjsProjects;
}

/**
 * Fonction pour rendre les projets (fallback si le système de filtrage n'est pas disponible)
 */
function renderProjects() {
    const container = document.getElementById('projects-grid');

    if (projects.length === 0) {
        container.innerHTML = `
            <div class="project-item fade-in">
                <div class="empty-state">
                    <i class="fas fa-box-open"></i>
                    <h3>Aucun projet pour le moment</h3>
                    <p>Créez votre premier projet WordPress pour commencer</p>
                </div>
            </div>
        `;
        return;
    }

    container.innerHTML = projects.map(project => createProjectHTML(project)).join('');

    // Ajouter les animations
    const items = container.querySelectorAll('.project-item');
    items.forEach((item, index) => {
        item.style.animationDelay = `${index * 0.1}s`;
    });

    // Restaurer l'état des projets (collapsed/expanded)
    setTimeout(() => restoreProjectStates(), 100);

    // Vérifier le statut des boutons npm run dev
    setTimeout(() => checkNextjsDevStatus(), 1000);
}

/**
 * Fonction pour créer le HTML d'un projet
 */
function createProjectHTML(project) {
    // Services disponibles
    const services = [];

    // Déterminer le type de projet
    const isNextjsApp = project.type === 'nextjs';
    const isWordPress = project.type === 'wordpress' || project.type === 'wordpress_nextjs' || !project.type; // Fallback pour anciens projets

    if (project.status === 'active') {
        if (isNextjsApp) {
            // Projet Next.js pur avec client/API séparés

            // Client Next.js
            if (project.port) {
                services.push({
                    name: 'Client Next.js',
                    icon: 'fab fa-react',
                    url: getProjectUrl(project.port),
                    display: `:${project.port}`,
                    isMain: true,
                    type: 'nextjs-client',
                    buttons: [
                        {
                            text: 'Ouvrir',
                            icon: 'fas fa-external-link-alt',
                            class: 'btn-primary',
                            action: `window.open('${getProjectUrl(project.port)}', '_blank')`
                        }
                    ]
                });
            }

            // Base de données (MySQL ou MongoDB)
            if (project.pma_port) {
                // MySQL avec phpMyAdmin
                services.push({
                    name: 'phpMyAdmin',
                    icon: 'fas fa-database',
                    url: getProjectUrl(project.pma_port),
                    display: `:${project.pma_port}`,
                    isMain: false,
                    type: 'phpmyadmin',
                    buttons: [
                        {
                            text: 'Import SQL',
                            icon: 'fas fa-upload',
                            class: 'btn-secondary',
                            action: `updateDatabase('${project.name}')`
                        },
                        {
                            text: 'Export SQL',
                            icon: 'fas fa-download',
                            class: 'btn-secondary',
                            action: `exportDatabase('${project.name}')`
                        }
                    ],
                    configButton: {
                        icon: 'fas fa-cog',
                        action: `openMysqlConfigModal('${project.name}')`,
                        title: 'Configuration MySQL'
                    }
                });
            } else if (project.urls && project.urls.mongo_express) {
                // MongoDB avec Mongo Express
                const mongoPort = project.urls.mongo_express.split(':').pop();
                services.push({
                    name: 'Mongo Express',
                    icon: 'fas fa-leaf',
                    url: project.urls.mongo_express,
                    display: `:${mongoPort}`,
                    isMain: false,
                    type: 'mongo-express',
                    buttons: [
                        {
                            text: 'Ouvrir',
                            icon: 'fas fa-external-link-alt',
                            class: 'btn-primary',
                            action: `window.open('${project.urls.mongo_express}', '_blank')`
                        }
                    ]
                });
            }

            // Mailpit
            if (project.mailpit_port) {
                services.push({
                    name: 'Mailpit',
                    icon: 'fas fa-envelope',
                    url: getProjectUrl(project.mailpit_port),
                    display: `:${project.mailpit_port}`,
                    isMain: false,
                    type: 'mailpit',
                    buttons: [
                        {
                            text: 'Voir les e-mails',
                            icon: 'fas fa-inbox',
                            class: 'btn-secondary',
                            action: `window.open('${getProjectUrl(project.mailpit_port)}', '_blank')`,
                            title: 'Ouvrir l\'interface Mailpit'
                        }
                    ]
                });
            }

            // API Express
            if (project.urls && project.urls.api) {
                const apiPort = project.urls.api.split(':').pop();
                services.push({
                    name: 'API Express',
                    icon: 'fas fa-server',
                    url: project.urls.api,
                    display: `:${apiPort}`,
                    isMain: false,
                    type: 'api-express',
                    buttons: [
                        {
                            text: 'Health Check',
                            icon: 'fas fa-heartbeat',
                            class: 'btn-success',
                            action: `window.open('${project.urls.api}/health', '_blank')`
                        },
                        {
                            text: 'API Routes',
                            icon: 'fas fa-route',
                            class: 'btn-info',
                            action: `window.open('${project.urls.api}/api', '_blank')`
                        }
                    ]
                });
            }

        } else if (isWordPress) {
            // Projet WordPress 

            // WordPress via IP:port direct
            // Vérifier si le projet est en cours d'import
            const isImporting = projectsImporting && projectsImporting.has(project.name);
            
            services.push({
                name: 'WordPress',
                icon: 'fab fa-wordpress',
                url: getProjectUrl(project.port),
                display: `:${project.port}`,
                isMain: true,
                type: 'wordpress',
                buttons: [
                    {
                        text: isImporting ? '🔒 Site' : 'Site',
                        icon: 'fas fa-globe',
                        class: isImporting ? 'btn-secondary btn-disabled-import' : 'btn-primary',
                        action: isImporting ? `showImportInProgressAlert()` : `window.open('${getProjectUrl(project.port)}', '_blank')`,
                        disabled: isImporting,
                        title: isImporting ? 'Import en cours - Accès temporairement bloqué' : ''
                    },
                    {
                        text: isImporting ? '🔒 Admin' : 'Admin',
                        icon: 'fas fa-user-shield',
                        class: isImporting ? 'btn-secondary btn-disabled-import' : 'btn-primary',
                        action: isImporting ? `showImportInProgressAlert()` : `window.open('` + getProjectUrl(project.port, 'wp-admin/?autologin=1&user=' + window.APP_CONFIG.wp_admin_user + '&pass=' + window.APP_CONFIG.wp_admin_password) + `', '_blank')`,
                        disabled: isImporting,
                        title: isImporting ? 'Import en cours - Accès temporairement bloqué' : ''
                    }
                ],
                configButton: {
                    icon: 'fas fa-cog',
                    action: `openPhpConfigModal('${project.name}')`,
                    title: 'Configuration PHP'
                }
            });

            // Services avec ports directs
            if (project.pma_port) {
                services.push({
                    name: 'phpMyAdmin',
                    icon: 'fas fa-database',
                    url: getProjectUrl(project.pma_port),
                    display: `:${project.pma_port}`,
                    isMain: false,
                    type: 'phpmyadmin',
                    buttons: [
                        {
                            text: 'Import SQL',
                            icon: 'fas fa-upload',
                            class: 'btn-secondary',
                            action: `updateDatabase('${project.name}')`
                        },
                        {
                            text: 'Export SQL',
                            icon: 'fas fa-download',
                            class: 'btn-secondary',
                            action: `exportDatabase('${project.name}')`
                        }
                    ],
                    configButton: {
                        icon: 'fas fa-cog',
                        action: `openMysqlConfigModal('${project.name}')`,
                        title: 'Configuration MySQL'
                    }
                });
            }

            if (project.mailpit_port) {
                services.push({
                    name: 'Mailpit',
                    icon: 'fas fa-envelope',
                    url: getProjectUrl(project.mailpit_port),
                    display: `:${project.mailpit_port}`,
                    isMain: false,
                    type: 'mailpit',
                    buttons: [
                        {
                            text: 'Voir les e-mails',
                            icon: 'fas fa-inbox',
                            class: 'btn-secondary',
                            action: `window.open('${getProjectUrl(project.mailpit_port)}', '_blank')`,
                            title: 'Ouvrir l\'interface Mailpit'
                        }
                    ]
                });
            }

            // Next.js pour WordPress (si activé)
            if ((project.nextjs_enabled || project.has_nextjs) && project.nextjs_port) {
                services.push({
                    name: 'Next.js',
                    icon: 'fab fa-react',
                    url: getProjectUrl(project.nextjs_port),
                    display: `:${project.nextjs_port}`,
                    isMain: false,
                    type: 'nextjs',
                    buttons: [
                        {
                            text: 'Install',
                            icon: 'fas fa-download',
                            class: 'btn-info',
                            action: `runNpmCommand('${project.name}', 'install')`,
                            title: 'Installer les dépendances'
                        },
                        {
                            text: 'Run Dev',
                            icon: 'fas fa-play',
                            class: 'btn-success',
                            action: `runNpmCommand('${project.name}', 'dev')`,
                            title: 'Démarrer en mode développement'
                        },
                        {
                            text: 'Build',
                            icon: 'fas fa-hammer',
                            class: 'btn-warning',
                            action: `runNpmCommand('${project.name}', 'build')`,
                            title: 'Construire pour la production'
                        }
                    ]
                });
            }
        }
    }

    // Ajouter Next.js pour WordPress si pas activé
    if (isWordPress && !project.nextjs_enabled && !project.has_nextjs) {
        services.push({
            name: 'Next.js',
            icon: 'fab fa-react',
            url: '#',
            display: 'Non activé',
            isMain: false,
            type: 'nextjs',
            inactive: true,
            buttons: [
                {
                    text: 'Ajouter Next.js',
                    icon: 'fab fa-react',
                    class: 'btn-secondary',
                    action: `addNextjs('${project.name}')`
                }
            ]
        });
    }

    // Déterminer l'URL principale et l'icône du projet
    let mainUrl = '';
    let mainIcon = 'fas fa-cube';
    let projectTypeLabel = 'Projet';

    if (isNextjsApp) {
        mainUrl = getProjectUrl(project.port);
        mainIcon = 'fab fa-react';
        projectTypeLabel = 'App Next.js';
    } else if (isWordPress) {
        mainUrl = getProjectUrl(project.port);
        if (project.type === 'wordpress_nextjs' || project.has_nextjs || project.nextjs_enabled) {
            mainIcon = 'fab fa-wordpress';
            projectTypeLabel = 'WordPress + Next.js';
        } else {
            mainIcon = 'fab fa-wordpress';
            projectTypeLabel = 'WordPress';
        }
    }

    return `
        <div class="project-item" 
             data-project="${project.name}" 
             data-project-name="${project.name}"
             data-port-wordpress="${project.port || ''}"
             data-port-phpmyadmin="${project.pma_port || ''}"
             data-port-mailpit="${project.mailpit_port || ''}">
            <div class="project-header" ${project.status === 'active' ? `onclick="toggleProject('${project.name}')" style="cursor: pointer;"` : 'style="cursor: default;"'}>
                <div class="project-header-info">
                    <div class="project-title">
                        <i class="${mainIcon} me-2"></i>
                        ${project.name}
                        ${project.status === 'active' ? `
                        <button class="project-toggle-btn" onclick="event.stopPropagation(); toggleProject('${project.name}')" title="Masquer/Afficher les détails">
                            <i class="fas fa-chevron-down"></i>
                        </button>
                        ` : ''}
                    </div>    

                    ${project.status === 'active' && mainUrl ? `
                        <div class="project-ip-port">
                        <a href="${mainUrl}" target="_blank" class="ip-port-link" onclick="event.stopPropagation();">
                        <i class="fas fa-external-link-alt me-1"></i>
                                ${window.APP_CONFIG.host}:${project.port}
                            </a>
                        </div>
                    ` : ''}
                    
                    ${(project.nextjs_enabled || project.has_nextjs) && project.nextjs_port ? `
                        <div class="project-nextjs-ip" style="display: none;">
                            <i class="fab fa-react me-1"></i>
                            <a href="${getProjectUrl(project.nextjs_port)}" target="_blank" class="nextjs-ip-link" onclick="event.stopPropagation();">
                                Next.js: ${window.APP_CONFIG.host}:${project.nextjs_port}
                            </a>
                        </div>
                    ` : ''}
                </div>
                <div class="project-header-right" onclick="event.stopPropagation();">
                    ${isWordPress ? `
                    <div class="btn-group">
                        <button class="btn-modern btn-secondary instance-dropdown-btn" type="button" 
                                data-bs-toggle="dropdown" 
                                data-bs-auto-close="true" 
                                aria-expanded="false" 
                                title="Instances de développement"
                                id="instances-dropdown-${project.name}">
                            <i class="fas fa-server me-1"></i>
                            <span class="instance-label">Instance principale</span>
                            <i class="fas fa-chevron-down ms-1"></i>
                        </button>
                        <ul class="dropdown-menu dropdown-menu-dark dropdown-menu-end instances-dropdown" 
                            data-project="${project.name}">
                            <li class="dropdown-header"><small>Chargement...</small></li>
                        </ul>
                    </div>
                    ` : ''}
                    <div class="btn-group">
                        <button class="btn-modern btn-secondary" type="button" data-bs-toggle="dropdown" data-bs-auto-close="true" aria-expanded="false" title="Commandes du projet">
                            <i class="fas fa-bolt me-1"></i>
                            Commandes
                            <i class="fas fa-chevron-down ms-1"></i>
                        </button>
                        <ul class="dropdown-menu dropdown-menu-dark dropdown-menu-end project-commands-dropdown">
                            <li><a class="dropdown-item" href="#" onclick="restartProject('${project.name}'); return false;"><i class="fas fa-redo me-2"></i>Redémarrer</a></li>
                            <li><a class="dropdown-item" href="#" onclick="rebuildProject('${project.name}'); return false;"><i class="fas fa-hammer me-2"></i>Rebuild Containers</a></li>
                            <li><a class="dropdown-item" href="#" onclick="openCloneModal('${project.name}'); return false;"><i class="fas fa-clone me-2"></i>Cloner</a></li>
                            <li><a class="dropdown-item" href="#" onclick="openSnapshotsModal('${project.name}'); return false;"><i class="fas fa-camera me-2"></i>Snapshots</a></li>
                            ${isWordPress && project.status === 'active' ? `
                            <li><hr class="dropdown-divider"></li>
                            <li><a class="dropdown-item wpcli-cmd" href="#" data-project="${project.name}" data-cmd="fix-permissions"><i class="fas fa-wrench me-2"></i>Fix Permissions</a></li>
                            <li><a class="dropdown-item wpdebug-submenu-btn" href="#" data-project="${project.name}"><i class="fas fa-bug me-2"></i>WP Debug<span class="float-end">›</span></a></li>
                            <li><a class="dropdown-item wpcli-cmd" href="#" data-project="${project.name}" data-cmd="rewrite flush"><i class="fas fa-sync me-2"></i>Flush Rewrite Rules</a></li>
                            <li><a class="dropdown-item wpcli-cmd" href="#" data-project="${project.name}" data-cmd="cache flush"><i class="fas fa-broom me-2"></i>Vider le Cache</a></li>
                            <li><hr class="dropdown-divider"></li>
                            <li><a class="dropdown-item wpcli-submenu-btn" href="#" data-project="${project.name}"><i class="fas fa-terminal me-2"></i>Autres (WP-CLI)<span class="float-end">›</span></a></li>
                            ` : ''}
                            <li><hr class="dropdown-divider"></li>
                            <li><a class="dropdown-item text-danger" href="#" onclick="deleteProject('${project.name}'); return false;"><i class="fas fa-trash me-2"></i>Supprimer le site</a></li>
                        </ul>
                    </div>
                    
                    ${project.status === 'active' ? `
                        <button class="btn-modern btn-running" onclick="stopProject('${project.name}')" title="Arrêter le projet">
                            Running
                            <i class="fas fa-stop me-1"></i>
                        </button>
                    ` : `
                        <button class="btn-modern btn-start" onclick="startProject('${project.name}')" title="Démarrer le projet">
                            Start
                            <i class="fas fa-play me-1"></i>
                        </button>
                    `}
                </div>
            </div>

            <div class="project-content ${project.status === 'active' ? 'open' : 'collapsed'}" id="project-content-${project.name}">
                ${project.status === 'active' ? `
                    ${services.length > 0 ? `
                        <div class="services-grid">
                            ${services.map(service => `
                                <div class="service-card ${service.inactive ? 'service-inactive' : ''} service-${service.type}">
                                    ${service.configButton ? `
                                        <div class="service-config-button">
                                            <button class="btn-config" onclick="${service.configButton.action}" title="${service.configButton.title}">
                                                <i class="${service.configButton.icon}"></i>
                                            </button>
                                        </div>
                                    ` : ''}
                                    <a href="${service.inactive ? 'javascript:void(0)' : service.url}" ${service.inactive ? '' : 'target="_blank"'} class="service-link">
                                        <i class="${service.icon} service-icon"></i>
                                        <div class="service-name">${service.name}</div>
                                        <div class="service-port">${service.display}</div>
                                    </a>
                                    ${service.buttons ? `
                                        <div class="service-buttons">
                                            ${service.buttons.map(button => `
                                                <button class="btn-service ${button.class}" onclick="${button.action}" ${button.title ? `title="${button.title}"` : ''}>
                                                    <i class="${button.icon}"></i>
                                                    <span>${button.text}</span>
                                                </button>
                                            `).join('')}
                                        </div>
                                    ` : ''}
                                </div>
                            `).join('')}
                        </div>
                    ` : `
                        <div class="empty-services">
                            <p class="text-muted">
                                <i class="fas fa-info-circle me-2"></i>
                                Aucun service configuré pour ce projet.
                            </p>
                        </div>
                    `}
                ` : `
                `}
            </div>
        </div>
    `;
}

/**
 * Fonctions de toggle/collapse des projets
 */
function toggleProject(projectName) {
    const projectContent = document.getElementById(`project-content-${projectName}`);
    const projectItem = document.querySelector(`[data-project="${projectName}"]`);
    const toggleBtn = projectItem.querySelector('.project-toggle-btn i');

    if (!projectContent) return;

    // Toggle la classe collapsed
    projectContent.classList.toggle('collapsed');

    // Ajouter ou retirer la classe open selon l'état
    if (projectContent.classList.contains('collapsed')) {
        projectContent.classList.remove('open');
        toggleBtn.style.transform = 'rotate(0deg)';
        // Sauvegarder l'état collapsed dans le localStorage
        saveProjectState(projectName, 'collapsed');
    } else {
        projectContent.classList.add('open');
        toggleBtn.style.transform = 'rotate(-180deg)';
        // Sauvegarder l'état expanded dans le localStorage
        saveProjectState(projectName, 'expanded');
    }
}

/**
 * Sauvegarder l'état des projets dans le localStorage
 */
function saveProjectState(projectName, state) {
    const projectStates = JSON.parse(localStorage.getItem('projectStates') || '{}');
    projectStates[projectName] = state;
    localStorage.setItem('projectStates', JSON.stringify(projectStates));
}

/**
 * Restaurer l'état des projets depuis le localStorage
 */
function restoreProjectStates() {
    const projectStates = JSON.parse(localStorage.getItem('projectStates') || '{}');

    Object.entries(projectStates).forEach(([projectName, state]) => {
        const projectContent = document.getElementById(`project-content-${projectName}`);
        const projectItem = document.querySelector(`[data-project="${projectName}"]`);
        const toggleBtn = projectItem?.querySelector('.project-toggle-btn i');

        if (projectContent && state === 'collapsed') {
            projectContent.classList.add('collapsed');
            if (toggleBtn) {
                toggleBtn.style.transform = 'rotate(0deg)';
            }
        }
    });
}

/**
 * Fonction pour rafraîchir les projets
 */
function refreshProjects() {
    loadProjects();
}

/**
 * Mettre à jour le statut d'un projet spécifique sans recharger toute la liste
 */
function updateProjectStatus(projectName, newStatus) {
    console.log(`🔄 updateProjectStatus appelée: ${projectName} → ${newStatus}`);

    // Chercher la carte du projet par différents sélecteurs
    let projectCard = document.querySelector(`[data-project-name="${projectName}"]`);

    // Si pas trouvé, essayer d'autres sélecteurs
    if (!projectCard) {
        projectCard = document.querySelector(`[data-project="${projectName}"]`);
    }

    // Chercher par bouton de démarrage/arrêt
    if (!projectCard) {
        const startButton = document.querySelector(`button[onclick="startProject('${projectName}')"]`);
        if (startButton) {
            projectCard = startButton.closest('.card, .project-card, .project-item');
        }
    }

    // Chercher dans toute la liste des projets affichés
    if (!projectCard) {
        const allProjectItems = document.querySelectorAll('.project-item');
        for (const item of allProjectItems) {
            const projectTitle = item.querySelector('.project-title');
            if (projectTitle && projectTitle.textContent.trim().includes(projectName)) {
                projectCard = item;
                break;
            }
        }
    }

    if (!projectCard) {
        console.log(`❌ Project card not found for ${projectName}, falling back to full reload`);
        setTimeout(() => loadProjects(), 1000);
        return;
    }

    console.log(`✅ Project card trouvée pour ${projectName}`);

    // Mettre à jour le badge de statut
    const statusBadge = projectCard.querySelector('.badge');
    if (statusBadge) {
        // Supprimer les anciennes classes de statut
        statusBadge.classList.remove('bg-success', 'bg-danger', 'bg-warning', 'bg-secondary');

        // Ajouter la nouvelle classe selon le statut
        switch (newStatus) {
            case 'running':
                statusBadge.classList.add('bg-success');
                statusBadge.textContent = 'Running';
                break;
            case 'stopped':
                statusBadge.classList.add('bg-danger');
                statusBadge.textContent = 'Stopped';
                break;
            case 'partial':
                statusBadge.classList.add('bg-warning');
                statusBadge.textContent = 'Partial';
                break;
            default:
                statusBadge.classList.add('bg-secondary');
                statusBadge.textContent = 'Unknown';
        }
    }

    // Mettre à jour les boutons
    const startBtn = projectCard.querySelector(`button[onclick="startProject('${projectName}')"]`);
    const stopBtn = projectCard.querySelector(`button[onclick="stopProject('${projectName}')"]`);

    // Chercher aussi les boutons avec d'autres sélecteurs
    const runningBtn = projectCard.querySelector('.btn-running');
    const stoppedBtn = projectCard.querySelector('.btn-stopped');

    console.log(`🔘 Boutons trouvés - start: ${!!startBtn}, stop: ${!!stopBtn}, running: ${!!runningBtn}, stopped: ${!!stoppedBtn}`);

    if (newStatus === 'running') {
        // Projet en cours d'exécution
        if (startBtn) {
            startBtn.disabled = true;
            startBtn.classList.remove('loading');
            startBtn.innerHTML = 'Start <i class="fas fa-play ms-1"></i>';
        }

        if (stopBtn) {
            stopBtn.disabled = false;
            stopBtn.classList.remove('loading');
            stopBtn.innerHTML = 'Stop <i class="fas fa-stop ms-1"></i>';
        }

        // Transformer le bouton en "Running" si c'est le style moderne
        if (stoppedBtn) {
            stoppedBtn.className = 'btn-modern btn-running';
            stoppedBtn.innerHTML = 'Running <i class="fas fa-stop me-1"></i>';
            stoppedBtn.setAttribute('onclick', `stopProject('${projectName}')`);
            stoppedBtn.title = 'Arrêter le projet';
        }

    } else {
        // Projet arrêté
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.classList.remove('loading');
            startBtn.innerHTML = 'Start <i class="fas fa-play ms-1"></i>';
        }

        if (stopBtn) {
            stopBtn.disabled = true;
            stopBtn.classList.remove('loading');
            stopBtn.innerHTML = 'Stop <i class="fas fa-stop ms-1"></i>';
        }

        // Transformer le bouton en "Stopped" si c'est le style moderne
        if (runningBtn) {
            runningBtn.className = 'btn-modern btn-stopped';
            runningBtn.innerHTML = 'Stopped <i class="fas fa-play me-1"></i>';
            runningBtn.setAttribute('onclick', `startProject('${projectName}')`);
            runningBtn.title = 'Démarrer le projet';
        }
    }

    console.log(`✅ Statut projet ${projectName} mis à jour vers ${newStatus}`);
}

/**
 * Fonction pour cacher la barre de progression
 */
function hideImportProgress() {
    const progressDiv = document.getElementById('import-progress');
    if (progressDiv) {
        progressDiv.classList.add('d-none');
        document.body.classList.remove('import-progress-visible');
    }
}

/**
 * Fonction pour afficher la barre de progression
 */
function showImportProgress() {
    const progressDiv = document.getElementById('import-progress');
    if (progressDiv) {
        progressDiv.classList.remove('d-none');
        document.body.classList.add('import-progress-visible');
    }
}


/**
 * Fonction pour vérifier le statut des boutons npm run dev
 */
async function checkNextjsDevStatus() {
    const projects = document.querySelectorAll('.project-item');

    for (const projectItem of projects) {
        const projectName = projectItem.dataset.project;

        // Chercher le bouton dans les service Next.js
        const nextjsCard = projectItem.querySelector('.service-nextjs');
        if (!nextjsCard) continue;

        const devButtons = nextjsCard.querySelectorAll('button');
        let devButton = null;

        // Trouver le bouton Run Dev ou Stop Dev
        for (const btn of devButtons) {
            const text = btn.textContent || '';
            if (text.includes('Run Dev') || text.includes('Stop Dev')) {
                devButton = btn;
                break;
            }
        }

        // Chercher l'élément project-nextjs-ip
        const nextjsIpElement = projectItem.querySelector('.project-nextjs-ip');

        if (devButton) {
            try {
                const response = await fetch(`/check_nextjs_status/${projectName}`);
                const data = await response.json();

                console.log(`Status for ${projectName}:`, data); // Debug

                if (data.success && data.dev_running) {
                    // npm run dev est en cours - bouton Stop Dev
                    devButton.disabled = false;
                    devButton.innerHTML = '<i class="fas fa-stop me-1"></i><span>Stop Dev</span>';
                    devButton.classList.add('btn-running');
                    devButton.classList.remove('btn-success');
                    devButton.title = 'Arrêter npm run dev';
                    devButton.setAttribute('onclick', `stopNpmDev('${projectName}')`);

                    // Afficher l'IP Next.js si npm dev est actif
                    if (nextjsIpElement) {
                        nextjsIpElement.style.display = 'block';
                    }
                } else {
                    // npm run dev n'est pas en cours - bouton Run Dev
                    devButton.disabled = false;
                    devButton.innerHTML = '<i class="fas fa-play me-1"></i><span>Run Dev</span>';
                    devButton.classList.add('btn-success');
                    devButton.classList.remove('btn-running');
                    devButton.title = 'Démarrer le conteneur Next.js avec npm run dev';
                    devButton.setAttribute('onclick', `startNextjsContainer('${projectName}')`);

                    // Masquer l'IP Next.js si npm dev n'est pas actif
                    if (nextjsIpElement) {
                        nextjsIpElement.style.display = 'none';
                    }
                }
            } catch (error) {
                console.error(`Erreur lors de la vérification du statut npm dev pour ${projectName}:`, error);

                // En cas d'erreur, masquer l'IP Next.js par sécurité
                if (nextjsIpElement) {
                    nextjsIpElement.style.display = 'none';
                }
            }
        }
    }
}

/**
 * Fonctions pour NPM et Next.js
 */
async function runNpmCommand(projectName, command) {
    // Créer une tâche dans le gestionnaire
    const task = startNpmTask ? startNpmTask(projectName, command) : null;

    const button = event.target.closest('button');
    const originalText = button.innerHTML;

    // Vérifier si npm run dev est déjà en cours
    if (command === 'dev') {
        try {
            const statusResponse = await fetch(`/check_nextjs_status/${projectName}`);
            const statusData = await statusResponse.json();

            if (statusData.dev_running) {
                if (task && typeof taskManager !== 'undefined') {
                    taskManager.completeTask(task.id, 'npm run dev était déjà en cours', false);
                }
                showError('npm run dev est déjà en cours d\'exécution');
                return;
            }
        } catch (error) {
            console.error('Erreur lors de la vérification du statut:', error);
        }
    }

    // Changer l'état du bouton
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>En cours...';

    // Mettre à jour la tâche
    if (task && typeof taskManager !== 'undefined') {
        taskManager.updateTask(task.id, {
            message: `Exécution de npm ${command}...`,
            progress: 25
        });
    }

    try {
        const response = await fetch(`/nextjs_npm/${projectName}/${command}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (data.success) {
            // Compléter la tâche avec succès
            if (task && typeof taskManager !== 'undefined') {
                taskManager.completeTask(task.id, `✅ ${data.message}`, true);
            }

            // Messages spécifiques selon la commande
            if (command === 'dev') {
                // Recharger les projets pour afficher l'IP Next.js
                setTimeout(() => loadProjects(), 2000);
            } else if (command === 'build') {
                // Recharger les projets pour afficher l'IP Next.js
                setTimeout(() => loadProjects(), 2000);
            }
        } else {
            // Compléter la tâche avec erreur
            if (task && typeof taskManager !== 'undefined') {
                taskManager.completeTask(task.id, `❌ ${data.message}`, false);
            }
        }
    } catch (error) {
        console.error(`Erreur npm ${command}:`, error);
        if (task && typeof taskManager !== 'undefined') {
            taskManager.completeTask(task.id, `❌ Erreur lors de l'exécution de npm ${command}`, false);
        }
    } finally {
        // Restaurer l'état du bouton
        button.disabled = false;
        button.innerHTML = originalText;
    }
}

/**
 * Fonction pour arrêter npm run dev
 */
async function stopNpmDev(projectName) {
    // Créer une tâche dans le gestionnaire
    const task = startStopNpmDevTask ? startStopNpmDevTask(projectName) : null;

    try {
        // Désactiver temporairement le bouton
        const projectItem = document.querySelector(`[data-project="${projectName}"]`);
        const nextjsCard = projectItem?.querySelector('.service-nextjs');
        const devButtons = nextjsCard?.querySelectorAll('button') || [];

        let devButton = null;
        for (const btn of devButtons) {
            const text = btn.textContent || '';
            if (text.includes('Stop Dev')) {
                devButton = btn;
                break;
            }
        }

        if (devButton) {
            devButton.disabled = true;
            devButton.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i><span>Arrêt...</span>';
        }

        // Mettre à jour la tâche
        if (task && typeof taskManager !== 'undefined') {
            taskManager.updateTask(task.id, {
                message: 'Arrêt de npm run dev...',
                progress: 50
            });
        }

        const response = await fetch(`/stop_nextjs_dev/${projectName}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (data.success) {
            if (task && typeof taskManager !== 'undefined') {
                taskManager.completeTask(task.id, data.message, true);
            }

            // Attendre 1 seconde puis vérifier le statut pour mettre à jour le bouton
            setTimeout(async () => {
                await checkNextjsDevStatus();
            }, 1000);
        } else {
            if (task && typeof taskManager !== 'undefined') {
                taskManager.completeTask(task.id, data.message, false);
            }

            // Restaurer le bouton en cas d'erreur
            if (devButton) {
                devButton.disabled = false;
                devButton.innerHTML = '<i class="fas fa-stop me-1"></i><span>Stop Dev</span>';
            }
        }
    } catch (error) {
        console.error('Erreur lors de l\'arrêt npm dev:', error);
        if (task && typeof taskManager !== 'undefined') {
            taskManager.completeTask(task.id, 'Erreur lors de l\'arrêt de npm run dev', false);
        }

        // Restaurer le bouton en cas d'erreur
        const projectItem = document.querySelector(`[data-project="${projectName}"]`);
        const nextjsCard = projectItem?.querySelector('.service-nextjs');
        const devButtons = nextjsCard?.querySelectorAll('button') || [];

        for (const btn of devButtons) {
            const text = btn.textContent || '';
            if (text.includes('Arrêt...')) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-stop me-1"></i><span>Stop Dev</span>';
                break;
            }
        }
    }
}

/**
 * Fonction pour redémarrer le conteneur Next.js
 */
async function startNextjsContainer(projectName) {
    // Créer une tâche dans le gestionnaire
    const task = startNextjsContainerTask ? startNextjsContainerTask(projectName) : null;

    try {
        // Mettre à jour la tâche
        if (task && typeof taskManager !== 'undefined') {
            taskManager.updateTask(task.id, {
                message: 'Démarrage du conteneur Next.js...',
                progress: 50
            });
        }

        const response = await fetch(`/start_nextjs_container/${projectName}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (data.success) {
            if (task && typeof taskManager !== 'undefined') {
                taskManager.completeTask(task.id, data.message, true);
            }

            // Attendre que le conteneur démarre puis vérifier le statut
            setTimeout(async () => {
                await checkNextjsDevStatus();
            }, 3000);
        } else {
            if (task && typeof taskManager !== 'undefined') {
                taskManager.completeTask(task.id, data.message, false);
            }
        }
    } catch (error) {
        console.error('Erreur lors du démarrage du conteneur:', error);
        if (task && typeof taskManager !== 'undefined') {
            taskManager.completeTask(task.id, 'Erreur lors du démarrage du conteneur Next.js', false);
        }
    }
}

/**
 * Fonctions pour les projets
 */
async function startProject(projectName) {
    // Détecter si c'est une instance dev
    const allCards = document.querySelectorAll('[data-project-name]');
    let isDevInstance = false;
    
    for (const card of allCards) {
        if (card.dataset.currentInstance === projectName) {
            isDevInstance = true;
            break;
        }
    }
    
    // Si c'est une instance dev, utiliser l'API dédiée
    if (isDevInstance) {
        console.log('Starting dev instance:', projectName);
        try {
            const response = await fetch(`/api/dev-instances/${encodeURIComponent(projectName)}/start`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'}
            });
            const data = await response.json();
            if (data.success) {
                // Recharger les projets pour mettre à jour l'UI
                if (typeof loadProjects === 'function') {
                    loadProjects();
                }
            } else {
                alert(`Erreur: ${data.error}`);
            }
        } catch (error) {
            console.error('Error starting instance:', error);
            alert(`Erreur: ${error.message}`);
        }
        return;
    }
    
    // Sinon, démarrer le projet normalement
    if (!taskManager) {
        console.error('TaskManager non disponible');
        return;
    }

    // Générer l'ID de la tâche
    const taskId = taskManager.generateTaskId('start_project', projectName);

    // Créer la tâche avec le callback défini dès la création
    const task = taskManager.createTask(taskId, 'Démarrage projet', 'start_project', projectName, {
        onStart: async (startedTask) => {
            await executeStartProject(projectName, startedTask);
        }
    });

    if (!task) {
        console.error('Impossible de créer la tâche');
        return;
    }

    console.log(`📋 Tâche de démarrage créée: ${task.id} (statut: ${task.status})`);
}

async function executeStartProject(projectName, task) {
    try {
        const button = document.querySelector(`button[onclick="startProject('${projectName}')"]`);
        if (button) {
            button.classList.add('loading');
            button.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Starting';
        }

        // Mettre à jour la tâche si disponible
        if (task && taskManager) {
            taskManager.updateTask(task.id, {
                message: `Démarrage des conteneurs Docker...`,
                progress: 25
            });
        }

        const response = await fetch(`/start_project/${projectName}`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            if (task && taskManager) {
                // Créer un message avec bouton "Voir le site"
                const message = `Projet ${projectName} démarré avec succès`;
                const actionButton = data.project_url ? {
                    text: 'Voir le site',
                    url: data.project_url,
                    icon: 'fas fa-external-link-alt'
                } : null;

                taskManager.completeTask(task.id, message, true, actionButton);
            } else {
                // Fallback: log dans la console
                console.log(`Projet ${projectName} démarré avec succès`);
            }
            // Mettre à jour seulement le statut du projet spécifique
            updateProjectStatus(projectName, 'running');
        } else {
            if (task && taskManager) {
                taskManager.completeTask(task.id, data.message || 'Erreur lors du démarrage', false);
            } else {
                // Fallback: log dans la console
                console.error(data.message || 'Erreur lors du démarrage');
            }
        }
    } catch (error) {
        console.error('Erreur démarrage:', error);
        if (task && taskManager) {
            taskManager.completeTask(task.id, 'Erreur lors du démarrage du projet', false);
        } else {
            // Fallback: log dans la console
            console.error('Erreur lors du démarrage du projet');
        }
    } finally {
        // Remettre le bouton à l'état normal
        const button = document.querySelector(`button[onclick="startProject('${projectName}')"]`);
        if (button) {
            button.classList.remove('loading');
            button.innerHTML = 'Start <i class="fas fa-play ms-1"></i>';
        }
    }
}

async function stopProject(projectName) {
    // Détecter si c'est une instance dev
    const allCards = document.querySelectorAll('[data-project-name]');
    let isDevInstance = false;
    
    for (const card of allCards) {
        if (card.dataset.currentInstance === projectName) {
            isDevInstance = true;
            break;
        }
    }
    
    // Si c'est une instance dev, utiliser l'API dédiée
    if (isDevInstance) {
        console.log('Stopping dev instance:', projectName);
        try {
            const response = await fetch(`/api/dev-instances/${encodeURIComponent(projectName)}/stop`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'}
            });
            const data = await response.json();
            if (data.success) {
                // Recharger les projets pour mettre à jour l'UI
                if (typeof loadProjects === 'function') {
                    loadProjects();
                }
            } else {
                alert(`Erreur: ${data.error}`);
            }
        } catch (error) {
            console.error('Error stopping instance:', error);
            alert(`Erreur: ${error.message}`);
        }
        return;
    }
    
    // Sinon, arrêter le projet normalement
    if (!taskManager) {
        console.error('TaskManager non disponible');
        return;
    }

    console.log(`🛑 Arrêt du projet: ${projectName}`);

    // Générer l'ID de la tâche
    const taskId = taskManager.generateTaskId('stop_project', projectName);

    // Créer la tâche avec le callback défini dès la création
    const task = taskManager.createTask(taskId, 'Arrêt projet', 'stop_project', projectName, {
        onStart: async (startedTask) => {
            console.log(`🛑 Exécution callback arrêt pour ${projectName}`);
            await executeStopProject(projectName, startedTask);
        }
    });

    if (!task) {
        console.error('Impossible de créer la tâche');
        return;
    }

    console.log(`📋 Tâche d'arrêt créée: ${task.id} (statut: ${task.status})`);
}

async function executeStopProject(projectName, task) {
    try {
        const button = document.querySelector(`button[onclick="stopProject('${projectName}')"]`);
        if (button) {
            button.classList.add('loading');
            button.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Stopping';
        }

        // Mettre à jour la tâche si disponible
        if (task && taskManager) {
            taskManager.updateTask(task.id, {
                message: `Arrêt des conteneurs Docker...`,
                progress: 25
            });
        }

        const response = await fetch(`/stop_project/${projectName}`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            if (task && taskManager) {
                taskManager.completeTask(task.id, `Projet ${projectName} arrêté avec succès`, true);
            } else {
                // Fallback: log dans la console
                console.log(`Projet ${projectName} arrêté avec succès`);
            }
            // Mettre à jour seulement le statut du projet spécifique
            updateProjectStatus(projectName, 'stopped');
        } else {
            if (task && taskManager) {
                taskManager.completeTask(task.id, data.message || 'Erreur lors de l\'arrêt', false);
            } else {
                // Fallback: log dans la console
                console.error(data.message || 'Erreur lors de l\'arrêt');
            }
        }
    } catch (error) {
        console.error('Erreur arrêt:', error);
        if (task && taskManager) {
            taskManager.completeTask(task.id, 'Erreur lors de l\'arrêt du projet', false);
        } else {
            // Fallback: log dans la console
            console.error('Erreur lors de l\'arrêt du projet');
        }
    } finally {
        // Remettre le bouton à l'état normal
        const button = document.querySelector(`button[onclick="stopProject('${projectName}')"]`);
        if (button) {
            button.classList.remove('loading');
            button.innerHTML = 'Running <i class="fas fa-stop ms-1"></i>';
        }
    }
}

async function restartProject(projectName) {
    // Créer une tâche dans le gestionnaire
    const task = (typeof startRestartTask === 'function' && typeof taskManager !== 'undefined' && taskManager)
        ? startRestartTask(projectName) : null;

    try {
        // Mettre à jour la tâche si disponible
        if (task && taskManager) {
            taskManager.updateTask(task.id, {
                message: `Redémarrage du projet ${projectName}...`,
                details: 'Arrêt des services...',
                progress: 10
            });
        }

        // Mettre le bouton en état de chargement
        const restartButton = document.querySelector(`button[onclick="restartProject('${projectName}')"]`);
        if (restartButton) {
            restartButton.classList.add('loading');
            restartButton.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Restarting...';
        }

        const response = await fetch(`/restart_project/${projectName}`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            // Mise à jour du progrès
            if (task && taskManager) {
                taskManager.updateTask(task.id, {
                    message: `Redémarrage de ${projectName}...`,
                    details: data.details ? JSON.stringify(data.details) : 'Services redémarrés avec succès',
                    progress: 90
                });
            }

            // Attendre un peu pour laisser le temps au redémarrage de se finaliser
            setTimeout(() => {
                if (task && taskManager) {
                    taskManager.completeTask(task.id, `✅ ${data.message}`, true, data.project_url);
                } else {
                    console.log(data.message);
                }

                // Recharger la liste des projets
                loadProjects();
            }, 1000);

        } else {
            if (task && taskManager) {
                let errorDetails = '';
                if (data.details && data.details.error_messages) {
                    errorDetails = data.details.error_messages.join(', ');
                }
                taskManager.completeTask(task.id, `❌ ${data.message}${errorDetails ? ' - ' + errorDetails : ''}`, false);
            } else {
                console.error(data.message);
            }
        }

    } catch (error) {
        console.error('Erreur lors du redémarrage:', error);
        if (task && taskManager) {
            taskManager.completeTask(task.id, `❌ Erreur lors du redémarrage: ${error.message}`, false);
        } else {
            console.error(`Erreur lors du redémarrage: ${error.message}`);
        }
    } finally {
        // Remettre le bouton à l'état normal
        const restartButton = document.querySelector(`button[onclick="restartProject('${projectName}')"]`);
        if (restartButton) {
            restartButton.classList.remove('loading');
            restartButton.innerHTML = 'Restart <i class="fas fa-redo me-1"></i>';
        }
    }
}

async function rebuildProject(projectName) {
    // Créer une tâche dans le gestionnaire
    const task = (typeof startRebuildTask === 'function' && typeof taskManager !== 'undefined' && taskManager)
        ? startRebuildTask(projectName) : null;

    try {
        // Mettre à jour la tâche si disponible
        if (task && taskManager) {
            taskManager.updateTask(task.id, {
                message: `Rebuild du projet ${projectName}...`,
                details: 'Reconstruction des conteneurs (volumes préservés)...',
                progress: 10
            });
        }

        const response = await fetch(`/rebuild_project/${projectName}`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            // Mise à jour du progrès
            if (task && taskManager) {
                taskManager.updateTask(task.id, {
                    message: `Rebuild de ${projectName}...`,
                    details: data.details ? JSON.stringify(data.details) : 'Conteneurs reconstruits avec succès (volumes préservés)',
                    progress: 90
                });
            }

            // Attendre un peu pour laisser le temps au rebuild de se finaliser
            setTimeout(() => {
                if (task && taskManager) {
                    taskManager.completeTask(task.id, `✅ ${data.message}`, true, data.project_url);
                } else {
                    console.log(data.message);
                }

                // Recharger la liste des projets
                loadProjects();
            }, 1000);

        } else {
            if (task && taskManager) {
                let errorDetails = '';
                if (data.details && data.details.error_messages) {
                    errorDetails = data.details.error_messages.join(', ');
                }
                taskManager.completeTask(task.id, `❌ ${data.message}${errorDetails ? ' - ' + errorDetails : ''}`, false);
            } else {
                console.error(data.message);
            }
        }

    } catch (error) {
        console.error('Erreur lors du rebuild:', error);
        if (task && taskManager) {
            taskManager.completeTask(task.id, `❌ Erreur lors du rebuild: ${error.message}`, false);
        } else {
            console.error(`Erreur lors du rebuild: ${error.message}`);
        }
    }
}

async function deleteProject(projectName) {
    console.log('deleteProject called with:', projectName);
    
    // D'abord, chercher si projectName est une instance dev
    // Chercher dans toutes les cards si l'une a currentInstance === projectName
    let projectCard = null;
    let isDevInstance = false;
    let targetName = projectName;
    
    // Chercher toutes les project cards
    const allCards = document.querySelectorAll('[data-project-name]');
    for (const card of allCards) {
        // Cas 1: projectName est le nom d'une instance active
        if (card.dataset.currentInstance === projectName) {
            projectCard = card;
            isDevInstance = true;
            targetName = projectName;
            console.log('Instance dev trouvée via currentInstance:', projectName);
            break;
        }
        // Cas 2: projectName est le nom du projet parent
        if (card.dataset.projectName === projectName) {
            projectCard = card;
            isDevInstance = card.dataset.isDevInstance === 'true';
            targetName = isDevInstance ? card.dataset.currentInstance : projectName;
            console.log('Project card trouvée:', {projectName, isDevInstance, targetName});
            break;
        }
    }
    
    // Si c'est une instance dev, utiliser la fonction dédiée
    if (isDevInstance && targetName) {
        console.log('Redirection vers deleteDevInstance:', targetName);
        if (typeof window.deleteDevInstance === 'function') {
            return window.deleteDevInstance(targetName);
        } else {
            console.error('window.deleteDevInstance not found');
            alert('Erreur: fonction de suppression d\'instance non disponible');
            return;
        }
    }
    
    // Sinon, supprimer le projet normalement
    const itemType = 'le projet';

    if (!confirm(`Êtes-vous sûr de vouloir supprimer ${itemType} ${projectName} ?`)) {
        return;
    }

    // Créer une tâche dans le gestionnaire
    const task = (typeof startDeleteTask === 'function' && typeof taskManager !== 'undefined' && taskManager)
        ? startDeleteTask(projectName) : null;

    try {
        // Mettre à jour la tâche si disponible
        if (task && taskManager) {
            taskManager.updateTask(task.id, {
                message: `Suppression du projet ${projectName}...`,
                details: 'Arrêt des conteneurs Docker...',
                progress: 20
            });
        }

        // Appeler la route de suppression de projet
        const deleteUrl = `/delete_project/${encodeURIComponent(projectName)}`;
        
        const response = await fetch(deleteUrl, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        // Vérifier si la réponse est bien du JSON
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('La réponse du serveur n\'est pas au format JSON');
        }
        
        const data = await response.json();

        if (data.success) {
            // Mise à jour du progrès
            if (task && taskManager) {
                taskManager.updateTask(task.id, {
                    message: `Suppression en cours...`,
                    details: data.details ? JSON.stringify(data.details) : 'Nettoyage des fichiers...',
                    progress: 80
                });
            }

            // Attendre un peu pour laisser le temps à la suppression de se finaliser
            setTimeout(() => {
                if (task && taskManager) {
                    taskManager.completeTask(task.id, `✅ ${data.message}`, true);
                } else {
                    // Fallback: utiliser showSuccess si disponible
                    if (typeof showSuccess === 'function') {
                        showSuccess(data.message);
                    }
                }

                // Recharger la liste des projets
                loadProjects();
            }, 1000);

            // Afficher les détails si disponibles
            if (data.details && data.details.messages && data.details.messages.length > 0) {
                console.log('Détails de la suppression:', data.details.messages);
            }

        } else {
            if (task && taskManager) {
                let errorDetails = '';
                if (data.details && data.details.error_messages) {
                    errorDetails = data.details.error_messages.join(', ');
                }
                taskManager.completeTask(task.id, `❌ ${data.message}${errorDetails ? ' - ' + errorDetails : ''}`, false);
            } else {
                // Fallback: utiliser showError si disponible
                if (typeof showError === 'function') {
                    showError(data.message);
                }
            }

            // Afficher les détails de l'erreur
            if (data.details && data.details.error_messages) {
                console.error('Erreurs lors de la suppression:', data.details.error_messages);
            }
        }
    } catch (error) {
        console.error('Erreur suppression:', error);
        if (task && taskManager) {
            taskManager.completeTask(task.id, `❌ Erreur lors de la suppression du projet: ${error.message}`, false);
        } else {
            // Fallback: utiliser showError si disponible
            if (typeof showError === 'function') {
                showError('Erreur lors de la suppression du projet');
            }
        }
    }
}

/**
 * Fonctions utilitaires pour les uploads et formulaires
 */
function initFileUpload() {
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('wp_migrate_archive');
    if (!uploadZone || !fileInput) return;

    const uploadContent = uploadZone.querySelector('.upload-content');
    const fileInfo = uploadZone.querySelector('.upload-file-info');
    const fileName = fileInfo?.querySelector('.file-name');

    // Clic sur la zone d'upload
    uploadZone.addEventListener('click', function () {
        fileInput.click();
    });

    // Changement de fichier
    fileInput.addEventListener('change', function (e) {
        const file = e.target.files[0];
        if (file) {
            showFileInfo(file);
        }
    });

    // Drag & Drop
    uploadZone.addEventListener('dragover', function (e) {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });

    uploadZone.addEventListener('dragleave', function (e) {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
    });

    uploadZone.addEventListener('drop', function (e) {
        e.preventDefault();
        uploadZone.classList.remove('dragover');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            const file = files[0];
            fileInput.files = files;
            showFileInfo(file);
        }
    });

    function showFileInfo(file) {
        const allowedExtensions = ['.zip', '.sql', '.gz'];

        // Vérifier l'extension
        const extension = file.name.toLowerCase().substring(file.name.lastIndexOf('.'));
        if (!allowedExtensions.includes(extension)) {
            showError('Type de fichier non autorisé. Utilisez .zip, .sql ou .gz');
            fileInput.value = '';
            return;
        }

        // Vérifier la taille (8GB max)
        if (file.size > 8 * 1024 * 1024 * 1024) {
            showError('Fichier trop volumineux. Taille maximale : 8GB');
            fileInput.value = '';
            return;
        }

        // Afficher les informations du fichier
        if (fileName && uploadContent && fileInfo) {
            fileName.textContent = file.name;
            uploadContent.classList.add('d-none');
            fileInfo.classList.remove('d-none');
        }
    }
}

function clearFile() {
    const fileInput = document.getElementById('wp_migrate_archive');
    const uploadZone = document.getElementById('upload-zone');
    if (!fileInput || !uploadZone) return;

    const uploadContent = uploadZone.querySelector('.upload-content');
    const fileInfo = uploadZone.querySelector('.upload-file-info');

    fileInput.value = '';
    if (uploadContent && fileInfo) {
        uploadContent.classList.remove('d-none');
        fileInfo.classList.add('d-none');
    }
}

function initCreateProjectForm() {
    const form = document.getElementById('createProjectForm');
    if (!form) return;

    form.addEventListener('submit', function (e) {
        e.preventDefault();

        const formData = new FormData(form);
        const submitButton = form.querySelector('button[type="submit"]');

        // Validation
        const projectName = formData.get('project_name');
        if (!projectName || !projectName.match(/^[a-zA-Z0-9-_]+$/)) {
            showError('Le nom du projet doit contenir uniquement des lettres, chiffres, tirets et underscores');
            return;
        }

        // Fermer le modal immédiatement après le clic
        const modal = bootstrap.Modal.getInstance(document.getElementById('createProjectModal'));
        if (modal) {
            modal.hide();
        }

        // Créer une tâche de création de projet
        const task = (typeof startCreateProjectTask === 'function') ? startCreateProjectTask() : null;

        // Désactiver le bouton et afficher le loader
        if (submitButton) {
            submitButton.classList.add('loading');
            submitButton.disabled = true;
        }

        // Mettre à jour la tâche
        if (task && typeof taskManager !== 'undefined') {
            taskManager.updateTask(task.id, {
                message: `Création du projet "${projectName}"...`,
                details: `Nom: ${projectName}`,
                progress: 10
            });
        }

        // Envoyer la requête
        fetch('/create_project', {
            method: 'POST',
            body: formData
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (task && typeof taskManager !== 'undefined') {
                        taskManager.completeTask(task.id, 'Projet créé avec succès !', true);
                    }

                    // Réinitialiser le formulaire
                    form.reset();
                    clearFile();
                    // Recharger les projets
                    setTimeout(() => loadProjects(), 1000);
                } else {
                    if (task && typeof taskManager !== 'undefined') {
                        taskManager.completeTask(task.id, data.message || 'Erreur lors de la création du projet', false);
                    }
                }
            })
            .catch(error => {
                console.error('Erreur:', error);
                if (task && typeof taskManager !== 'undefined') {
                    taskManager.completeTask(task.id, 'Erreur lors de la création du projet', false);
                }
            })
            .finally(() => {
                if (submitButton) {
                    submitButton.classList.remove('loading');
                    submitButton.disabled = false;
                }
            });
    });

    // Réinitialiser le formulaire à la fermeture du modal
    const modal = document.getElementById('createProjectModal');
    if (modal) {
        modal.addEventListener('hidden.bs.modal', function () {
            form.reset();
            clearFile();
        });
    }
}

/**
 * Fonction pour corriger les permissions WordPress (www-data:www-data avec chmod 775)
 */
async function fixWordPressPermissions(projectName) {
    if (!taskManager) {
        console.error('TaskManager non disponible');
        return;
    }

    console.log(`🔧 Correction des permissions WordPress pour: ${projectName}`);

    // Générer l'ID de la tâche
    const taskId = taskManager.generateTaskId('fix_wp_permissions', projectName);

    // Créer la tâche avec le callback défini dès la création
    const task = taskManager.createTask(taskId, 'Correction permissions WP', 'fix_wp_permissions', projectName, {
        onStart: async (startedTask) => {
            console.log(`🔧 Exécution correction permissions pour ${projectName}`);
            await executeFixWordPressPermissions(projectName, startedTask);
        }
    });

    if (!task) {
        console.error('Impossible de créer la tâche');
        return;
    }

    console.log(`📋 Tâche de correction permissions créée: ${task.id} (statut: ${task.status})`);
}

async function executeFixWordPressPermissions(projectName, task) {
    try {
        const button = document.querySelector(`button[onclick="fixWordPressPermissions('${projectName}')"]`);
        if (button) {
            button.classList.add('loading');
            button.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Correction...';
        }

        // Mettre à jour la tâche si disponible
        if (task && taskManager) {
            taskManager.updateTask(task.id, {
                message: `Correction des permissions pour wp-content...`,
                progress: 25
            });
        }

        const response = await fetch(`/fix_wordpress_permissions/${projectName}`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            if (task && taskManager) {
                const message = `Permissions WordPress corrigées avec succès`;
                const details = data.commands_executed ? data.commands_executed.join(', ') : '';
                taskManager.completeTask(task.id, message, true);
            }
            console.log(`✅ Permissions WordPress corrigées pour ${projectName}`);
        } else {
            if (task && taskManager) {
                const errorMsg = data.errors ? data.errors.join(', ') : data.message;
                taskManager.completeTask(task.id, errorMsg, false);
            }
            console.error(`❌ ${data.message}`);
        }
    } catch (error) {
        console.error('Erreur correction permissions:', error);
        if (task && taskManager) {
            taskManager.completeTask(task.id, 'Erreur lors de la correction des permissions', false);
        }
    } finally {
        // Remettre le bouton à l'état normal
        const button = document.querySelector(`button[onclick="fixWordPressPermissions('${projectName}')"]`);
        if (button) {
            button.classList.remove('loading');
            button.innerHTML = '<i class="fas fa-wrench me-1"></i>Fix Permissions';
        }
    }
}

/**
 * Ajouter un log à la modale d'import
 */
function addImportLog(message, progress, status) {
    const timestamp = new Date().toLocaleTimeString('fr-FR');
    const logEntry = {
        timestamp,
        message,
        progress,
        status
    };
    
    importLogsBuffer.push(logEntry);
    
    console.log('📝 Log ajouté:', message, '- Buffer size:', importLogsBuffer.length);
    
    // Si la modale est ouverte, mettre à jour l'affichage
    const logsModal = document.getElementById('importLogsModal');
    if (logsModal && logsModal.classList.contains('show')) {
        updateImportLogsDisplay();
    }
}

/**
 * Mettre à jour l'affichage des logs dans la modale
 */
function updateImportLogsDisplay() {
    const logsContent = document.getElementById('import-logs-content');
    if (!logsContent) {
        console.warn('⚠️ Élément import-logs-content non trouvé');
        return;
    }
    
    console.log('🔄 Mise à jour de l\'affichage des logs, buffer:', importLogsBuffer.length, 'entrées');
    
    let html = '';
    importLogsBuffer.forEach(log => {
        let color = '#d4d4d4'; // Couleur par défaut
        let icon = '📊';
        
        if (log.status === 'complete') {
            color = '#4ec9b0';
            icon = '✅';
        } else if (log.status === 'error') {
            color = '#f48771';
            icon = '❌';
        } else if (log.status === 'importing') {
            color = '#6a9fb5';
            icon = '🔄';
        } else if (log.message.includes('✅')) {
            color = '#4ec9b0';
        } else if (log.message.includes('❌') || log.message.includes('⚠️')) {
            color = '#f48771';
        } else if (log.message.includes('🔄')) {
            color = '#6a9fb5';
        }
        
        const progressBar = log.progress ? ` [${log.progress}%]` : '';
        html += `<div style="color: ${color}; margin-bottom: 4px;">[${log.timestamp}]${progressBar} ${icon} ${log.message}</div>`;
    });
    
    logsContent.innerHTML = html || '<div style="color: #6a9fb5;">📡 Aucun log disponible</div>';
    
    // Auto-scroll vers le bas
    logsContent.scrollTop = logsContent.scrollHeight;
    
    console.log('✅ Affichage des logs mis à jour');
}

/**
 * Afficher la modale des logs d'import
 */
function showImportLogsModal() {
    console.log('📋 showImportLogsModal appelée');
    
    // Vérifier que Bootstrap est disponible
    if (typeof bootstrap === 'undefined' || !bootstrap.Modal) {
        console.error('❌ Bootstrap n\'est pas disponible');
        // Réessayer après un court délai
        setTimeout(() => {
            if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
                showImportLogsModal();
            }
        }, 500);
        return;
    }
    
    const modalElement = document.getElementById('importLogsModal');
    if (!modalElement) {
        console.error('❌ Élément importLogsModal non trouvé dans le DOM');
        return;
    }
    
    console.log('✅ Élément modal trouvé');
    
    // Si la modale est déjà ouverte, juste mettre à jour
    if (modalElement.classList.contains('show')) {
        console.log('📋 Modale déjà ouverte, mise à jour seulement');
        updateImportLogsDisplay();
        updateStopImportButton();
        return;
    }
    
    // Créer une nouvelle instance de la modale
    try {
        // Disposer l'ancienne instance si elle existe
        if (importLogsModalInstance) {
            try {
                importLogsModalInstance.dispose();
            } catch (e) {
                // Ignorer les erreurs de dispose
            }
            importLogsModalInstance = null;
        }
        
        // Vérifier si une instance existe déjà sur l'élément
        const existingInstance = bootstrap.Modal.getInstance(modalElement);
        if (existingInstance) {
            importLogsModalInstance = existingInstance;
        } else {
            importLogsModalInstance = new bootstrap.Modal(modalElement, {
                backdrop: 'static',
                keyboard: true
            });
        }
        
        console.log('✅ Instance Bootstrap Modal obtenue');
        
        // Écouter l'événement de fermeture pour réinitialiser l'instance
        modalElement.removeEventListener('hidden.bs.modal', onModalHidden);
        modalElement.addEventListener('hidden.bs.modal', onModalHidden);
        
        const projectNameSpan = document.getElementById('import-logs-project-name');
        if (projectNameSpan) {
            projectNameSpan.textContent = currentImportProject || window.currentImportProject || '-';
        }
        
        updateImportLogsDisplay();
        updateStopImportButton();
        
        importLogsModalInstance.show();
        console.log('✅ Modale affichée');
        
    } catch (error) {
        console.error('❌ Erreur lors de la création/affichage de la modale:', error);
        console.error('Stack:', error.stack);
    }
}

// Fonction séparée pour l'événement de fermeture
function onModalHidden() {
    console.log('🚪 Modale fermée');
    importLogsModalInstance = null;
    updateStopImportButton();
}

/**
 * Masquer la modale des logs d'import
 */
function hideImportLogsModal() {
    if (importLogsModalInstance) {
        try {
            importLogsModalInstance.hide();
        } catch (e) {
            console.warn('Erreur lors de la fermeture de la modale:', e);
        }
    }
}

/**
 * Effacer les logs d'import
 */
function clearImportLogs() {
    if (confirm('Êtes-vous sûr de vouloir effacer tous les logs ?')) {
        importLogsBuffer = [];
        updateImportLogsDisplay();
    }
}

/**
 * Mettre à jour la visibilité du bouton d'arrêt d'import
 */
function updateStopImportButton() {
    const stopBtn = document.getElementById('stop-import-btn');
    if (!stopBtn) return;
    
    // Vérifier s'il y a une tâche d'import en cours
    let hasRunningImport = false;
    if (typeof taskManager !== 'undefined' && taskManager) {
        for (const [taskId, task] of taskManager.tasks.entries()) {
            if (task.type === 'import_db' && task.status === 'running') {
                hasRunningImport = true;
                currentImportTaskId = taskId;
                break;
            }
        }
    }
    
    stopBtn.style.display = hasRunningImport ? 'inline-block' : 'none';
}

/**
 * Arrêter l'import en cours
 */
async function stopImport() {
    if (!currentImportProject) {
        showToast('Aucun import en cours', 'error');
        return;
    }
    
    if (!confirm('Êtes-vous sûr de vouloir arrêter l\'import en cours ?')) {
        return;
    }
    
    const stopBtn = document.getElementById('stop-import-btn');
    if (stopBtn) {
        stopBtn.disabled = true;
        stopBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Arrêt en cours...';
    }
    
    try {
        const response = await fetch(`/api/database/stop-import/${currentImportProject}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            addImportLog('❌ Import arrêté par l\'utilisateur', null, 'error');
            showToast('Import arrêté avec succès', 'success');
            
            // Marquer la tâche comme échouée
            if (currentImportTaskId && typeof taskManager !== 'undefined' && taskManager) {
                taskManager.completeTask(currentImportTaskId, 'Import arrêté par l\'utilisateur', false);
            }
        } else {
            showToast(data.message || 'Erreur lors de l\'arrêt de l\'import', 'error');
        }
    } catch (error) {
        console.error('Erreur lors de l\'arrêt de l\'import:', error);
        showToast('Erreur de connexion lors de l\'arrêt de l\'import', 'error');
    } finally {
        if (stopBtn) {
            stopBtn.disabled = false;
            stopBtn.innerHTML = '<i class="fas fa-stop me-1"></i> Arrêter l\'import';
        }
        updateStopImportButton();
    }
}

// Initialisation principale
document.addEventListener('DOMContentLoaded', function () {
    
    initProgressTracking();
    loadProjects();

    // Initialiser la gestion des fichiers
    initFileUpload();

    // Initialiser la gestion du formulaire
    initCreateProjectForm();
    
    // Initialiser les gestionnaires WP-CLI
    initWPCLIHandlers();

    // Rafraîchir automatiquement toutes les 30 secondes
    setInterval(loadProjects, 30000);

    // Vérifier le statut des boutons npm run dev toutes les 10 secondes
    setInterval(checkNextjsDevStatus, 10000);
});

// Exposer les fonctions globalement pour qu'elles soient accessibles depuis d'autres scripts
window.showImportLogsModal = showImportLogsModal;
window.hideImportLogsModal = hideImportLogsModal;
window.addImportLog = addImportLog;
window.updateImportLogsDisplay = updateImportLogsDisplay;
window.clearImportLogs = clearImportLogs;
window.stopImport = stopImport;
window.importLogsBuffer = importLogsBuffer;
window.currentImportProject = currentImportProject;
window.projectsImporting = projectsImporting;
window.updateProjectButtonsState = updateProjectButtonsState;
window.showImportInProgressAlert = showImportInProgressAlert;
window.unlockAllImports = unlockAllImports;
window.checkImportTimeouts = checkImportTimeouts;

/**
 * Exécute une commande WP-CLI depuis le menu
 */
function runWPCLICommand(projectName, command) {
    console.log(`%c[runWPCLICommand] ▶️ Project: ${projectName}, Command: ${command}`, 'color: #2196F3; font-weight: bold;');
    
    if (!projectName || !command) {
        console.error('[runWPCLICommand] ❌ Paramètres manquants:', { projectName, command });
        showToast('Erreur: paramètres manquants', 'error');
        return;
    }
    
    if (command === 'fix-permissions') {
        console.log('[runWPCLICommand] 🔧 Appel de fixWordPressPermissions...');
        if (typeof fixWordPressPermissions === 'function') {
            fixWordPressPermissions(projectName);
        } else if (typeof window.fixWordPressPermissions === 'function') {
            window.fixWordPressPermissions(projectName);
        } else {
            console.error('[runWPCLICommand] ❌ fixWordPressPermissions non définie');
            showToast('Erreur: fonction fix permissions non disponible', 'error');
        }
    } else {
        if (typeof executeQuickWPCLI === 'function') {
            executeQuickWPCLI(projectName, command);
        } else if (typeof window.executeQuickWPCLI === 'function') {
            window.executeQuickWPCLI(projectName, command);
        } else {
            console.error('[runWPCLICommand] ❌ executeQuickWPCLI non définie');
            showToast('Erreur: fonction WP-CLI non disponible', 'error');
        }
    }
}

// Variable globale pour le projet du sous-menu
let wpcliSubmenuProject = null;
let wpcliSubmenuElement = null;

/**
 * Crée le sous-menu WP-CLI s'il n'existe pas
 */
function createWPCLISubmenu() {
    if (wpcliSubmenuElement) return wpcliSubmenuElement;
    
    const submenu = document.createElement('div');
    submenu.id = 'wpcli-floating-submenu';
    submenu.className = 'dropdown-menu dropdown-menu-dark';
    submenu.style.cssText = 'position: fixed; z-index: 99999; min-width: 220px; display: none;';
    submenu.innerHTML = `
        <a class="dropdown-item" href="#" data-cmd="plugin list"><i class="fas fa-plug me-2"></i>Lister les Plugins</a>
        <a class="dropdown-item" href="#" data-cmd="theme list"><i class="fas fa-palette me-2"></i>Lister les Thèmes</a>
        <a class="dropdown-item" href="#" data-cmd="user list"><i class="fas fa-users me-2"></i>Lister les Utilisateurs</a>
        <hr class="dropdown-divider">
        <a class="dropdown-item" href="#" data-cmd="terminal"><i class="fas fa-terminal me-2"></i>Terminal WP-CLI</a>
    `;
    document.body.appendChild(submenu);
    
    // Event listener pour les items du sous-menu
    submenu.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        const item = e.target.closest('.dropdown-item');
        if (item) {
            const cmd = item.dataset.cmd;
            if (cmd && wpcliSubmenuProject) {
                runSubmenuCommand(cmd);
            }
        }
    });
    
    wpcliSubmenuElement = submenu;
    return submenu;
}

/**
 * Ouvre le sous-menu WP-CLI flottant
 */
function openWPCLISubmenu(event, projectName) {
    console.log(`[WPCLI Submenu] Opening for project: ${projectName}`);
    
    if (!projectName) {
        console.error('[WPCLI Submenu] Missing project name');
        return;
    }
    
    event.preventDefault();
    event.stopPropagation();
    
    wpcliSubmenuProject = projectName;
    
    // Fermer le sous-menu WP Debug s'il est ouvert
    if (window.wpDebugSubmenuElement && window.wpDebugSubmenuElement.style.display === 'block') {
        window.wpDebugSubmenuElement.style.display = 'none';
    }
    
    // Créer ou récupérer le sous-menu
    const submenu = createWPCLISubmenu();
    
    // Récupérer le trigger
    const trigger = event.target.closest('a') || event.target;
    const rect = trigger.getBoundingClientRect();
    
    // Calculer la position
    let left = rect.right + 10;
    let top = rect.top + window.scrollY;
    
    // Ajuster si pas assez d'espace à droite
    if (window.innerWidth - rect.right < 250) {
        left = rect.left - 230;
    }
    
    // Ajuster si pas assez d'espace en bas
    if (rect.top + 200 > window.innerHeight) {
        top = window.innerHeight + window.scrollY - 210;
    }
    
    // Positionner et afficher
    submenu.style.left = `${left}px`;
    submenu.style.top = `${top}px`;
    submenu.style.display = 'block';
    
    console.log(`[WPCLI Submenu] Positioned at (${left}, ${top})`);
}

/**
 * Exécute une commande depuis le sous-menu WP-CLI
 */
function runSubmenuCommand(command) {
    console.log(`[WPCLI Submenu] Running command: ${command} for project: ${wpcliSubmenuProject}`);
    
    // Fermer le sous-menu
    if (wpcliSubmenuElement) {
        wpcliSubmenuElement.style.display = 'none';
    }
    
    if (!wpcliSubmenuProject) {
        console.error('[WPCLI Submenu] No project selected');
        showToast('Erreur: aucun projet sélectionné', 'error');
        return;
    }
    
    if (command === 'terminal') {
        console.log('[WPCLI Submenu] Opening terminal...');
        if (typeof openWPCLIModal === 'function') {
            openWPCLIModal(wpcliSubmenuProject);
        } else if (typeof window.openWPCLIModal === 'function') {
            window.openWPCLIModal(wpcliSubmenuProject);
        } else {
            console.error('[WPCLI Submenu] openWPCLIModal not defined');
            showToast('Erreur: fonction terminal non disponible', 'error');
        }
    } else {
        console.log('[WPCLI Submenu] Executing WP-CLI command...');
        if (typeof executeQuickWPCLI === 'function') {
            executeQuickWPCLI(wpcliSubmenuProject, command);
        } else if (typeof window.executeQuickWPCLI === 'function') {
            window.executeQuickWPCLI(wpcliSubmenuProject, command);
        } else {
            console.error('[WPCLI Submenu] executeQuickWPCLI not defined');
            showToast('Erreur: fonction WP-CLI non disponible', 'error');
        }
    }
}

// Exposer les fonctions globalement
window.runWPCLICommand = runWPCLICommand;
window.openWPCLISubmenu = openWPCLISubmenu;
window.runSubmenuCommand = runSubmenuCommand;

/**
 * Initialisation des gestionnaires WP-CLI
 * Appelée depuis le DOMContentLoaded principal
 */
function initWPCLIHandlers() {
    
    // Event delegation pour les commandes WP-CLI (.wpcli-cmd)
    document.addEventListener('click', function(e) {
        // Log de debug pour tout clic
        if (e.target.closest('.dropdown-item')) {
        }
        
        // Gérer les clics sur .wpcli-cmd
        const wpcliCmd = e.target.closest('.wpcli-cmd');
        if (wpcliCmd) {
            e.preventDefault();
            e.stopPropagation();
            
            const projectName = wpcliCmd.dataset.project;
            const cmd = wpcliCmd.dataset.cmd;
            
            console.log(`%c[WP-CLI CMD] 🎯 Command clicked: ${cmd} for ${projectName}`, 'color: #4CAF50; font-weight: bold;');
            
            if (projectName && cmd) {
                runWPCLICommand(projectName, cmd);
            } else {
                console.error('[WP-CLI CMD] ❌ Missing data:', { projectName, cmd });
            }
            return;
        }
        
        // Gérer les clics sur .wpcli-submenu-btn
        const submenuBtn = e.target.closest('.wpcli-submenu-btn');
        if (submenuBtn) {
            e.preventDefault();
            e.stopPropagation();
            
            const projectName = submenuBtn.getAttribute('data-project') || submenuBtn.dataset.project;
            console.log(`%c[WP-CLI SUBMENU] 🎯 Submenu clicked for: ${projectName}`, 'color: #2196F3; font-weight: bold;');
            
            if (projectName) {
                openWPCLISubmenu(e, projectName);
            } else {
                console.error('[WP-CLI SUBMENU] ❌ No project name found');
            }
            return;
        }
        
        // Gérer les clics sur .wpdebug-submenu-btn
        const wpDebugBtn = e.target.closest('.wpdebug-submenu-btn');
        if (wpDebugBtn) {
            e.preventDefault();
            e.stopPropagation();
            
            const projectName = wpDebugBtn.getAttribute('data-project') || wpDebugBtn.dataset.project;
            console.log(`%c[WP DEBUG SUBMENU] 🐛 Submenu clicked for: ${projectName}`, 'color: #FF9800; font-weight: bold;');
            
            if (projectName) {
                if (typeof openWPDebugSubmenu === 'function') {
                    openWPDebugSubmenu(e, projectName);
                } else if (typeof window.openWPDebugSubmenu === 'function') {
                    window.openWPDebugSubmenu(e, projectName);
                } else {
                    console.error('[WP DEBUG SUBMENU] ❌ openWPDebugSubmenu not defined');
                }
            } else {
                console.error('[WP DEBUG SUBMENU] ❌ No project name found');
            }
            return;
        }
        
        // Fermer les sous-menus quand on clique ailleurs
        const clickedInsideWPDebug = e.target.closest('#wpdebug-floating-submenu') || e.target.closest('.wpdebug-submenu-btn');
        const clickedInsideWPCLI = e.target.closest('#wpcli-floating-submenu') || e.target.closest('.wpcli-submenu-btn');
        const clickedInsideDropdown = e.target.closest('.dropdown-menu');
        
        
        // Fermer le sous-menu WP Debug si on clique ailleurs (mais pas dans le dropdown principal)
        if (window.wpDebugSubmenuElement && window.wpDebugSubmenuElement.style.display === 'block') {
            if (!clickedInsideWPDebug && !clickedInsideDropdown) {
                window.wpDebugSubmenuElement.style.display = 'none';
                console.log('[WP Debug] ✅ Submenu closed (outside click)');
            } else {
                console.log('[WP Debug] ⏸️ Submenu kept open (clicked inside)');
            }
        }
        
        // Fermer le sous-menu WP-CLI si on clique ailleurs
        if (wpcliSubmenuElement && wpcliSubmenuElement.style.display === 'block') {
            if (!clickedInsideWPCLI && !clickedInsideDropdown) {
                wpcliSubmenuElement.style.display = 'none';
            }
        }
    }, true); // UseCapture = true pour capturer l'événement avant Bootstrap
    
    // Empêcher la fermeture du dropdown si un sous-menu est ouvert
    document.addEventListener('hide.bs.dropdown', function(e) {
        // Vérifier si un sous-menu WP Debug ou WP-CLI est ouvert
        const wpDebugOpen = window.wpDebugSubmenuElement && window.wpDebugSubmenuElement.style.display === 'block';
        const wpCliOpen = wpcliSubmenuElement && wpcliSubmenuElement.style.display === 'block';
        
        // Si un sous-menu est ouvert, empêcher la fermeture du dropdown principal
        if (wpDebugOpen || wpCliOpen) {
            e.preventDefault();
            console.log('[Dropdown] Fermeture empêchée (sous-menu ouvert)');
            return false;
        }
        
        // Sinon, fermer normalement et nettoyer les sous-menus
        if (wpcliSubmenuElement) {
            wpcliSubmenuElement.style.display = 'none';
        }
        if (window.wpDebugSubmenuElement) {
            window.wpDebugSubmenuElement.style.display = 'none';
            console.log('[WP Debug] Submenu closed (dropdown hidden)');
        }
    });
    
    // Positionner intelligemment les dropdowns (haut ou bas selon l'espace)
    document.addEventListener('show.bs.dropdown', function(e) {
        const dropdown = e.target;
        const menu = dropdown.querySelector('.dropdown-menu');
        
        if (!menu) return;
        
        // Réinitialiser les classes
        dropdown.classList.remove('dropup');
        
        setTimeout(() => {
            const rect = dropdown.getBoundingClientRect();
            const menuHeight = menu.offsetHeight;
            const spaceBelow = window.innerHeight - rect.bottom;
            const spaceAbove = rect.top;
            
            // Si pas assez d'espace en bas et plus d'espace en haut, ouvrir vers le haut
            if (spaceBelow < menuHeight && spaceAbove > spaceBelow) {
                dropdown.classList.add('dropup');
            }
        }, 10);
    });
    
    console.log('[Init WP-CLI] ✅ Gestionnaires configurés avec useCapture=true');
}