/**
 * TaskManager - Gestionnaire de tâches robuste et simple
 * Version refactorisée pour plus de fiabilité
 */

class TaskManager {
    constructor() {
        this.tasks = new Map();
        this.exclusiveQueue = []; // Queue simple pour tâches exclusives
        this.isExclusiveTaskRunning = false;

        // Éléments DOM
        this.sidebarContainer = null;
        this.sidebarElement = null;
        this.badgeElement = null;
        this.isOpen = false;

        // Socket.IO pour synchronisation
        this.socket = null;

        this.init();
    }

    init() {
        // Initialiser les éléments DOM
        this.sidebarContainer = document.getElementById('task-sidebar-content');
        this.sidebarElement = document.getElementById('task-sidebar');
        this.badgeElement = document.getElementById('task-sidebar-badge');

        // Charger les tâches sauvegardées (seulement les non-exclusives)
        this.loadTasksFromStorage();

        // Nettoyer les tâches anciennes
        this.cleanupOldTasks();

        // Afficher les tâches
        this.renderAllTasks();

        // Badge toujours visible
        this.updateBadgeVisibility();

        // Nettoyer automatiquement
        setInterval(() => this.cleanupOldTasks(), 30000);

        // Mettre à jour les temps écoulés toutes les secondes
        setInterval(() => this.updateElapsedTimes(), 1000);

        // Initialiser Socket.IO après un court délai pour s'assurer que io() est disponible
        setTimeout(() => this.initSocket(), 100);

        //console.log('✅ TaskManager refactorisé initialisé');
    }

    /**
     * Initialiser Socket.IO pour la synchronisation en temps réel
     */
    initSocket() {
        // Éviter les multiples connexions — on partage l'instance globale
        if (this.socket && this.socket.connected) {
            //console.log('🔌 Socket déjà connecté, réutilisation');
            return;
        }

        if (typeof window.getSocketIO !== 'function') {
            //console.warn('getSocketIO non disponible');
            return;
        }

        this.socket = window.getSocketIO();
        if (!this.socket) {
            //console.warn('Socket.IO non disponible pour la synchronisation des tâches');
            return;
        }

        try {

            // Événements de synchronisation des tâches
            this.socket.on('task_created', (data) => {
                //console.log('📡 Tâche créée par un autre client:', data);
                this.handleRemoteTaskCreated(data);
            });

            this.socket.on('task_updated', (data) => {
                //console.log('📡 Tâche mise à jour par le serveur:', data);
                this.handleRemoteTaskUpdated(data);
            });

            this.socket.on('task_completed', (data) => {
                //console.log('📡 Tâche terminée par le serveur:', data);
                this.handleRemoteTaskCompleted(data);
            });

            this.socket.on('project_status_changed', (data) => {
                //console.log('📡 Statut projet changé:', data);
                this.handleProjectStatusChanged(data);
            });

            // Événements pour les instances dev
            this.socket.on('task_start', (data) => {
                //console.log('📡 Tâche démarrée:', data);
                this.handleTaskStart(data);
            });

            this.socket.on('task_complete', (data) => {
                //console.log('📡 Tâche terminée:', data);
                this.handleTaskComplete(data);
            });

            this.socket.on('connect', () => {
                //console.log('🔌 TaskManager connecté au WebSocket');
            });

            this.socket.on('disconnect', (reason) => {
                //console.log('🔌 TaskManager déconnecté du WebSocket:', reason);
            });

            this.socket.on('connect_error', (error) => {
                //console.error('❌ Erreur de connexion TaskManager WebSocket:', error);
            });

        } catch (error) {
            //console.error('❌ Erreur lors de l\'initialisation Socket.IO:', error);
        }
    }

    /**
     * Gérer une tâche créée à distance
     */
    handleRemoteTaskCreated(data) {
        const { taskId, taskName, taskType, projectName, status, message } = data;

        // Vérifier si on a déjà cette tâche (éviter les doublons)
        if (this.tasks.has(taskId)) {
            return;
        }

        // Créer la tâche sans émettre d'événement (pour éviter les boucles)
        const task = {
            id: taskId,
            name: taskName,
            type: taskType,
            projectName: projectName,
            status: status || 'running',
            progress: 0,
            message: message || 'Démarré par un autre utilisateur...',
            details: '',
            startTime: Date.now(),
            lastUpdate: Date.now(),
            isExclusive: this.isExclusiveTaskType(taskType),
            isRemote: true // Marquer comme tâche distante
        };

        this.tasks.set(taskId, task);
        this.renderSingleTask(taskId);
        this.updateBadgeVisibility();
    }

    /**
     * Gérer une mise à jour de tâche à distance
     */
    handleRemoteTaskUpdated(data) {
        const { taskId, progress, message, details } = data;
        const task = this.tasks.get(taskId);

        if (!task) {
            return;
        }

        // Si c'est seulement une mise à jour de progression, utiliser la méthode optimisée
        if (progress !== undefined && message === undefined && details === undefined) {
            this.updateTaskProgress(taskId, progress);
            return;
        }

        // Sinon, mise à jour complète
        if (progress !== undefined) task.progress = progress;
        if (message !== undefined) task.message = message;
        if (details !== undefined) task.details = details;
        task.lastUpdate = Date.now();

        this.tasks.set(taskId, task);
        this.renderSingleTask(taskId);
    }

