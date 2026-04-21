/**
 * /deployments — servers CRUD, project git config, deploy + live log.
 *
 * Reuses the app-wide Socket.IO singleton (window.getSocketIO) and the
 * toast helpers (showSuccess / showError) that already ship with the
 * dashboard.
 */

const DEPLOY_STATE = {
    servers: [],
    deployments: [],
    deployableProjects: [],
    currentDeploymentId: null,
    currentRoom: null,
    socket: null,
    logListener: null,
    completeListener: null,
};

/* ───── i18n bridge ─────
 * The page template embeds a small JSON dict (see deployments.html
 * `script#deploy-i18n`) so every user-facing string emitted from JS
 * still goes through Flask-Babel.
 */
const DEPLOY_I18N = (() => {
    try {
        const el = document.getElementById('deploy-i18n');
        if (el && el.textContent) return JSON.parse(el.textContent);
    } catch (_) { /* fall through */ }
    return {};
})();

function t(key, fallback) {
    return (DEPLOY_I18N && DEPLOY_I18N[key]) || fallback || key;
}

/* ───── utilities ───── */

function deployToast(kind, msg) {
    if (kind === 'success' && window.showSuccess) return window.showSuccess(msg);
    if (kind === 'error'   && window.showError)   return window.showError(msg);
    console[kind === 'error' ? 'error' : 'log'](msg);
}

function headerJson() {
    const csrf = window.CSRF_TOKEN || '';
    if (!csrf) console.warn('[deployments] CSRF token missing — mutating requests will fail.');
    return { 'Content-Type': 'application/json', 'X-CSRFToken': csrf };
}

function fmtDate(iso) {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        return d.toLocaleString();
    } catch (e) { return iso; }
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

/** Whitelist a status enum before injecting into a CSS class. */
const KNOWN_STATUSES = new Set(['running', 'success', 'failed', 'timeout']);
function safeStatus(s) {
    return KNOWN_STATUSES.has(s) ? s : 'failed';
}

/** Whitelist an env enum before injecting into a CSS class. */
const KNOWN_ENVS = new Set(['staging', 'production']);
function safeEnv(s) {
    return KNOWN_ENVS.has(s) ? s : 'staging';
}

/* ───── loaders ───── */

