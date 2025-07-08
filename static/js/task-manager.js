// Gestionnaire de tâches en cours avec persistance
class TaskManager {
    constructor() {
        this.tasks = new Map();
        this.toasterContainer = null;
        this.init();
    }

    init() {
        // Initialiser le container
        this.toasterContainer = document.getElementById('task-toaster');
        
        // Charger les tâches sauvegardées
        this.loadTasksFromStorage();
        
        // Nettoyer les tâches anciennes au démarrage
        this.cleanupOldTasks();
        
        // Mettre à jour l'affichage
        this.renderTasks();
        
        // Nettoyer automatiquement toutes les 30 secondes
        setInterval(() => this.cleanupOldTasks(), 30000);
    }

    // Créer une nouvelle tâche
    createTask(taskId, taskName, taskType, projectName = null) {
        const task = {
            id: taskId,
            name: taskName,
            type: taskType, // 'npm_install', 'npm_dev', 'npm_build', 'create_project', 'import_db', 'export_db', 'start_project', 'stop_project'
            projectName: projectName,
            status: 'running', // 'running', 'completed', 'error'
            progress: 0,
            message: 'Initialisation...',
            details: '',
            startTime: Date.now(),
            lastUpdate: Date.now()
        };

        this.tasks.set(taskId, task);
        this.saveTasksToStorage();
        this.renderTasks();
        
        return task;
    }

    // Mettre à jour une tâche
    updateTask(taskId, updates) {
        const task = this.tasks.get(taskId);
        if (!task) return;

        Object.assign(task, updates, { lastUpdate: Date.now() });
        this.tasks.set(taskId, task);
        this.saveTasksToStorage();
        this.renderTasks();
    }

    // Marquer une tâche comme terminée
    completeTask(taskId, finalMessage = null, success = true) {
        const task = this.tasks.get(taskId);
        if (!task) return;

        task.status = success ? 'completed' : 'error';
        task.progress = 100;
        task.lastUpdate = Date.now();
        
        if (finalMessage) {
            task.message = finalMessage;
        }

        this.tasks.set(taskId, task);
        this.saveTasksToStorage();
        this.renderTasks();

        // Auto-supprimer après 4 secondes
        setTimeout(() => {
            this.removeTask(taskId);
        }, 4000);
    }

    // Supprimer une tâche
    removeTask(taskId) {
        this.tasks.delete(taskId);
        this.saveTasksToStorage();
        this.renderTasks();
    }

    // Obtenir une tâche
    getTask(taskId) {
        return this.tasks.get(taskId);
    }

    // Vérifier si une tâche existe et est en cours
    hasRunningTask(taskType, projectName = null) {
        for (const task of this.tasks.values()) {
            if (task.type === taskType && 
                task.status === 'running' && 
                (projectName === null || task.projectName === projectName)) {
                return true;
            }
        }
        return false;
    }

    // Sauvegarder les tâches en localStorage
    saveTasksToStorage() {
        const tasksArray = Array.from(this.tasks.values());
        localStorage.setItem('wp-launcher-tasks', JSON.stringify(tasksArray));
    }

    // Charger les tâches depuis localStorage
    loadTasksFromStorage() {
        const stored = localStorage.getItem('wp-launcher-tasks');
        if (stored) {
            try {
                const tasksArray = JSON.parse(stored);
                this.tasks.clear();
                tasksArray.forEach(task => {
                    this.tasks.set(task.id, task);
                });
            } catch (error) {
                console.error('Erreur lors du chargement des tâches:', error);
                localStorage.removeItem('wp-launcher-tasks');
            }
        }
    }

    // Nettoyer les tâches anciennes
    cleanupOldTasks() {
        const now = Date.now();
        const maxAge = 60 * 60 * 1000; // 1 heure

        for (const [taskId, task] of this.tasks.entries()) {
            // Supprimer les tâches terminées depuis plus de 10 minutes
            if (task.status !== 'running' && (now - task.lastUpdate) > 10 * 60 * 1000) {
                this.tasks.delete(taskId);
            }
            // Supprimer les tâches en cours depuis plus d'1 heure (probablement crashées)
            else if (task.status === 'running' && (now - task.startTime) > maxAge) {
                task.status = 'error';
                task.message = 'Tâche expirée (timeout)';
                task.lastUpdate = now;
            }
        }

        this.saveTasksToStorage();
    }

