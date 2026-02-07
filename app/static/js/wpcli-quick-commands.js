/**
 * Exécution rapide de commandes WP-CLI depuis le dropdown
 */

/**
 * Exécute une commande WP-CLI rapide et affiche le résultat
 */
async function executeQuickWPCLI(projectName, command) {
    // Log immédiat pour confirmer que la fonction est appelée
    console.log(`%c[WP-CLI] ▶️ Exécution: "${command}" sur "${projectName}"`, 'color: #4CAF50; font-weight: bold;');
    
    // Afficher une notification toast immédiate pour feedback utilisateur
    showToast(`Exécution: ${command}...`, 'info');
    
    // Déterminer le nom de la tâche selon la commande
    let taskName = `WP-CLI: ${command}`;
    if (command === 'cache flush') {
        taskName = 'Vider le cache';
    } else if (command === 'rewrite flush') {
        taskName = 'Flush Rewrite Rules';
    } else if (command.includes('plugin list')) {
        taskName = 'Lister les Plugins';
    } else if (command.includes('theme list')) {
        taskName = 'Lister les Thèmes';
    } else if (command.includes('user list')) {
        taskName = 'Lister les Utilisateurs';
    }
    
    try {
        // Exécuter la commande
        console.log(`[WP-CLI] 📡 Envoi de la requête POST /wpcli/execute/${projectName}...`);
        const response = await fetch(`/wpcli/execute/${projectName}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ command })
        });
        
        console.log(`[WP-CLI] 📥 Réponse reçue: ${response.status}`);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const result = await response.json();
        console.log(`[WP-CLI] 📋 Résultat:`, result);
        
        if (result.success) {
            // Déterminer le message selon la commande
            let successMessage = '✅ Commande exécutée avec succès';
            if (command === 'cache flush') {
                successMessage = '🧹 Cache vidé avec succès';
            } else if (command === 'rewrite flush') {
                successMessage = '🔄 Règles de réécriture régénérées';
            } else if (command.includes('transient delete')) {
                successMessage = '🗑️ Transients supprimés';
            } else if (command.includes('plugin list')) {
                successMessage = '📦 Liste des plugins récupérée';
            } else if (command.includes('theme list')) {
                successMessage = '🎨 Liste des thèmes récupérée';
            } else if (command.includes('user list')) {
                successMessage = '👥 Liste des utilisateurs récupérée';
            }
            
            // Afficher le résultat dans une modale si c'est une commande de lecture
            if (command.includes('list') || command.includes('version') || command.includes('verify')) {
                showToast(successMessage, 'success');
                
                if (result.parsed_output && Array.isArray(result.parsed_output)) {
                    // Afficher un tableau formaté
                    const tableHtml = formatWPCLITable(result.parsed_output, command);
                    showWPCLIResultModal(command, tableHtml);
                } else if (result.output) {
                    // Afficher le texte brut
                    showWPCLIResultModal(command, `<pre class="text-light">${result.output}</pre>`);
                }
            } else {
                // Pour les commandes d'action (cache, rewrite, etc.), afficher un toast de succès
                showToast(successMessage, 'success');
            }
        } else {
            // Erreur
            const errorMessage = `Erreur: ${result.error || result.message || 'Commande échouée'}`;
            showToast(errorMessage, 'error');
            console.error(`[WP-CLI] ❌ ${errorMessage}`);
        }
        
    } catch (error) {
        console.error('[WP-CLI] ❌ Erreur exécution:', error);
        showToast(`Erreur: ${error.message}`, 'error');
    }
}

/**
 * Formate un tableau JSON en HTML avec un style amélioré
 */
function formatWPCLITable(data, command = '') {
    if (!data || data.length === 0) {
        return '<p class="text-muted text-center p-4">Aucun résultat</p>';
    }
    
    const keys = Object.keys(data[0]);
    
    // Définir les colonnes prioritaires selon le type de commande
    let priorityColumns = [];
    if (command.includes('plugin')) {
        priorityColumns = ['name', 'status', 'version', 'update', 'auto_update'];
    } else if (command.includes('theme')) {
        priorityColumns = ['name', 'status', 'version', 'update'];
    } else if (command.includes('user')) {
        priorityColumns = ['ID', 'user_login', 'display_name', 'user_email', 'roles'];
    }
    
    // Réorganiser les colonnes
    const sortedKeys = [...new Set([...priorityColumns.filter(k => keys.includes(k)), ...keys])];
    
    let html = `
        <div class="wpcli-table-wrapper">
            <div class="wpcli-table-info mb-2">
                <span class="badge bg-info">${data.length} élément${data.length > 1 ? 's' : ''}</span>
            </div>
            <div class="table-responsive wpcli-table-container">
                <table class="table table-hover table-dark wpcli-results-table mb-0">
    `;
    
    // Header
    html += '<thead><tr>';
    sortedKeys.forEach(key => {
        // Capitaliser et formatter le nom de colonne
        const formattedKey = formatColumnName(key);
        html += `<th class="wpcli-th">${formattedKey}</th>`;
    });
    html += '</tr></thead>';
    
    // Body
    html += '<tbody>';
    data.forEach((row, index) => {
        html += '<tr>';
        sortedKeys.forEach(key => {
            let value = row[key] !== null && row[key] !== undefined ? row[key] : '-';
            
            // Formater les valeurs spéciales
            let cellClass = 'wpcli-td';
            let cellContent = value;
            
            if (key === 'status') {
                cellContent = formatStatusBadge(value);
            } else if (key === 'update' && value !== '-') {
                cellContent = value === 'available' ? '<span class="badge bg-warning">Disponible</span>' : 
                              value === 'none' ? '<span class="badge bg-secondary">À jour</span>' : value;
            } else if (key === 'auto_update') {
                cellContent = value === 'on' ? '<i class="fas fa-check text-success"></i>' : 
                              value === 'off' ? '<i class="fas fa-times text-muted"></i>' : value;
            } else if (key === 'roles' && typeof value === 'string') {
                cellContent = value.split(',').map(r => `<span class="badge bg-primary me-1">${r.trim()}</span>`).join('');
            } else if (key === 'user_email') {
                cellContent = `<a href="mailto:${value}" class="text-info">${value}</a>`;
            }
            
            html += `<td class="${cellClass}">${cellContent}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table></div></div>';
    
    return html;
}

/**
 * Formate le nom d'une colonne pour l'affichage
 */
function formatColumnName(key) {
    const nameMap = {
        'name': 'Nom',
        'status': 'Statut',
        'version': 'Version',
        'update': 'MAJ',
        'auto_update': 'MAJ Auto',
        'ID': 'ID',
        'user_login': 'Identifiant',
        'display_name': 'Nom affiché',
        'user_email': 'Email',
        'roles': 'Rôles',
        'user_registered': 'Date inscription',
        'title': 'Titre',
        'description': 'Description'
    };
    
    return nameMap[key] || key.split('_').map(word => 
        word.charAt(0).toUpperCase() + word.slice(1)
    ).join(' ');
}

/**
 * Formate le badge de statut
 */
function formatStatusBadge(status) {
    const statusMap = {
        'active': { class: 'bg-success', label: 'Actif' },
        'inactive': { class: 'bg-secondary', label: 'Inactif' },
        'must-use': { class: 'bg-info', label: 'Must-Use' },
        'dropin': { class: 'bg-warning', label: 'Drop-in' },
        'parent': { class: 'bg-primary', label: 'Parent' },
        'update-available': { class: 'bg-warning', label: 'MAJ dispo' }
    };
    
    const config = statusMap[status] || { class: 'bg-secondary', label: status };
    return `<span class="badge ${config.class}">${config.label}</span>`;
}

/**
 * Affiche une modale avec le résultat d'une commande WP-CLI
 */
function showWPCLIResultModal(command, content) {
    // Créer la modale si elle n'existe pas
    let modal = document.getElementById('wpcliResultModal');
    if (!modal) {
        const modalHtml = `
            <div class="modal fade" id="wpcliResultModal" tabindex="-1">
                <div class="modal-dialog modal-xl modal-dialog-centered">
                    <div class="modal-content bg-dark border-secondary">
                        <div class="modal-header border-secondary">
                            <div>
                                <h5 class="modal-title text-light" id="wpcliResultModalTitle">
                                    <i class="fas fa-terminal me-2"></i>Résultat WP-CLI
                                </h5>
                                <small class="text-muted" id="wpcliResultModalSubtitle"></small>
                            </div>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body p-0" id="wpcliResultModalBody" style="max-height: 70vh; overflow-y: auto; background: #1e1e1e;"></div>
                        <div class="modal-footer border-secondary">
                            <button type="button" class="btn-modern btn-secondary" data-bs-dismiss="modal">
                                <i class="fas fa-times me-1"></i>
                                Fermer
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        modal = document.getElementById('wpcliResultModal');
    }
    
    // Formater le titre selon la commande
    let title = 'Résultat WP-CLI';
    let icon = 'fas fa-terminal';
    if (command.includes('plugin list')) {
        title = 'Liste des Plugins';
        icon = 'fas fa-plug';
    } else if (command.includes('theme list')) {
        title = 'Liste des Thèmes';
        icon = 'fas fa-palette';
    } else if (command.includes('user list')) {
        title = 'Liste des Utilisateurs';
        icon = 'fas fa-users';
    }
    
    // Mettre à jour le contenu
    document.getElementById('wpcliResultModalTitle').innerHTML = `<i class="${icon} me-2"></i>${title}`;
    document.getElementById('wpcliResultModalSubtitle').textContent = `wp ${command}`;
    document.getElementById('wpcliResultModalBody').innerHTML = content;
    
    // Afficher la modale
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}

// Exposer les fonctions globalement
window.executeQuickWPCLI = executeQuickWPCLI;
window.formatWPCLITable = formatWPCLITable;
window.showWPCLIResultModal = showWPCLIResultModal;
