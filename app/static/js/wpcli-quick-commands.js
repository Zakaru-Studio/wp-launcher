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
                    // Afficher un tableau formaté (retourne un Node construit côté client avec textContent)
                    const tableNode = formatWPCLITable(result.parsed_output, command);
                    showWPCLIResultModal(command, tableNode);
                } else if (result.output) {
                    // Afficher le texte brut en toute sûreté (textContent empêche toute injection HTML)
                    const pre = document.createElement('pre');
                    pre.className = 'text-light';
                    pre.textContent = result.output;
                    showWPCLIResultModal(command, pre);
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
 * Formate un tableau JSON en Node DOM (sans innerHTML) avec un style amélioré.
 * Toutes les valeurs provenant du serveur sont insérées via textContent afin
 * d'empêcher toute injection HTML/XSS.
 */
function formatWPCLITable(data, command = '') {
    if (!data || data.length === 0) {
        const p = document.createElement('p');
        p.className = 'text-muted text-center p-4';
        p.textContent = 'Aucun résultat';
        return p;
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

    // Wrapper
    const wrapper = document.createElement('div');
    wrapper.className = 'wpcli-table-wrapper';

    const infoDiv = document.createElement('div');
    infoDiv.className = 'wpcli-table-info mb-2';
    const countBadge = document.createElement('span');
    countBadge.className = 'badge bg-info';
    countBadge.textContent = `${data.length} élément${data.length > 1 ? 's' : ''}`;
    infoDiv.appendChild(countBadge);
    wrapper.appendChild(infoDiv);

    const tableContainer = document.createElement('div');
    tableContainer.className = 'table-responsive wpcli-table-container';
    const table = document.createElement('table');
    table.className = 'table table-hover table-dark wpcli-results-table mb-0';

    // Header
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    sortedKeys.forEach(key => {
        const th = document.createElement('th');
        th.className = 'wpcli-th';
        th.textContent = formatColumnName(key);
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Body
    const tbody = document.createElement('tbody');
    data.forEach(row => {
        const tr = document.createElement('tr');
        sortedKeys.forEach(key => {
            const td = document.createElement('td');
            td.className = 'wpcli-td';
            const rawValue = row[key] !== null && row[key] !== undefined ? row[key] : '-';

            if (key === 'status') {
                td.appendChild(formatStatusBadge(rawValue));
            } else if (key === 'update' && rawValue !== '-') {
                if (rawValue === 'available') {
                    const b = document.createElement('span');
                    b.className = 'badge bg-warning';
                    b.textContent = 'Disponible';
                    td.appendChild(b);
                } else if (rawValue === 'none') {
                    const b = document.createElement('span');
                    b.className = 'badge bg-secondary';
                    b.textContent = 'À jour';
                    td.appendChild(b);
                } else {
                    td.textContent = String(rawValue);
                }
            } else if (key === 'auto_update') {
                if (rawValue === 'on') {
                    const i = document.createElement('i');
                    i.className = 'fas fa-check text-success';
                    td.appendChild(i);
                } else if (rawValue === 'off') {
                    const i = document.createElement('i');
                    i.className = 'fas fa-times text-muted';
                    td.appendChild(i);
                } else {
                    td.textContent = String(rawValue);
                }
            } else if (key === 'roles' && typeof rawValue === 'string') {
                rawValue.split(',').forEach(r => {
                    const badge = document.createElement('span');
                    badge.className = 'badge bg-primary me-1';
                    badge.textContent = r.trim();
                    td.appendChild(badge);
                });
            } else if (key === 'user_email') {
                const a = document.createElement('a');
                a.className = 'text-info';
                a.href = 'mailto:' + String(rawValue);
                a.textContent = String(rawValue);
                td.appendChild(a);
            } else {
                td.textContent = String(rawValue);
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    tableContainer.appendChild(table);
    wrapper.appendChild(tableContainer);
    return wrapper;
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
 * Formate le badge de statut (retourne un élément DOM, pas une string HTML)
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

    const config = statusMap[status] || { class: 'bg-secondary', label: String(status) };
    const span = document.createElement('span');
    span.className = 'badge ' + config.class;
    span.textContent = config.label;
    return span;
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
    
    // Mettre à jour le contenu — title/icon sont choisis parmi des constantes ci-dessus
    const titleEl = document.getElementById('wpcliResultModalTitle');
    titleEl.replaceChildren();
    const iconEl = document.createElement('i');
    iconEl.className = icon + ' me-2';
    titleEl.appendChild(iconEl);
    titleEl.appendChild(document.createTextNode(title));
    document.getElementById('wpcliResultModalSubtitle').textContent = `wp ${command}`;

    // content peut être un Node (construit côté client sans innerHTML) ou, par
    // rétro-compatibilité, une string. On préfère toujours les Nodes.
    const body = document.getElementById('wpcliResultModalBody');
    body.replaceChildren();
    if (content instanceof Node) {
        body.appendChild(content);
    } else if (typeof content === 'string') {
        // Fallback safe: on affiche la string brute comme texte pour éviter l'injection
        const pre = document.createElement('pre');
        pre.className = 'text-light';
        pre.textContent = content;
        body.appendChild(pre);
    }
    
    // Afficher la modale
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}

// Exposer les fonctions globalement
window.executeQuickWPCLI = executeQuickWPCLI;
window.formatWPCLITable = formatWPCLITable;
window.showWPCLIResultModal = showWPCLIResultModal;