    /**
     * Gérer une tâche terminée à distance
     */
    handleRemoteTaskCompleted(data) {
        const { taskId, success, finalMessage } = data;
        const task = this.tasks.get(taskId);

        if (!task) {
            return;
        }

        // Terminer la tâche
        task.status = success ? 'completed' : 'error';
        task.progress = 100;
        task.lastUpdate = Date.now();

        if (finalMessage) {
            task.message = finalMessage;
        }

        this.tasks.set(taskId, task);
        this.renderSingleTask(taskId);
        this.updateBadgeVisibility();

        // Les tâches terminées restent visibles - suppression manuelle uniquement
        // setTimeout(() => {
        //     this.removeTask(taskId);
        // }, 6000);
    }

    /**
     * Gérer un changement de statut de projet
     */
    handleProjectStatusChanged(data) {
        const { projectName, status } = data;

        // Mettre à jour l'affichage du projet
        if (typeof updateProjectStatus === 'function') {
            updateProjectStatus(projectName, status);
        }
    }

    /**
     * Gérer le démarrage d'une tâche (instance dev)
     */
    handleTaskStart(data) {
        const { task_id, task_name, task_type, project_name, owner, status, message } = data;

        // Créer la tâche si elle n'existe pas déjà
        if (this.tasks.has(task_id)) {
            return;
        }

        const task = {
            id: task_id,
            name: task_name,
            type: task_type,
            projectName: project_name || owner,
            status: status || 'running',
            progress: 0,
            message: message || 'En cours...',
            details: '',
            startTime: Date.now(),
            lastUpdate: Date.now(),
            isExclusive: false,
            isRemote: true
        };

        this.tasks.set(task_id, task);
        this.openSidebar();
        this.renderSingleTask(task_id, true);
        this.updateBadgeVisibility();
        this.startAutoProgress(task_id);
    }

    /**
     * Gérer la completion d'une tâche (instance dev)
     */
    handleTaskComplete(data) {
        const { task_id, success, message, instance } = data;
        const task = this.tasks.get(task_id);

        if (!task) {
            return;
        }

        // Terminer la tâche
        this.completeTask(task_id, message, success);

        // Si c'était une création d'instance réussie, recharger les projets
        if (success && instance && typeof loadProjects === 'function') {
            setTimeout(() => loadProjects(), 1000);
        }
    }

    /**
     * Mettre à jour le statut d'un projet après completion d'une tâche
     */
    updateProjectStatusAfterTask(task) {
        let newStatus = null;

        switch (task.type) {
            case 'start_project':
                newStatus = 'running';
                break;
            case 'stop_project':
                newStatus = 'stopped';
                break;
            case 'delete_project':
                // Supprimer le projet de l'affichage
                this.removeProjectFromUI(task.projectName);
                return;
        }

        if (newStatus && task.projectName) {
            //console.log(`🔄 Mise à jour statut projet: ${task.projectName} → ${newStatus}`);

            // Mettre à jour l'affichage local
            if (typeof updateProjectStatus === 'function') {
                updateProjectStatus(task.projectName, newStatus);
            }

            // Émettre l'événement pour synchroniser avec les autres clients
            if (this.socket && this.socket.connected) {
                this.socket.emit('project_status_changed', {
                    projectName: task.projectName,
                    status: newStatus
                });
            }
        }
    }

    /**
     * Supprimer un projet de l'interface utilisateur
     */
    removeProjectFromUI(projectName) {
        //console.log(`🗑️ Suppression projet de l'UI: ${projectName}`);

        // Recharger la liste des projets pour supprimer le projet supprimé
        if (typeof loadProjects === 'function') {
            setTimeout(() => loadProjects(), 1000);
        }
    }

    /**
     * Types de tâches exclusives qui ne peuvent pas s'exécuter simultanément
     */
    isExclusiveTaskType(taskType) {
        const exclusiveTypes = ['start_project', 'stop_project', 'delete_project', 'create_project'];
        return exclusiveTypes.includes(taskType);
    }

    /**
     * Vérifier si c'est une notification simple
     */
    isNotificationType(taskType) {
        return taskType && taskType.startsWith('notification_');
    }

