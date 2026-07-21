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
    projects: [],        // registered project folders
    targets: [],         // connections (project × server × branch)
    targetHistory: {},   // targetId -> { rows: [...], expanded: bool }
    deployableProjects: [],
    view: 'grid',        // 'grid' (folders) | 'detail' (one project)
    currentProject: null,
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
const KNOWN_STATUSES = new Set(['running', 'success', 'failed', 'timeout', 'cancelled']);
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
    // The servers table was removed from the page, but we still fetch the
    // list so the connection modal's server picker stays populated.
    const tbody = document.getElementById('servers-tbody');
    try {
        const res = await fetch('/api/servers');
        if (res.status === 403) {
            DEPLOY_STATE.servers = [];
            if (tbody) tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="6">${escapeHtml(t('admins_only', 'Admins only — contact an administrator to see servers.'))}</td></tr>`;
            return;
        }
        const data = await res.json();
        DEPLOY_STATE.servers = data.servers || [];
        renderServers();
    } catch (e) {
        if (tbody) tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="6">${escapeHtml(t('failed_load_servers', 'Failed to load servers') + ': ' + e.message)}</td></tr>`;
    }
}

function renderServers() {
    if (!document.getElementById('servers-tbody')) return;
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
    // The global "Recent deployments" table was removed — each project
    // now shows its own recent activity. Nothing to load if it's absent.
    const tbody = document.getElementById('deployments-tbody');
    if (!tbody) return;
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
    if (!tbody) return;
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
        const cancelBtn = status === 'running'
            ? `<button class="deploy-server-action-btn is-danger" data-action="cancel" data-deployment-id="${id}"
                       title="${escapeHtml(t('cancel_deployment', 'Cancel deployment'))}">
                   <span class="material-symbols-outlined">stop_circle</span>
               </button>`
            : '';
        return `
            <tr>
                <td><strong>${escapeHtml(d.project_name)}</strong></td>
                <td>${escapeHtml(d.server_label || ('#' + (sid ?? '?')))} <small class="profile-field-hint">(${escapeHtml(env)})</small></td>
                <td><code>${escapeHtml(d.branch)}</code></td>
                <td><code>${escapeHtml(sha)}</code></td>
                <td><span class="status-pill status-${status}">${dot}${escapeHtml(status)}</span></td>
                <td><small>${escapeHtml(fmtDate(d.started_at))}</small></td>
                <td class="text-end">
                    ${cancelBtn}
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
        await loadServers();
        populateDeployServerSelect();
        // The server form is step 2 of the connection modal: refresh the
        // connection's server picker, preselect the new server, and swap
        // back to the connection step (no second modal to close).
        populateTargetServerSelect();
        const newId = data.server && safeInt(data.server.id);
        const sel = document.getElementById('target-server');
        if (sel && newId !== null) { sel.value = String(newId); suggestConnectionLabel(); refreshTargetDeployPathField(); }
        backToConnectionStep();
    } catch (e) {
        deployToast('error', e.message);
    }
}

/** Swap the connection modal to its inline "new server" step. */
function openServerFromConnection() {
    DEPLOY_STATE._connTitle = document.getElementById('target-modal-title').textContent;
    openServerModal();   // reset the server fields (create mode)
    document.getElementById('target-modal-title').textContent = t('new_server', 'New server');
    document.getElementById('targetForm').hidden = true;
    document.getElementById('serverForm').hidden = false;
}

/** Swap back from the "new server" step to the connection step. */
function backToConnectionStep() {
    document.getElementById('serverForm').hidden = true;
    document.getElementById('targetForm').hidden = false;
    const ttl = document.getElementById('target-modal-title');
    if (ttl && DEPLOY_STATE._connTitle) ttl.textContent = DEPLOY_STATE._connTitle;
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
        loadProjects();
        loadTargets();
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
    setDeployResultMessage(safe);
}

/** Footer confirmation line shown once a deployment finishes. Hidden
 *  while it is still running. */
function setDeployResultMessage(status) {
    const el = document.getElementById('deploy-result-msg');
    if (!el) return;
    const safe = safeStatus(status);
    if (safe === 'running') { el.hidden = true; el.textContent = ''; return; }
    el.hidden = false;
    if (safe === 'success') {
        el.className = 'deploy-result-msg is-ok';
        el.textContent = '✓ ' + t('deploy_success_msg', 'Deployment completed successfully.');
    } else if (safe === 'cancelled') {
        el.className = 'deploy-result-msg is-warn';
        el.textContent = t('deploy_cancelled_msg', 'Deployment was cancelled.');
    } else {
        el.className = 'deploy-result-msg is-error';
        el.textContent = '✗ ' + t('deploy_error_msg', 'An error occurred during deployment.');
    }
}

/** Hide the "Deploy" action button — used in the live-log / replay views
 *  where the deployment already runs on its own. */
function hideDeployButton() {
    const btn = document.getElementById('deploy-run-btn');
    if (btn) { btn.disabled = true; btn.style.display = 'none'; }
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
        showDeployLogView(newId, `Deploy #${newId} — ${project} → ${branch}`);
    } catch (e) {
        errBox.hidden = false;
        errBox.className = 'deploy-alert is-error';
        errBox.textContent = e.message;
    }
}

/** Switch the deploy modal into its live-log step and subscribe to the
 *  deployment's socket room. Shared by the manual deploy flow and the
 *  one-click target redeploy (which opens the modal fresh). Calling
 *  modal.show() on an already-open modal is a Bootstrap no-op, so this
 *  is safe from both entry points. */
