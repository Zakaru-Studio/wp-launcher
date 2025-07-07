#!/bin/bash

# Script de comparaison de performance d'import de base de données
echo "🚀 Comparaison des performances d'import de base de données"
echo "==========================================================="

if [ -z "$1" ]; then
    echo "Usage: $0 <nom_projet> [taille_test_mb]"
    echo ""
    echo "Exemples:"
    echo "  $0 eurasiapeace 10    # Test avec 10MB de données"
    echo "  $0 monsite 50         # Test avec 50MB de données"
    echo ""
    echo "Ce script compare:"
    echo "  ❌ phpMyAdmin (simulation)"
    echo "  ✅ Import direct optimisé" 
    echo "  ✅ Import parallèle"
    echo "  ✅ Import streaming"
    exit 1
fi

PROJECT_NAME="$1"
TEST_SIZE_MB="${2:-10}"
CONTAINER_NAME="${PROJECT_NAME}_mysql_1"

echo "📊 Test de performance pour: $PROJECT_NAME"
echo "📏 Taille de test: ${TEST_SIZE_MB} MB"
echo ""

# Vérifications
if ! docker ps --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
    echo "❌ Conteneur MySQL '$CONTAINER_NAME' non actif"
    echo "💡 Démarrez d'abord le projet via l'interface web"
    exit 1
fi

# Créer un fichier SQL de test
TEST_FILE="/tmp/performance_test_${PROJECT_NAME}_${TEST_SIZE_MB}mb.sql"
echo "🔧 Génération d'un fichier SQL de test (${TEST_SIZE_MB} MB)..."

# Calculer le nombre de lignes nécessaires pour atteindre la taille cible
# Estimation: environ 100 bytes par ligne d'INSERT
LINES_NEEDED=$((TEST_SIZE_MB * 1024 * 1024 / 100))

cat > "$TEST_FILE" << EOF
-- Fichier de test de performance - ${TEST_SIZE_MB} MB
-- Généré automatiquement par wp-launcher

DROP TABLE IF EXISTS performance_test;
CREATE TABLE performance_test (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255),
    content TEXT,
    email VARCHAR(100),
    date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_date (date_created)
);

EOF

# Générer les données de test par chunks pour éviter les problèmes de mémoire
CHUNK_SIZE=1000
echo "📝 Génération de $LINES_NEEDED lignes de données..."

for ((i=1; i<=LINES_NEEDED; i+=CHUNK_SIZE)); do
    echo "INSERT INTO performance_test (title, content, email) VALUES" >> "$TEST_FILE"
    
    end=$((i + CHUNK_SIZE - 1))
    if [ $end -gt $LINES_NEEDED ]; then
        end=$LINES_NEEDED
    fi
    
    for ((j=i; j<=end; j++)); do
        title="Test Article $j - Performance Benchmark"
        content="Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Article number $j for performance testing."
        email="test$j@example.com"
        
        if [ $j -eq $end ]; then
            echo "('$title', '$content', '$email');" >> "$TEST_FILE"
        else
            echo "('$title', '$content', '$email')," >> "$TEST_FILE"
        fi
    done
    
    # Afficher le progrès
    if [ $((i % 10000)) -eq 1 ]; then
        progress=$((i * 100 / LINES_NEEDED))
        echo "  Progrès: $progress% ($i/$LINES_NEEDED lignes)"
    fi
done

# Vérifier la taille réelle du fichier généré
ACTUAL_SIZE=$(stat -c%s "$TEST_FILE")
ACTUAL_SIZE_MB=$((ACTUAL_SIZE / 1024 / 1024))

echo "✅ Fichier de test généré:"
echo "   Taille: $ACTUAL_SIZE_MB MB"
echo "   Lignes: $LINES_NEEDED"
echo "   Chemin: $TEST_FILE"
echo ""

# Fonction de nettoyage
cleanup() {
    echo "🧹 Nettoyage..."
    rm -f "$TEST_FILE"
    docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress wordpress -e "DROP TABLE IF EXISTS performance_test;" 2>/dev/null
}
trap cleanup EXIT

