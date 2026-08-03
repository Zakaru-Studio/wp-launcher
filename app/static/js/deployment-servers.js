/**
 * /deployments/servers — dedicated server management page.
 *
 * Standalone CRUD over /api/servers (list / create / edit / delete /
 * test). Self-contained on purpose: it must NOT depend on the
 * connection-modal flow that lives in deployments.js, so this page can
 * be opened on its own. Uses the app-wide toast helpers (showSuccess /
 * showError) already shipped by the dashboard.
 */

const SERVERS_STATE = {
    servers: [],
};

/* ───── i18n bridge (same JSON block convention as deployments.html) ───── */
const SRV_I18N = (() => {
    try {
        const el = document.getElementById('deploy-i18n');
        if (el && el.textContent) return JSON.parse(el.textContent);
    } catch (_) { /* fall through */ }
    return {};
})();

function t(key, fallback) {
    return (SRV_I18N && SRV_I18N[key]) || fallback || key;
}

/* ───── utilities ───── */

function srvToast(kind, msg) {
    if (kind === 'success' && window.showSuccess) return window.showSuccess(msg);
    if (kind === 'error'   && window.showError)   return window.showError(msg);
    console[kind === 'error' ? 'error' : 'log'](msg);
}

function headerJson() {
    const csrf = window.CSRF_TOKEN || '';
    if (!csrf) console.warn('[servers] CSRF token missing — mutating requests will fail.');
    return { 'Content-Type': 'application/json', 'X-CSRFToken': csrf };
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = String(s ?? '');
    return div.innerHTML;
}

/** Coerce a server-supplied value into a safe integer (or null). */
function safeInt(v) {
    const n = Number(v);
    return Number.isFinite(n) && Math.floor(n) === n ? n : null;
}

/** Whitelist an env enum before injecting into a CSS class. */
const KNOWN_ENVS = new Set(['staging', 'production']);
function safeEnv(s) {
    return KNOWN_ENVS.has(s) ? s : 'staging';
}

function srvModal() {
    return bootstrap.Modal.getOrCreateInstance(document.getElementById('serverModal'));
}

/* ───── load + render ───── */