function showDeployLogView(deploymentId, title) {
    const id = safeInt(deploymentId);
    const modalEl = document.getElementById('deployModal');
    let modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
    modal.show();
    // Set the steps AFTER show() so the show.bs.modal reset handler
    // (which reveals the configure step) can't clobber us.
    document.getElementById('deploy-step-configure').hidden = true;
    document.getElementById('deploy-step-log').hidden = false;
    hideDeployButton();
    document.getElementById('deploy-log-title').textContent = title;
    document.getElementById('deploy-log-pane').textContent = '';
    setDeployStatus('running');
    subscribeToDeployment(id);
    loadDeployments();
    loadTargets();
}

async function replayDeployment(deploymentId) {
    const id = safeInt(deploymentId);
    if (id === null) return;
    try {
        const res = await fetch(`/api/deployments/${id}/log`);
        const data = await res.json();
        const modalEl = document.getElementById('deployModal');
        const modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
        // A replay is read-only: no socket subscription, no currentId
        // leak that would catch log events from a different live deploy.
        teardownDeploymentSubscription();
        modal.show();
        // Set the steps AFTER show() so the show.bs.modal reset handler
        // (which reveals the configure step) can't clobber us — otherwise
        // "View logs" would land on the parameters form, not the log.
        document.getElementById('deploy-step-configure').hidden = true;
        document.getElementById('deploy-step-log').hidden = false;
        hideDeployButton();
        document.getElementById('deploy-log-title').textContent = `Deploy #${id} — logs`;
        document.getElementById('deploy-log-pane').textContent = data.log || t('no_log_output', '(no log output)');
        setDeployStatus(safeStatus(data.status || 'success'));
    } catch (e) {
        deployToast('error', e.message);
    }
}

/* ───── deployment projects (folders) + connections ───── */

/** Number of history rows shown before the "See more" button. */
const TARGET_HISTORY_PAGE = 5;

async function loadProjects() {
    try {
        const res = await fetch('/api/deployment-projects');
        const data = await res.json();
        DEPLOY_STATE.projects = data.projects || [];
    } catch (e) {
        DEPLOY_STATE.projects = [];
    }
    renderProjectsView();
}

async function loadTargets() {
    try {
        const res = await fetch('/api/deployment-targets');
        const data = await res.json();
        DEPLOY_STATE.targets = data.targets || [];
    } catch (e) {
        DEPLOY_STATE.targets = [];
    }
    // Re-rendering rebuilds the cards (and destroys any open history
    // drawer), so drop the cached runs — stale after a new deploy anyway.
    DEPLOY_STATE.targetHistory = {};
    renderProjectsView();
}

/** All connections of a project (from the already-loaded target list). */
function connectionsOf(project) {
    return DEPLOY_STATE.targets.filter(tg => tg.project_name === project);
}

/** Folder icon markup: try the site favicon(s), falling back through the
 *  candidate list and finally to the generic folder glyph. */
function faviconImg(project, urls) {
    if (!Array.isArray(urls) || !urls.length) {
        return `<span class="material-symbols-outlined">folder</span>`;
    }
    const first = urls[0];
    const rest = urls.slice(1).join('|');
    return `<img class="deploy-folder-favicon" src="${escapeHtml(first)}"
                 data-fallbacks="${escapeHtml(rest)}" alt="" loading="lazy"
                 referrerpolicy="no-referrer" onerror="onFaviconError(this)">`;
}

/** onerror handler: advance to the next favicon candidate, or swap in the
 *  folder glyph once they're all exhausted. */
function onFaviconError(img) {
    const fb = (img.dataset.fallbacks || '').split('|').filter(Boolean);
    if (fb.length) {
        img.dataset.fallbacks = fb.slice(1).join('|');
        img.src = fb[0];
        return;
    }
    const span = document.createElement('span');
    span.className = 'material-symbols-outlined';
    span.textContent = 'folder';
    img.replaceWith(span);
}

/** Show or hide the sibling sections + section header so a project opens
 *  as a focused, dedicated deployment view. Also swaps the page title for
 *  the open project's name. */
function setDedicatedView(on, project) {
    const others = ['servers-section', 'recent-deployments-section'];
    others.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = on ? 'none' : '';
    });
    const header = document.querySelector('#projects-section .deploy-section-header');
    if (header) header.style.display = on ? 'none' : '';
    const section = document.getElementById('projects-section');
    if (section) section.classList.toggle('is-project-detail', on);

    // The global page actions (Add server / Deploy) are irrelevant inside
    // a single project's view — hide them there, restore on the grid.
    const pageActions = document.querySelector('.page-header-actions');
    if (pageActions) pageActions.style.display = on ? 'none' : '';

    // Swap the page header title for the current project (restore on back).
    const titleEl = document.getElementById('deploy-page-title');
    const subEl = document.getElementById('deploy-page-subtitle');
    if (titleEl && DEPLOY_STATE.pageTitleDefault == null) {
        DEPLOY_STATE.pageTitleDefault = titleEl.textContent;
        DEPLOY_STATE.pageSubtitleDefault = subEl ? subEl.textContent : '';
    }
    if (on && project) {
        const meta = DEPLOY_STATE.projects.find(p => p.project_name === project);
        const icon = meta && meta.favicon_urls && meta.favicon_urls.length
            ? faviconImg(project, meta.favicon_urls)
            : '';
        if (titleEl) titleEl.innerHTML = `<span class="deploy-page-title-project">${icon}<span>${escapeHtml(project)}</span></span>`;
        if (subEl) subEl.style.display = 'none';
    } else if (titleEl) {
        titleEl.textContent = DEPLOY_STATE.pageTitleDefault ?? titleEl.textContent;
        if (subEl) subEl.style.display = '';
    }
}

