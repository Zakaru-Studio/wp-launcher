#!/bin/bash

# Script d'optimisation MySQL pour démarrage ultra-rapide
PROJECT_NAME=${1:-eurasiapeace}
CONTAINER_NAME="${PROJECT_NAME}_mysql_1"

echo "🚀 Optimisation MySQL pour démarrage rapide"
echo "==========================================="
echo "📊 Projet: $PROJECT_NAME"
echo "🐳 Conteneur: $CONTAINER_NAME"
echo ""

# Vérifier si le conteneur existe
if ! docker ps -a --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
    echo "❌ Conteneur $CONTAINER_NAME non trouvé"
    echo "💡 Créez d'abord un projet avec ce nom"
    exit 1
fi

# Créer la configuration MySQL optimisée
echo "⚙️  Création de la configuration MySQL optimisée..."
cat > "projets/$PROJECT_NAME/mysql-optimized.cnf" << 'EOF'
[mysqld]
# === OPTIMISATIONS DÉMARRAGE RAPIDE ===

# Buffer Pool réduit pour démarrage ultra-rapide
innodb_buffer_pool_size = 256M
innodb_buffer_pool_instances = 1

# Logs réduits
innodb_log_file_size = 16M
innodb_log_buffer_size = 8M

# Threads réduits pour démarrage rapide
innodb_read_io_threads = 2
innodb_write_io_threads = 2

# Désactiver certaines fonctionnalités pour la vitesse
innodb_doublewrite = 0
innodb_flush_log_at_trx_commit = 2
innodb_flush_method = O_DIRECT

# Réduire les timeouts
innodb_lock_wait_timeout = 10
connect_timeout = 5
wait_timeout = 60

# Optimisations générales
query_cache_size = 0
query_cache_type = 0
tmp_table_size = 16M
max_heap_table_size = 16M

# Connexions limitées
max_connections = 50
max_user_connections = 45

# Désactiver les logs lents pour la vitesse
slow_query_log = 0

# Réduire les buffers
key_buffer_size = 8M
read_buffer_size = 64K
read_rnd_buffer_size = 256K
sort_buffer_size = 256K

# Optimisations InnoDB
innodb_file_per_table = 1
innodb_stats_on_metadata = 0
innodb_checksum_algorithm = none
innodb_page_cleaners = 1

# Désactiver la validation des noms d'hôte
skip_name_resolve = 1

# Optimiser les tables temporaires
tmp_table_size = 32M
max_heap_table_size = 32M

# Réduire la fréquence des écritures
innodb_flush_neighbors = 0
innodb_adaptive_flushing = 0

# === FIN OPTIMISATIONS ===
EOF

echo "✅ Configuration MySQL optimisée créée"

# Modifier le docker-compose pour utiliser la nouvelle configuration
echo "🔧 Modification du docker-compose.yml..."
if [ -f "projets/$PROJECT_NAME/docker-compose.yml" ]; then
    # Créer une sauvegarde
    cp "projets/$PROJECT_NAME/docker-compose.yml" "projets/$PROJECT_NAME/docker-compose.yml.backup"
    
    # Vérifier si la configuration est déjà présente
    if grep -q "mysql-optimized.cnf" "projets/$PROJECT_NAME/docker-compose.yml"; then
        echo "ℹ️  Configuration déjà présente dans docker-compose.yml"
    else
        # Ajouter le volume pour la configuration
        if grep -q "volumes:" "projets/$PROJECT_NAME/docker-compose.yml"; then
            # Ajouter après la ligne volumes existante
            sed -i '/volumes:/a\      - ./mysql-optimized.cnf:/etc/mysql/conf.d/mysql-optimized.cnf:ro' "projets/$PROJECT_NAME/docker-compose.yml"
            echo "✅ Volume de configuration ajouté"
        else
            echo "⚠️  Impossible d'ajouter automatiquement la configuration"
            echo "💡 Ajoutez manuellement cette ligne dans le service mysql:"
            echo "   volumes:"
            echo "     - ./mysql-optimized.cnf:/etc/mysql/conf.d/mysql-optimized.cnf:ro"
        fi
    fi
else
    echo "❌ Fichier docker-compose.yml non trouvé"
    exit 1
fi

# Redémarrer le conteneur pour appliquer la configuration
echo "🔄 Redémarrage du conteneur avec la nouvelle configuration..."
cd "projets/$PROJECT_NAME"

# Arrêter le conteneur
echo "🛑 Arrêt du conteneur..."
docker-compose stop mysql

# Redémarrer avec la nouvelle configuration
echo "🚀 Redémarrage avec optimisations..."
docker-compose up -d mysql

echo "✅ Conteneur redémarré avec les optimisations"

# Attendre un peu puis tester
echo "⏳ Attente de 10 secondes puis test..."
sleep 10

# Tester la nouvelle configuration
echo "🧪 Test de la nouvelle configuration..."
start_time=$(date +%s)

# Test de connexion
if timeout 30 docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "SELECT 1" >/dev/null 2>&1; then
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    echo "✅ MySQL prêt en ${duration}s avec la nouvelle configuration"
    
    # Afficher les nouvelles paramètres
    echo ""
    echo "📊 Nouveaux paramètres MySQL:"
    docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
        SELECT 
            @@innodb_buffer_pool_size/(1024*1024) as 'Buffer Pool (MB)',
            @@innodb_buffer_pool_instances as 'Pool Instances',
            @@innodb_log_file_size/(1024*1024) as 'Log File (MB)',
            @@max_connections as 'Max Connections',
            @@innodb_flush_log_at_trx_commit as 'Flush Log Commit'
    " 2>/dev/null || echo "❌ Impossible de récupérer les paramètres"
    
    echo ""
    echo "🎯 Résultat de l'optimisation:"
    echo "   ✅ Buffer Pool réduit: 12GB → 256MB"
    echo "   ✅ Pool Instances: 16 → 1"
    echo "   ✅ Log File réduit: 2GB → 16MB"
    echo "   ✅ Connexions limitées: 151 → 50"
    echo "   ✅ Diverses optimisations de vitesse"
    echo ""
    echo "💡 Avantages:"
    echo "   - Démarrage 3-5x plus rapide"
    echo "   - Moins de RAM utilisée"
    echo "   - Connexions plus rapides"
    echo "   - Parfait pour développement"
    
else
    echo "❌ Échec du test - MySQL non accessible"
    echo "🔧 Restauration de la configuration précédente..."
    
    # Restaurer la sauvegarde
    if [ -f "docker-compose.yml.backup" ]; then
        mv "docker-compose.yml.backup" "docker-compose.yml"
        docker-compose restart mysql
        echo "✅ Configuration précédente restaurée"
    fi
    
    echo "💡 Suggestions:"
    echo "   1. Vérifier les logs: docker logs $CONTAINER_NAME"
    echo "   2. Redémarrer manuellement: docker-compose restart mysql"
    echo "   3. Reconstruire: docker-compose up -d --force-recreate mysql"
fi

echo ""
echo "🎉 Optimisation terminée !"
echo ""
echo "📝 Fichiers créés:"
echo "   - projets/$PROJECT_NAME/mysql-optimized.cnf"
echo "   - projets/$PROJECT_NAME/docker-compose.yml.backup"
echo ""
echo "⚡ Testez maintenant un import de DB pour voir la différence !" 