    /**
     * Créer une nouvelle tâche
     */
    createTask(taskId, taskName, taskType, projectName = null, options = {}) {
        // Vérifier s'il existe déjà une tâche similaire en cours pour éviter les doublons
        if (this.isExclusiveTaskType(taskType) && projectName) {
            const existingTask = Array.from(this.tasks.values()).find(task =>
                task.type === taskType &&
                task.projectName === projectName &&
                (task.status === 'running' || task.status === 'queued')
            );

            if (existingTask) {
                //console.log(`⚠️ Tâche similaire déjà en cours/queue: ${taskName} ${projectName}`);
                return existingTask;
            }
        }

        const task = {
            id: taskId,
            name: taskName,
            type: taskType,
            projectName: projectName,
            status: 'pending',
            progress: 0,
            message: 'En attente...',
            details: options.details || '',
            startTime: Date.now(),
            lastUpdate: Date.now(),
            isExclusive: this.isExclusiveTaskType(taskType),
            onStart: options.onStart || null,
            onProgress: options.onProgress || null,
            onComplete: options.onComplete || null
        };

        // Ajouter la tâche à la collection
        this.tasks.set(taskId, task);

        // Ouvrir immédiatement la sidebar et afficher la tâche
        //console.log(`🎨 CRÉATION TÂCHE: ${taskId} (${task.status})`);
        this.openSidebar(); // Ouvrir la sidebar IMMÉDIATEMENT

        if (task.isExclusive) {
            if (this.isExclusiveTaskRunning) {
                // Mettre en queue
                task.status = 'queued';
                task.message = `En attente (position ${this.exclusiveQueue.length + 1})`;
                task.details = 'Une autre action est en cours, cette tâche démarrera automatiquement à sa fin.';
                this.exclusiveQueue.push(taskId);
                this.tasks.set(taskId, task);
                //console.log(`📋 Tâche exclusive mise en queue: ${taskName} ${projectName || ''}`);
            } else {
                // Démarrer immédiatement
                this.startExclusiveTask(taskId);
            }
        } else {
            // Tâche non-exclusive, démarrer immédiatement
            this.startNonExclusiveTask(taskId);
        }

        // Afficher la tâche UNE SEULE FOIS après avoir défini son statut final
        this.renderSingleTask(taskId, true);

        // Sauvegarder
        this.saveTasksToStorage();
        this.updateBadgeVisibility();

        // Émettre l'événement de création de tâche pour synchronisation
        this.emitTaskCreated(task);

        return task;
    }

    /**
     * Démarrer une tâche exclusive
     */
    startExclusiveTask(taskId) {
        const task = this.tasks.get(taskId);
        if (!task) return;

        this.isExclusiveTaskRunning = true;
        task.status = 'running';
        task.message = 'Initialisation...';
        task.startTime = Date.now();
        task.lastUpdate = Date.now();

        this.tasks.set(taskId, task);
        //console.log(`🚀 Tâche exclusive démarrée: ${task.name} ${task.projectName || ''}`);

        // Démarrer la progression automatique
        this.startAutoProgress(taskId);

        // Appeler le callback onStart si défini (avec un délai pour s'assurer que le rendu est fait)
        if (typeof task.onStart === 'function') {
            try {
                //console.log(`📞 Appel du callback onStart pour: ${task.id}`);
                setTimeout(() => {
                    task.onStart(task);
                }, 100);
            } catch (error) {
                //console.error('Erreur dans le callback onStart:', error);
            }
        } else {
            //console.warn(`⚠️ Aucun callback onStart défini pour la tâche: ${task.id}`);
        }
    }

    /**
     * Démarrer une tâche non-exclusive
     */
    startNonExclusiveTask(taskId) {
        const task = this.tasks.get(taskId);
        if (!task) return;

        // Les notifications sont déjà "complètes", pas besoin de progression
        if (this.isNotificationType(task.type)) {
            // La notification est déjà prête, ne rien faire de plus
            return;
        }

        task.status = 'running';
        task.message = 'En cours...';
        task.startTime = Date.now();
        task.lastUpdate = Date.now();

        this.tasks.set(taskId, task);
        //console.log(`🚀 Tâche non-exclusive démarrée: ${task.name} ${task.projectName || ''}`);

        // Démarrer la progression automatique
        this.startAutoProgress(taskId);

        // Appeler le callback onStart si défini (avec un délai pour s'assurer que le rendu est fait)
        if (typeof task.onStart === 'function') {
            try {
                //console.log(`📞 Appel du callback onStart pour: ${task.id}`);
                setTimeout(() => {
                    task.onStart(task);
                }, 100);
            } catch (error) {
                //console.error('Erreur dans le callback onStart:', error);
            }
        } else {
            //console.warn(`⚠️ Aucun callback onStart défini pour la tâche: ${task.id}`);
        }
    }

    /**
     * Démarrer la progression automatique d'une tâche
     */
    startAutoProgress(taskId) {
        const task = this.tasks.get(taskId);
        if (!task) return;

        // Stocker l'ID de l'intervalle pour pouvoir l'arrêter
        if (task.progressInterval) {
            clearInterval(task.progressInterval);
        }

        let currentProgress = 0;
        const progressStep = 100 / (5 * 10); // 5 secondes * 10 updates par seconde = 50 steps

        // Initialiser la barre à 0%
        this.updateTaskProgress(taskId, 0);

        task.progressInterval = setInterval(() => {
            const currentTask = this.tasks.get(taskId);
            if (!currentTask || currentTask.status !== 'running') {
                clearInterval(task.progressInterval);
                return;
            }

            currentProgress += progressStep;
            if (currentProgress >= 100) {
                currentProgress = 100;
                clearInterval(task.progressInterval);
                
                // Ajouter la classe de pulsation quand on atteint 100%
                setTimeout(() => {
                    const progressFill = document.querySelector(`[data-task-id="${taskId}"] .task-progress-fill`);
                    if (progressFill) {
                        progressFill.classList.add('completed');
                    }
                }, 100);
            }

            // Mettre à jour seulement la progression, pas tout le rendu
            this.updateTaskProgress(taskId, Math.round(currentProgress));
        }, 100); // Update toutes les 100 (10 fois par seconde)

        // Stocker l'ID de l'intervalle dans la tâche
        task.progressInterval = task.progressInterval;
        this.tasks.set(taskId, task);
    }