async function loadServers() {
    const tbody = document.getElementById('servers-tbody');
    try {
        const res = await fetch('/api/servers');
        if (res.status === 403) {
            SERVERS_STATE.servers = [];
            if (tbody) tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="7">${escapeHtml(t('admins_only', 'Admins only — contact an administrator to see servers.'))}</td></tr>`;
            return;
        }
        const data = await res.json();
        SERVERS_STATE.servers = data.servers || [];
        renderServers();
    } catch (e) {
        if (tbody) tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="7">${escapeHtml(t('failed_load_servers', 'Failed to load servers') + ': ' + e.message)}</td></tr>`;
    }
}

function renderServers() {
    const tbody = document.getElementById('servers-tbody');
    if (!tbody) return;
    const servers = SERVERS_STATE.servers;
    if (!servers.length) {
        tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="7">${escapeHtml(t('no_server_yet', 'No server registered yet. Click "Add server".'))}</td></tr>`;
        return;
    }

    tbody.innerHTML = servers.map(s => {
        const id = safeInt(s.id);
        if (id === null) return '';
        const env = safeEnv(s.env);
        const envClass = env === 'production' ? 'env-production' : 'env-staging';
        const port = safeInt(s.ssh_port) ?? 22;
        const fpShort = s.host_fingerprint ? String(s.host_fingerprint).slice(0, 22) + '…' : '—';
        return `
            <tr data-server-id="${id}">
                <td><strong>${escapeHtml(s.label)}</strong></td>
                <td><span class="env-pill ${envClass}"><span class="env-dot"></span>${escapeHtml(env)}</span></td>
                <td><code>${escapeHtml(s.hostname)}:${port}</code></td>
                <td>${escapeHtml(s.ssh_user)}</td>
                <td><code>${escapeHtml(s.deploy_base_path)}</code></td>
                <td><code title="${escapeHtml(s.host_fingerprint || '')}">${escapeHtml(fpShort)}</code></td>
                <td class="text-end">
                    <button class="deploy-server-action-btn" data-action="test" data-server-id="${id}"
                            title="${escapeHtml(t('test', 'Test'))}">
                        <span class="material-symbols-outlined">wifi_tethering</span>
                    </button>
                    <button class="deploy-server-action-btn" data-action="edit" data-server-id="${id}"
                            title="${escapeHtml(t('edit_server', 'Edit server'))}">
                        <span class="material-symbols-outlined">edit</span>
                    </button>
                    <button class="deploy-server-action-btn is-danger" data-action="delete" data-server-id="${id}"
                            title="${escapeHtml(t('delete', 'Delete'))}">
                        <span class="material-symbols-outlined">delete</span>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

/* ───── create / edit modal ───── */

function openServerModal(serverId) {
    const form = document.getElementById('serverForm');
    const idField = document.getElementById('server-id');
    const title = document.getElementById('server-modal-title');
    const fpBox = document.getElementById('server-fingerprint-box');
    const fpVal = document.getElementById('server-fingerprint-value');
    const resultBox = document.getElementById('server-test-result');
    const keyHint = document.getElementById('server-key-hint');

    resultBox.hidden = true;
    resultBox.textContent = '';
    resultBox.className = 'deploy-alert';
    fpVal.textContent = '—';

    const id = safeInt(serverId);
    if (id !== null) {
        const server = SERVERS_STATE.servers.find(s => s.id === id);
        if (!server) return;
        title.textContent = t('edit_server', 'Edit server');
        idField.value = String(id);
        document.getElementById('server-label').value = server.label;
        document.getElementById('server-env').value = safeEnv(server.env);
        document.getElementById('server-hostname').value = server.hostname;
        document.getElementById('server-ssh-port').value = safeInt(server.ssh_port) ?? 22;
        document.getElementById('server-ssh-user').value = server.ssh_user;
        document.getElementById('server-deploy-path').value = server.deploy_base_path;
        document.getElementById('server-private-key').value = '';
        keyHint.style.display = 'inline';
        if (server.host_fingerprint) {
            fpBox.hidden = false;
            fpVal.textContent = server.host_fingerprint;
        } else {
            fpBox.hidden = true;
        }
    } else {
        title.textContent = t('add_server', 'Add server');
        idField.value = '';
        form.reset();
        document.getElementById('server-ssh-port').value = 22;
        keyHint.style.display = 'none';
        fpBox.hidden = true;
    }
    srvModal().show();
}

async function testServerConnection() {
    const resultBox = document.getElementById('server-test-result');
    const fpBox = document.getElementById('server-fingerprint-box');
    const fpVal = document.getElementById('server-fingerprint-value');

    resultBox.hidden = false;
    resultBox.className = 'deploy-alert';
    resultBox.textContent = t('testing', 'Testing…');

    const serverId = safeInt(document.getElementById('server-id').value);
    const body = {
        hostname: document.getElementById('server-hostname').value,
        ssh_port: safeInt(document.getElementById('server-ssh-port').value) ?? 22,
        ssh_user: document.getElementById('server-ssh-user').value,
    };
    const pk = document.getElementById('server-private-key').value;
    if (pk.trim()) body.private_key = pk;
    if (serverId !== null) body.server_id = serverId;

    try {
        const res = await fetch('/api/servers/test', {
            method: 'POST',
            headers: headerJson(),
            body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.ok) {
            resultBox.className = 'deploy-alert is-ok';
            resultBox.textContent = t('connection_ok', 'Connection OK. Fingerprint pinned:') + ' ' + (data.fingerprint || '—');
            fpBox.hidden = false;
            fpVal.textContent = data.fingerprint || '';
        } else {
            resultBox.className = 'deploy-alert is-error';
            resultBox.textContent = data.error || t('connection_failed', 'Connection failed.');
        }
    } catch (e) {
        resultBox.className = 'deploy-alert is-error';
        resultBox.textContent = t('request_failed', 'Request failed') + ': ' + e.message;
    }
}

/** Open the edit modal for a server, then immediately run a test. */
function testServerById(serverId) {
    const id = safeInt(serverId);
    if (id === null) return;
    openServerModal(id);
    setTimeout(testServerConnection, 250);
}

async function saveServer(event) {
    event.preventDefault();
    // safeInt('') === 0, so an empty hidden field must map to null
    // (create) rather than server #0 (which would 404 on PATCH).
    const serverIdRaw = document.getElementById('server-id').value;
    const serverId = serverIdRaw ? safeInt(serverIdRaw) : null;
    const fpVal = document.getElementById('server-fingerprint-value').textContent.trim();
    const body = {
        label: document.getElementById('server-label').value.trim(),
        env: safeEnv(document.getElementById('server-env').value),
        hostname: document.getElementById('server-hostname').value.trim(),
        ssh_port: safeInt(document.getElementById('server-ssh-port').value) ?? 22,
        ssh_user: document.getElementById('server-ssh-user').value.trim(),
        deploy_base_path: document.getElementById('server-deploy-path').value.trim(),
        host_fingerprint: fpVal && fpVal !== '—' ? fpVal : null,
    };
    const pk = document.getElementById('server-private-key').value;
    if (pk.trim()) body.private_key = pk;

    const url = serverId !== null ? `/api/servers/${serverId}` : '/api/servers';
    const method = serverId !== null ? 'PATCH' : 'POST';
    if (serverId === null && !body.private_key) {
        srvToast('error', t('private_key_required', 'A private key is required when creating a server.'));
        return;
    }

    const resultBox = document.getElementById('server-test-result');
    try {
        const res = await fetch(url, { method, headers: headerJson(), body: JSON.stringify(body) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = data.error || t('save_failed', 'Save failed');
            // Surface the error inline in the modal — a transient toast is
            // easy to miss, and the modal stays open so the user can fix it.
            resultBox.hidden = false;
            resultBox.className = 'deploy-alert is-error';
            resultBox.textContent = msg;
            srvToast('error', msg);
            return;
        }
        srvToast('success', serverId !== null ? t('server_updated', 'Server updated') : t('server_created', 'Server created'));
        srvModal().hide();
        await loadServers();
    } catch (e) {
        resultBox.hidden = false;
        resultBox.className = 'deploy-alert is-error';
        resultBox.textContent = e.message;
        srvToast('error', e.message);
    }
}

async function deleteServer(serverId) {
    const id = safeInt(serverId);
    if (id === null) return;
    if (!confirm(t('confirm_delete_server', 'Delete this server? Existing deployment history is kept.'))) return;
    try {
        const res = await fetch(`/api/servers/${id}`, { method: 'DELETE', headers: headerJson() });
        if (res.ok) {
            srvToast('success', t('server_deleted', 'Server deleted'));
            await loadServers();
        } else {
            const data = await res.json().catch(() => ({}));
            srvToast('error', data.error || t('delete_failed', 'Delete failed'));
        }
    } catch (e) {
        srvToast('error', e.message);
    }
}

/* ───── wiring ───── */

document.addEventListener('DOMContentLoaded', () => {
    loadServers();

    const tbody = document.getElementById('servers-tbody');
    if (tbody) {
        tbody.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-action]');
            if (!btn) return;
            const id = btn.getAttribute('data-server-id');
            switch (btn.getAttribute('data-action')) {
                case 'edit':   openServerModal(id); break;
                case 'test':   testServerById(id); break;
                case 'delete': deleteServer(id); break;
            }
        });
    }
});