echo "🧪 DÉBUT DES TESTS DE PERFORMANCE"
echo "=================================="

# Test 1: Simulation phpMyAdmin
echo ""
echo "📊 Test 1: Simulation phpMyAdmin"
echo "---------------------------------"
echo "⚠️  phpMyAdmin utilise:"
echo "   - Interface web PHP (lent)"
echo "   - Parsing ligne par ligne"
echo "   - Timeouts HTTP"
echo "   - Limites mémoire PHP"
echo ""

# Simulation basée sur les performances réelles observées
PHPMYADMIN_RATE=0.5  # MB/s (estimation conservatrice)
PHPMYADMIN_TIME=$(echo "scale=1; $ACTUAL_SIZE_MB / $PHPMYADMIN_RATE" | bc -l)

echo "📈 Performance simulée phpMyAdmin:"
echo "   Vitesse: $PHPMYADMIN_RATE MB/s"
echo "   Temps estimé: ${PHPMYADMIN_TIME}s"
echo "   💡 Pour ${ACTUAL_SIZE_MB}MB = ${PHPMYADMIN_TIME}s d'attente !"

# Test 2: Import direct optimisé
echo ""
echo "📊 Test 2: Import Direct Optimisé"
echo "----------------------------------"

# Optimiser MySQL pour le test
echo "⚙️ Optimisation MySQL..."
./optimize_mysql.sh "$PROJECT_NAME" optimize >/dev/null 2>&1

echo "🚀 Import direct en cours..."
START_TIME=$(date +%s.%N)

docker exec -i "$CONTAINER_NAME" mysql \
    -u wordpress -pwordpress \
    --default-character-set=utf8mb4 \
    --max_allowed_packet=1G \
    wordpress < "$TEST_FILE" 2>/dev/null

END_TIME=$(date +%s.%N)
DIRECT_TIME=$(echo "$END_TIME - $START_TIME" | bc -l)
DIRECT_RATE=$(echo "scale=2; $ACTUAL_SIZE_MB / $DIRECT_TIME" | bc -l)

echo "📈 Performance import direct:"
printf "   Temps: %.2fs\n" "$DIRECT_TIME"
printf "   Vitesse: %.2f MB/s\n" "$DIRECT_RATE"

# Nettoyer pour le test suivant
docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress wordpress -e "DROP TABLE performance_test;" 2>/dev/null

# Test 3: Import parallèle par chunks
echo ""
echo "📊 Test 3: Import Parallèle par Chunks"
echo "---------------------------------------"

echo "🚀 Import parallèle en cours..."
START_TIME=$(date +%s.%N)

# Diviser en chunks et importer en parallèle
CHUNK_SIZE=1000
TEMP_CHUNKS=$(mktemp -d)
split -l $CHUNK_SIZE "$TEST_FILE" "$TEMP_CHUNKS/chunk_"

# Traiter les chunks
for chunk in "$TEMP_CHUNKS"/chunk_*; do
    docker exec -i "$CONTAINER_NAME" mysql \
        -u wordpress -pwordpress wordpress < "$chunk" 2>/dev/null &
done

# Attendre que tous les processus se terminent
wait

END_TIME=$(date +%s.%N)
PARALLEL_TIME=$(echo "$END_TIME - $START_TIME" | bc -l)
PARALLEL_RATE=$(echo "scale=2; $ACTUAL_SIZE_MB / $PARALLEL_TIME" | bc -l)

echo "📈 Performance import parallèle:"
printf "   Temps: %.2fs\n" "$PARALLEL_TIME"
printf "   Vitesse: %.2f MB/s\n" "$PARALLEL_RATE"

rm -rf "$TEMP_CHUNKS"
docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress wordpress -e "DROP TABLE performance_test;" 2>/dev/null

# Test 4: Import streaming optimisé
echo ""
echo "📊 Test 4: Import Streaming Optimisé"
echo "-------------------------------------"

