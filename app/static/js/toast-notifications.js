/**
 * ========================================
 * TOAST NOTIFICATIONS SYSTEM
 * Utilise la Task Sidebar pour toutes les notifications
 * ========================================
 */

function showToast(message, type = 'info', duration = 5000) {
    // Attendre que le TaskManager soit disponible
    if (typeof taskManager === 'undefined' || !taskManager) {
        console.warn('TaskManager non disponible, notification ignorée:', message);
        return null;
    }

    // Générer un ID unique pour la notification
    const notificationId = `notification_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    
    // Mapper les types vers des types de tâches
    const taskType = `notification_${type}`;
    
    // Déterminer le nom de la notification selon le type
    const notificationName = {
        'success': 'Succès',
        'error': 'Erreur',
        'warning': 'Attention',
        'info': 'Information'
    }[type] || 'Notification';

    // Créer la tâche de notification
    const task = taskManager.createTask(
        notificationId,
        notificationName,
        taskType,
        null, // pas de projectName pour les notifications
        {
            details: '',
            autoRemove: true,
            isNotification: true
        }
    );

    if (task) {
        // Mettre à jour immédiatement le message et le statut
        taskManager.updateTask(notificationId, {
            message: message,
            status: type === 'error' ? 'error' : type === 'warning' ? 'notification' : 'completed',
            progress: 100
        });

        // Auto-suppression après la durée spécifiée
        setTimeout(() => {
            taskManager.removeTask(notificationId);
        }, duration);
    }

    return task;
}

// Fonctions raccourcies pour plus de commodité
function showSuccess(message, duration = 5000) {
    return showToast(message, 'success', duration);
}

function showError(message, duration = 6000) {
    return showToast(message, 'error', duration);
}

function showWarning(message, duration = 5000) {
    return showToast(message, 'warning', duration);
}

function showInfo(message, duration = 5000) {
    return showToast(message, 'info', duration);
}

// Exposer globalement
if (typeof window !== 'undefined') {
    window.showToast = showToast;
    window.showSuccess = showSuccess;
    window.showError = showError;
    window.showWarning = showWarning;
    window.showInfo = showInfo;
}