    /**
     * Mettre à jour seulement la progression d'une tâche (optimisé pour éviter le glitch)
     */
    updateTaskProgress(taskId, progress) {
        const task = this.tasks.get(taskId);
        if (!task) return;

        // Mettre à jour la progression dans les données
        task.progress = progress;
        task.lastUpdate = Date.now();
        this.tasks.set(taskId, task);

        // Mettre à jour seulement la barre de progression dans le DOM
        const progressFill = document.querySelector(`[data-task-id="${taskId}"] .task-progress-fill`);
        if (progressFill) {
            // Désactiver temporairement la transition pour une mise à jour immédiate
            progressFill.style.transition = 'none';
            progressFill.style.width = `${progress}%`;
            
            // Réactiver la transition après un court délai
            setTimeout(() => {
                progressFill.style.transition = '';
            }, 50);
        }

        // Sauvegarder sans re-rendre
        this.saveTasksToStorage();
    }

    /**
     * Mettre à jour une tâche
     */
    updateTask(taskId, updates) {
        const task = this.tasks.get(taskId);
        if (!task) {
            //console.warn(`Tâche non trouvée pour mise à jour: ${taskId}`);
            return;
        }

        // Mettre à jour les propriétés
        Object.assign(task, updates, { lastUpdate: Date.now() });
        this.tasks.set(taskId, task);

        // Sauvegarder et afficher
        this.saveTasksToStorage();
        this.renderSingleTask(taskId);

        // Émettre l'événement de mise à jour pour synchronisation
        this.emitTaskUpdated(task, updates);

        // Appeler le callback onProgress si défini
        if (typeof task.onProgress === 'function') {
            try {
                task.onProgress(task);
            } catch (error) {
                //console.error('Erreur dans le callback onProgress:', error);
            }
        }
    }

    /**
     * Terminer une tâche
     */
    completeTask(taskId, finalMessage = null, success = true, actionButton = null) {
        const task = this.tasks.get(taskId);
        if (!task) {
            //console.warn(`Tâche non trouvée pour completion: ${taskId}`);
            return;
        }

        // Nettoyer l'intervalle de progression automatique
        if (task.progressInterval) {
            clearInterval(task.progressInterval);
            task.progressInterval = null;
        }

        // Mettre à jour le statut
        task.status = success ? 'completed' : 'error';
        task.progress = 100;
        task.lastUpdate = Date.now();

        if (finalMessage) {
            task.message = finalMessage;
        }

        // Ajouter un bouton pour voir les logs si c'est un import de base de données
        if (task.type === 'import_db' && typeof showImportLogsModal === 'function') {
            task.actionButton = {
                text: (window.I18N && window.I18N.view_logs) || 'Voir les logs',
                icon: 'fas fa-terminal',
                action: 'showImportLogsModal()',
                class: 'btn-info'
            };
        }

        // Ajouter le bouton d'action si fourni
        if (actionButton) {
            task.actionButton = actionButton;
        }

        this.tasks.set(taskId, task);
        this.saveTasksToStorage();
        this.renderSingleTask(taskId);
        this.updateBadgeVisibility();

        // Ajouter la classe de pulsation pour les tâches complétées avec succès
        if (success) {
            setTimeout(() => {
                const progressFill = document.querySelector(`[data-task-id="${taskId}"] .task-progress-fill`);
                if (progressFill) {
                    progressFill.classList.add('completed');
                }
            }, 100);
        }

        //console.log(`${success ? '✅' : '❌'} Tâche terminée: ${task.name} ${task.projectName || ''}`);

        // Émettre l'événement de completion pour synchronisation
        this.emitTaskCompleted(task, success, finalMessage);

        // Mettre à jour le statut du projet si c'est une tâche de projet
        if (success && task.projectName) {
            this.updateProjectStatusAfterTask(task);
        }

        // Appeler le callback onComplete si défini
        if (typeof task.onComplete === 'function') {
            try {
                task.onComplete(task, success);
            } catch (error) {
                //console.error('Erreur dans le callback onComplete:', error);
            }
        }

        // Si c'était une tâche exclusive, traiter la queue
        if (task.isExclusive) {
            this.isExclusiveTaskRunning = false;
            this.processExclusiveQueue();
        }

        // Les tâches terminées restent visibles - suppression manuelle uniquement
        // setTimeout(() => {
        //     this.removeTask(taskId);
        // }, 6000);
    }

    /**
     * Traiter la queue des tâches exclusives
     */
    processExclusiveQueue() {
        if (this.exclusiveQueue.length === 0 || this.isExclusiveTaskRunning) {
            return;
        }

        // Prendre la première tâche de la queue
        const nextTaskId = this.exclusiveQueue.shift();
        const nextTask = this.tasks.get(nextTaskId);

        if (!nextTask) {
            // Tâche supprimée entre temps, essayer la suivante
            this.processExclusiveQueue();
            return;
        }

        // Mettre à jour les positions des tâches restantes
        this.exclusiveQueue.forEach((taskId, index) => {
            const task = this.tasks.get(taskId);
            if (task) {
                task.message = `En attente (position ${index + 1})`;
                this.tasks.set(taskId, task);
                this.renderSingleTask(taskId);
            }
        });

        // Démarrer la tâche suivante
        this.startExclusiveTask(nextTaskId);
    }