async function loadServers() {
    const tbody = document.getElementById('servers-tbody');
    try {
        const res = await fetch('/api/servers');
        if (res.status === 403) {
            tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="6">${escapeHtml(t('admins_only', 'Admins only — contact an administrator to see servers.'))}</td></tr>`;
            return;
        }
        const data = await res.json();
        DEPLOY_STATE.servers = data.servers || [];
        renderServers();
    } catch (e) {
        tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="6">${escapeHtml(t('failed_load_servers', 'Failed to load servers') + ': ' + e.message)}</td></tr>`;
    }
}

function renderServers() {
    const tbody = document.getElementById('servers-tbody');
    const servers = DEPLOY_STATE.servers;
    if (!servers.length) {
        tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="6">${escapeHtml(t('no_server_yet', 'No server registered yet. Click "Add server".'))}</td></tr>`;
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
                <td><code title="${escapeHtml(s.host_fingerprint || '')}">${escapeHtml(fpShort)}</code></td>
                <td class="text-end">
                    <button class="deploy-server-action-btn" data-action="test" data-server-id="${id}"
                            title="${escapeHtml(t('test', 'Test'))}">
                        <span class="material-symbols-outlined">wifi_tethering</span>
                    </button>
                    <button class="deploy-server-action-btn" data-action="edit" data-server-id="${id}"
                            title="${escapeHtml(t('edit', 'Edit'))}">
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

async function loadDeployments() {
    const tbody = document.getElementById('deployments-tbody');
    try {
        const res = await fetch('/api/deployments?limit=30');
        const data = await res.json();
        DEPLOY_STATE.deployments = data.deployments || [];
        renderDeployments();
    } catch (e) {
        tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="7">${escapeHtml(t('failed_load_deployments', 'Failed to load deployments.'))}</td></tr>`;
    }
}

function renderDeployments() {
    const tbody = document.getElementById('deployments-tbody');
    const rows = DEPLOY_STATE.deployments;
    if (!rows.length) {
        tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="7">${escapeHtml(t('no_deployment_yet', 'No deployment yet.'))}</td></tr>`;
        return;
    }
    tbody.innerHTML = rows.map(d => {
        const id = safeInt(d.id);
        if (id === null) return '';
        const sid = safeInt(d.server_id);
        const sha = d.commit_sha ? String(d.commit_sha).slice(0, 7) : '—';
        const status = safeStatus(d.status);
        const env = d.server_env ? safeEnv(d.server_env) : '';
        const dot = status === 'running'
            ? '<span class="status-dot is-pulse"></span>'
            : '<span class="status-dot"></span>';
        return `
            <tr>
                <td><strong>${escapeHtml(d.project_name)}</strong></td>
                <td>${escapeHtml(d.server_label || ('#' + (sid ?? '?')))} <small class="profile-field-hint">(${escapeHtml(env)})</small></td>
                <td><code>${escapeHtml(d.branch)}</code></td>
                <td><code>${escapeHtml(sha)}</code></td>
                <td><span class="status-pill status-${status}">${dot}${escapeHtml(status)}</span></td>
                <td><small>${escapeHtml(fmtDate(d.started_at))}</small></td>
                <td class="text-end">
                    <button class="deploy-server-action-btn" data-action="replay" data-deployment-id="${id}"
                            title="${escapeHtml(t('view_logs', 'View logs'))}">
                        <span class="material-symbols-outlined">article</span>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

async function loadDeployableProjects() {
    try {
        const res = await fetch('/api/deployments/deployable-projects');
        const data = await res.json();
        DEPLOY_STATE.deployableProjects = data.projects || [];
        const sel = document.getElementById('deploy-project');
        if (sel) {
            sel.innerHTML = `<option value="">${escapeHtml(t('select_project', '— Select a project —'))}</option>` +
                (data.projects || []).map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join('');
        }
    } catch (e) {
        console.error('Deployable projects:', e);
    }
}

function populateDeployServerSelect() {
    const sel = document.getElementById('deploy-server');
    if (!sel) return;
    if (!DEPLOY_STATE.servers.length) {
        sel.innerHTML = `<option value="">${escapeHtml(t('no_server_available', 'No server available'))}</option>`;
        return;
    }
    sel.innerHTML = `<option value="">${escapeHtml(t('select_server', '— Select a server —'))}</option>` +
        DEPLOY_STATE.servers.map(s => {
            const id = safeInt(s.id);
            if (id === null) return '';
            return `<option value="${id}">${escapeHtml(s.label)} (${escapeHtml(safeEnv(s.env))}) — ${escapeHtml(s.hostname)}</option>`;
        }).join('');
}

/* ───── server modal ───── */

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

    const id = safeInt(serverId);
    if (id !== null) {
        const server = DEPLOY_STATE.servers.find(s => s.id === id);
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

async function testServerById(serverId) {
    const id = safeInt(serverId);
    if (id === null) return;
    openServerModal(id);
    setTimeout(testServerConnection, 200);
    const modal = new bootstrap.Modal(document.getElementById('serverModal'));
    modal.show();
}

async function saveServer(event) {
    event.preventDefault();
    const serverId = safeInt(document.getElementById('server-id').value);
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
        deployToast('error', t('private_key_required', 'A private key is required when creating a server.'));
        return;
    }

    try {
        const res = await fetch(url, { method, headers: headerJson(), body: JSON.stringify(body) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            deployToast('error', data.error || t('save_failed', 'Save failed'));
            return;
        }
        deployToast('success', serverId !== null ? t('server_updated', 'Server updated') : t('server_created', 'Server created'));
        bootstrap.Modal.getInstance(document.getElementById('serverModal')).hide();
        await loadServers();
        populateDeployServerSelect();
    } catch (e) {
        deployToast('error', e.message);
    }
}

async function deleteServer(serverId) {
    const id = safeInt(serverId);
    if (id === null) return;
    if (!confirm(t('confirm_delete_server', 'Delete this server? Existing deployment history is kept.'))) return;
    try {
        const res = await fetch(`/api/servers/${id}`, { method: 'DELETE', headers: headerJson() });
        if (res.ok) {
            deployToast('success', t('server_deleted', 'Server deleted'));
            await loadServers();
            populateDeployServerSelect();
        } else {
            const data = await res.json().catch(() => ({}));
            deployToast('error', data.error || t('delete_failed', 'Delete failed'));
        }
    } catch (e) {
        deployToast('error', e.message);
    }
}

/* ───── deploy modal ───── */

async function onDeployProjectChange() {
    const project = document.getElementById('deploy-project').value;
    if (!project) {
        document.getElementById('deploy-branch').value = '';
        document.getElementById('deploy-git-remote').value = '';
        document.getElementById('deploy-path').value = '';
        document.getElementById('deploy-path-default-hint').textContent = '';
        return;
    }
    try {
        const res = await fetch(`/api/projects/${encodeURIComponent(project)}/git`);
        const data = await res.json();
        document.getElementById('deploy-branch').value = data.git_default_branch || 'main';
        document.getElementById('deploy-git-remote').value = data.git_remote_url || '';
    } catch (e) {
        document.getElementById('deploy-branch').value = 'main';
    }
    refreshDeployPathField();
}

/** Load the (project × server) deploy path override and the default
 *  that would be used if no override is set. Called on project or
 *  server selection change. */
async function refreshDeployPathField() {
    const project = document.getElementById('deploy-project').value;
    const serverId = safeInt(document.getElementById('deploy-server').value);
    const input = document.getElementById('deploy-path');
    const hint = document.getElementById('deploy-path-default-hint');
    if (!project || serverId === null) {
        input.value = '';
        hint.textContent = '';
        return;
    }
    try {
        const res = await fetch(
            `/api/projects/${encodeURIComponent(project)}/deploy-paths/${serverId}`
        );
        const data = await res.json();
        input.value = data.deploy_path || '';
        hint.textContent = data.default_deploy_path
            ? `${t('default', 'Default')}: ${data.default_deploy_path}`
            : '';
    } catch (e) {
        input.value = '';
        hint.textContent = '';
    }
}

async function saveDeployPath() {
    const project = document.getElementById('deploy-project').value;
    const serverId = safeInt(document.getElementById('deploy-server').value);
    if (!project || serverId === null) {
        deployToast('error', t('pick_project_and_server', 'Pick a project and a server first.'));
        return;
    }
    const body = { deploy_path: document.getElementById('deploy-path').value.trim() };
    try {
        const res = await fetch(
            `/api/projects/${encodeURIComponent(project)}/deploy-paths/${serverId}`,
            { method: 'PUT', headers: headerJson(), body: JSON.stringify(body) }
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            deployToast('error', data.error || t('failed_save_path', 'Failed to save deploy path'));
            return;
        }
        deployToast(
            'success',
            data.deploy_path
                ? t('path_saved', 'Custom deploy path saved')
                : t('path_cleared', 'Override cleared — will use server default')
        );
    } catch (e) {
        deployToast('error', e.message);
    }
}

async function saveProjectGitConfig() {
    const project = document.getElementById('deploy-project').value;
    if (!project) { deployToast('error', t('pick_project', 'Pick a project first.')); return; }
    const body = {
        git_remote_url: document.getElementById('deploy-git-remote').value.trim() || null,
        git_default_branch: (document.getElementById('deploy-branch').value || 'main').trim(),
    };
    try {
        const res = await fetch(`/api/projects/${encodeURIComponent(project)}/git`, {
            method: 'PATCH',
            headers: headerJson(),
            body: JSON.stringify(body),
        });
        if (res.ok) deployToast('success', t('git_config_saved', 'Git config saved'));
        else {
            const d = await res.json().catch(() => ({}));
            deployToast('error', d.error || t('failed_save_git', 'Failed to save git config'));
        }
    } catch (e) {
        deployToast('error', e.message);
    }
}

function _ensureSocket() {
    if (!DEPLOY_STATE.socket && typeof window.getSocketIO === 'function') {
        DEPLOY_STATE.socket = window.getSocketIO();
    }
    return DEPLOY_STATE.socket;
}

/** Subscribe to the socket room for a specific deployment. Always
 *  tears down any previous room/listeners first so we don't leak
 *  handlers or receive stale events. */
function subscribeToDeployment(deploymentId) {
    teardownDeploymentSubscription();
    const id = safeInt(deploymentId);
    if (id === null) return;
    DEPLOY_STATE.currentDeploymentId = id;
    const socket = _ensureSocket();
    if (!socket) return;

    const room = `deploy_${id}`;
    DEPLOY_STATE.currentRoom = room;
    socket.emit('join', { room });

    DEPLOY_STATE.logListener = (data) => {
        if (safeInt(data.id) !== DEPLOY_STATE.currentDeploymentId) return;
        appendDeployLogLine(data.line, data.stream || 'stdout');
    };
    DEPLOY_STATE.completeListener = (data) => {
        if (safeInt(data.id) !== DEPLOY_STATE.currentDeploymentId) return;
        setDeployStatus(safeStatus(data.status || 'success'));
        loadDeployments();
    };
    socket.on('deployment_log', DEPLOY_STATE.logListener);
    socket.on('deployment_complete', DEPLOY_STATE.completeListener);
}

/** Leave the current deployment room and drop all listeners. Called
 *  on modal close and before subscribing to a new deployment. */
function teardownDeploymentSubscription() {
    const socket = DEPLOY_STATE.socket;
    if (socket) {
        if (DEPLOY_STATE.currentRoom) {
            try { socket.emit('leave', { room: DEPLOY_STATE.currentRoom }); } catch (_) {}
        }
        if (DEPLOY_STATE.logListener) {
            try { socket.off('deployment_log', DEPLOY_STATE.logListener); } catch (_) {}
        }
        if (DEPLOY_STATE.completeListener) {
            try { socket.off('deployment_complete', DEPLOY_STATE.completeListener); } catch (_) {}
        }
    }
    DEPLOY_STATE.currentDeploymentId = null;
    DEPLOY_STATE.currentRoom = null;
    DEPLOY_STATE.logListener = null;
    DEPLOY_STATE.completeListener = null;
}

function appendDeployLogLine(line, stream) {
    const pane = document.getElementById('deploy-log-pane');
    if (!pane) return;
    const span = document.createElement('div');
    span.className = 'line-' + (stream === 'stderr' ? 'stderr' : 'stdout');
    span.textContent = line;
    pane.appendChild(span);
    pane.scrollTop = pane.scrollHeight;
}

function setDeployStatus(status) {
    const safe = safeStatus(status);
    const pill = document.getElementById('deploy-status-pill');
    const label = document.getElementById('deploy-status-label');
    const dot = pill ? pill.querySelector('.status-dot') : null;
    if (label) label.textContent = safe;
    if (pill) pill.className = 'status-pill status-' + safe;
    if (dot) dot.classList.toggle('is-pulse', safe === 'running');
}

async function runDeployment() {
    const project = document.getElementById('deploy-project').value;
    const serverId = safeInt(document.getElementById('deploy-server').value);
    const branch = document.getElementById('deploy-branch').value.trim() || 'main';

    const errBox = document.getElementById('deploy-error');
    errBox.hidden = true;
    errBox.className = 'deploy-alert';

    if (!project || serverId === null) {
        errBox.hidden = false;
        errBox.className = 'deploy-alert is-error';
        errBox.textContent = t('project_and_server_required', 'Project and server are required.');
        return;
    }

    try {
        const res = await fetch('/api/deployments/run', {
            method: 'POST',
            headers: headerJson(),
            body: JSON.stringify({ project, server_id: serverId, branch }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            errBox.hidden = false;
            errBox.className = 'deploy-alert is-error';
            errBox.textContent = data.error || t('deployment_refused', 'Deployment refused.');
            return;
        }
        const newId = safeInt(data.deployment_id);
        document.getElementById('deploy-step-configure').hidden = true;
        document.getElementById('deploy-step-log').hidden = false;
        document.getElementById('deploy-run-btn').disabled = true;
        document.getElementById('deploy-log-title').textContent = `Deploy #${newId} — ${project} → ${branch}`;
        document.getElementById('deploy-log-pane').textContent = '';
        setDeployStatus('running');
        subscribeToDeployment(newId);
        loadDeployments();
    } catch (e) {
        errBox.hidden = false;
        errBox.className = 'deploy-alert is-error';
        errBox.textContent = e.message;
    }
}

async function replayDeployment(deploymentId) {
    const id = safeInt(deploymentId);
    if (id === null) return;
    try {
        const res = await fetch(`/api/deployments/${id}/log`);
        const data = await res.json();
        const modalEl = document.getElementById('deployModal');
        const modal = new bootstrap.Modal(modalEl);
        // A replay is read-only: no socket subscription, no currentId
        // leak that would catch log events from a different live deploy.
        teardownDeploymentSubscription();
        document.getElementById('deploy-step-configure').hidden = true;
        document.getElementById('deploy-step-log').hidden = false;
        document.getElementById('deploy-run-btn').disabled = true;
        document.getElementById('deploy-log-title').textContent = `Deploy #${id} — logs`;
        document.getElementById('deploy-log-pane').textContent = data.log || t('no_log_output', '(no log output)');
        setDeployStatus(safeStatus(data.status || 'success'));
        modal.show();
    } catch (e) {
        deployToast('error', e.message);
    }
}

/* ───── event delegation ───── */

function onServersTbodyClick(event) {
    const btn = event.target.closest('button[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = safeInt(btn.dataset.serverId);
    if (id === null) return;
    if (action === 'test') testServerById(id);
    else if (action === 'edit') {
        openServerModal(id);
        const modal = new bootstrap.Modal(document.getElementById('serverModal'));
        modal.show();
    }
    else if (action === 'delete') deleteServer(id);
}

function onDeploymentsTbodyClick(event) {
    const btn = event.target.closest('button[data-action="replay"]');
    if (!btn) return;
    const id = safeInt(btn.dataset.deploymentId);
    if (id !== null) replayDeployment(id);
}

/* ───── reset modals on close ───── */

function bindDeployModalLifecycle() {
    const el = document.getElementById('deployModal');
    if (!el) return;
    el.addEventListener('show.bs.modal', () => {
        document.getElementById('deploy-step-configure').hidden = false;
        document.getElementById('deploy-step-log').hidden = true;
        document.getElementById('deploy-run-btn').disabled = false;
        populateDeployServerSelect();
    });
    // Tear down socket room + listeners when the modal closes so we
    // don't receive log events from a stale deployment on the next open.
    el.addEventListener('hidden.bs.modal', () => {
        teardownDeploymentSubscription();
        const pane = document.getElementById('deploy-log-pane');
        if (pane) pane.textContent = '';
        const errBox = document.getElementById('deploy-error');
        if (errBox) { errBox.hidden = true; errBox.className = 'deploy-alert'; }
    });
    const projectSel = document.getElementById('deploy-project');
    if (projectSel) projectSel.addEventListener('change', onDeployProjectChange);
    const serverSel = document.getElementById('deploy-server');
    if (serverSel) serverSel.addEventListener('change', refreshDeployPathField);
}

/* ───── boot ───── */

document.addEventListener('DOMContentLoaded', () => {
    loadServers();
    loadDeployments();
    loadDeployableProjects();
    bindDeployModalLifecycle();
    const sTbody = document.getElementById('servers-tbody');
    if (sTbody) sTbody.addEventListener('click', onServersTbodyClick);
    const dTbody = document.getElementById('deployments-tbody');
    if (dTbody) dTbody.addEventListener('click', onDeploymentsTbodyClick);
});

// Expose to inline onclick handlers still present in the templates.
window.openServerModal = openServerModal;
window.saveServer = saveServer;
window.deleteServer = deleteServer;
window.testServerById = testServerById;
window.testServerConnection = testServerConnection;
window.runDeployment = runDeployment;
window.saveProjectGitConfig = saveProjectGitConfig;
window.saveDeployPath = saveDeployPath;
window.replayDeployment = replayDeployment;
