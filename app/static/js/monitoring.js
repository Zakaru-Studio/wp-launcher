/**
 * Monitoring Dashboard
 */

let cpuChart, memoryChart, diskChart;
let refreshInterval;
let refreshIntervalDelay = 5000; // Délai par défaut
let currentTab = 'serveur';
let tabsLoaded = {
    serveur: false,
    docker: false,
    processus: false
};

// Pagination des processus
let currentProcessPage = 1;
let totalProcessPages = 1;
let processesPerPage = 20;
let allProcesses = [];

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
    initCharts();
    // Charger uniquement l'onglet serveur au démarrage
    loadServerStats();
    tabsLoaded.serveur = true;
    
    // Rafraîchir l'onglet actif
    startAutoRefresh();
});

/**
 * Démarre le rafraîchissement automatique
 */
function startAutoRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    
    refreshInterval = setInterval(() => {
        if (currentTab === 'serveur') {
            loadSystemStats();
        } else if (currentTab === 'docker') {
            loadDockerStats();
        } else if (currentTab === 'processus') {
            loadProcesses();
        }
    }, refreshIntervalDelay);
}

/**
 * Met à jour l'intervalle de rafraîchissement
 */
function updateRefreshInterval() {
    const select = document.getElementById('refresh-interval');
    refreshIntervalDelay = parseInt(select.value);
    startAutoRefresh();

    if (typeof showToast === 'function') {
        showToast(`Actualisation réglée sur ${refreshIntervalDelay / 1000}s`, 'success');
    }
}

/**
 * Stitch refresh range pill toggle (5S/10S/30S/1M)
 */
function setRefreshRange(ms, btn) {
    refreshIntervalDelay = ms;
    const select = document.getElementById('refresh-interval');
    if (select) {
        const val = String(ms);
        if ([...select.options].some(o => o.value === val)) {
            select.value = val;
        }
    }
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    startAutoRefresh();
}

// Nettoyer l'intervalle quand on quitte la page
window.addEventListener('beforeunload', function() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
});

/**
 * Change d'onglet et charge les données si nécessaire
 */
function switchTab(tabName) {
    currentTab = tabName;

    // Désactiver tous les onglets
    document.querySelectorAll('.monitoring-tab').forEach(tab => {
        tab.classList.remove('active');
    });

    // Masquer tout le contenu
    document.querySelectorAll('.tab-content-pane').forEach(pane => {
        pane.classList.remove('active');
    });

    // Activer l'onglet et le contenu sélectionnés
    event.target.classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');

    // Charger les données si ce n'est pas déjà fait
    if (!tabsLoaded[tabName]) {
        if (tabName === 'docker') {
            renderDockerSkeleton();
            loadDockerStats();
        } else if (tabName === 'processus') {
            renderProcessSkeleton();
            loadProcesses();
        }
        tabsLoaded[tabName] = true;
    }
}

/**
 * Render placeholder skeleton cards while Docker stats are fetched.
 * Keeps the UI feeling responsive — the user sees structure immediately
 * even when the API call takes a few seconds.
 */
function renderDockerSkeleton(count = 4) {
    const containersList = document.getElementById('docker-containers-list');
    if (!containersList) return;

    const countEl = document.getElementById('docker-count');
    if (countEl) countEl.innerHTML = '<span class="skeleton-bar" style="width:80px;height:14px"></span>';

    let cards = '';
    for (let i = 0; i < count; i++) {
        cards += `
            <div class="docker-container-item is-loading" aria-busy="true">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="d-flex align-items-center gap-2">
                        <span class="skeleton-bar" style="width:160px;height:16px"></span>
                        <span class="skeleton-pill" style="width:70px"></span>
                    </div>
                </div>
                <div class="container-stats">
                    <div class="container-stat">
                        <span class="skeleton-bar" style="width:30px;height:9px;margin:0 auto 6px"></span>
                        <span class="skeleton-bar" style="width:50px;height:18px;margin:0 auto"></span>
                    </div>
                    <div class="container-stat">
                        <span class="skeleton-bar" style="width:50px;height:9px;margin:0 auto 6px"></span>
                        <span class="skeleton-bar" style="width:80px;height:18px;margin:0 auto"></span>
                    </div>
                    <div class="container-stat">
                        <span class="skeleton-bar" style="width:45px;height:9px;margin:0 auto 6px"></span>
                        <span class="skeleton-bar" style="width:90px;height:14px;margin:0 auto"></span>
                    </div>
                </div>
            </div>
        `;
    }
    containersList.innerHTML = cards;
}

/**
 * Render placeholder rows while the process list is fetched.
 */
