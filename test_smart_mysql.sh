#!/bin/bash

# Script de test de la nouvelle logique MySQL intelligente
PROJECT_NAME=${1:-eurasiapeace}
CONTAINER_NAME="${PROJECT_NAME}_mysql_1"

echo "🧪 Test de la logique MySQL intelligente"
echo "========================================"
echo "📊 Projet: $PROJECT_NAME"
echo "🐳 Conteneur: $CONTAINER_NAME"
echo ""

# Test 1: Vérifier l'état du conteneur
echo "🔍 Test 1: État du conteneur"
echo "----------------------------"
if docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
    echo "✅ Conteneur $CONTAINER_NAME trouvé et actif"
    CONTAINER_STATUS="running"
else
    echo "❌ Conteneur $CONTAINER_NAME non trouvé ou arrêté"
    CONTAINER_STATUS="stopped"
fi
echo ""

# Test 2: Test de connexion instantané (comme la nouvelle logique)
echo "🚀 Test 2: Connexion MySQL instantanée"
echo "-------------------------------------"
if [ "$CONTAINER_STATUS" = "running" ]; then
    start_time=$(date +%s.%N)
    
    if timeout 2 docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "SELECT 1" >/dev/null 2>&1; then
        end_time=$(date +%s.%N)
        duration=$(echo "$end_time - $start_time" | bc 2>/dev/null || echo "N/A")
        echo "✅ MySQL prêt instantanément ! (${duration}s)"
        MYSQL_READY="yes"
    else
        echo "❌ MySQL pas encore prêt"
        MYSQL_READY="no"
    fi
else
    echo "❌ Test impossible, conteneur arrêté"
    MYSQL_READY="no"
fi
echo ""

# Test 3: Simulation de la nouvelle logique d'attente progressive
echo "🎯 Test 3: Simulation attente progressive"
echo "----------------------------------------"
if [ "$MYSQL_READY" = "no" ] && [ "$CONTAINER_STATUS" = "running" ]; then
    echo "⏳ Simulation des phases d'attente progressive..."
    
    # Phase 1: Tests rapides (3 × 1s)
    echo "📍 Phase 1: Tests rapides (3 × 1s)"
    for i in {1..3}; do
        start_time=$(date +%s.%N)
        if timeout 3 docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "SELECT 1" >/dev/null 2>&1; then
            end_time=$(date +%s.%N)
            duration=$(echo "$end_time - $start_time" | bc 2>/dev/null || echo "N/A")
            echo "✅ MySQL prêt à la tentative $i ! (${duration}s)"
            MYSQL_READY="yes"
            break
        else
            echo "⏳ Tentative $i/3 échouée, attente 1s..."
            sleep 1
        fi
    done
    
    # Phase 2: Si pas encore prêt, tests normaux (5 × 2s)
    if [ "$MYSQL_READY" = "no" ]; then
        echo "📍 Phase 2: Tests normaux (5 × 2s)"
        for i in {1..5}; do
            start_time=$(date +%s.%N)
            if timeout 3 docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "SELECT 1" >/dev/null 2>&1; then
                end_time=$(date +%s.%N)
                duration=$(echo "$end_time - $start_time" | bc 2>/dev/null || echo "N/A")
                echo "✅ MySQL prêt à la tentative $i ! (${duration}s)"
                MYSQL_READY="yes"
                break
            else
                echo "⏳ Tentative $i/5 échouée, attente 2s..."
                sleep 2
            fi
        done
    fi
    
    # Phase 3: Si toujours pas prêt, tests lents (max 3 × 3s)
    if [ "$MYSQL_READY" = "no" ]; then
        echo "📍 Phase 3: Tests étendus (3 × 3s max)"
        for i in {1..3}; do
            start_time=$(date +%s.%N)
            if timeout 3 docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "SELECT 1" >/dev/null 2>&1; then
                end_time=$(date +%s.%N)
                duration=$(echo "$end_time - $start_time" | bc 2>/dev/null || echo "N/A")
                echo "✅ MySQL prêt à la tentative $i ! (${duration}s)"
                MYSQL_READY="yes"
                break
            else
                echo "⏳ Tentative $i/3 échouée, attente 3s..."
                sleep 3
            fi
        done
    fi