    /**
     * Supprimer une tâche
     */
    removeTask(taskId) {
        const task = this.tasks.get(taskId);
        if (!task) return;

        // Supprimer de la queue si présente
        const queueIndex = this.exclusiveQueue.indexOf(taskId);
        if (queueIndex !== -1) {
            this.exclusiveQueue.splice(queueIndex, 1);
            // Mettre à jour les positions
            this.exclusiveQueue.forEach((id, index) => {
                const queuedTask = this.tasks.get(id);
                if (queuedTask) {
                    queuedTask.message = `En attente (position ${index + 1})`;
                    this.tasks.set(id, queuedTask);
                    this.renderSingleTask(id);
                }
            });
        }

        // Supprimer de la collection
        this.tasks.delete(taskId);

        // Supprimer du DOM
        this.removeSingleTaskFromDOM(taskId);

        // Sauvegarder et mettre à jour
        this.saveTasksToStorage();
        this.updateBadgeVisibility();

        //console.log(`🗑️ Tâche supprimée: ${task.name} ${task.projectName || ''}`);
    }

    /**
     * Définir des callbacks pour une tâche
     */
    setTaskCallbacks(taskId, callbacks = {}) {
        const task = this.tasks.get(taskId);
        if (!task) return;

        if (callbacks.onStart) task.onStart = callbacks.onStart;
        if (callbacks.onProgress) task.onProgress = callbacks.onProgress;
        if (callbacks.onComplete) task.onComplete = callbacks.onComplete;

        this.tasks.set(taskId, task);
    }

    /**
     * Vérifier si une tâche exclusive peut démarrer
     */
    canStartExclusiveTask() {
        return !this.isExclusiveTaskRunning;
    }

    /**
     * Vérifier s'il y a des tâches en cours d'exécution
     */
    hasRunningTasks() {
        for (let task of this.tasks.values()) {
            if (task.status === 'running') {
                return true;
            }
        }
        return false;
    }

    /**
     * Obtenir le nombre de tâches en queue
     */
    getQueueLength() {
        return this.exclusiveQueue.length;
    }

    /**
     * Obtenir une tâche
     */
    getTask(taskId) {
        return this.tasks.get(taskId);
    }

    /**
     * Vérifier si une tâche existe
     */
    hasTask(taskId) {
        return this.tasks.has(taskId);
    }

    /**
     * Sauvegarder en localStorage (seulement les tâches non-exclusives)
     */
    saveTasksToStorage() {
        try {
            const tasksToSave = Array.from(this.tasks.values())
                .filter(task => !task.isExclusive || task.status === 'completed' || task.status === 'error');
            localStorage.setItem('wp-launcher-tasks', JSON.stringify(tasksToSave));
        } catch (error) {
            //console.error('Erreur lors de la sauvegarde:', error);
        }
    }

    /**
     * Charger depuis localStorage
     */
    loadTasksFromStorage() {
        try {
            const stored = localStorage.getItem('wp-launcher-tasks');
            if (stored) {
                const tasksArray = JSON.parse(stored);
                this.tasks.clear();
                tasksArray.forEach(task => {
                    // Ne recharger que les tâches non-exclusives ou terminées
                    if (!task.isExclusive || task.status === 'completed' || task.status === 'error') {
                        this.tasks.set(task.id, task);
                    }
                });
            }
        } catch (error) {
            //console.error('Erreur lors du chargement:', error);
            localStorage.removeItem('wp-launcher-tasks');
        }
    }

    /**
     * Mettre à jour les temps écoulés des tâches en cours
     */
    updateElapsedTimes() {
        const runningTasks = Array.from(this.tasks.values())
            .filter(task => task.status === 'running' || task.status === 'queued');

        if (runningTasks.length === 0) return;

        runningTasks.forEach(task => {
            const taskElement = this.sidebarContainer?.querySelector(`[data-task-id="${task.id}"]`);
            if (taskElement) {
                const timeElement = taskElement.querySelector('.task-time');
                if (timeElement) {
                    const elapsed = this.formatElapsedTime(task.startTime);
                    timeElement.textContent = elapsed;
                }
            }
        });
    }

    /**
     * Nettoyer les tâches anciennes
     */
    cleanupOldTasks() {
        const now = Date.now();
        const maxAge = 60 * 60 * 1000; // 1 heure

        for (const [taskId, task] of this.tasks.entries()) {
            // Ne plus supprimer automatiquement les tâches terminées - elles restent visibles
            // if ((task.status === 'completed' || task.status === 'error') && 
            //     (now - task.lastUpdate) > 10 * 60 * 1000) {
            //     this.removeTask(taskId);
            // }

            // Marquer comme expirées les tâches en cours depuis plus d'1 heure
            if (task.status === 'running' && (now - task.startTime) > maxAge) {
                this.completeTask(taskId, 'Tâche expirée (timeout)', false);
            }
        }
    }