/** Dispatch: grid of folders, or one project's dedicated detail view. */
function renderProjectsView() {
    const view = document.getElementById('projects-view');
    if (!view) return;
    const createBtn = document.getElementById('create-project-btn');

    // If the current project was deleted out from under us, fall back.
    if (DEPLOY_STATE.view === 'detail' &&
        !DEPLOY_STATE.projects.some(p => p.project_name === DEPLOY_STATE.currentProject)) {
        DEPLOY_STATE.view = 'grid';
        DEPLOY_STATE.currentProject = null;
    }

    if (DEPLOY_STATE.view === 'detail' && DEPLOY_STATE.currentProject) {
        if (createBtn) createBtn.style.display = 'none';
        setDedicatedView(true, DEPLOY_STATE.currentProject);
        renderProjectDetail(view, DEPLOY_STATE.currentProject);
    } else {
        if (createBtn) createBtn.style.display = '';
        setDedicatedView(false);
        renderProjectGrid(view);
    }
}

function renderProjectGrid(view) {
    const projects = DEPLOY_STATE.projects;
    if (!projects.length) {
        view.innerHTML = `<div class="deploy-targets-empty">${escapeHtml(t('no_project_yet', 'No project yet. Click "Create project" to add one.'))}</div>`;
        return;
    }
    view.innerHTML = `<div class="deploy-folder-grid">` + projects.map(p => {
        const name = p.project_name;
        const count = safeInt(p.connection_count) ?? 0;
        // Distinct env badges from this project's connections.
        const envs = [...new Set(connectionsOf(name).map(c => safeEnv(c.server_env)))];
        const envPills = envs.map(e => {
            const cls = e === 'production' ? 'env-production' : 'env-staging';
            return `<span class="env-pill ${cls}"><span class="env-dot"></span>${escapeHtml(e)}</span>`;
        }).join('');
        let last = '';
        if (p.last_status) {
            const st = safeStatus(p.last_status);
            last = `<span class="status-pill status-${st}"><span class="status-dot"></span>${escapeHtml(st)}</span>`
                 + `<span class="deploy-folder-last-date">${escapeHtml(fmtDate(p.last_started_at))}</span>`;
        } else {
            last = `<span class="deploy-folder-last-none">${escapeHtml(t('never_deployed', 'Never deployed'))}</span>`;
        }
        const connLabel = count > 1
            ? `${count} ${escapeHtml(t('connections', 'connections'))}`
            : `${count} ${escapeHtml(t('connection', 'connection'))}`;
        return `
            <div class="deploy-folder" data-action="open-project" data-project="${escapeHtml(name)}" role="button" tabindex="0">
                <button class="deploy-folder-delete" data-action="delete-project" data-project="${escapeHtml(name)}"
                        title="${escapeHtml(t('delete', 'Delete'))}">
                    <span class="material-symbols-outlined">delete</span>
                </button>
                <div class="deploy-folder-icon">${faviconImg(name, p.favicon_urls)}</div>
                <div class="deploy-folder-name">${escapeHtml(name)}</div>
                <div class="deploy-folder-envs">${envPills || `<span class="deploy-folder-noenv">${escapeHtml(t('no_connection_short', 'no connection'))}</span>`}</div>
                <div class="deploy-folder-meta">
                    <span class="deploy-folder-count">${connLabel}</span>
                    <span class="deploy-folder-last">${last}</span>
                </div>
            </div>
        `;
    }).join('') + `</div>`;
}

function renderProjectDetail(view, project) {
    const conns = connectionsOf(project);
    const staging = conns.filter(c => safeEnv(c.server_env) === 'staging');
    const prod = conns.filter(c => safeEnv(c.server_env) === 'production');
    view.innerHTML = `
        <div class="deploy-detail-head">
            <button class="deploy-back-btn" data-action="back-to-grid">
                <span class="material-symbols-outlined">arrow_back</span>
                <span>${escapeHtml(t('back', 'Back'))}</span>
            </button>
        </div>
        <div class="deploy-env-columns">
            ${renderEnvColumn('staging', 'Staging', staging, project)}
            ${renderEnvColumn('production', 'Production', prod, project)}
        </div>
        <div class="deploy-detail-activity">
            <div class="deploy-detail-activity-head">${escapeHtml(t('recent_activity', 'Recent activity'))}</div>
            <div id="project-activity" class="deploy-activity-list">
                <div class="deploy-target-history-row">${escapeHtml(t('loading', 'Loading...'))}</div>
            </div>
        </div>
    `;
    loadProjectActivity(project);
}

/** One environment column (Staging or Production). Renders its
 *  connection cards, or a "Configure" placeholder when empty. */
function renderEnvColumn(envKey, envLabel, items, project) {
    const cls = envKey === 'production' ? 'env-production' : 'env-staging';
    const glyph = envKey === 'production' ? 'rocket_launch' : 'science';
    const body = items.length
        ? items.map(tg => renderTargetCard(tg)).join('')
        : `
            <div class="deploy-env-placeholder">
                <span class="material-symbols-outlined deploy-env-placeholder-icon">${glyph}</span>
                <div class="deploy-env-placeholder-text">${escapeHtml(t('no_env_connection', 'No {env} connection yet.').replace('{env}', envLabel))}</div>
                <button class="deploy-env-placeholder-btn" data-action="add-connection" data-project="${escapeHtml(project)}">
                    <span class="material-symbols-outlined">tune</span>
                    <span>${escapeHtml(t('configure', 'Configure'))}</span>
                </button>
            </div>`;
    return `
        <div class="deploy-env-col">
            <div class="deploy-env-col-head">
                <span class="env-pill ${cls}"><span class="env-dot"></span>${escapeHtml(envLabel)}</span>
            </div>
            <div class="deploy-env-col-body">${body}</div>
        </div>`;
}