else
    echo "ℹ️  Test non nécessaire (MySQL déjà prêt ou conteneur arrêté)"
fi
echo ""

# Test 4: Performance de connexion
echo "🚀 Test 4: Performance de connexion"
echo "----------------------------------"
if [ "$MYSQL_READY" = "yes" ]; then
    echo "⏱️  Mesure de 5 connexions rapides..."
    total_time=0
    for i in {1..5}; do
        start_time=$(date +%s.%N)
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "SELECT 1" >/dev/null 2>&1
        end_time=$(date +%s.%N)
        duration=$(echo "$end_time - $start_time" | bc 2>/dev/null || echo "0")
        total_time=$(echo "$total_time + $duration" | bc 2>/dev/null || echo "0")
        printf "  Test %d: %.3fs\n" $i $duration
    done
    
    avg_time=$(echo "$total_time / 5" | bc -l 2>/dev/null || echo "N/A")
    printf "📊 Temps moyen: %.3fs\n" $avg_time
    
    if (( $(echo "$avg_time < 0.1" | bc -l 2>/dev/null || echo 0) )); then
        echo "🚀 Performance: EXCELLENTE (< 0.1s)"
    elif (( $(echo "$avg_time < 0.5" | bc -l 2>/dev/null || echo 0) )); then
        echo "👍 Performance: BONNE (< 0.5s)"
    else
        echo "⚠️ Performance: ACCEPTABLE (> 0.5s)"
    fi
else
    echo "❌ Test impossible, MySQL non accessible"
fi
echo ""

# Test 5: Informations système MySQL
echo "📋 Test 5: Informations MySQL"
echo "-----------------------------"
if [ "$MYSQL_READY" = "yes" ]; then
    echo "🔍 Configuration MySQL actuelle:"
    docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
        SELECT 
            @@version as 'Version',
            @@innodb_buffer_pool_size/(1024*1024*1024) as 'Buffer Pool (GB)',
            @@max_connections as 'Max Conn',
            @@innodb_buffer_pool_instances as 'Pool Instances'
    " 2>/dev/null || echo "❌ Impossible de récupérer les infos"
    
    echo ""
    echo "⏱️  Uptime MySQL:"
    docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
        SHOW STATUS LIKE 'Uptime'
    " 2>/dev/null | tail -1 || echo "❌ Uptime non disponible"
else
    echo "❌ Test impossible, MySQL non accessible"
fi
echo ""

# Résumé et recommandations
echo "📊 Résumé du Test"
echo "================="
echo "🐳 Conteneur: $CONTAINER_STATUS"
echo "🗄️  MySQL: $MYSQL_READY"

if [ "$MYSQL_READY" = "yes" ]; then
    echo "✅ Résultat: SUCCÈS"
    echo ""
    echo "💡 Avantages de la nouvelle logique:"
    echo "   - Test instantané si MySQL déjà prêt"
    echo "   - Attente progressive intelligente"
    echo "   - Maximum 60s au lieu de 2+ minutes"
    echo "   - Feedback en temps réel"
    echo ""
    echo "🎯 Prochaine étape:"
    echo "   Testez un import de DB pour voir la différence !"
else
    echo "⚠️ Résultat: MySQL non prêt"
    echo ""
    echo "🔧 Solutions possibles:"
    echo "   1. Redémarrer: docker-compose -f projets/$PROJECT_NAME/docker-compose.yml restart mysql"
    echo "   2. Vérifier logs: docker logs $CONTAINER_NAME"
    echo "   3. Reconstruire: docker-compose -f projets/$PROJECT_NAME/docker-compose.yml up -d --force-recreate mysql"
fi

echo ""
echo "🎉 Test terminé !" 