/**
 * Bouton « Update » de la barre latérale.
 *
 * Interroge /api/system/update/check au chargement : le bouton n'apparaît
 * que si une release plus récente existe sur GitHub. La comparaison de
 * versions et la mise en cache sont faites côté serveur (quota API).
 *
 * L'application applique la mise à jour puis redémarre : on attend donc
 * que le service réponde à nouveau avant de recharger la page, plutôt que
 * de recharger immédiatement sur un serveur encore arrêté.
 */
(function () {
    'use strict';

    var state = { latest: null, releaseUrl: null, busy: false };

    function t(key, fallback) {
        return (window.I18N && window.I18N[key]) || fallback;
    }

    function el(id) { return document.getElementById(id); }

    function showButton(info) {
        var btn = el('sidebar-update-btn');
        if (!btn) return;
        state.latest = info.latest_version;
        state.releaseUrl = info.release_url;

        var version = el('sidebar-update-version');
        if (version) version.textContent = info.latest_version || '';
        btn.hidden = false;
    }

    function hideButton() {
        var btn = el('sidebar-update-btn');
        if (btn) btn.hidden = true;
    }

    /**
     * Revalide l'état du bouton.
     *
     * L'affichage ET le masquage doivent être pilotés ici : la version de la
     * barre latérale est rafraîchie en direct par l'événement Socket.IO
     * `app_version` après un redémarrage, donc sans rechargement de page. Un
     * check qui ne saurait qu'afficher laisserait le bouton en place une fois
     * la mise à jour appliquée.
     *
     * `force` contourne le cache d'une heure du serveur — indispensable juste
     * après une mise à jour, sinon la réponse « mise à jour disponible » mise
     * en cache avant le redémarrage serait resservie.
     */
    function checkForUpdate(force) {
        // Réservé aux admins : la route répond 403 aux autres, on ignore.
        fetch('/api/system/update/check' + (force ? '?force=1' : ''),
              { headers: { 'Accept': 'application/json' }, cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (info) {
                if (info && info.update_available) showButton(info);
                else hideButton();
            })
            .catch(function () { /* hors ligne : on laisse l'état courant */ });
    }

    /**
     * Le serveur annonce sa version à chaque connexion Socket.IO. Après le
     * redémarrage qui suit une mise à jour, le socket se reconnecte : c'est
     * le signal fiable pour revalider le bouton, y compris si l'onglet n'a
     * jamais été rechargé.
     */
    function watchVersionBroadcast(attempt) {
        attempt = attempt || 0;
        if (typeof window.getSocketIO !== 'function' || !window.getSocketIO()) {
            // main.js branche le socket peu après le DOMContentLoaded.
            if (attempt < 10) setTimeout(function () { watchVersionBroadcast(attempt + 1); }, 300);
            return;
        }
        var socket = window.getSocketIO();
        var known = null;
        socket.on('app_version', function (data) {
            var version = data && data.version;
            if (!version) return;
            if (known !== null && version !== known) checkForUpdate(true);
            known = version;
        });
    }

    window.openUpdateModal = function () {
        var modalEl = el('updateAppModal');
        if (!modalEl || typeof bootstrap === 'undefined') return;

        var summary = el('update-modal-summary');
        if (summary) {
            summary.textContent = t('update_summary', 'Une nouvelle version est disponible :')
                + ' ' + (state.latest || '');
        }
        var link = el('update-release-link');
        if (link) {
            if (state.releaseUrl) { link.href = state.releaseUrl; link.hidden = false; }
            else { link.hidden = true; }
        }
        var err = el('update-modal-error');
        if (err) { err.hidden = true; err.textContent = ''; }

        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    };

    function fail(message) {
        state.busy = false;
        var btn = el('confirm-update-app');
        if (btn) { btn.disabled = false; btn.classList.remove('is-busy'); }
        var err = el('update-modal-error');
        if (err) { err.textContent = message; err.hidden = false; }
        if (typeof showError === 'function') showError(message);
    }

    /**
     * Le service redémarre : on sonde jusqu'à ce qu'il réponde, puis on
     * recharge. Sans cette attente, le rechargement tomberait sur un port
     * fermé et afficherait une erreur de connexion.
     */
    function waitForRestart() {
        var attempts = 0;
        var MAX = 40;   // ~80 s, systemd relance avec RestartSec=10

        (function poll() {
            attempts++;
            fetch('/login', { method: 'HEAD', cache: 'no-store' })
                .then(function () { window.location.reload(); })
                .catch(function () {
                    if (attempts < MAX) return setTimeout(poll, 2000);
                    fail(t('update_restart_timeout',
                        "Le service met du temps à redémarrer. Rechargez la page dans un instant."));
                });
        })();
    }

    function applyUpdate() {
        if (state.busy) return;
        state.busy = true;

        var btn = el('confirm-update-app');
        if (btn) { btn.disabled = true; btn.classList.add('is-busy'); }

        if (typeof showToast === 'function') {
            showToast(t('update_in_progress', 'Mise à jour en cours…'), 'info');
        }

        // Le patch fetch global de base.html ajoute le jeton CSRF.
        fetch('/api/system/update/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ version: state.latest })
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (!res.ok || !res.data.success) {
                    return fail(res.data.error || t('update_failed', 'La mise à jour a échoué.'));
                }
                waitForRestart();
            })
            .catch(function (e) { fail(String(e)); });
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (!el('sidebar-update-btn')) return;   // non-admin : rien à faire
        checkForUpdate();
        watchVersionBroadcast();
        var confirm = el('confirm-update-app');
        if (confirm) confirm.addEventListener('click', applyUpdate);
    });
})();
