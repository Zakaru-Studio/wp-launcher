/**
 * ========================================
 * NOTIFICATIONS — deux canaux
 * ========================================
 *
 * 1. Le TOAST (sonner, en bas à droite) : éphémère, il passe sous les yeux
 *    et disparaît. C'est le signal ambiant.
 * 2. Le CENTRE DE NOTIFICATIONS (la cloche) : il garde l'historique et ne
 *    s'ouvre plus tout seul — c'est l'utilisateur qui décide de le consulter.
 *
 * Répartition :
 *
 *   TOAST SEUL — le message n'a aucune valeur une fois lu : validation de
 *   formulaire, accusé de réception d'une action instantanée (« liste
 *   actualisée »), erreur de câblage interne, avertissement « opération en
 *   cours ». Les archiver reviendrait à noyer la cloche sous du bruit.
 *   C'est le cas par défaut, donc l'immense majorité des appels.
 *
 *   LES DEUX — le message rend compte d'un changement d'état durable
 *   déclenché par l'utilisateur : backup lancé/terminé/échoué, snapshot
 *   créé/restauré/supprimé, projet ou service supprimé, import terminé,
 *   compte modifié. On veut pouvoir y revenir plus tard, et surtout ne pas
 *   le rater si le toast s'efface pendant qu'on regarde ailleurs.
 *   → passer `{ persist: true }`.
 *
 *   CLOCHE SEULE — le cycle de vie des tâches longues (démarrage, arrêt,
 *   clonage, déploiement…) : progression, file d'attente, temps écoulé.
 *   Toaster chaque tick serait insupportable. TaskManager s'en charge, et
 *   n'émet qu'un seul toast à l'arrivée — l'issue de la tâche (voir
 *   TaskManager.toastTaskOutcome).
 */

// Dedup map: last time we showed a given (type + message) pair.
// Any identical toast fired within DEDUPE_WINDOW_MS is skipped so a
// looping poll can't fill the screen with 20 copies of the same error.
const DEDUPE_WINDOW_MS = 10000;
const _recentToasts = new Map();

// Sonner arrive en module ES, donc après les scripts classiques : tout ce qui
// est notifié avant est mis en attente plutôt que perdu.
const _pendingToasts = [];
let _sonnerReady = false;
let _sonnerUnavailable = false;
const SONNER_LOAD_TIMEOUT_MS = 10000;

const NOTIF_LABELS = {
    success: 'Succès',
    error: 'Erreur',
    warning: 'Attention',
    info: 'Information',
};

document.addEventListener('sonner:ready', () => {
    _sonnerReady = true;
    while (_pendingToasts.length) _emit(_pendingToasts.shift());
});

// Filet de sécurité : si le module ne se charge pas (fichier vendorisé
// manquant, erreur de parsing), on bascule tout vers la cloche plutôt que de
// laisser les messages en attente indéfiniment.
setTimeout(() => {
    if (_sonnerReady) return;
    _sonnerUnavailable = true;
    console.warn('Sonner indisponible : bascule des toasts vers le centre de notifications.');
    while (_pendingToasts.length) {
        const t = _pendingToasts.shift();
        _record(t.message, t.type);
    }
}, SONNER_LOAD_TIMEOUT_MS);

/** Envoie réellement le toast à sonner. */
function _emit({ message, type, duration, description, action }) {
    const fn = window.sonnerToast && (window.sonnerToast[type] || window.sonnerToast);
    if (typeof fn !== 'function') return;
    fn(message, {
        duration,
        ...(description ? { description } : {}),
        ...(action ? { action } : {}),
    });
}

/**
 * Inscrit le message dans le centre de notifications (la cloche).
 * N'ouvre pas le panneau : le badge suffit à signaler qu'il y a du nouveau.
 */
function _record(message, type) {
    if (typeof taskManager === 'undefined' || !taskManager) {
        console.warn('TaskManager non disponible, notification non archivée:', message);
        return null;
    }

    const notificationId = `notification_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    const task = taskManager.createTask(
        notificationId,
        NOTIF_LABELS[type] || 'Notification',
        `notification_${type}`,
        null,
        { details: '', isNotification: true }
    );

    if (task) {
        taskManager.updateTask(notificationId, {
            message: message,
            status: type === 'error' ? 'error' : type === 'warning' ? 'notification' : 'completed',
            progress: 100,
        });
    }

    return task;
}

/**
 * @param {string} message
 * @param {'success'|'error'|'warning'|'info'} type
 * @param {number|object} duration  ms, ou directement les options
 * @param {object} options
 * @param {boolean} options.persist  archiver aussi dans la cloche
 * @param {string}  options.description  seconde ligne du toast
 * @param {{label: string, onClick: Function}} options.action  bouton du toast
 */
function showToast(message, type = 'info', duration = 5000, options = {}) {
    // Confort d'appel : showSuccess('...', { persist: true })
    if (duration && typeof duration === 'object') {
        options = duration;
        duration = options.duration || 5000;
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

    const payload = {
        message,
        type,
        duration,
        description: options.description,
        action: options.action,
    };

    if (_sonnerUnavailable) {
        // Plus de toaster : la cloche devient le seul canal, on y met tout.
        return _record(message, type);
    }
    if (_sonnerReady) {
        _emit(payload);
    } else {
        _pendingToasts.push(payload);
    }

    return options.persist ? _record(message, type) : null;
}

// Fonctions raccourcies pour plus de commodité
function showSuccess(message, duration = 5000, options = {}) {
    return showToast(message, 'success', duration, options);
}

function showError(message, duration = 6000, options = {}) {
    return showToast(message, 'error', duration, options);
}

function showWarning(message, duration = 5000, options = {}) {
    return showToast(message, 'warning', duration, options);
}

function showInfo(message, duration = 5000, options = {}) {
    return showToast(message, 'info', duration, options);
}

// Exposer globalement
if (typeof window !== 'undefined') {
    window.showToast = showToast;
    window.showSuccess = showSuccess;
    window.showError = showError;
    window.showWarning = showWarning;
    window.showInfo = showInfo;
}
