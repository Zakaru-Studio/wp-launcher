/**
 * Gestion des Sauvegardes
 */

// Pagination
const BACKUPS_PER_PAGE = 20;
let allMysqlBackups = [];
let allMongodbBackups = [];
let currentMysqlPage = 1;
let currentMongodbPage = 1;

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
    // Charger la liste des backups au démarrage
    refreshBackupList();
});

/**
 * Change d'onglet de backup
 */
function switchBackupTab(tabName) {
    // Désactiver tous les onglets
    document.querySelectorAll('.backup-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Masquer tout le contenu
    document.querySelectorAll('.backup-content-pane').forEach(pane => {
        pane.classList.remove('active');
    });
    
    // Activer l'onglet et le contenu sélectionnés
    event.target.closest('.backup-tab').classList.add('active');
    document.getElementById(`backup-${tabName}`).classList.add('active');
}

/**
 * Rafraîchit la liste des backups
 */
async function refreshBackupList() {
    try {
        const response = await fetch('/api/backups');
        const data = await response.json();

        if (data.success) {
            // MySQL backups
            allMysqlBackups = data.backups.mysql;
            document.getElementById('mysql-count').textContent = data.total_mysql;
            currentMysqlPage = 1;
            renderMysqlPage();

            // MongoDB backups
            allMongodbBackups = data.backups.mongodb;
            document.getElementById('mongodb-count').textContent = data.total_mongodb;
            currentMongodbPage = 1;
            renderMongodbPage();

            // Storage panel (Stitch aside)
            updateStoragePanel();

            showToast('Liste des backups actualisée', 'success');
        } else {
            showToast('Erreur lors du chargement des backups', 'error');
        }
    } catch (error) {
        console.error('Erreur chargement backups:', error);
        showToast('Erreur de connexion', 'error');
    }
}

/**
 * Rend la page MySQL actuelle
 */
function renderMysqlPage() {
    const mysqlList = document.getElementById('mysql-backup-list');
    const mysqlPagination = document.getElementById('mysql-pagination');
    
    if (allMysqlBackups.length === 0) {
        mysqlList.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-database"></i>
                <h3>Aucun backup MySQL</h3>
                <p>Lancez un backup pour commencer</p>
            </div>
        `;
        mysqlPagination.style.display = 'none';
        return;
    }
    
    const totalPages = Math.ceil(allMysqlBackups.length / BACKUPS_PER_PAGE);
    const startIndex = (currentMysqlPage - 1) * BACKUPS_PER_PAGE;
    const endIndex = startIndex + BACKUPS_PER_PAGE;
    const pageBackups = allMysqlBackups.slice(startIndex, endIndex);
    
    mysqlList.innerHTML = pageBackups.map(backup => createBackupItem(backup, 'mysql')).join('');
    
    // Afficher/masquer la pagination
    if (totalPages > 1) {
        mysqlPagination.style.display = 'flex';
        document.getElementById('mysql-current-page').textContent = currentMysqlPage;
        document.getElementById('mysql-total-pages').textContent = totalPages;
        document.getElementById('btn-mysql-prev').disabled = currentMysqlPage === 1;
        document.getElementById('btn-mysql-next').disabled = currentMysqlPage === totalPages;
    } else {
        mysqlPagination.style.display = 'none';
    }
}

/**
 * Rend la page MongoDB actuelle
 */
function renderMongodbPage() {
    const mongodbList = document.getElementById('mongodb-backup-list');
    const mongodbPagination = document.getElementById('mongodb-pagination');
    
    if (allMongodbBackups.length === 0) {
        mongodbList.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-leaf"></i>
                <h3>Aucun backup MongoDB</h3>
                <p>Lancez un backup pour commencer</p>
            </div>
        `;
        mongodbPagination.style.display = 'none';
        return;
    }
    
    const totalPages = Math.ceil(allMongodbBackups.length / BACKUPS_PER_PAGE);
    const startIndex = (currentMongodbPage - 1) * BACKUPS_PER_PAGE;
    const endIndex = startIndex + BACKUPS_PER_PAGE;
    const pageBackups = allMongodbBackups.slice(startIndex, endIndex);
    
    mongodbList.innerHTML = pageBackups.map(backup => createBackupItem(backup, 'mongodb')).join('');
    
    // Afficher/masquer la pagination
    if (totalPages > 1) {
        mongodbPagination.style.display = 'flex';
        document.getElementById('mongodb-current-page').textContent = currentMongodbPage;
        document.getElementById('mongodb-total-pages').textContent = totalPages;
        document.getElementById('btn-mongodb-prev').disabled = currentMongodbPage === 1;
        document.getElementById('btn-mongodb-next').disabled = currentMongodbPage === totalPages;
    } else {
        mongodbPagination.style.display = 'none';
    }
}

/**
 * Page précédente MySQL
 */
function previousMysqlPage() {
    if (currentMysqlPage > 1) {
        currentMysqlPage--;
        renderMysqlPage();
    }
}

/**
 * Page suivante MySQL
 */
function nextMysqlPage() {
    const totalPages = Math.ceil(allMysqlBackups.length / BACKUPS_PER_PAGE);
    if (currentMysqlPage < totalPages) {
        currentMysqlPage++;
        renderMysqlPage();
    }
}

/**
 * Page précédente MongoDB
 */
function previousMongodbPage() {
    if (currentMongodbPage > 1) {
        currentMongodbPage--;
        renderMongodbPage();
    }
}

/**
 * Page suivante MongoDB
 */
function nextMongodbPage() {
    const totalPages = Math.ceil(allMongodbBackups.length / BACKUPS_PER_PAGE);
    if (currentMongodbPage < totalPages) {
        currentMongodbPage++;
        renderMongodbPage();
    }
}

/**
 * Crée l'HTML pour un item de backup (Stitch .backup-row layout)
 */
function createBackupItem(backup, type) {
    const date = new Date(backup.created * 1000);
    const dateStr = date.toLocaleString('fr-FR', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });

    const typeLabel = type === 'mysql' ? 'MySQL' : 'MongoDB';
    const iconClass = type === 'mysql' ? 'fas fa-database' : 'fas fa-leaf';
    const destination = type === 'mysql'
        ? 'Local / backups/mysql'
        : 'Local / backups/mongodb';

    const sizeMb = backup.size_mb != null ? backup.size_mb : 0;
    const sizeDisplay = sizeMb >= 1024
        ? `${(sizeMb / 1024).toFixed(1)} GB`
        : `${sizeMb} MB`;

    return `
        <div class="backup-row" data-backup-project="${backup.project}" data-backup-file="${backup.filename}">
            <div class="backup-row-name">
                <div class="backup-row-icon"><i class="${iconClass}"></i></div>
                <div class="backup-row-text">
                    <div class="backup-row-title">${backup.project}</div>
                    <div class="backup-row-dest">
                        <i class="fas fa-cloud"></i>
                        <span>${destination}</span>
                    </div>
                </div>
            </div>
            <div class="backup-row-type-cell">
                <span class="backup-row-type">${typeLabel}</span>
            </div>
            <div class="backup-row-size-cell">
                <div class="backup-row-size">${sizeDisplay}</div>
                <div class="backup-row-time">${dateStr}</div>
            </div>
            <div class="backup-row-status">
                <span class="backup-status-pill">
                    <span class="status-dot"></span>
                    Complete
                </span>
                <button class="backup-kebab backup-action-btn danger" onclick="deleteBackup('${type}', '${backup.project}', '${backup.filename}')" title="Supprimer">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
    `;
}