/** Load the project's recent deployments (all connections) into the
 *  dedicated view's activity panel. */
async function loadProjectActivity(project) {
    const box = document.getElementById('project-activity');
    if (!box) return;
    try {
        const params = new URLSearchParams({ project, limit: '15' });
        const res = await fetch(`/api/deployments?${params.toString()}`);
        const data = await res.json();
        const rows = data.deployments || [];
        // Guard against a late response after the user navigated away.
        if (DEPLOY_STATE.currentProject !== project) return;
        if (!rows.length) {
            box.innerHTML = `<div class="deploy-target-history-row">${escapeHtml(t('no_deployment_yet', 'No deployment yet.'))}</div>`;
            return;
        }
        box.innerHTML = rows.map(d => {
            const did = safeInt(d.id);
            if (did === null) return '';
            const status = safeStatus(d.status);
            const env = d.server_env ? safeEnv(d.server_env) : '';
            const sha = d.commit_sha ? String(d.commit_sha).slice(0, 7) : '—';
            return `
                <div class="deploy-target-history-row">
                    <span class="status-pill status-${status}"><span class="status-dot"></span>${escapeHtml(status)}</span>
                    <span class="deploy-activity-server">${escapeHtml(d.server_label || '')}${env ? ` <small>(${escapeHtml(env)})</small>` : ''}</span>
                    <code>${escapeHtml(d.branch || '')}</code>
                    <code>${escapeHtml(sha)}</code>
                    <span>${escapeHtml(fmtDate(d.started_at))}</span>
                    <button class="deploy-target-history-link" data-action="target-logs" data-deployment-id="${did}">
                        ${escapeHtml(t('view_logs', 'View logs'))}
                    </button>
                </div>
            `;
        }).join('');
    } catch (e) {
        box.innerHTML = `<div class="deploy-target-history-row">${escapeHtml(e.message)}</div>`;
    }
}

/* ───── project navigation ───── */

