#!/bin/bash

# Script de monitoring pour suivre l'import de base de données
PROJECT_NAME=$1

if [ -z "$PROJECT_NAME" ]; then
    echo "Usage: $0 <project_name>"
    echo "Exemple: $0 eurasiapeace"
    exit 1
fi

CONTAINER_NAME="${PROJECT_NAME}_mysql_1"

echo "📊 Monitoring de l'import pour le projet: $PROJECT_NAME"
echo "🐳 Conteneur MySQL: $CONTAINER_NAME"
echo "================================================="

# Vérifier que le conteneur existe
if ! docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
    echo "❌ Conteneur $CONTAINER_NAME non trouvé"
    exit 1
fi

echo "✅ Conteneur trouvé, début du monitoring..."
echo ""

# Fonction pour obtenir le nombre de tables
get_table_count() {
    docker exec $CONTAINER_NAME mysql -u wordpress -pwordpress -e "USE wordpress; SHOW TABLES;" 2>/dev/null | wc -l
}

# Fonction pour obtenir la taille de la base de données
get_db_size() {
    docker exec $CONTAINER_NAME mysql -u wordpress -pwordpress -e "SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS 'DB Size (MB)' FROM information_schema.tables WHERE table_schema='wordpress';" 2>/dev/null | tail -1
}

# Fonction pour vérifier les processus MySQL
get_mysql_processes() {
    docker exec $CONTAINER_NAME mysql -u wordpress -pwordpress -e "SHOW PROCESSLIST;" 2>/dev/null | grep -v "Sleep" | wc -l
}

# Monitoring en temps réel
echo "⏱️  Monitoring en temps réel (Ctrl+C pour arrêter)"
echo "Time     | Tables | DB Size(MB) | Processes | Status"
echo "---------|--------|-------------|-----------|--------"

initial_count=$(get_table_count)
start_time=$(date +%s)

while true; do
    current_time=$(date +%H:%M:%S)
    table_count=$(get_table_count)
    db_size=$(get_db_size)
    processes=$(get_mysql_processes)
    
    # Calculer le progrès
    if [ $table_count -gt $initial_count ]; then
        status="📈 Importing..."
    elif [ $processes -gt 1 ]; then
        status="🔄 Processing..."
    else
        status="⏸️  Waiting..."
    fi
    
    printf "%-8s | %-6s | %-11s | %-9s | %s\n" "$current_time" "$table_count" "$db_size" "$processes" "$status"
    
    # Vérifier si l'import est terminé (pas de processus actif depuis 30 secondes)
    if [ $processes -eq 1 ]; then
        sleep_count=$((sleep_count + 1))
        if [ $sleep_count -gt 6 ]; then
            echo ""
            echo "✅ Import semble terminé"
            echo "📊 Résumé final:"
            echo "   - Tables: $table_count"
            echo "   - Taille DB: ${db_size}MB"
            echo "   - Durée: $(($(date +%s) - start_time)) secondes"
            break
        fi
    else
        sleep_count=0
    fi
    
    sleep 5
done

echo ""
echo "🎯 Monitoring terminé" 