    // Rendre l'affichage des tâches
    renderTasks() {
        if (!this.toasterContainer) return;

        // Trier les tâches par ordre de création (plus récent en haut)
        const sortedTasks = Array.from(this.tasks.values())
            .sort((a, b) => b.startTime - a.startTime);

        this.toasterContainer.innerHTML = sortedTasks.map(task => this.renderTask(task)).join('');
    }

    // Rendre une tâche individuelle
    renderTask(task) {
        const statusIcon = this.getStatusIcon(task);
        const statusClass = task.status === 'completed' ? 'completed' : 
                           task.status === 'error' ? 'error' : '';
        const elapsed = this.formatElapsedTime(task.startTime);

        return `
            <div class="task-toast ${statusClass}" data-task-id="${task.id}">
                <div class="task-toast-header">
                    <div class="task-toast-title">
                        ${statusIcon}
                        ${task.name}
                    </div>
                    <button class="task-toast-close" onclick="taskManager.removeTask('${task.id}')">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                
                <div class="task-toast-content">
                    <div class="task-toast-message">${task.message}</div>
                    ${task.details ? `<div class="task-toast-details">${task.details}</div>` : ''}
                    
                    ${task.status === 'running' ? `
                        <div class="task-toast-progress">
                            <div class="task-progress-bar">
                                <div class="task-progress-fill ${task.progress === 0 ? 'indeterminate' : ''}" 
                                     style="width: ${task.progress}%"></div>
                            </div>
                        </div>
                    ` : ''}
                </div>
                
                <div class="task-toast-footer">
                    <span class="task-time">${elapsed}</span>
                    <span class="task-status">${this.getStatusText(task.status)}</span>
                </div>
            </div>
        `;
    }

    // Obtenir l'icône selon le type et statut de tâche
    getStatusIcon(task) {
        if (task.status === 'completed') {
            return '<i class="fas fa-check-circle text-success"></i>';
        } else if (task.status === 'error') {
            return '<i class="fas fa-exclamation-triangle text-danger"></i>';
        }

        // Icônes par type de tâche
        const icons = {
            'npm_install': '<i class="fas fa-download fa-spin"></i>',
            'npm_dev': '<i class="fas fa-play fa-spin"></i>',
            'npm_build': '<i class="fas fa-hammer fa-spin"></i>',
            'create_project': '<i class="fas fa-rocket fa-spin"></i>',
            'import_db': '<i class="fas fa-database fa-spin"></i>',
            'export_db': '<i class="fas fa-file-export fa-spin"></i>',
            'start_project': '<i class="fas fa-play fa-spin"></i>',
            'stop_project': '<i class="fas fa-stop fa-spin"></i>',
            'notification': '<i class="fas fa-info-circle"></i>'
        };

        return icons[task.type] || '<i class="fas fa-cog fa-spin"></i>';
    }

    // Obtenir le texte de statut
    getStatusText(status) {
        const texts = {
            'running': 'En cours',
            'completed': 'Terminé',
            'error': 'Erreur'
        };
        return texts[status] || status;
    }

    // Formater le temps écoulé
    formatElapsedTime(startTime) {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        
        if (elapsed < 60) {
            return `${elapsed}s`;
        } else if (elapsed < 3600) {
            const minutes = Math.floor(elapsed / 60);
            const seconds = elapsed % 60;
            return `${minutes}m ${seconds}s`;
        } else {
            const hours = Math.floor(elapsed / 3600);
            const minutes = Math.floor((elapsed % 3600) / 60);
            return `${hours}h ${minutes}m`;
        }
    }

    // Générer un ID unique pour une tâche
    generateTaskId(type, projectName = null) {
        const timestamp = Date.now();
        const random = Math.random().toString(36).substring(2, 5);
        return `${type}_${projectName || 'global'}_${timestamp}_${random}`;
    }