function renderProcessSkeleton(count = 8) {
    const list = document.getElementById('process-list');
    if (!list) return;
    let rows = '';
    for (let i = 0; i < count; i++) {
        rows += `
            <div class="process-item is-loading" aria-busy="true">
                <div class="process-info">
                    <span class="skeleton-bar" style="width:${100 + (i % 3) * 40}px;height:14px"></span>
                    <span class="skeleton-bar" style="width:60px;height:10px;margin-top:6px"></span>
                </div>
                <span class="skeleton-bar" style="width:80px;height:18px"></span>
            </div>
        `;
    }
    list.innerHTML = rows;
}

/**
 * Rafraîchit les stats du serveur
 */
function refreshServerStats() {
    loadSystemStats();
}

/**
 * Rafraîchit les stats Docker
 */
function refreshDockerStats() {
    renderDockerSkeleton();
    loadDockerStats();
}

/**
 * Rafraîchit la liste des processus
 */
function refreshProcessList() {
    loadProcesses();
}

/**
 * Initialise les graphiques
 */
function initCharts() {
    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false
            }
        },
        scales: {
            y: {
                beginAtZero: true,
                max: 100,
                ticks: {
                    callback: function(value) {
                        return value + '%';
                    }
                }
            }
        }
    };

    // CPU Chart
    const cpuCtx = document.getElementById('cpuChart').getContext('2d');
    cpuChart = new Chart(cpuCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'CPU %',
                data: [],
                borderColor: 'rgb(75, 192, 192)',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                tension: 0.4,
                fill: true
            }]
        },
        options: chartOptions
    });

    // Memory Chart
    const memoryCtx = document.getElementById('memoryChart').getContext('2d');
    memoryChart = new Chart(memoryCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'RAM %',
                data: [],
                borderColor: 'rgb(153, 102, 255)',
                backgroundColor: 'rgba(153, 102, 255, 0.2)',
                tension: 0.4,
                fill: true
            }]
        },
        options: chartOptions
    });

    // Disk Chart
    const diskCtx = document.getElementById('diskChart').getContext('2d');
    diskChart = new Chart(diskCtx, {
        type: 'doughnut',
        data: {
            labels: ['Utilisé', 'Libre'],
            datasets: [{
                data: [0, 100],
                backgroundColor: [
                    'rgb(255, 99, 132)',
                    'rgb(54, 162, 235)'
                ]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    });
}

/**
 * Charge les statistiques serveur (alias pour loadSystemStats)
 */
async function loadServerStats() {
    return await loadSystemStats();
}

/**
 * Charge les statistiques système
 */
async function loadSystemStats() {
    try {
        const response = await fetch('/api/monitoring/system');
        const data = await response.json();

        if (data.success) {
            // CPU (Stitch: "42" with % implicit; we keep a compact label)
            updateChart(cpuChart, data.cpu.percent);
            const cpuEl = document.getElementById('cpu-value');
            if (cpuEl) cpuEl.innerHTML = `${data.cpu.percent.toFixed(0)}<span class="metric-value-unit">%</span>`;

            // Memory — new Stitch layout: big number = used GB, total displayed separately
            updateChart(memoryChart, data.memory.percent);
            const memValueEl = document.getElementById('memory-value');
            if (memValueEl) memValueEl.innerHTML = `${data.memory.used.toFixed(1)}<span class="metric-value-unit">GB</span>`;
            const memUsed = document.getElementById('memory-used');
            const memTotal = document.getElementById('memory-total');
            if (memUsed) memUsed.textContent = data.memory.used.toFixed(1);
            if (memTotal) memTotal.textContent = data.memory.total.toFixed(1);
            const memPct = document.getElementById('memory-pct-label');
            if (memPct) memPct.textContent = data.memory.percent.toFixed(1);
            const memFill = document.getElementById('memory-progress-fill');
            if (memFill) memFill.style.width = `${data.memory.percent}%`;
            const memTotalDisplay = document.getElementById('memory-total-display');
            if (memTotalDisplay) memTotalDisplay.textContent = `/ ${data.memory.total.toFixed(1)} GB`;

            // Disk
            diskChart.data.datasets[0].data = [data.disk.percent, 100 - data.disk.percent];
            diskChart.update();
            const diskEl = document.getElementById('disk-value');
            if (diskEl) diskEl.innerHTML = `${data.disk.percent.toFixed(0)}<span class="metric-value-unit">%</span>`;
            const diskUsed = document.getElementById('disk-used');
            const diskTotal = document.getElementById('disk-total');
            if (diskUsed) diskUsed.textContent = data.disk.used.toFixed(1);
            if (diskTotal) diskTotal.textContent = data.disk.total.toFixed(1);
        }
    } catch (error) {
        console.error('Erreur chargement stats système:', error);
    }
}

/**
 * Met à jour un graphique avec une nouvelle valeur
 */
function updateChart(chart, value) {
    const now = new Date().toLocaleTimeString();
    
    chart.data.labels.push(now);
    chart.data.datasets[0].data.push(value);

    // Garder seulement les 10 dernières valeurs
    if (chart.data.labels.length > 10) {
        chart.data.labels.shift();
        chart.data.datasets[0].data.shift();
    }

    chart.update('none'); // Update sans animation pour être plus fluide
}

/**
 * Charge les statistiques Docker
 */
async function loadDockerStats() {
    try {
        const response = await fetch('/api/monitoring/docker');
        const data = await response.json();

        if (data.success) {
            const containersList = document.getElementById('docker-containers-list');
            document.getElementById('docker-count').textContent = `${data.total_containers} conteneur${data.total_containers > 1 ? 's' : ''}`;

            if (data.containers.length === 0) {
                containersList.innerHTML = '<p class="text-muted text-center">Aucun conteneur actif</p>';
                return;
            }

            containersList.innerHTML = data.containers.map(container => `
                <div class="docker-container-item">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${container.name}</strong>
                            <span class="badge bg-info ms-2">${container.project}</span>
                        </div>
                    </div>
                    <div class="container-stats">
                        <div class="container-stat">
                            <div class="container-stat-label">CPU</div>
                            <div class="container-stat-value">${container.cpu}</div>
                        </div>
                        <div class="container-stat">
                            <div class="container-stat-label">Mémoire</div>
                            <div class="container-stat-value">${container.memory_usage}</div>
                        </div>
                        <div class="container-stat">
                            <div class="container-stat-label">Réseau</div>
                            <div class="container-stat-value" style="font-size: 0.9rem;">${container.network}</div>
                        </div>
                    </div>
                </div>
            `).join('');
        }
    } catch (error) {
        console.error('Erreur chargement stats Docker:', error);
    }
}

/**
 * Charge la liste des processus
 */
async function loadProcesses() {
    try {
        const response = await fetch('/api/monitoring/processes?limit=1000');
        const data = await response.json();

        if (data.success) {
            allProcesses = data.processes;
            document.getElementById('process-count').textContent = `${data.total_processes} processus`;
            
            // Calculer le nombre de pages
            totalProcessPages = Math.ceil(allProcesses.length / processesPerPage);
            document.getElementById('total-pages').textContent = totalProcessPages;
            
            // Afficher la première page
            currentProcessPage = 1;
            renderProcessPage();
        }
    } catch (error) {
        console.error('Erreur chargement processus:', error);
    }
}

/**
 * Affiche une page de processus
 */
function renderProcessPage() {
    const processList = document.getElementById('process-list');
    
    if (allProcesses.length === 0) {
        processList.innerHTML = '<p class="text-muted text-center">Aucun processus</p>';
        return;
    }
    
    const startIndex = (currentProcessPage - 1) * processesPerPage;
    const endIndex = startIndex + processesPerPage;
    const pageProcesses = allProcesses.slice(startIndex, endIndex);
    
    processList.innerHTML = pageProcesses.map(proc => `
        <div class="process-item">
            <div class="process-info">
                <strong>${proc.name}</strong>
                <small class="text-muted d-block">PID: ${proc.pid} | User: ${proc.user}</small>
            </div>
            <div class="text-end me-3">
                <div>CPU: <strong>${proc.cpu.toFixed(1)}%</strong></div>
                <div><small>RAM: ${proc.memory.toFixed(1)}%</small></div>
            </div>
            <div class="process-actions">
                <button class="btn-kill" onclick="killProcess(${proc.pid}, '${proc.name}')" title="Terminer le processus">
                    <i class="fas fa-times me-1"></i>Kill
                </button>
            </div>
        </div>
    `).join('');
    
    // Mettre à jour les boutons de pagination
    document.getElementById('current-page').textContent = currentProcessPage;
    document.getElementById('btn-prev-page').disabled = currentProcessPage === 1;
    document.getElementById('btn-next-page').disabled = currentProcessPage === totalProcessPages;
}

/**
 * Page précédente
 */
function previousProcessPage() {
    if (currentProcessPage > 1) {
        currentProcessPage--;
        renderProcessPage();
    }
}

/**
 * Page suivante
 */
function nextProcessPage() {
    if (currentProcessPage < totalProcessPages) {
        currentProcessPage++;
        renderProcessPage();
    }
}

/**
 * Tue un processus
 */
async function killProcess(pid, name) {
    if (!confirm(`Terminer le processus "${name}" (PID: ${pid}) ?\n\nAttention : Cette action est irréversible.`)) {
        return;
    }
    
    try {
        const response = await fetch('/api/monitoring/kill-process', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ pid: pid })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`Processus ${pid} terminé avec succès`, 'success');
            // Recharger la liste après 1 seconde
            setTimeout(loadProcesses, 1000);
        } else {
            showToast(`Erreur: ${data.error}`, 'error');
        }
    } catch (error) {
        showToast('Erreur lors de la terminaison du processus', 'error');
        console.error('Erreur kill process:', error);
    }
}


