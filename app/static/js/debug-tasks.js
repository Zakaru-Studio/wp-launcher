/**
 * Debug Tasks - Outils de débogage pour les tâches
 * Ce fichier peut être supprimé en production
 */

// Debug: afficher les événements Socket.IO dans la console
if (typeof window !== 'undefined') {
    window.debugSocketIO = false;
    
    // Activer/désactiver le debug Socket.IO
    window.enableSocketDebug = function(enable = true) {
        window.debugSocketIO = enable;
        console.log(`🔧 Debug Socket.IO: ${enable ? 'activé' : 'désactivé'}`);
    };
    
    // Afficher l'état actuel des tâches
    window.debugTasks = function() {
        if (typeof taskManager !== 'undefined' && taskManager && taskManager.tasks) {
            console.log('📋 Tâches en cours:');
            taskManager.tasks.forEach((task, id) => {
                console.log(`  - ${id}: ${task.title} (${task.status}) - ${task.progress}%`);
            });
        } else {
            console.log('❌ TaskManager non disponible');
        }
    };
    
    // Tester l'ouverture de la modale d'import
    window.testImportModal = function() {
        if (typeof showImportLogsModal === 'function') {
            console.log('🧪 Test d\'ouverture de la modale d\'import...');
            showImportLogsModal();
        } else {
            console.log('❌ Fonction showImportLogsModal non disponible');
        }
    };
    
    // Afficher l'état du buffer de logs d'import
    window.debugImportLogs = function() {
        if (typeof importLogsBuffer !== 'undefined') {
            console.log(`📝 Buffer de logs d'import: ${importLogsBuffer.length} entrées`);
            importLogsBuffer.forEach((log, i) => {
                console.log(`  ${i}: [${log.timestamp}] ${log.message}`);
            });
        } else {
            console.log('❌ importLogsBuffer non disponible');
        }
    };
    
    console.log('🔧 Debug Tasks chargé. Commandes disponibles:');
    console.log('  - enableSocketDebug(true/false)');
    console.log('  - debugTasks()');
    console.log('  - testImportModal()');
    console.log('  - debugImportLogs()');
}