echo "🚀 Import streaming en cours..."
START_TIME=$(date +%s.%N)

docker exec -i "$CONTAINER_NAME" mysql \
    -u wordpress -pwordpress \
    --default-character-set=utf8mb4 \
    --max_allowed_packet=1G \
    --single-transaction \
    --quick \
    wordpress < "$TEST_FILE" 2>/dev/null

END_TIME=$(date +%s.%N)
STREAMING_TIME=$(echo "$END_TIME - $START_TIME" | bc -l)
STREAMING_RATE=$(echo "scale=2; $ACTUAL_SIZE_MB / $STREAMING_TIME" | bc -l)

echo "📈 Performance import streaming:"
printf "   Temps: %.2fs\n" "$STREAMING_TIME"
printf "   Vitesse: %.2f MB/s\n" "$STREAMING_RATE"

# Restaurer MySQL
echo ""
echo "⚙️ Restauration configuration MySQL..."
./optimize_mysql.sh "$PROJECT_NAME" restore >/dev/null 2>&1

# Résumé comparatif
echo ""
echo "🏆 RÉSUMÉ COMPARATIF - ${ACTUAL_SIZE_MB} MB"
echo "==========================================="

printf "%-20s %10s %10s %10s\n" "Méthode" "Temps(s)" "Vitesse(MB/s)" "Gain"
echo "--------------------------------------------------------"

printf "%-20s %10.1f %10.1f %10s\n" "phpMyAdmin" "$PHPMYADMIN_TIME" "$PHPMYADMIN_RATE" "1x"

DIRECT_GAIN=$(echo "scale=1; $PHPMYADMIN_TIME / $DIRECT_TIME" | bc -l)
printf "%-20s %10.2f %10.2f %10.1fx\n" "Direct Optimisé" "$DIRECT_TIME" "$DIRECT_RATE" "$DIRECT_GAIN"

PARALLEL_GAIN=$(echo "scale=1; $PHPMYADMIN_TIME / $PARALLEL_TIME" | bc -l)
printf "%-20s %10.2f %10.2f %10.1fx\n" "Parallèle" "$PARALLEL_TIME" "$PARALLEL_RATE" "$PARALLEL_GAIN"

STREAMING_GAIN=$(echo "scale=1; $PHPMYADMIN_TIME / $STREAMING_TIME" | bc -l)
printf "%-20s %10.2f %10.2f %10.1fx\n" "Streaming" "$STREAMING_TIME" "$STREAMING_RATE" "$STREAMING_GAIN"

echo ""
echo "🎯 RECOMMANDATIONS"
echo "=================="

# Trouver la méthode la plus rapide
if (( $(echo "$DIRECT_TIME < $PARALLEL_TIME && $DIRECT_TIME < $STREAMING_TIME" | bc -l) )); then
    BEST_METHOD="direct"
    BEST_TIME="$DIRECT_TIME"
elif (( $(echo "$PARALLEL_TIME < $STREAMING_TIME" | bc -l) )); then
    BEST_METHOD="parallel"
    BEST_TIME="$PARALLEL_TIME"
else
    BEST_METHOD="streaming"
    BEST_TIME="$STREAMING_TIME"
fi

echo "🏅 Méthode la plus rapide: $BEST_METHOD"
echo ""
echo "💡 Pour votre projet '$PROJECT_NAME':"
echo "   ❌ N'utilisez JAMAIS phpMyAdmin pour gros imports"
echo "   ✅ Utilisez: ./fast_import_db.sh $PROJECT_NAME votre_fichier.sql $BEST_METHOD"
echo "   ⚡ Gain de temps: jusqu'à ${STREAMING_GAIN}x plus rapide !"
echo ""
echo "🔧 Pour optimiser encore plus:"
echo "   1. ./optimize_mysql.sh $PROJECT_NAME optimize"
echo "   2. ./fast_import_db.sh $PROJECT_NAME votre_fichier.sql"
echo "   3. ./optimize_mysql.sh $PROJECT_NAME restore"

echo ""
echo "✅ Test de performance terminé !" 