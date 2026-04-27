/**
 * ========================================
 * TOAST NOTIFICATIONS SYSTEM
 * Utilise la Task Sidebar pour toutes les notifications
 * ========================================
 */

// Dedup map: last time we showed a given (type + message) pair.
// Any identical toast fired within DEDUPE_WINDOW_MS is skipped so a
// looping poll can't fill the bell with 20 copies of the same error.
const DEDUPE_WINDOW_MS = 10000;
const _recentToasts = new Map();

function showToast(message, type = 'info', duration = 5000) {
    // Attendre que le TaskManager soit disponible
    if (typeof taskManager === 'undefined' || !taskManager) {
        console.warn('TaskManager non disponible, notification ignorée:', message);
        return null;
    }

    // Dedup identical toasts within the short window.
    const dedupeKey = `${type}::${message}`;
    const now = Date.now();
    const last = _recentToasts.get(dedupeKey);
    if (last && (now - last) < DEDUPE_WINDOW_MS) {
        return null;
    }
    _recentToasts.set(dedupeKey, now);
    // Trim the map occasionally to avoid unbounded growth.
    if (_recentToasts.size > 50) {
        const cutoff = now - DEDUPE_WINDOW_MS;
        for (const [k, t] of _recentToasts) {
            if (t < cutoff) _recentToasts.delete(k);
        }
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

