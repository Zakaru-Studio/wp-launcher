#!/bin/bash

# Script d'optimisation MySQL pour imports ultra-rapides
if [ -z "$1" ]; then
    echo "Usage: $0 <nom_projet> [action]"
    echo ""
    echo "Actions disponibles:"
    echo "  optimize   - Optimise MySQL pour import rapide (défaut)"
    echo "  restore    - Restaure la configuration normale"
    echo "  status     - Affiche la configuration actuelle"
    echo "  benchmark  - Test de performance MySQL"
    echo ""
    echo "Exemple: $0 eurasiapeace optimize"
    exit 1
fi

PROJECT_NAME="$1"
ACTION="${2:-optimize}"
CONTAINER_NAME="${PROJECT_NAME}_mysql_1"

echo "🔧 Optimisation MySQL pour: $PROJECT_NAME"
echo "=========================================="

# Vérifier que le conteneur existe
if ! docker ps --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
    echo "❌ Conteneur MySQL '$CONTAINER_NAME' non actif"
    exit 1
fi

echo "✅ Conteneur MySQL trouvé: $CONTAINER_NAME"

case "$ACTION" in
    "optimize")
        echo ""
        echo "🚀 OPTIMISATION MYSQL POUR IMPORT RAPIDE"
        echo "========================================="
        
        echo "⚙️ Configuration des buffers et caches..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            -- Buffers et caches
            SET GLOBAL innodb_buffer_pool_size = 2147483648;  -- 2GB
            SET GLOBAL innodb_log_buffer_size = 67108864;     -- 64MB
            SET GLOBAL key_buffer_size = 268435456;           -- 256MB
            SET GLOBAL sort_buffer_size = 16777216;           -- 16MB
            SET GLOBAL read_buffer_size = 2097152;            -- 2MB
            SET GLOBAL read_rnd_buffer_size = 8388608;        -- 8MB
            SET GLOBAL join_buffer_size = 16777216;           -- 16MB
        " 2>/dev/null && echo "  ✅ Buffers configurés"
        
        echo "⚙️ Configuration des packets et timeouts..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            -- Packets et timeouts
            SET GLOBAL max_allowed_packet = 1073741824;      -- 1GB
            SET GLOBAL net_buffer_length = 1048576;          -- 1MB
            SET GLOBAL connect_timeout = 60;
            SET GLOBAL wait_timeout = 28800;                 -- 8 heures
            SET GLOBAL interactive_timeout = 28800;          -- 8 heures
        " 2>/dev/null && echo "  ✅ Packets et timeouts configurés"
        
        echo "⚙️ Optimisations InnoDB..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            -- InnoDB optimisations
            SET GLOBAL innodb_flush_log_at_trx_commit = 0;   -- Pas de flush à chaque transaction
            SET GLOBAL innodb_flush_method = 'O_DIRECT';     -- Éviter double buffering
            SET GLOBAL innodb_log_file_size = 536870912;     -- 512MB
            SET GLOBAL innodb_thread_concurrency = 0;        -- Auto
            SET GLOBAL innodb_read_io_threads = 8;           -- Plus d'I/O threads
            SET GLOBAL innodb_write_io_threads = 8;
        " 2>/dev/null && echo "  ✅ InnoDB optimisé"
        
        echo "⚙️ Désactivation des vérifications coûteuses..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            -- Désactiver vérifications pendant import
            SET GLOBAL foreign_key_checks = 0;
            SET GLOBAL unique_checks = 0;
            SET GLOBAL sql_log_bin = 0;                      -- Pas de binlog
            SET autocommit = 0;                              -- Transactions manuelles
        " 2>/dev/null && echo "  ✅ Vérifications désactivées"
        
        echo "⚙️ Configuration des logs..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            -- Logs
            SET GLOBAL sync_binlog = 0;                      -- Pas de sync binlog
            SET GLOBAL general_log = 0;                      -- Pas de log général
            SET GLOBAL slow_query_log = 0;                   -- Pas de slow query log
        " 2>/dev/null && echo "  ✅ Logs optimisés"
        
        echo ""
        echo "✅ MySQL optimisé pour import ultra-rapide !"
        echo "💡 Utilisez 'restore' pour revenir à la configuration normale après import"
        ;;
        
    "restore")
        echo ""
        echo "🔄 RESTAURATION CONFIGURATION MYSQL NORMALE"
        echo "==========================================="
        
        echo "⚙️ Restauration des vérifications..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SET GLOBAL foreign_key_checks = 1;
            SET GLOBAL unique_checks = 1;
            SET GLOBAL sql_log_bin = 1;
            SET autocommit = 1;
            COMMIT;
        " 2>/dev/null && echo "  ✅ Vérifications restaurées"
        
        echo "⚙️ Restauration des logs..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SET GLOBAL sync_binlog = 1;
            SET GLOBAL general_log = 1;
            SET GLOBAL slow_query_log = 1;
        " 2>/dev/null && echo "  ✅ Logs restaurés"
        
        echo "⚙️ Restauration InnoDB..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SET GLOBAL innodb_flush_log_at_trx_commit = 1;
        " 2>/dev/null && echo "  ✅ InnoDB restauré"
        
        echo ""
        echo "✅ Configuration MySQL restaurée à la normale"
        ;;
        
    "status")
        echo ""
        echo "📊 STATUT CONFIGURATION MYSQL"
        echo "============================="
        
        echo "🔍 Variables critiques pour performance:"
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SELECT 
                'innodb_buffer_pool_size' as Variable_name,
                @@innodb_buffer_pool_size / 1024 / 1024 as 'Value_MB'
            UNION ALL
            SELECT 
                'max_allowed_packet',
                @@max_allowed_packet / 1024 / 1024
            UNION ALL
            SELECT 
                'innodb_flush_log_at_trx_commit',
                @@innodb_flush_log_at_trx_commit
            UNION ALL
            SELECT 
                'foreign_key_checks',
                @@foreign_key_checks
            UNION ALL
            SELECT 
                'unique_checks',
                @@unique_checks
            UNION ALL
            SELECT 
                'autocommit',
                @@autocommit;
        " 2>/dev/null
        
        echo ""
        echo "🔍 Statut des connexions:"
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SHOW STATUS LIKE 'Connections';
            SHOW STATUS LIKE 'Threads_connected';
            SHOW STATUS LIKE 'Uptime';
        " 2>/dev/null
        ;;
        
    "benchmark")
        echo ""
        echo "🧪 BENCHMARK MYSQL"
        echo "=================="
        
        echo "🔧 Création table de test..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress wordpress -e "
            DROP TABLE IF EXISTS benchmark_test;
            CREATE TABLE benchmark_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                data VARCHAR(255),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        " 2>/dev/null
        
        echo "⏱️ Test insertion 10,000 lignes..."
        START_TIME=$(date +%s.%N)
        
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress wordpress -e "
            INSERT INTO benchmark_test (data) VALUES 
            $(for i in {1..10000}; do echo "('Test data $i')"; done | paste -sd,);
        " 2>/dev/null
        
        END_TIME=$(date +%s.%N)
        DURATION=$(echo "$END_TIME - $START_TIME" | bc -l)
        
        echo "⏱️ Test lecture 10,000 lignes..."
        START_TIME2=$(date +%s.%N)
        
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress wordpress -e "
            SELECT COUNT(*) FROM benchmark_test;
        " >/dev/null 2>&1
        
        END_TIME2=$(date +%s.%N)
        DURATION2=$(echo "$END_TIME2 - $START_TIME2" | bc -l)
        
        echo ""
        echo "📊 RÉSULTATS BENCHMARK:"
        echo "   Insertion 10K lignes: ${DURATION}s"
        echo "   Lecture 10K lignes: ${DURATION2}s"
        
        # Calculer la vitesse théorique pour un import
        INSERTS_PER_SEC=$(echo "scale=0; 10000 / $DURATION" | bc -l)
        echo "   Performance: $INSERTS_PER_SEC insertions/sec"
        
        # Estimation pour différentes tailles de BDD
        echo ""
        echo "🔮 ESTIMATIONS IMPORT (basées sur ce benchmark):"
        for size in 1 10 100 500 1000; do
            # Estimation: 100 insertions par MB de dump SQL
            estimated_inserts=$((size * 100))
            estimated_time=$(echo "scale=1; $estimated_inserts / $INSERTS_PER_SEC" | bc -l)
            echo "   ${size} MB: ${estimated_time}s"
        done
        
        # Nettoyage
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress wordpress -e "
            DROP TABLE benchmark_test;
        " 2>/dev/null
        ;;
        
    *)
        echo "❌ Action '$ACTION' non reconnue"
        echo "Actions disponibles: optimize, restore, status, benchmark"
        exit 1
        ;;
esac

echo ""
echo "💡 CONSEILS POUR IMPORT RAPIDE:"
echo "   1. Utilisez 'optimize' avant l'import"
echo "   2. Utilisez ./fast_import_db.sh pour l'import"
echo "   3. Utilisez 'restore' après l'import"
echo "   4. Surveillez l'espace disque pendant l'import" 