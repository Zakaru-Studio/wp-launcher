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
    socket: null,
    listenerAttached: false,
};

/* ───── utilities ───── */

function deployToast(kind, msg) {
    if (kind === 'success' && window.showSuccess) return window.showSuccess(msg);
    if (kind === 'error'   && window.showError)   return window.showError(msg);
    console[kind === 'error' ? 'error' : 'log'](msg);
}

function headerJson() {
    const csrf = window.CSRF_TOKEN || '';
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

/* ───── loaders ───── */

async function loadServers() {
    const tbody = document.getElementById('servers-tbody');
    try {
        const res = await fetch('/api/servers');
        if (res.status === 403) {
            tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="6">Admins only — contact an administrator to see servers.</td></tr>`;
            return;
        }
        const data = await res.json();
        DEPLOY_STATE.servers = data.servers || [];
        renderServers();
    } catch (e) {
        tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="6">Failed to load servers: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function renderServers() {
    const tbody = document.getElementById('servers-tbody');
    const servers = DEPLOY_STATE.servers;
    if (!servers.length) {
        tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="6">No server registered yet. Click "Add server".</td></tr>`;
        return;
    }

    tbody.innerHTML = servers.map(s => {
        const envClass = s.env === 'production' ? 'env-production' : 'env-staging';
        const fpShort = s.host_fingerprint ? s.host_fingerprint.slice(0, 22) + '…' : '—';
        return `
            <tr data-server-id="${s.id}">
                <td><strong>${escapeHtml(s.label)}</strong></td>
                <td><span class="env-pill ${envClass}"><span class="env-dot"></span>${escapeHtml(s.env)}</span></td>
                <td><code>${escapeHtml(s.hostname)}:${s.ssh_port}</code></td>
                <td>${escapeHtml(s.ssh_user)}</td>
                <td><code title="${escapeHtml(s.host_fingerprint || '')}">${escapeHtml(fpShort)}</code></td>
                <td class="text-end">
                    <button class="deploy-server-action-btn" title="Test"
                            onclick="testServerById(${s.id})">
                        <span class="material-symbols-outlined">wifi_tethering</span>
                    </button>
                    <button class="deploy-server-action-btn" title="Edit"
                            onclick="openServerModal(${s.id})">
                        <span class="material-symbols-outlined">edit</span>
                    </button>
                    <button class="deploy-server-action-btn is-danger" title="Delete"
                            onclick="deleteServer(${s.id})">
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
        tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="7">Failed to load deployments.</td></tr>`;
    }
}

function renderDeployments() {
    const tbody = document.getElementById('deployments-tbody');
    const rows = DEPLOY_STATE.deployments;
    if (!rows.length) {
        tbody.innerHTML = `<tr class="deploy-empty-row"><td colspan="7">No deployment yet.</td></tr>`;
        return;
    }
    tbody.innerHTML = rows.map(d => {
        const sha = d.commit_sha ? d.commit_sha.slice(0, 7) : '—';
        const status = d.status || 'running';
        const dot = status === 'running' ? '<span class="status-dot is-pulse"></span>' : '<span class="status-dot"></span>';
        return `
            <tr>
                <td><strong>${escapeHtml(d.project_name)}</strong></td>
                <td>${escapeHtml(d.server_label || ('#' + d.server_id))} <small class="profile-field-hint">(${escapeHtml(d.server_env || '')})</small></td>
                <td><code>${escapeHtml(d.branch)}</code></td>
                <td><code>${escapeHtml(sha)}</code></td>
                <td><span class="status-pill status-${status}">${dot}${escapeHtml(status)}</span></td>
                <td><small>${escapeHtml(fmtDate(d.started_at))}</small></td>
                <td class="text-end">
                    <button class="deploy-server-action-btn" title="View logs"
                            onclick="replayDeployment(${d.id})">
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
            sel.innerHTML = `<option value="">— Select a project —</option>` +
                data.projects.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join('');
        }
    } catch (e) {
        console.error('Deployable projects:', e);
    }
}

function populateDeployServerSelect() {
    const sel = document.getElementById('deploy-server');
    if (!sel) return;
    if (!DEPLOY_STATE.servers.length) {
        sel.innerHTML = `<option value="">No server available</option>`;
        return;
    }
    sel.innerHTML = `<option value="">— Select a server —</option>` +
        DEPLOY_STATE.servers.map(s =>
            `<option value="${s.id}">${escapeHtml(s.label)} (${escapeHtml(s.env)}) — ${escapeHtml(s.hostname)}</option>`
        ).join('');
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

    if (serverId) {
        const server = DEPLOY_STATE.servers.find(s => s.id === serverId);
        if (!server) return;
        title.textContent = 'Edit server';
        idField.value = server.id;
        document.getElementById('server-label').value = server.label;
        document.getElementById('server-env').value = server.env;
        document.getElementById('server-hostname').value = server.hostname;
        document.getElementById('server-ssh-port').value = server.ssh_port;
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
        title.textContent = 'Add server';
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
    resultBox.textContent = 'Testing…';

    const serverId = document.getElementById('server-id').value || null;
    const body = {
        hostname: document.getElementById('server-hostname').value,
        ssh_port: Number(document.getElementById('server-ssh-port').value) || 22,
        ssh_user: document.getElementById('server-ssh-user').value,
    };
    const pk = document.getElementById('server-private-key').value;
    if (pk.trim()) body.private_key = pk;
    if (serverId) body.server_id = Number(serverId);

    try {
        const res = await fetch('/api/servers/test', {
            method: 'POST',
            headers: headerJson(),
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.ok) {
            resultBox.className = 'deploy-alert is-ok';
            resultBox.textContent = 'Connection OK. Fingerprint pinned: ' + (data.fingerprint || '—');
            fpBox.hidden = false;
            fpVal.textContent = data.fingerprint || '';
        } else {
            resultBox.className = 'deploy-alert is-error';
            resultBox.textContent = data.error || 'Connection failed.';
        }
    } catch (e) {
        resultBox.className = 'deploy-alert is-error';
        resultBox.textContent = 'Request failed: ' + e.message;
    }
}

async function testServerById(serverId) {
    openServerModal(serverId);
    setTimeout(testServerConnection, 200);
    const modal = new bootstrap.Modal(document.getElementById('serverModal'));
    modal.show();
}

async function saveServer(event) {
    event.preventDefault();
    const serverId = document.getElementById('server-id').value;
    const fpVal = document.getElementById('server-fingerprint-value').textContent.trim();
    const body = {
        label: document.getElementById('server-label').value.trim(),
        env: document.getElementById('server-env').value,
        hostname: document.getElementById('server-hostname').value.trim(),
        ssh_port: Number(document.getElementById('server-ssh-port').value) || 22,
        ssh_user: document.getElementById('server-ssh-user').value.trim(),
        deploy_base_path: document.getElementById('server-deploy-path').value.trim(),
        host_fingerprint: fpVal && fpVal !== '—' ? fpVal : null,
    };
    const pk = document.getElementById('server-private-key').value;
    if (pk.trim()) body.private_key = pk;

    const url = serverId ? `/api/servers/${serverId}` : '/api/servers';
    const method = serverId ? 'PATCH' : 'POST';
    if (!serverId && !body.private_key) {
        deployToast('error', 'A private key is required when creating a server.');
        return;
    }

    try {
        const res = await fetch(url, { method, headers: headerJson(), body: JSON.stringify(body) });
        const data = await res.json();
        if (!res.ok) {
            deployToast('error', data.error || 'Save failed');
            return;
        }
        deployToast('success', serverId ? 'Server updated' : 'Server created');
        bootstrap.Modal.getInstance(document.getElementById('serverModal')).hide();
        await loadServers();
        populateDeployServerSelect();
    } catch (e) {
        deployToast('error', e.message);
    }
}

async function deleteServer(serverId) {
    if (!confirm('Delete this server? Existing deployment history is kept.')) return;
    const res = await fetch(`/api/servers/${serverId}`, { method: 'DELETE', headers: headerJson() });
    if (res.ok) {
        deployToast('success', 'Server deleted');
        await loadServers();
        populateDeployServerSelect();
    } else {
        const data = await res.json().catch(() => ({}));
        deployToast('error', data.error || 'Delete failed');
    }
}

/* ───── deploy modal ───── */

async function onDeployProjectChange() {
    const project = document.getElementById('deploy-project').value;
    if (!project) {
        document.getElementById('deploy-branch').value = '';
        document.getElementById('deploy-git-remote').value = '';
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
}

async function saveProjectGitConfig() {
    const project = document.getElementById('deploy-project').value;
    if (!project) { deployToast('error', 'Pick a project first.'); return; }
    const body = {
        git_remote_url: document.getElementById('deploy-git-remote').value.trim() || null,
        git_default_branch: (document.getElementById('deploy-branch').value || 'main').trim(),
    };
    const res = await fetch(`/api/projects/${encodeURIComponent(project)}/git`, {
        method: 'PATCH',
        headers: headerJson(),
        body: JSON.stringify(body),
    });
    if (res.ok) deployToast('success', 'Git config saved');
    else {
        const d = await res.json().catch(() => ({}));
        deployToast('error', d.error || 'Failed to save git config');
    }
}

function ensureSocketSubscribed(deploymentId) {
    if (!DEPLOY_STATE.socket && typeof window.getSocketIO === 'function') {
        DEPLOY_STATE.socket = window.getSocketIO();
    }
    if (!DEPLOY_STATE.socket || DEPLOY_STATE.listenerAttached) {
        DEPLOY_STATE.currentDeploymentId = deploymentId;
        return;
    }
    DEPLOY_STATE.socket.emit('join', { room: `deploy_${deploymentId}` });
    DEPLOY_STATE.currentDeploymentId = deploymentId;
    DEPLOY_STATE.socket.on('deployment_log', (data) => {
        if (data.id !== DEPLOY_STATE.currentDeploymentId) return;
        appendDeployLogLine(data.line, data.stream || 'stdout');
    });
    DEPLOY_STATE.socket.on('deployment_complete', (data) => {
        if (data.id !== DEPLOY_STATE.currentDeploymentId) return;
        setDeployStatus(data.status || 'success');
        loadDeployments();
    });
    DEPLOY_STATE.listenerAttached = true;
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
    const pill = document.getElementById('deploy-status-pill');
    const label = document.getElementById('deploy-status-label');
    const dot = pill ? pill.querySelector('.status-dot') : null;
    if (label) label.textContent = status;
    if (pill) pill.className = 'status-pill status-' + status;
    if (dot) dot.classList.toggle('is-pulse', status === 'running');
}

async function runDeployment() {
    const project = document.getElementById('deploy-project').value;
    const serverId = document.getElementById('deploy-server').value;
    const branch = document.getElementById('deploy-branch').value.trim() || 'main';

    const errBox = document.getElementById('deploy-error');
    errBox.hidden = true;
    errBox.className = 'deploy-alert';

    if (!project || !serverId) {
        errBox.hidden = false;
        errBox.className = 'deploy-alert is-error';
        errBox.textContent = 'Project and server are required.';
        return;
    }

    try {
        const res = await fetch('/api/deployments/run', {
            method: 'POST',
            headers: headerJson(),
            body: JSON.stringify({ project, server_id: Number(serverId), branch }),
        });
        const data = await res.json();
        if (!res.ok) {
            errBox.hidden = false;
            errBox.className = 'deploy-alert is-error';
            errBox.textContent = data.error || 'Deployment refused.';
            return;
        }
        document.getElementById('deploy-step-configure').hidden = true;
        document.getElementById('deploy-step-log').hidden = false;
        document.getElementById('deploy-run-btn').disabled = true;
        document.getElementById('deploy-log-title').textContent = `Deploy #${data.deployment_id} — ${project} → ${branch}`;
        document.getElementById('deploy-log-pane').innerHTML = '';
        setDeployStatus('running');
        ensureSocketSubscribed(data.deployment_id);
        loadDeployments();
    } catch (e) {
        errBox.hidden = false;
        errBox.className = 'deploy-alert is-error';
        errBox.textContent = e.message;
    }
}

async function replayDeployment(deploymentId) {
    try {
        const res = await fetch(`/api/deployments/${deploymentId}/log`);
        const data = await res.json();
        const modalEl = document.getElementById('deployModal');
        const modal = new bootstrap.Modal(modalEl);
        document.getElementById('deploy-step-configure').hidden = true;
        document.getElementById('deploy-step-log').hidden = false;
        document.getElementById('deploy-run-btn').disabled = true;
        document.getElementById('deploy-log-title').textContent = `Deploy #${deploymentId} — logs`;
        document.getElementById('deploy-log-pane').textContent = data.log || '(no log output)';
        setDeployStatus(data.status || 'success');
        modal.show();
    } catch (e) {
        deployToast('error', e.message);
    }
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
    const projectSel = document.getElementById('deploy-project');
    if (projectSel) projectSel.addEventListener('change', onDeployProjectChange);
}

/* ───── boot ───── */

document.addEventListener('DOMContentLoaded', () => {
    loadServers();
    loadDeployments();
    loadDeployableProjects();
    bindDeployModalLifecycle();
});

// Expose to inline onclick handlers in the template
window.openServerModal = openServerModal;
window.saveServer = saveServer;
window.deleteServer = deleteServer;
window.testServerById = testServerById;
window.testServerConnection = testServerConnection;
window.runDeployment = runDeployment;
window.saveProjectGitConfig = saveProjectGitConfig;
window.replayDeployment = replayDeployment;
