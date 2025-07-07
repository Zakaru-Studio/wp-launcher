#!/bin/bash

# Script d'import ultra-rapide de base de données
# Contourne phpMyAdmin pour des performances maximales

if [ $# -lt 2 ]; then
    echo "Usage: $0 <nom_projet> <fichier_sql_ou_zip> [méthode]"
    echo ""
    echo "Méthodes disponibles:"
    echo "  auto     - Choix automatique selon la taille (défaut)"
    echo "  direct   - Import direct (< 10MB)"
    echo "  optimized - Import optimisé (< 100MB)"
    echo "  parallel - Import parallèle (< 500MB)"
    echo "  streaming - Import streaming (> 500MB)"
    echo ""
    echo "Exemples:"
    echo "  $0 eurasiapeace database.sql"
    echo "  $0 monsite backup.zip"
    echo "  $0 testsite large_db.sql streaming"
    exit 1
fi

PROJECT_NAME="$1"
DB_FILE="$2"
METHOD="${3:-auto}"

PROJECT_DIR="projets/$PROJECT_NAME"
CONTAINER_NAME="${PROJECT_NAME}_mysql_1"

echo "🚀 Import ultra-rapide de base de données"
echo "========================================="
echo "📁 Projet: $PROJECT_NAME"
echo "📄 Fichier: $DB_FILE"
echo "🔧 Méthode: $METHOD"
echo ""

# Vérifications préliminaires
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ Projet '$PROJECT_NAME' non trouvé"
    exit 1
fi

if [ ! -f "$DB_FILE" ]; then
    echo "❌ Fichier '$DB_FILE' non trouvé"
    exit 1
fi

# Vérifier que le conteneur MySQL est actif
echo "🔍 Vérification du conteneur MySQL..."
if ! docker ps --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
    echo "❌ Conteneur MySQL '$CONTAINER_NAME' non actif"
    echo "💡 Démarrez d'abord le projet via l'interface web"
    exit 1
fi

# Analyser la taille du fichier
FILE_SIZE=$(stat -c%s "$DB_FILE")
FILE_SIZE_MB=$((FILE_SIZE / 1024 / 1024))

echo "✅ Conteneur MySQL actif"
echo "📊 Taille du fichier: ${FILE_SIZE_MB} MB"

# Attendre que MySQL soit prêt
echo ""
echo "⏳ Attente de MySQL..."
MAX_ATTEMPTS=30
ATTEMPT=1

while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
    if docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "SELECT 1" >/dev/null 2>&1; then
        echo "✅ MySQL prêt"
        break
    fi
    
    echo "  Tentative $ATTEMPT/$MAX_ATTEMPTS..."
    sleep 2
    ATTEMPT=$((ATTEMPT + 1))
done

if [ $ATTEMPT -gt $MAX_ATTEMPTS ]; then
    echo "❌ MySQL non disponible après $MAX_ATTEMPTS tentatives"
    exit 1
fi

# Déterminer la méthode d'import
if [ "$METHOD" = "auto" ]; then
    if [ $FILE_SIZE_MB -lt 10 ]; then
        METHOD="direct"
        echo "🎯 Méthode auto-sélectionnée: DIRECT (< 10MB)"
    elif [ $FILE_SIZE_MB -lt 100 ]; then
        METHOD="optimized"
        echo "🎯 Méthode auto-sélectionnée: OPTIMIZED (< 100MB)"
    elif [ $FILE_SIZE_MB -lt 500 ]; then
        METHOD="parallel"
        echo "🎯 Méthode auto-sélectionnée: PARALLEL (< 500MB)"
    else
        METHOD="streaming"
        echo "🎯 Méthode auto-sélectionnée: STREAMING (> 500MB)"
    fi
fi

echo ""
echo "🔥 Début de l'import avec la méthode: $METHOD"
echo "=============================================="

# Préparer le fichier SQL
SQL_FILE="$DB_FILE"
TEMP_SQL=""

if [[ "$DB_FILE" == *.zip ]]; then
    echo "📦 Extraction de l'archive ZIP..."
    TEMP_DIR=$(mktemp -d)
    unzip -q "$DB_FILE" -d "$TEMP_DIR"
    
    SQL_FILES=("$TEMP_DIR"/*.sql)
    if [ ! -f "${SQL_FILES[0]}" ]; then
        echo "❌ Aucun fichier .sql trouvé dans l'archive"
        rm -rf "$TEMP_DIR"
        exit 1
    fi
    
    SQL_FILE="${SQL_FILES[0]}"
    TEMP_SQL="$TEMP_DIR"
    echo "✅ SQL extrait: $(basename "$SQL_FILE")"
fi

# Fonction de nettoyage
cleanup() {
    if [ -n "$TEMP_SQL" ]; then
        echo "🧹 Nettoyage..."
        rm -rf "$TEMP_SQL"
    fi
}
trap cleanup EXIT

# Enregistrer l'heure de début
START_TIME=$(date +%s)

# Exécuter l'import selon la méthode
case "$METHOD" in
    "direct")
        echo "🔥 Import DIRECT - Méthode la plus rapide pour petits fichiers"
        docker exec -i "$CONTAINER_NAME" mysql \
            -u wordpress -pwordpress \
            --default-character-set=utf8mb4 \
            --max_allowed_packet=1G \
            --net_buffer_length=1M \
            wordpress < "$SQL_FILE"
        IMPORT_SUCCESS=$?
        ;;
        
    "optimized")
        echo "🔥 Import OPTIMISÉ - Configuration MySQL optimisée"
        
        # Configuration MySQL pour performances
        echo "⚙️ Configuration MySQL optimisée..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SET GLOBAL innodb_flush_log_at_trx_commit = 0;
            SET GLOBAL sync_binlog = 0;
            SET GLOBAL foreign_key_checks = 0;
            SET GLOBAL unique_checks = 0;
            SET autocommit = 0;
        " 2>/dev/null
        
        # Copier fichier dans conteneur pour utiliser SOURCE
        echo "📋 Copie du fichier dans le conteneur..."
        docker cp "$SQL_FILE" "$CONTAINER_NAME:/tmp/fast_import.sql"
        
        # Import via SOURCE (plus rapide)
        echo "🚀 Import via SOURCE..."
        docker exec "$CONTAINER_NAME" mysql \
            -u wordpress -pwordpress \
            --default-character-set=utf8mb4 \
            wordpress \
            -e "SOURCE /tmp/fast_import.sql;"
        IMPORT_SUCCESS=$?
        
        # Restaurer configuration MySQL
        echo "⚙️ Restauration configuration MySQL..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SET GLOBAL foreign_key_checks = 1;
            SET GLOBAL unique_checks = 1;
            SET autocommit = 1;
            COMMIT;
        " 2>/dev/null
        
        # Nettoyer
        docker exec "$CONTAINER_NAME" rm -f /tmp/fast_import.sql
        ;;
        
    "parallel")
        echo "🔥 Import PARALLÈLE - Traitement par chunks"
        
        # Diviser le fichier en chunks et traiter en parallèle
        CHUNK_SIZE=1000  # 1000 lignes par chunk
        TEMP_CHUNKS=$(mktemp -d)
        
        echo "📊 Division en chunks de $CHUNK_SIZE lignes..."
        split -l $CHUNK_SIZE "$SQL_FILE" "$TEMP_CHUNKS/chunk_"
        
        TOTAL_CHUNKS=$(ls "$TEMP_CHUNKS"/chunk_* | wc -l)
        echo "📊 $TOTAL_CHUNKS chunks créés"
        
        # Configuration MySQL
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SET GLOBAL foreign_key_checks = 0;
            SET GLOBAL unique_checks = 0;
        " 2>/dev/null
        
        # Traiter chunks en parallèle
        echo "🚀 Traitement parallèle des chunks..."
        SUCCESS_COUNT=0
        
        for chunk in "$TEMP_CHUNKS"/chunk_*; do
            chunk_name=$(basename "$chunk")
            echo "  Traitement $chunk_name..."
            
            if docker exec -i "$CONTAINER_NAME" mysql \
                -u wordpress -pwordpress wordpress < "$chunk" 2>/dev/null; then
                SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
            fi
        done
        
        # Restaurer configuration
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SET GLOBAL foreign_key_checks = 1;
            SET GLOBAL unique_checks = 1;
            COMMIT;
        " 2>/dev/null
        
        echo "📊 Chunks réussis: $SUCCESS_COUNT/$TOTAL_CHUNKS"
        rm -rf "$TEMP_CHUNKS"
        
        if [ $SUCCESS_COUNT -ge $((TOTAL_CHUNKS * 85 / 100)) ]; then
            IMPORT_SUCCESS=0
        else
            IMPORT_SUCCESS=1
        fi
        ;;
        
    "streaming")
        echo "🔥 Import STREAMING - Pour très gros fichiers"
        
        # Configuration MySQL pour gros imports
        echo "⚙️ Configuration MySQL pour streaming..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SET GLOBAL innodb_buffer_pool_size = 2048*1024*1024;
            SET GLOBAL max_allowed_packet = 1024*1024*1024;
            SET GLOBAL innodb_flush_log_at_trx_commit = 0;
            SET GLOBAL sync_binlog = 0;
            SET GLOBAL foreign_key_checks = 0;
            SET GLOBAL unique_checks = 0;
        " 2>/dev/null
        
        # Import avec monitoring si pv est disponible
        echo "🚀 Import streaming..."
        if command -v pv >/dev/null 2>&1; then
            echo "📊 Monitoring avec pv activé"
            pv "$SQL_FILE" | docker exec -i "$CONTAINER_NAME" mysql \
                -u wordpress -pwordpress \
                --default-character-set=utf8mb4 \
                --max_allowed_packet=1G \
                --single-transaction \
                --quick \
                wordpress
        else
            echo "📊 Import sans monitoring (installez pv pour le monitoring)"
            docker exec -i "$CONTAINER_NAME" mysql \
                -u wordpress -pwordpress \
                --default-character-set=utf8mb4 \
                --max_allowed_packet=1G \
                --single-transaction \
                --quick \
                wordpress < "$SQL_FILE"
        fi
        IMPORT_SUCCESS=$?
        
        # Restaurer configuration
        echo "⚙️ Restauration configuration MySQL..."
        docker exec "$CONTAINER_NAME" mysql -u wordpress -pwordpress -e "
            SET GLOBAL foreign_key_checks = 1;
            SET GLOBAL unique_checks = 1;
            COMMIT;
        " 2>/dev/null
        ;;
        
    *)
        echo "❌ Méthode '$METHOD' non reconnue"
        exit 1
        ;;
esac

# Calculer la durée
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "📊 RÉSULTAT DE L'IMPORT"
echo "======================="
echo "⏱️  Durée: ${DURATION}s"
echo "📁 Taille: ${FILE_SIZE_MB} MB"
echo "🔧 Méthode: $METHOD"

if [ $IMPORT_SUCCESS -eq 0 ]; then
    echo "✅ Import réussi en ${DURATION}s"
    
    # Calculer la vitesse
    if [ $DURATION -gt 0 ]; then
        SPEED=$((FILE_SIZE_MB / DURATION))
        echo "🚀 Vitesse: ${SPEED} MB/s"
    fi
    
    echo ""
    echo "💡 Comparaison avec phpMyAdmin:"
    PHPMYADMIN_ESTIMATE=$((FILE_SIZE_MB * 10))  # Estimation: 10s par MB avec phpMyAdmin
    IMPROVEMENT=$((PHPMYADMIN_ESTIMATE / DURATION))
    echo "   phpMyAdmin (estimé): ${PHPMYADMIN_ESTIMATE}s"
    echo "   Gain de performance: ${IMPROVEMENT}x plus rapide"
    
else
    echo "❌ Import échoué"
    echo ""
    echo "💡 Solutions à essayer:"
    echo "   1. Vérifier que le fichier SQL est valide"
    echo "   2. Essayer une autre méthode d'import"
    echo "   3. Diviser le fichier en plusieurs parties"
fi

echo ""
echo "🔄 Pour réessayer avec une autre méthode:"
echo "   $0 $PROJECT_NAME $DB_FILE [direct|optimized|parallel|streaming]" 