    /**
     * Rendu complet des tâches
     */
    renderAllTasks() {
        if (!this.sidebarContainer) return;

        const sortedTasks = Array.from(this.tasks.values())
            .sort((a, b) => b.startTime - a.startTime);

        if (sortedTasks.length === 0) {
            this.sidebarContainer.innerHTML = `
                <div class="task-sidebar-empty">
                    <i class="fas fa-inbox"></i>
                    <p>Aucune tâche en cours</p>
                </div>
            `;
        } else {
            this.sidebarContainer.innerHTML = sortedTasks.map(task => this.renderTaskHTML(task)).join('');
        }

        this.updateTaskCount(sortedTasks.length);
    }

    /**
     * Rendu d'une tâche spécifique - VERSION SIMPLIFIÉE
     */
    renderSingleTask(taskId, isNew = false) {
        const task = this.tasks.get(taskId);
        if (!task) {
            //console.warn(`❌ Tentative de rendu d'une tâche inexistante: ${taskId}`);
            return;
        }

        if (!this.sidebarContainer) {
            //console.warn(`❌ sidebarContainer non trouvé pour le rendu de: ${taskId}`);
            return;
        }

        //console.log(`🎨 RENDU SIMPLE: ${task.name} (${task.status}) - ID: ${taskId}`);

        // Supprimer l'élément existant s'il y en a un
        const existingElement = this.sidebarContainer.querySelector(`[data-task-id="${taskId}"]`);
        if (existingElement) {
            //console.log(`🗑️ Suppression élément existant: ${taskId}`);
            existingElement.remove();
        }

        // Supprimer le message vide si présent
        const emptyElement = this.sidebarContainer.querySelector('.task-sidebar-empty');
        if (emptyElement) {
            //console.log(`🗑️ Suppression message vide`);
            emptyElement.remove();
        }

        // Créer le nouvel élément
        const newHTML = this.renderTaskHTML(task, isNew);
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = newHTML.trim();
        const newElement = tempDiv.firstChild;

        if (!newElement) {
            //console.error(`❌ Impossible de créer l'élément DOM pour: ${taskId}`);
            return;
        }

        // Insérer au début du container
        this.sidebarContainer.insertBefore(newElement, this.sidebarContainer.firstChild);
        //console.log(`✅ ÉLÉMENT AJOUTÉ: ${taskId}`);

        // Supprimer la classe d'animation après l'animation (300ms)
        if (isNew) {
            setTimeout(() => {
                newElement.classList.remove('task-item-new');
            }, 350);
        }

        // Vérification immédiate
        const verifyElement = this.sidebarContainer.querySelector(`[data-task-id="${taskId}"]`);
        if (verifyElement) {
            //console.log(`✅ VÉRIFICATION OK: Élément visible dans la sidebar`);
        } else {
            //console.error(`❌ VÉRIFICATION FAIL: Élément non trouvé après insertion`);
        }

        this.updateTaskCount(this.tasks.size);
    }

    /**
     * Supprimer une tâche du DOM
     */
    removeSingleTaskFromDOM(taskId) {
        if (!this.sidebarContainer) return;

        const existingElement = this.sidebarContainer.querySelector(`[data-task-id="${taskId}"]`);
        if (existingElement) {
            existingElement.remove();
        }

        // Afficher le message vide si plus de tâches
        if (this.tasks.size === 0) {
            this.sidebarContainer.innerHTML = `
                <div class="task-sidebar-empty">
                    <i class="fas fa-inbox"></i>
                    <p>Aucune tâche en cours</p>
                </div>
            `;
        }

        this.updateTaskCount(this.tasks.size);
    }

    /**
     * Générer le HTML d'une tâche
     */
    renderTaskHTML(task, isNew = false) {
        const statusIcon = this.getStatusIcon(task);
        const statusClass = this.getStatusClass(task);
        const elapsed = this.formatElapsedTime(task.startTime);
        const taskDateTime = this.formatDateTime(task.startTime);
        const projectInfo = task.projectName ? ` • ${task.projectName}` : '';
        const newClass = isNew ? ' task-item-new' : '';

        const html = `
            <div class="task-item ${statusClass}${newClass}" data-task-id="${task.id}">
                <div class="task-item-header">
                    <div class="task-item-title">
                        ${statusIcon}
                        ${task.name}${projectInfo}
                    </div>
                    <button class="task-item-close" onclick="taskManager.removeTask('${task.id}')">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                
                <div class="task-item-content">
                    <div class="task-item-message">${task.message}</div>
                    ${task.details ? `<div class="task-item-details">${task.details}</div>` : ''}
                    
                    ${(task.status === 'running' || task.status === 'queued') && !this.isNotificationType(task.type) ? `
                        <div class="task-item-progress">
                            <div class="task-progress-bar">
                                <div class="task-progress-fill ${task.progress === 0 || task.status === 'queued' ? 'indeterminate' : ''}" 
                                     style="width: ${task.status === 'queued' ? '100' : task.progress}%"></div>
                            </div>
                        </div>
                    ` : ''}
                    
                    ${task.actionButton && task.status === 'completed' ? (
                        task.actionButton.url
                            ? `<div class="task-action-button">
                                <a href="${task.actionButton.url}" target="_blank" rel="noopener" class="btn-task-action">
                                    <i class="${task.actionButton.icon}"></i>
                                    ${task.actionButton.text}
                                </a>
                            </div>`
                            : `<div class="task-action-button">
                                <button type="button" class="btn-task-action" onclick="${task.actionButton.action}">
                                    <i class="${task.actionButton.icon}"></i>
                                    ${task.actionButton.text}
                                </button>
                            </div>`
                    ) : ''}
                </div>
                
                <div class="task-item-footer">
                    <div class="task-footer-left">
                        <span class="task-datetime">${taskDateTime}</span>
                    <span class="task-time">${elapsed}</span>
                    </div>
                    <span class="task-status">${this.getStatusText(task.status)}</span>
                </div>
            </div>
        `;
        return html;
    }

