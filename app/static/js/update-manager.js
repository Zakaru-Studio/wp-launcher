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

    function checkForUpdate() {
        // Réservé aux admins : la route répond 403 aux autres, on ignore.
        fetch('/api/system/update/check', { headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (info) {
                if (info && info.update_available) showButton(info);
            })
            .catch(function () { /* hors ligne : on laisse le bouton masqué */ });
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
        var confirm = el('confirm-update-app');
        if (confirm) confirm.addEventListener('click', applyUpdate);
    });
})();
