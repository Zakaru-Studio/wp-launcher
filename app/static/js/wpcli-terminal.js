/**
 * Gestion du terminal WP-CLI
 */

let currentWPCLIProject = null;
let wpcliCommandHistory = [];
let wpcliHistoryIndex = -1;

/**
 * Ouvre la modale WP-CLI pour un projet
 */
function openWPCLIModal(projectName) {
    currentWPCLIProject = projectName;
    
    // Mettre à jour le titre
    document.getElementById('wpcli-project-name').textContent = projectName;
    document.getElementById('terminal-project').textContent = projectName;
    
    // Charger l'historique depuis localStorage
    loadWPCLIHistory();
    
    // Afficher la modale
    const modal = new bootstrap.Modal(document.getElementById('wpcliModal'));
    modal.show();
    
    // Focus sur l'input
    setTimeout(() => {
        document.getElementById('wpcli-input').focus();
    }, 500);
}

/**
 * Exécute une commande rapide (depuis les boutons)
 */
function wpcliQuickCommand(command) {
    const input = document.getElementById('wpcli-input');
    input.value = command;
    executeWPCLICommand();
}

/**
 * Exécute la commande dans le terminal
 */
async function executeWPCLICommand() {
    const input = document.getElementById('wpcli-input');
    const command = input.value.trim();
    
    if (!command) return;
    
    // Ajouter à l'historique
    addToWPCLIHistory(command);
    
    // Afficher la commande dans le terminal
    addTerminalLine(`wp ${command}`, 'command');
    
    // Vider l'input
    input.value = '';
    
    // Commandes spéciales locales
    if (command === 'help') {
        showWPCLIHelp();
        return;
    }
    
    if (command === 'clear' || command === 'cls') {
        clearWPCLITerminal();
        return;
    }
    
    // Afficher message de chargement
    const loadingLine = addTerminalLine('Exécution en cours...', 'warning');
    
    try {
        // Appel API
        const response = await fetch(`/wpcli/execute/${currentWPCLIProject}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ command })
        });
        
        const result = await response.json();
        
        // Supprimer le message de chargement
        loadingLine.remove();
        
        if (result.success) {
            // Afficher la sortie
            if (result.output) {
                // Si c'est du JSON formaté, l'afficher joliment
                if (result.parsed_output && Array.isArray(result.parsed_output)) {
                    displayJSONTable(result.parsed_output);
                } else {
                    // Afficher la sortie brute
                    const lines = result.output.split('\n');
                    lines.forEach(line => {
                        if (line.trim()) {
                            addTerminalLine(line, 'success');
                        }
                    });
                }
            } else {
                addTerminalLine('✓ Commande exécutée avec succès', 'success');
            }
        } else {
            // Afficher l'erreur
            addTerminalLine(`✗ Erreur: ${result.error}`, 'error');
            if (result.output) {
                addTerminalLine(result.output, 'error');
            }
        }
        
    } catch (error) {
        loadingLine.remove();
        addTerminalLine(`✗ Erreur réseau: ${error.message}`, 'error');
    }
    
    // Scroll vers le bas
    scrollTerminalToBottom();
}

/**
 * Affiche un tableau JSON formaté
 */
function displayJSONTable(data) {
    if (!data || data.length === 0) {
        addTerminalLine('Aucun résultat', 'warning');
        return;
    }
    
    // Obtenir les colonnes
    const keys = Object.keys(data[0]);
    
    // Header
    const headerLine = keys.join(' | ');
    addTerminalLine(headerLine, 'success');
    addTerminalLine('─'.repeat(headerLine.length), 'text');
    
    // Data rows
    data.forEach(row => {
        const values = keys.map(key => {
            const value = row[key];
            return value !== null && value !== undefined ? String(value) : '';
        });
        addTerminalLine(values.join(' | '), 'text');
    });
}

/**
 * Ajoute une ligne au terminal
 */
function addTerminalLine(text, type = 'text') {
    const output = document.getElementById('wpcli-output');
    const line = document.createElement('div');
    line.className = 'terminal-line';
    
    const textSpan = document.createElement('span');
    textSpan.className = `terminal-${type}`;
    textSpan.textContent = text;
    
    line.appendChild(textSpan);
    output.appendChild(line);
    
    return line;
}

/**
 * Efface le terminal
 */
function clearWPCLITerminal() {
    const output = document.getElementById('wpcli-output');
    output.innerHTML = `
        <div class="terminal-line">
            <span class="terminal-prompt">wp-cli@<span id="terminal-project">${currentWPCLIProject}</span></span>
            <span class="terminal-text">Terminal effacé</span>
        </div>
    `;
}

/**
 * Scroll vers le bas du terminal
 */
function scrollTerminalToBottom() {
    const output = document.getElementById('wpcli-output');
    output.scrollTop = output.scrollHeight;
}

/**
 * Affiche l'aide
 */
function showWPCLIHelp() {
    addTerminalLine('═══════════════════════════════════════════════════════════════', 'success');
    addTerminalLine('                 COMMANDES WP-CLI DISPONIBLES', 'success');
    addTerminalLine('═══════════════════════════════════════════════════════════════', 'success');
    addTerminalLine('', 'text');
    
    addTerminalLine('📦 PLUGINS:', 'success');
    addTerminalLine('  plugin list                           - Liste tous les plugins', 'text');
    addTerminalLine('  plugin install <slug>                 - Installe un plugin', 'text');
    addTerminalLine('  plugin activate <slug>                - Active un plugin', 'text');
    addTerminalLine('  plugin deactivate <slug>              - Désactive un plugin', 'text');
    addTerminalLine('  plugin update <slug>                  - Met à jour un plugin', 'text');
    addTerminalLine('  plugin update --all                   - Met à jour tous les plugins', 'text');
    addTerminalLine('  plugin delete <slug>                  - Supprime un plugin', 'text');
    addTerminalLine('', 'text');
    
    addTerminalLine('🎨 THÈMES:', 'success');
    addTerminalLine('  theme list                            - Liste tous les thèmes', 'text');
    addTerminalLine('  theme install <slug>                  - Installe un thème', 'text');
    addTerminalLine('  theme activate <slug>                 - Active un thème', 'text');
    addTerminalLine('  theme update <slug>                   - Met à jour un thème', 'text');
    addTerminalLine('  theme update --all                    - Met à jour tous les thèmes', 'text');
    addTerminalLine('', 'text');
    
    addTerminalLine('👥 UTILISATEURS:', 'success');
    addTerminalLine('  user list                             - Liste tous les utilisateurs', 'text');
    addTerminalLine('  user create <user> <email> --role=<role> - Crée un utilisateur', 'text');
    addTerminalLine('  user delete <id>                      - Supprime un utilisateur', 'text');
    addTerminalLine('  user update <id> --role=<role>        - Change le rôle', 'text');
    addTerminalLine('  user reset-password <id>              - Réinitialise le mot de passe', 'text');
    addTerminalLine('', 'text');
    
    addTerminalLine('📝 POSTS & PAGES:', 'success');
    addTerminalLine('  post list --post_type=post            - Liste les articles', 'text');
    addTerminalLine('  post list --post_type=page            - Liste les pages', 'text');
    addTerminalLine('  post create --post_title="Titre"      - Crée un article', 'text');
    addTerminalLine('  post delete <id>                      - Supprime un post', 'text');
    addTerminalLine('  post meta list <id>                   - Liste les meta d\'un post', 'text');
    addTerminalLine('', 'text');
    
    addTerminalLine('🗄️ BASE DE DONNÉES:', 'success');
    addTerminalLine('  db export                             - Exporte la base de données', 'text');
    addTerminalLine('  db optimize                           - Optimise la base de données', 'text');
    addTerminalLine('  db repair                             - Répare la base de données', 'text');
    addTerminalLine('  db query "SELECT ..."                 - Exécute une requête SQL', 'text');
    addTerminalLine('  search-replace "old" "new" --dry-run  - Remplace dans la DB (test)', 'text');
    addTerminalLine('  search-replace "old" "new"            - Remplace dans la DB', 'text');
    addTerminalLine('', 'text');
    
    addTerminalLine('⚙️ CORE & CONFIG:', 'success');
    addTerminalLine('  core version                          - Version de WordPress', 'text');
    addTerminalLine('  core update                           - Met à jour WordPress', 'text');
    addTerminalLine('  core verify-checksums                 - Vérifie l\'intégrité des fichiers', 'text');
    addTerminalLine('  config get <constant>                 - Affiche une constante wp-config', 'text');
    addTerminalLine('  option get <option>                   - Affiche une option', 'text');
    addTerminalLine('  option update <option> <value>        - Met à jour une option', 'text');
    addTerminalLine('', 'text');
    
    addTerminalLine('🧹 CACHE & PERFORMANCE:', 'success');
    addTerminalLine('  cache flush                           - Vide le cache objet', 'text');
    addTerminalLine('  rewrite flush                         - Régénère les permaliens', 'text');
    addTerminalLine('  transient delete --all                - Supprime tous les transients', 'text');
    addTerminalLine('  cron event list                       - Liste les tâches cron', 'text');
    addTerminalLine('  cron event run <hook>                 - Exécute une tâche cron', 'text');
    addTerminalLine('', 'text');
    
    addTerminalLine('🔧 MAINTENANCE:', 'success');
    addTerminalLine('  maintenance-mode activate             - Active le mode maintenance', 'text');
    addTerminalLine('  maintenance-mode deactivate           - Désactive le mode maintenance', 'text');
    addTerminalLine('  maintenance-mode status               - Statut du mode maintenance', 'text');
    addTerminalLine('', 'text');
    
    addTerminalLine('🛠️ MÉDIA:', 'success');
    addTerminalLine('  media regenerate                      - Régénère toutes les miniatures', 'text');
    addTerminalLine('  media regenerate <id>                 - Régénère une miniature', 'text');
    addTerminalLine('  media import <file>                   - Importe un média', 'text');
    addTerminalLine('', 'text');
    
    addTerminalLine('───────────────────────────────────────────────────────────────', 'text');
    addTerminalLine('💡 COMMANDES LOCALES:', 'success');
    addTerminalLine('  help   - Affiche cette aide', 'text');
    addTerminalLine('  clear  - Efface le terminal', 'text');
    addTerminalLine('───────────────────────────────────────────────────────────────', 'text');
    addTerminalLine('', 'text');
    addTerminalLine('📖 Tapez une commande et appuyez sur Entrée pour l\'exécuter', 'warning');
    addTerminalLine('⬆️⬇️ Utilisez les flèches haut/bas pour naviguer dans l\'historique', 'warning');
    addTerminalLine('', 'text');
    
    scrollTerminalToBottom();
}

/**
 * Gestion de l'historique des commandes
 */
function addToWPCLIHistory(command) {
    // Éviter les doublons consécutifs
    if (wpcliCommandHistory.length === 0 || wpcliCommandHistory[wpcliCommandHistory.length - 1] !== command) {
        wpcliCommandHistory.push(command);
        
        // Limiter à 50 commandes
        if (wpcliCommandHistory.length > 50) {
            wpcliCommandHistory.shift();
        }
        
        // Sauvegarder dans localStorage
        saveWPCLIHistory();
    }
    
    // Reset index
    wpcliHistoryIndex = wpcliCommandHistory.length;
}

function loadWPCLIHistory() {
    try {
        const saved = localStorage.getItem('wpcli_history');
        if (saved) {
            wpcliCommandHistory = JSON.parse(saved);
            wpcliHistoryIndex = wpcliCommandHistory.length;
        }
    } catch (e) {
        console.error('Erreur chargement historique WP-CLI:', e);
    }
}

function saveWPCLIHistory() {
    try {
        localStorage.setItem('wpcli_history', JSON.stringify(wpcliCommandHistory));
    } catch (e) {
        console.error('Erreur sauvegarde historique WP-CLI:', e);
    }
}

function navigateHistory(direction) {
    if (wpcliCommandHistory.length === 0) return;
    
    if (direction === 'up') {
        if (wpcliHistoryIndex > 0) {
            wpcliHistoryIndex--;
        }
    } else if (direction === 'down') {
        if (wpcliHistoryIndex < wpcliCommandHistory.length - 1) {
            wpcliHistoryIndex++;
        } else {
            wpcliHistoryIndex = wpcliCommandHistory.length;
            document.getElementById('wpcli-input').value = '';
            return;
        }
    }
    
    if (wpcliHistoryIndex >= 0 && wpcliHistoryIndex < wpcliCommandHistory.length) {
        document.getElementById('wpcli-input').value = wpcliCommandHistory[wpcliHistoryIndex];
    }
}

/**
 * Initialisation des événements
 */
document.addEventListener('DOMContentLoaded', function() {
    const input = document.getElementById('wpcli-input');
    
    if (input) {
        // Enter pour exécuter
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                executeWPCLICommand();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                navigateHistory('up');
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                navigateHistory('down');
            }
        });
    }
});