function openProject(project) {
    DEPLOY_STATE.view = 'detail';
    DEPLOY_STATE.currentProject = project;
    DEPLOY_STATE.targetHistory = {};
    renderProjectsView();
    const section = document.getElementById('projects-section');
    if (section && section.scrollIntoView) {
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function backToGrid() {
    DEPLOY_STATE.view = 'grid';
    DEPLOY_STATE.currentProject = null;
    renderProjectsView();
}

/* ───── project (folder) modal ───── */

/** Projects the user can deploy but hasn't created a folder for yet. */
function availableProjects() {
    const taken = new Set(DEPLOY_STATE.projects.map(p => p.project_name));
    return (DEPLOY_STATE.deployableProjects || []).filter(p => !taken.has(p));
}

function populateProjectSelect() {
    const sel = document.getElementById('project-select');
    if (!sel) return;
    const avail = availableProjects();
    if (!avail.length) {
        sel.innerHTML = `<option value="">${escapeHtml(t('all_projects_created', 'All your projects are already created'))}</option>`;
        return;
    }
    sel.innerHTML = `<option value="">${escapeHtml(t('select_project', '— Select a project —'))}</option>` +
        avail.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join('');
}

function openProjectModal() {
    populateProjectSelect();
    const errBox = document.getElementById('project-error');
    if (errBox) { errBox.hidden = true; errBox.className = 'deploy-alert'; }
    const sel = document.getElementById('project-select');
    if (sel) sel.value = '';
    new bootstrap.Modal(document.getElementById('projectModal')).show();
}

async function saveProject(event) {
    event.preventDefault();
    const project = document.getElementById('project-select').value;
    const errBox = document.getElementById('project-error');
    if (errBox) { errBox.hidden = true; errBox.className = 'deploy-alert'; }
    if (!project) {
        if (errBox) { errBox.hidden = false; errBox.className = 'deploy-alert is-error'; errBox.textContent = t('pick_project', 'Pick a project first.'); }
        return;
    }
    try {
        const res = await fetch('/api/deployment-projects', {
            method: 'POST', headers: headerJson(), body: JSON.stringify({ project }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (errBox) { errBox.hidden = false; errBox.className = 'deploy-alert is-error'; errBox.textContent = data.error || t('save_failed', 'Save failed'); }
            return;
        }
        deployToast('success', t('project_created', 'Project created'));
        bootstrap.Modal.getInstance(document.getElementById('projectModal')).hide();
        await loadProjects();
        openProject(project);   // drop straight into the new folder
    } catch (e) {
        if (errBox) { errBox.hidden = false; errBox.className = 'deploy-alert is-error'; errBox.textContent = e.message; }
    }
}

async function deleteProject(project) {
    if (!project) return;
    if (!confirm(t('confirm_delete_project', 'Delete this project and all its connections? Run history is kept.'))) return;
    try {
        const res = await fetch(`/api/deployment-projects/${encodeURIComponent(project)}`, {
            method: 'DELETE', headers: headerJson(),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
            deployToast('success', t('project_deleted', 'Project deleted'));
            if (DEPLOY_STATE.currentProject === project) backToGrid();
            await loadProjects();
            await loadTargets();
        } else {
            deployToast('error', data.error || t('delete_failed', 'Delete failed'));
        }
    } catch (e) {
        deployToast('error', e.message);
    }
}

function renderTargetCard(tg) {
        const id = safeInt(tg.id);
        if (id === null) return '';
        const sid = safeInt(tg.server_id);
        const env = tg.server_env ? safeEnv(tg.server_env) : '';
        const envClass = env === 'production' ? 'env-production' : 'env-staging';
        const runCount = safeInt(tg.run_count) ?? 0;

        let lastRun;
        if (tg.last_status) {
            const status = safeStatus(tg.last_status);
            const sha = tg.last_commit_sha ? ` · <code>${escapeHtml(String(tg.last_commit_sha).slice(0, 7))}</code>` : '';
            lastRun = `<span class="status-pill status-${status}"><span class="status-dot"></span>${escapeHtml(status)}</span>`
                + `<span>${escapeHtml(fmtDate(tg.last_started_at))}</span>${sha}`;
        } else {
            lastRun = `<span>${escapeHtml(t('never_deployed', 'Never deployed'))}</span>`;
        }

        const historyToggle = runCount > 0
            ? `<button class="deploy-target-history-toggle" data-action="toggle-history" data-target-id="${id}">
                   <span class="material-symbols-outlined">expand_more</span>
                   <span>${escapeHtml(t('history', 'History'))} (${runCount})</span>
               </button>`
            : '';

        return `
            <div class="deploy-target-card" data-target-id="${id}">
                <div class="deploy-target-main">
                    <div class="deploy-target-info">
                        <p class="deploy-target-name">
                            ${escapeHtml(tg.label)}
                            ${env ? `<span class="env-pill ${envClass}"><span class="env-dot"></span>${escapeHtml(env)}</span>` : ''}
                        </p>
                        <div class="deploy-target-meta">
                            <span>${escapeHtml(tg.server_label || ('#' + (sid ?? '?')))}</span>
                            <code>${escapeHtml(tg.branch)}</code>
                        </div>
                        <div class="deploy-target-lastrun">${lastRun}</div>
                    </div>
                    <div class="deploy-target-actions">
                        <button class="deploy-target-redeploy-btn" data-action="redeploy" data-target-id="${id}">
                            <span class="material-symbols-outlined">rocket_launch</span>
                            <span>${escapeHtml(t('redeploy', 'Redeploy'))}</span>
                        </button>
                        <button class="deploy-server-action-btn" data-action="edit-target" data-target-id="${id}"
                                title="${escapeHtml(t('edit', 'Edit'))}">
                            <span class="material-symbols-outlined">edit</span>
                        </button>
                        <button class="deploy-server-action-btn is-danger" data-action="delete-target" data-target-id="${id}"
                                title="${escapeHtml(t('delete', 'Delete'))}">
                            <span class="material-symbols-outlined">delete</span>
                        </button>
                    </div>
                </div>
                ${historyToggle}
                <div class="deploy-target-history" hidden></div>
            </div>
        `;
}

function populateTargetProjectSelect() {
    const sel = document.getElementById('target-project');
    if (!sel) return;
    sel.innerHTML = `<option value="">${escapeHtml(t('select_project', '— Select a project —'))}</option>` +
        (DEPLOY_STATE.deployableProjects || []).map(p =>
            `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join('');
}

function populateTargetServerSelect() {
    const sel = document.getElementById('target-server');
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

function showTargetError(msg) {
    const errBox = document.getElementById('target-error');
    if (!errBox) return;
    errBox.hidden = false;
    errBox.className = 'deploy-alert is-error';
    errBox.textContent = msg;
}

/** Open the connection modal.
 *  @param targetId       edit an existing connection (or null to create)
 *  @param forcedProject  when creating from inside a project detail, the
 *                        project is fixed and its selector hidden. */
function openTargetModal(targetId, forcedProject) {
    // Always open on the connection step (step 2 is the inline new-server
    // form, which may have been left showing on a previous open).
    const sForm = document.getElementById('serverForm');
    const tForm = document.getElementById('targetForm');
    if (sForm) sForm.hidden = true;
    if (tForm) tForm.hidden = false;
    populateTargetProjectSelect();
    populateTargetServerSelect();
    const idField = document.getElementById('target-id');
    const title = document.getElementById('target-modal-title');
    const projectSel = document.getElementById('target-project');
    const projectField = document.getElementById('target-project-field');
    const errBox = document.getElementById('target-error');
    errBox.hidden = true;
    errBox.className = 'deploy-alert';

    const id = safeInt(targetId);
    if (id !== null) {
        const tg = DEPLOY_STATE.targets.find(x => x.id === id);
        if (!tg) return;
        title.textContent = t('edit_connection', 'Edit connection');
        idField.value = String(id);
        document.getElementById('target-label').value = tg.label || '';
        projectSel.value = tg.project_name || '';
        // Project is part of the connection's identity — lock it on edit.
        projectSel.disabled = true;
        if (projectField) projectField.style.display = '';
        document.getElementById('target-server').value = String(tg.server_id ?? '');
        document.getElementById('target-branch').value = tg.branch || '';
    } else {
        title.textContent = t('add_connection', 'Add connection');
        idField.value = '';
        document.getElementById('target-label').value = '';
        document.getElementById('target-server').value = '';
        document.getElementById('target-branch').value = '';
        if (forcedProject) {
            // Created from a project folder: pin the project and hide the
            // selector so the connection can only land in this project.
            projectSel.value = forcedProject;
            projectSel.disabled = true;
            if (projectField) projectField.style.display = 'none';
        } else {
            projectSel.disabled = false;
            projectSel.value = '';
            if (projectField) projectField.style.display = '';
        }
    }
    // Load the per-project Git remote and the (project × server) deploy
    // path override so both are editable inline (covers edit / forced /
    // empty — each helper no-ops when its inputs aren't ready yet).
    refreshTargetDeployPathField();
    loadTargetGitRemote();
}

/** Suggest "<project> → <env>" as the connection name once a server is
 *  picked, if the user hasn't typed one. */
function suggestConnectionLabel() {
    const labelEl = document.getElementById('target-label');
    if (!labelEl || labelEl.value.trim()) return;
    const project = document.getElementById('target-project').value;
    const serverId = safeInt(document.getElementById('target-server').value);
    if (!project || serverId === null) return;
    const server = DEPLOY_STATE.servers.find(s => s.id === serverId);
    if (!server) return;
    labelEl.value = `${project} → ${safeEnv(server.env)}`;
}

/** Load the (project × server) deploy-path override into the connection
 *  modal, plus the default that applies when no override is set. Called
 *  when the project or server selection changes, and when editing. */
async function refreshTargetDeployPathField() {
    const input = document.getElementById('target-deploy-path');
    const hint = document.getElementById('target-deploy-path-default-hint');
    if (!input) return;
    const project = document.getElementById('target-project').value;
    const serverId = safeInt(document.getElementById('target-server').value);
    if (!project || serverId === null) {
        input.value = '';
        if (hint) hint.textContent = '';
        return;
    }
    try {
        const res = await fetch(
            `/api/projects/${encodeURIComponent(project)}/deploy-paths/${serverId}`
        );
        const data = await res.json();
        input.value = data.deploy_path || '';
        if (hint) hint.textContent = data.default_deploy_path
            ? `${t('default', 'Default')}: ${data.default_deploy_path}`
            : '';
    } catch (e) {
        if (hint) hint.textContent = '';
    }
}

/** Load the project's stored Git remote URL into the connection modal.
 *  Stashes the project's default branch on the input so saving the remote
 *  later doesn't clobber it. Called when the project selection changes. */
async function loadTargetGitRemote() {
    const input = document.getElementById('target-git-remote');
    if (!input) return;
    const project = document.getElementById('target-project').value;
    if (!project) { input.value = ''; input.dataset.defaultBranch = ''; return; }
    try {
        const res = await fetch(`/api/projects/${encodeURIComponent(project)}/git`);
        const data = await res.json();
        input.value = data.git_remote_url || '';
        input.dataset.defaultBranch = data.git_default_branch || 'main';
    } catch (e) {
        input.value = '';
        input.dataset.defaultBranch = '';
    }
}

/** Persist the connection's two per-project extras: the Git remote URL
 *  (per project) and the (project × server) deploy path override. Returns
 *  an array of human-readable error messages (empty on full success) so
 *  the caller can keep the modal open and let the user retry. */
async function saveConnectionExtras(project, serverId) {
    const errors = [];
    if (!project) return errors;
    // Git remote (per project) — preserve the stashed default branch so we
    // don't reset it to "main" when the user only edited the remote URL.
    const gitInput = document.getElementById('target-git-remote');
    if (gitInput) {
        try {
            const res = await fetch(`/api/projects/${encodeURIComponent(project)}/git`, {
                method: 'PATCH',
                headers: headerJson(),
                body: JSON.stringify({
                    git_remote_url: (gitInput.value || '').trim() || null,
                    git_default_branch: gitInput.dataset.defaultBranch || 'main',
                }),
            });
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                errors.push(d.error || t('failed_save_git', 'Failed to save git config'));
            }
        } catch (e) { errors.push(e.message); }
    }
    // Deploy path override (project × server). Empty value clears the
    // override and falls back to the server default.
    const pathInput = document.getElementById('target-deploy-path');
    if (pathInput && serverId !== null) {
        try {
            const res = await fetch(
                `/api/projects/${encodeURIComponent(project)}/deploy-paths/${serverId}`,
                {
                    method: 'PUT',
                    headers: headerJson(),
                    body: JSON.stringify({ deploy_path: (pathInput.value || '').trim() }),
                }
            );
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                errors.push(d.error || t('failed_save_path', 'Failed to save deploy path'));
            }
        } catch (e) { errors.push(e.message); }
    }
    return errors;
}

async function saveTarget(event) {
    event.preventDefault();
    // NB: safeInt('') === 0 (Number('') is 0), so an empty hidden field
    // must be treated as "no id" (create) BEFORE parsing — otherwise a
    // fresh target would PATCH /…/0 and 404 with "Target not found".
    const idRaw = document.getElementById('target-id').value;
    const targetId = idRaw ? safeInt(idRaw) : null;
    const label = document.getElementById('target-label').value.trim();
    const project = document.getElementById('target-project').value;
    const serverId = safeInt(document.getElementById('target-server').value);
    const branch = document.getElementById('target-branch').value.trim();

    const errBox = document.getElementById('target-error');
    errBox.hidden = true;
    errBox.className = 'deploy-alert';

    if (!label) { showTargetError(t('target_label_required', 'A target name is required.')); return; }

    let url, method, body;
    if (targetId !== null) {
        url = `/api/deployment-targets/${targetId}`;
        method = 'PATCH';
        body = { label, branch };
        if (serverId !== null) body.server_id = serverId;
    } else {
        if (!project || serverId === null) {
            showTargetError(t('project_and_server_required', 'Project and server are required.'));
            return;
        }
        url = '/api/deployment-targets';
        method = 'POST';
        body = { label, project, server_id: serverId, branch };
    }

    try {
        const res = await fetch(url, { method, headers: headerJson(), body: JSON.stringify(body) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showTargetError(data.error || t('save_failed', 'Save failed')); return; }

        // The connection itself is saved. Now persist the two per-project
        // settings edited in the same modal (Git remote URL + deploy path
        // override). If this was a create, flip the modal to edit mode first
        // so that a retry after a failure here PATCHes the connection rather
        // than creating a duplicate.
        if (targetId === null && data.target && data.target.id != null) {
            document.getElementById('target-id').value = String(data.target.id);
        }
        const cfgProject = document.getElementById('target-project').value;
        const cfgServerId = safeInt(document.getElementById('target-server').value);
        const cfgErrors = await saveConnectionExtras(cfgProject, cfgServerId);
        if (cfgErrors.length) { showTargetError(cfgErrors.join(' · ')); return; }

        deployToast('success', targetId !== null ? t('connection_updated', 'Connection updated') : t('connection_created', 'Connection created'));
        bootstrap.Modal.getInstance(document.getElementById('targetModal')).hide();
        loadProjects();   // refresh folder counts / env badges
        loadTargets();
    } catch (e) {
        showTargetError(e.message);
    }
}

async function deleteTarget(targetId) {
    const id = safeInt(targetId);
    if (id === null) return;
    if (!confirm(t('confirm_delete_target', 'Delete this deployment target? Its run history is kept.'))) return;
    try {
        const res = await fetch(`/api/deployment-targets/${id}`, { method: 'DELETE', headers: headerJson() });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
            deployToast('success', t('connection_deleted', 'Connection deleted'));
            loadProjects();
            loadTargets();
        } else {
            deployToast('error', data.error || t('delete_failed', 'Delete failed'));
        }
    } catch (e) {
        deployToast('error', e.message);
    }
}

async function redeployTarget(targetId) {
    const id = safeInt(targetId);
    if (id === null) return;
    const tg = DEPLOY_STATE.targets.find(x => x.id === id);
    if (!tg) return;

    const msg = t('confirm_redeploy', 'Redeploy {project} on {server} ({branch})?')
        .replace('{project}', tg.project_name)
        .replace('{server}', tg.server_label || ('#' + tg.server_id))
        .replace('{branch}', tg.branch);
    if (!confirm(msg)) return;

    try {
        const res = await fetch(`/api/deployment-targets/${id}/deploy`, {
            method: 'POST',
            headers: headerJson(),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            deployToast('error', data.error || t('deployment_refused', 'Deployment refused.'));
            return;
        }
        const newId = safeInt(data.deployment_id);
        showDeployLogView(newId, `Deploy #${newId} — ${tg.project_name} → ${tg.branch}`);
    } catch (e) {
        deployToast('error', e.message);
    }
}

async function toggleTargetHistory(targetId) {
    const id = safeInt(targetId);
    if (id === null) return;
    const card = document.querySelector(`.deploy-target-card[data-target-id="${id}"]`);
    if (!card) return;
    const drawer = card.querySelector('.deploy-target-history');
    const toggle = card.querySelector('.deploy-target-history-toggle');
    if (!drawer) return;

    // Collapse if already open.
    if (!drawer.hidden) {
        drawer.hidden = true;
        if (toggle) toggle.classList.remove('is-open');
        return;
    }

    const tg = DEPLOY_STATE.targets.find(x => x.id === id);
    if (!tg) return;
    drawer.hidden = false;
    if (toggle) toggle.classList.add('is-open');

    // Serve from cache if we already fetched this target's runs.
    if (DEPLOY_STATE.targetHistory[id]) {
        renderTargetHistory(id);
        return;
    }

    drawer.innerHTML = `<div class="deploy-target-history-row">${escapeHtml(t('loading', 'Loading...'))}</div>`;
    try {
        const params = new URLSearchParams({
            project: tg.project_name,
            server_id: String(tg.server_id),
            branch: tg.branch,
            limit: '200',
        });
        const res = await fetch(`/api/deployments?${params.toString()}`);
        const data = await res.json();
        DEPLOY_STATE.targetHistory[id] = {
            rows: data.deployments || [],
            expanded: false,
        };
        renderTargetHistory(id);
    } catch (e) {
        drawer.innerHTML = `<div class="deploy-target-history-row">${escapeHtml(e.message)}</div>`;
    }
}

/** Render a single history row (status pill + sha + date + logs link). */
function renderTargetHistoryRow(d) {
    const did = safeInt(d.id);
    if (did === null) return '';
    const status = safeStatus(d.status);
    const sha = d.commit_sha ? String(d.commit_sha).slice(0, 7) : '—';
    return `
        <div class="deploy-target-history-row">
            <span class="status-pill status-${status}"><span class="status-dot"></span>${escapeHtml(status)}</span>
            <code>${escapeHtml(sha)}</code>
            <span>${escapeHtml(fmtDate(d.started_at))}</span>
            <button class="deploy-target-history-link" data-action="target-logs" data-deployment-id="${did}">
                ${escapeHtml(t('view_logs', 'View logs'))}
            </button>
        </div>
    `;
}

/** Paint the cached history for a target: first TARGET_HISTORY_PAGE runs,
 *  then a "See more" toggle that reveals the rest (and back). */
function renderTargetHistory(targetId) {
    const id = safeInt(targetId);
    const entry = DEPLOY_STATE.targetHistory[id];
    const card = document.querySelector(`.deploy-target-card[data-target-id="${id}"]`);
    if (!entry || !card) return;
    const drawer = card.querySelector('.deploy-target-history');
    if (!drawer) return;

    const rows = entry.rows;
    if (!rows.length) {
        drawer.innerHTML = `<div class="deploy-target-history-row">${escapeHtml(t('no_runs_yet', 'No runs yet for this target.'))}</div>`;
        return;
    }

    const shown = entry.expanded ? rows : rows.slice(0, TARGET_HISTORY_PAGE);
    let html = shown.map(renderTargetHistoryRow).join('');

    if (rows.length > TARGET_HISTORY_PAGE) {
        const hidden = rows.length - TARGET_HISTORY_PAGE;
        const label = entry.expanded
            ? escapeHtml(t('see_less', 'See less'))
            : `${escapeHtml(t('see_more', 'See more'))} (${hidden})`;
        html += `
            <button class="deploy-target-history-more" data-action="target-history-more" data-target-id="${id}">
                ${label}
            </button>
        `;
    }
    drawer.innerHTML = html;
}

function expandTargetHistory(targetId) {
    const id = safeInt(targetId);
    const entry = DEPLOY_STATE.targetHistory[id];
    if (!entry) return;
    entry.expanded = !entry.expanded;
    renderTargetHistory(id);
}

function openConnectionModal(targetId, forcedProject) {
    openTargetModal(targetId, forcedProject);
    new bootstrap.Modal(document.getElementById('targetModal')).show();
}

function onProjectsViewClick(event) {
    // Any element carrying data-action (folders are clickable divs, the
    // rest are buttons/links).
    const el = event.target.closest('[data-action]');
    if (!el) return;
    const action = el.dataset.action;

    // ── folder-grid actions ──
    if (action === 'open-project') {
        // Ignore clicks that originated on the delete button.
        if (event.target.closest('[data-action="delete-project"]')) return;
        if (el.dataset.project) openProject(el.dataset.project);
        return;
    }
    if (action === 'delete-project') {
        event.stopPropagation();
        deleteProject(el.dataset.project);
        return;
    }
    if (action === 'back-to-grid') { backToGrid(); return; }
    if (action === 'add-connection') {
        openConnectionModal(null, el.dataset.project || DEPLOY_STATE.currentProject);
        return;
    }

    // ── connection (target) actions ──
    if (action === 'target-logs') {
        const did = safeInt(el.dataset.deploymentId);
        if (did !== null) replayDeployment(did);
        return;
    }
    const id = safeInt(el.dataset.targetId);
    if (id === null) return;
    if (action === 'target-history-more') expandTargetHistory(id);
    else if (action === 'redeploy') redeployTarget(id);
    else if (action === 'edit-target') openConnectionModal(id);
    else if (action === 'delete-target') deleteTarget(id);
    else if (action === 'toggle-history') toggleTargetHistory(id);
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

async function cancelDeployment(deploymentId) {
    const id = safeInt(deploymentId);
    if (id === null) return;
    if (!confirm(t('confirm_cancel_deployment', 'Cancel this running deployment?'))) return;
    try {
        const res = await fetch(`/api/deployments/${id}/cancel`, {
            method: 'POST',
            headers: headerJson(),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
            deployToast('success', t('deployment_cancelled', 'Cancellation requested'));
        } else {
            deployToast('error', data.error || t('cancel_failed', 'Cancel failed'));
        }
        loadDeployments();
    } catch (e) {
        deployToast('error', e.message);
    }
}

function onDeploymentsTbodyClick(event) {
    const btn = event.target.closest('button[data-action]');
    if (!btn) return;
    const id = safeInt(btn.dataset.deploymentId);
    if (id === null) return;
    if (btn.dataset.action === 'replay') replayDeployment(id);
    else if (btn.dataset.action === 'cancel') cancelDeployment(id);
}

/* ───── reset modals on close ───── */

function bindDeployModalLifecycle() {
    const el = document.getElementById('deployModal');
    if (!el) return;
    el.addEventListener('show.bs.modal', () => {
        document.getElementById('deploy-step-configure').hidden = false;
        document.getElementById('deploy-step-log').hidden = true;
        // Restore the Deploy button for the manual configure step (it is
        // hidden in the live-log / replay views).
        const runBtn = document.getElementById('deploy-run-btn');
        if (runBtn) { runBtn.disabled = false; runBtn.style.display = ''; }
        const msg = document.getElementById('deploy-result-msg');
        if (msg) { msg.hidden = true; msg.textContent = ''; }
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
        const msg = document.getElementById('deploy-result-msg');
        if (msg) { msg.hidden = true; msg.textContent = ''; }
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
    // Load deployable projects first (needed by the create-project select
    // + folder env badges), then projects and connections.
    loadDeployableProjects().finally(() => { loadProjects(); loadTargets(); });
    bindDeployModalLifecycle();
    const sTbody = document.getElementById('servers-tbody');
    if (sTbody) sTbody.addEventListener('click', onServersTbodyClick);
    const dTbody = document.getElementById('deployments-tbody');
    if (dTbody) dTbody.addEventListener('click', onDeploymentsTbodyClick);
    const pView = document.getElementById('projects-view');
    if (pView) pView.addEventListener('click', onProjectsViewClick);
    // Auto-suggest a connection name once project/server are chosen.
    const tServer = document.getElementById('target-server');
    if (tServer) tServer.addEventListener('change', () => {
        suggestConnectionLabel();
        refreshTargetDeployPathField();
    });
    const tProject = document.getElementById('target-project');
    if (tProject) tProject.addEventListener('change', () => {
        suggestConnectionLabel();
        refreshTargetDeployPathField();
        loadTargetGitRemote();
    });
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
window.openTargetModal = openTargetModal;
window.saveTarget = saveTarget;
window.openProjectModal = openProjectModal;
window.saveProject = saveProject;
window.onFaviconError = onFaviconError;
window.openServerFromConnection = openServerFromConnection;