    /**
     * Obtenir l'icône de statut
     */
    getStatusIcon(task) {
        // Icônes spécifiques pour les notifications
        if (this.isNotificationType(task.type)) {
            if (task.type === 'notification_success') {
                return '<i class="fas fa-check-circle text-success"></i>';
            } else if (task.type === 'notification_error') {
                return '<i class="fas fa-exclamation-circle text-danger"></i>';
            } else if (task.type === 'notification_warning') {
                return '<i class="fas fa-exclamation-triangle text-warning"></i>';
            } else if (task.type === 'notification_info') {
                return '<i class="fas fa-info-circle text-info"></i>';
            }
        }

        if (task.status === 'completed') {
            return '<i class="fas fa-check-circle text-success"></i>';
        } else if (task.status === 'error') {
            return '<i class="fas fa-exclamation-triangle text-danger"></i>';
        } else if (task.status === 'queued') {
            return '<i class="fas fa-clock text-warning"></i>';
        }

        const icons = {
            'start_project': '<i class="fas fa-play fa-spin"></i>',
            'stop_project': '<i class="fas fa-stop fa-spin"></i>',
            'delete_project': '<i class="fas fa-trash fa-spin"></i>',
            'create_project': '<i class="fas fa-rocket fa-spin"></i>',
            'create_instance': '<i class="fas fa-laptop-code fa-spin"></i>',
            'delete_instance': '<i class="fas fa-trash-alt fa-spin"></i>',
            'import_db': '<i class="fas fa-database fa-spin"></i>',
            'export_db': '<i class="fas fa-file-export fa-spin"></i>',
            'npm_install': '<i class="fas fa-download fa-spin"></i>',
            'npm_dev': '<i class="fas fa-play fa-spin"></i>',
            'npm_build': '<i class="fas fa-hammer fa-spin"></i>',
            'config_update': '<i class="fas fa-cog fa-spin"></i>'
        };

        return icons[task.type] || '<i class="fas fa-cog fa-spin"></i>';
    }

    /**
     * Obtenir la classe CSS de statut
     */
    getStatusClass(task) {
        switch (task.status) {
            case 'completed': return 'completed';
            case 'error': return 'error';
            case 'queued': return 'notification';
            default: return '';
        }
    }

    /**
     * Obtenir le texte de statut
     */
    getStatusText(status) {
        const texts = {
            'pending': 'En attente',
            'running': 'En cours',
            'completed': 'Terminé',
            'error': 'Erreur',
            'queued': 'En file'
        };
        return texts[status] || status;
    }

    /**
     * Formater le temps écoulé
     */
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