    // Auto-suppression pour les notifications rapides
    autoRemoveNotification(taskId, delay = 3000) {
        setTimeout(() => {
            this.removeTask(taskId);
        }, delay);
    }
}

// Instance globale du gestionnaire de tâches
let taskManager;

// Initialiser le gestionnaire au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
    taskManager = new TaskManager();
});

// Fonctions utilitaires pour l'utilisation dans d'autres scripts

// Démarrer une tâche NPM
function startNpmTask(projectName, command) {
    const taskId = taskManager.generateTaskId(`npm_${command}`, projectName);
    const taskName = `NPM ${command.toUpperCase()}`;
    
    // Vérifier si une tâche similaire est déjà en cours
    if (taskManager.hasRunningTask(`npm_${command}`, projectName)) {
        console.log(`Une tâche npm ${command} est déjà en cours pour ce projet`);
        return null;
    }
    
    return taskManager.createTask(taskId, taskName, `npm_${command}`, projectName);
}

// Démarrer une tâche de création de projet
function startCreateProjectTask() {
    const taskId = taskManager.generateTaskId('create_project');
    const taskName = 'Création de projet';
    
    if (taskManager.hasRunningTask('create_project')) {
        console.log('Une création de projet est déjà en cours');
        return null;
    }
    
    return taskManager.createTask(taskId, taskName, 'create_project');
}

// Démarrer une tâche d'import/export de base de données
function startDatabaseTask(projectName, type) {
    const taskId = taskManager.generateTaskId(type, projectName);
    const taskName = type === 'import_db' ? 'Import base de données' : 'Export base de données';
    
    if (taskManager.hasRunningTask(type, projectName)) {
        console.log(`Une tâche ${taskName.toLowerCase()} est déjà en cours pour ce projet`);
        return null;
    }
    
    return taskManager.createTask(taskId, taskName, type, projectName);
}

// Démarrer une tâche de démarrage/arrêt de projet
function startProjectTask(projectName, action) {
    const taskId = taskManager.generateTaskId(`${action}_project`, projectName);
    const taskName = action === 'start' ? 'Démarrage projet' : 'Arrêt projet';
    
    if (taskManager.hasRunningTask(`${action}_project`, projectName)) {
        console.log(`Une tâche de ${taskName.toLowerCase()} est déjà en cours pour ce projet`);
        return null;
    }
    
    return taskManager.createTask(taskId, taskName, `${action}_project`, projectName);
}

// Démarrer une tâche de suppression de projet
function startDeleteTask(projectName) {
    const taskId = taskManager.generateTaskId('delete_project', projectName);
    const taskName = 'Suppression projet';
    
    if (taskManager.hasRunningTask('delete_project', projectName)) {
        console.log(`Une tâche de suppression est déjà en cours pour ce projet`);
        return null;
    }
    
    return taskManager.createTask(taskId, taskName, 'delete_project', projectName);
}

// Démarrer une tâche d'arrêt npm dev
function startStopNpmDevTask(projectName) {
    const taskId = taskManager.generateTaskId('stop_npm_dev', projectName);
    const taskName = 'Arrêt npm dev';
    
    if (taskManager.hasRunningTask('stop_npm_dev', projectName)) {
        console.log(`Une tâche d'arrêt npm dev est déjà en cours pour ce projet`);
        return null;
    }
    
    return taskManager.createTask(taskId, taskName, 'stop_npm_dev', projectName);
}

// Démarrer une tâche de démarrage conteneur Next.js
function startNextjsContainerTask(projectName) {
    const taskId = taskManager.generateTaskId('start_nextjs', projectName);
    const taskName = 'Démarrage Next.js';
    
    if (taskManager.hasRunningTask('start_nextjs', projectName)) {
        console.log(`Une tâche de démarrage Next.js est déjà en cours pour ce projet`);
        return null;
    }
    
    return taskManager.createTask(taskId, taskName, 'start_nextjs', projectName);
}

 