/**
 * Met à jour le panneau Storage Utilization
 */
function updateStoragePanel() {
    const totalMbMysql = allMysqlBackups.reduce((sum, b) => sum + (b.size_mb || 0), 0);
    const totalMbMongo = allMongodbBackups.reduce((sum, b) => sum + (b.size_mb || 0), 0);
    const totalMb = totalMbMysql + totalMbMongo;
    const totalGb = totalMb / 1024;

    const usedEl = document.getElementById('storage-used-value');
    const fillEl = document.getElementById('storage-bar-fill');
    const dbEl = document.getElementById('storage-db-value');
    const filesEl = document.getElementById('storage-files-value');
    if (!usedEl || !fillEl) return;

    usedEl.textContent = totalGb >= 1 ? totalGb.toFixed(1) : totalMb.toFixed(0);
    const unitEl = document.getElementById('storage-used-unit');
    if (unitEl) unitEl.textContent = totalGb >= 1 ? 'GB Used' : 'MB Used';

    // Progress relative to a soft 100 GB ceiling (arbitrary cap)
    const pct = Math.max(2, Math.min(100, (totalGb / 100) * 100));
    fillEl.style.width = pct + '%';

    if (dbEl) dbEl.textContent = (totalMbMysql / 1024).toFixed(1) + ' GB';
    if (filesEl) filesEl.textContent = (totalMbMongo / 1024).toFixed(1) + ' GB';
}

/**
 * Lance un backup
 */
async function runBackup(type) {
    const btn = event.target.closest('button');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>En cours...';

    try {
        const response = await fetch('/api/backups/run', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ type: type })
        });

        const data = await response.json();

        if (data.success) {
            showToast(`Backup ${type} lancé avec succès!`, 'success');
            // Recharger la liste des backups après 3 secondes
            setTimeout(refreshBackupList, 3000);
        } else {
            showToast(`Erreur: ${data.error}`, 'error');
        }
    } catch (error) {
        showToast('Erreur lors du lancement du backup', 'error');
        console.error('Erreur backup:', error);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

/**
 * Supprime un backup
 */
async function deleteBackup(type, project, filename) {
    if (!confirm(`Supprimer le backup "${filename}" du projet "${project}" ?\n\nCette action est irréversible.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/backups/${type}/${project}/${filename}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            showToast('Backup supprimé avec succès', 'success');
            refreshBackupList();
        } else {
            showToast(`Erreur: ${data.error}`, 'error');
        }
    } catch (error) {
        showToast('Erreur lors de la suppression du backup', 'error');
        console.error('Erreur suppression:', error);
    }
}