    /**
     * Formater la date et heure
     */
    formatDateTime(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();

        if (date.toDateString() === now.toDateString()) {
            return date.toLocaleTimeString('fr-FR', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        } else {
            return date.toLocaleString('fr-FR', {
                day: '2-digit',
                month: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        }
    }

    /**
     * Mettre à jour le compteur de tâches
     */
    updateTaskCount(count) {
        const countElement = document.getElementById('task-count');
        const badgeCountElement = document.getElementById('task-badge-count');

        if (countElement) {
            countElement.textContent = count;
        }

        if (badgeCountElement) {
            badgeCountElement.textContent = count;
            badgeCountElement.style.display = count > 0 ? 'flex' : 'none';
        }

        // Sync the new bell badges in the topbar (desktop + mobile)
        ['notif-bell-badge', 'notif-bell-badge-mobile'].forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            el.textContent = count;
            if (count > 0) {
                el.removeAttribute('hidden');
            } else {
                el.setAttribute('hidden', '');
            }
        });
    }

    /**
     * Mettre à jour la visibilité du badge (toujours visible)
     */
    updateBadgeVisibility() {
        if (this.badgeElement) {
            this.badgeElement.classList.add('visible');
        }

        // Fermer automatiquement si plus de tâches après un délai
        if (this.isOpen && this.tasks.size === 0) {
            setTimeout(() => this.closeSidebar(), 2000);
        }
    }

    /**
     * Gestion de la sidebar
     */
    openSidebar() {
        if (this.sidebarElement) {
            this.sidebarElement.classList.add('open');
            document.body.classList.add('sidebar-open');
            this.isOpen = true;
            //console.log('📂 Sidebar ouverte, classe sidebar-open ajoutée au body');
        }
    }

    closeSidebar() {
        if (this.sidebarElement) {
            this.sidebarElement.classList.remove('open');
            document.body.classList.remove('sidebar-open');
            this.isOpen = false;
            //console.log('📁 Sidebar fermée, classe sidebar-open supprimée du body');
        }
    }

    toggleSidebar() {
        if (this.isOpen) {
            this.closeSidebar();
        } else {
            this.openSidebar();
        }
    }

    /**
     * Émettre un événement de création de tâche
     */
    emitTaskCreated(task) {
        if (!this.socket || task.isRemote) return;

        this.socket.emit('task_created', {
            taskId: task.id,
            taskName: task.name,
            taskType: task.type,
            projectName: task.projectName,
            status: task.status,
            message: task.message
        });
    }

    /**
     * Émettre un événement de mise à jour de tâche
     */
    emitTaskUpdated(task, updates) {
        if (!this.socket || task.isRemote) return;

        this.socket.emit('task_updated', {
            taskId: task.id,
            progress: updates.progress,
            message: updates.message,
            details: updates.details
        });
    }

    /**
     * Émettre un événement de completion de tâche
     */
    emitTaskCompleted(task, success, finalMessage) {
        if (!this.socket || task.isRemote) return;

        this.socket.emit('task_completed', {
            taskId: task.id,
            success: success,
            finalMessage: finalMessage,
            projectName: task.projectName,
            taskType: task.type
        });
    }

    /**
     * Générer un ID unique
     */
    generateTaskId(type, projectName = null) {
        const timestamp = Date.now();
        const random = Math.random().toString(36).substring(2, 5);
        return `${type}_${projectName || 'global'}_${timestamp}_${random}`;
    }
}

// Instance globale
let taskManager;

// Initialisation
document.addEventListener('DOMContentLoaded', function () {
    // Éviter les multiples initialisations
    if (taskManager) {
        //console.log('⚠️ TaskManager déjà initialisé');
        return;
    }

    try {
        taskManager = new TaskManager();
    } catch (error) {
        //console.error('❌ Erreur lors de l\'initialisation du TaskManager:', error);
    }
});

// Fonctions globales pour l'interface
function toggleTaskSidebar() {
    if (taskManager) {
        taskManager.toggleSidebar();
    }
}

function clearCompletedTasks() {
    if (taskManager) {
        const completedTasks = Array.from(taskManager.tasks.values())
            .filter(task => task.status === 'completed' || task.status === 'error');

        if (completedTasks.length === 0) {
            //console.log('📋 Aucune tâche terminée à nettoyer');
            return;
        }

        //console.log(`🧹 Nettoyage de ${completedTasks.length} tâche(s) terminée(s)`);

        completedTasks.forEach(task => {
            taskManager.removeTask(task.id);
        });

        // Afficher un message de confirmation
        if (typeof showSuccess === 'function') {
            showSuccess(`${completedTasks.length} tâche(s) terminée(s) supprimée(s)`);
        }
    }
}

function clearAllTasks() {
    if (taskManager) {
        const allTasks = Array.from(taskManager.tasks.values());

        if (allTasks.length === 0) {
            //console.log('📋 Aucune tâche à supprimer');
            return;
        }

        allTasks.forEach(task => {
            taskManager.removeTask(task.id);
        });

        // Afficher un message de confirmation
        if (typeof showSuccess === 'function') {
            showSuccess(`Toutes les tâches ont été supprimées`);
        }
    }
}

// Fonctions utilitaires simplifiées

function startProjectTask(projectName, action) {
    if (!taskManager) {
        //console.error('TaskManager non initialisé');
        return null;
    }

    const taskId = taskManager.generateTaskId(`${action}_project`, projectName);
    const taskName = action === 'start' ? 'Démarrage projet' : 'Arrêt projet';

    return taskManager.createTask(taskId, taskName, `${action}_project`, projectName);
}

function startCreateProjectTask() {
    if (!taskManager) return null;

    const taskId = taskManager.generateTaskId('create_project');
    return taskManager.createTask(taskId, 'Création de projet', 'create_project');
}

function startDeleteTask(projectName) {
    if (!taskManager) return null;

    const taskId = taskManager.generateTaskId('delete_project', projectName);
    return taskManager.createTask(taskId, 'Suppression projet', 'delete_project', projectName);
}

function startRestartTask(projectName) {
    if (!taskManager) return null;

    const taskId = taskManager.generateTaskId('restart_project', projectName);
    return taskManager.createTask(taskId, 'Redémarrage projet', 'restart_project', projectName);
}

function startRebuildTask(projectName) {
    if (!taskManager) return null;

    const taskId = taskManager.generateTaskId('rebuild_project', projectName);
    return taskManager.createTask(taskId, 'Rebuild conteneurs', 'rebuild_project', projectName);
}

function startDatabaseTask(projectName, type) {
    if (!taskManager) return null;

    const taskId = taskManager.generateTaskId(type, projectName);
    const taskName = type === 'import_db' ? 'Import base de données' : 'Export base de données';
    return taskManager.createTask(taskId, taskName, type, projectName);
}

function startNpmTask(projectName, command) {
    if (!taskManager) return null;

    const taskId = taskManager.generateTaskId(`npm_${command}`, projectName);
    const taskName = `NPM ${command.toUpperCase()}`;
    return taskManager.createTask(taskId, taskName, `npm_${command}`, projectName);
}