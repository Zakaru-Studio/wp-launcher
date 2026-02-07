let currentLogFile = null;
let logStructure = {};

function initLogsViewer(initialLogStructure) {
    logStructure = initialLogStructure;
    
    renderTabs();
    if (Object.keys(logStructure).length > 0) {
        const firstCategory = Object.keys(logStructure)[0];
        activateTab(firstCategory);
    }
    
    document.getElementById('logViewer').style.display = 'flex';
}

function renderTabs() {
    const tabsContainer = document.getElementById('logsTabs');
    const contentContainer = document.getElementById('logsTabsContent');
    
    tabsContainer.innerHTML = '';
    contentContainer.innerHTML = '';
    
    if (Object.keys(logStructure).length === 0) {
        contentContainer.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-inbox"></i>
                <h3>Aucun fichier de log trouvé</h3>
                <p>Il n'y a actuellement aucun fichier de log dans le système.</p>
            </div>
        `;
        return;
    }
    
    Object.keys(logStructure).forEach(category => {
        const tab = document.createElement('button');
        tab.className = 'log-tab';
        tab.textContent = category;
        tab.onclick = () => activateTab(category);
        tabsContainer.appendChild(tab);
        
        const tabContent = document.createElement('div');
        tabContent.className = 'tab-content';
        tabContent.id = `tab-${category}`;
        
        const filesGrid = document.createElement('div');
        filesGrid.className = 'log-files-grid';
        
        logStructure[category].forEach(file => {
            const fileCard = createFileCard(file);
            filesGrid.appendChild(fileCard);
        });
        
        tabContent.appendChild(filesGrid);
        contentContainer.appendChild(tabContent);
    });
}

function createFileCard(file) {
    const card = document.createElement('div');
    card.className = 'log-file-card';
    card.setAttribute('data-file-path', file.path);
    
    card.innerHTML = `
        <div class="log-file-name">${file.name}</div>
        <div class="log-file-info">
            <span>${file.formatted_size}</span>
            <span>${file.modified}</span>
        </div>
        <div class="log-file-actions">
            <button class="btn-delete">
                <i class="fas fa-trash"></i> Supprimer
            </button>
        </div>
    `;
    
    const deleteBtn = card.querySelector('.btn-delete');
    
    card.addEventListener('click', () => viewLogFile(file.path, file.name));
    deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteLogFile(file.path, file.name);
    });
    
    return card;
}

function activateTab(category) {
    document.querySelectorAll('.log-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    
    const activeTab = document.querySelector(`[onclick="activateTab('${category}')"]`);
    const activeContent = document.getElementById(`tab-${category}`);
    
    if (activeTab) {
        activeTab.classList.add('active');
    }
    
    if (activeContent) {
        activeContent.classList.add('active');
    }
}

function viewLogFile(filePath, fileName) {
    currentLogFile = filePath;
    document.getElementById('logViewerTitle').textContent = fileName;
    
    document.querySelectorAll('.log-file-card').forEach(card => {
        card.classList.remove('selected');
    });
    
    const selectedCard = document.querySelector(`[data-file-path="${filePath}"]`);
    if (selectedCard) {
        selectedCard.classList.add('selected');
    }
    
    loadLogContent();
}

function loadLogContent() {
    if (!currentLogFile) return;
    
    const lines = document.getElementById('linesSelector').value;
    const contentDiv = document.getElementById('logContent');
    const statsDiv = document.getElementById('logStats');
    
    contentDiv.innerHTML = '<div class="loading"><i class="fas fa-spinner"></i> Chargement...</div>';
    statsDiv.innerHTML = '';
    
    fetch(`/api/logs/content?file=${encodeURIComponent(currentLogFile)}&lines=${lines}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                contentDiv.innerHTML = `<div style="color: #ff6b6b;">Erreur: ${data.error}</div>`;
                return;
            }
            
            contentDiv.textContent = data.content || 'Fichier vide';
            statsDiv.innerHTML = `Affichage des ${data.displayed_lines} dernières lignes sur ${data.total_lines} au total`;
        })
        .catch(error => {
            contentDiv.innerHTML = `<div style="color: #ff6b6b;">Erreur de chargement: ${error.message}</div>`;
        });
}

function deleteLogFile(filePath, fileName) {
    if (!confirm(`Êtes-vous sûr de vouloir supprimer le fichier "${fileName}" ?`)) {
        return;
    }
    
    fetch('/api/logs/delete', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ file: filePath })
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('Fichier supprimé avec succès', 'success');
                refreshLogs();
                
                if (currentLogFile === filePath) {
                    document.getElementById('logViewerTitle').textContent = 'Aucun fichier sélectionné';
                    document.getElementById('logContent').textContent = 'Sélectionnez un fichier de log pour voir son contenu...';
                    document.getElementById('logStats').innerHTML = '';
                    currentLogFile = null;
                }
            } else {
                showToast(data.error || 'Erreur lors de la suppression', 'error');
            }
        })
        .catch(error => {
            showToast('Erreur de connexion', 'error');
        });
}

function deleteAllLogs() {
    if (!confirm('Êtes-vous sûr de vouloir supprimer TOUS les fichiers de logs ? Cette action est irréversible.')) {
        return;
    }
    
    fetch('/api/logs/delete-all', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast(data.message, 'success');
                refreshLogs();
                
                document.getElementById('logViewerTitle').textContent = 'Aucun fichier sélectionné';
                document.getElementById('logContent').textContent = 'Sélectionnez un fichier de log pour voir son contenu...';
                document.getElementById('logStats').innerHTML = '';
                currentLogFile = null;
            } else {
                showToast(data.error || 'Erreur lors de la suppression', 'error');
            }
        })
        .catch(error => {
            showToast('Erreur de connexion', 'error');
        });
}

function refreshLogs() {
    fetch('/api/logs/refresh')
        .then(response => response.json())
        .then(data => {
            logStructure = data;
            renderTabs();
            
            if (Object.keys(logStructure).length > 0) {
                const firstCategory = Object.keys(logStructure)[0];
                activateTab(firstCategory);
            }
            
            showToast('Liste des logs actualisée', 'success');
        })
        .catch(error => {
            showToast('Erreur lors de l\'actualisation', 'error');
        });
}

document.addEventListener('DOMContentLoaded', function() {
    if (typeof window.initialLogStructure !== 'undefined') {
        initLogsViewer(window.initialLogStructure);
    }
});

