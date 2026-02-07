#!/bin/bash

# Script de backup automatique pour toutes les bases de données MySQL et MongoDB
# Utilise Docker pour exporter les données directement depuis les conteneurs
# Destiné à être exécuté toutes les 4 heures via cron

# Configuration
BACKUP_DIR="/home/dev-server/backups"
LOG_FILE="/home/dev-server/logs/backup_databases.log"
RETENTION_DAYS=7
MAX_BACKUPS_PER_PROJECT=6  # 6 backups * 4h = 24h de couverture
LOCAL_IP="${APP_HOST:-$(hostname -I | awk '{print $1}')}"

# Couleurs pour l'affichage
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Fonction de log
log_message() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    echo -e "${timestamp} [${level}] ${message}" | tee -a "$LOG_FILE"
}

# Initialisation
init_backup_system() {
    log_message "INFO" "🚀 Initialisation du système de backup"
    
    # Créer les dossiers nécessaires
    mkdir -p "$BACKUP_DIR"/{mysql,mongodb}
    mkdir -p "$(dirname "$LOG_FILE")"
    
    # Vérifier que Docker est accessible
    if ! command -v docker &> /dev/null; then
        log_message "ERROR" "❌ Docker n'est pas installé ou accessible"
        exit 1
    fi
    
    # Vérifier que Docker daemon est actif
    if ! docker info &> /dev/null; then
        log_message "ERROR" "❌ Docker daemon n'est pas actif"
        exit 1
    fi
    
    log_message "INFO" "✅ Système de backup initialisé"
}

# Détecter tous les conteneurs MySQL actifs
detect_mysql_containers() {
    log_message "INFO" "🔍 Détection des conteneurs MySQL actifs..."
    
    # Rechercher tous les conteneurs MySQL actifs
    docker ps --format "{{.Names}}" | grep "_mysql_" | while read container_name; do
        if [ ! -z "$container_name" ]; then
            project_name=$(echo "$container_name" | cut -d'_' -f1)
            log_message "INFO" "  └─ Trouvé: $project_name (MySQL)" >&2
            echo "$project_name"
        fi
    done
}

# Détecter tous les conteneurs MongoDB actifs
detect_mongodb_containers() {
    log_message "INFO" "🔍 Détection des conteneurs MongoDB actifs..."
    
    # Rechercher tous les conteneurs MongoDB actifs
    docker ps --format "{{.Names}}" | grep "_mongodb_" | while read container_name; do
        if [ ! -z "$container_name" ]; then
            project_name=$(echo "$container_name" | cut -d'_' -f1)
            log_message "INFO" "  └─ Trouvé: $project_name (MongoDB)" >&2
            echo "$project_name"
        fi
    done
}

# Backup MySQL pour un projet
backup_mysql_project() {
    local project_name="$1"
    local container_name="${project_name}_mysql_1"
    local timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_file="$BACKUP_DIR/mysql/${project_name}_${timestamp}.sql"
    
    log_message "INFO" "🗄️ Backup MySQL pour $project_name"
    
    # Vérifier que le conteneur existe et est actif
    if ! docker ps --format "{{.Names}}" | grep -q "$container_name"; then
        log_message "ERROR" "❌ Conteneur $container_name non trouvé ou inactif"
        return 1
    fi
    
    # Détecter le type de base de données
    local database_name="wordpress"
    if docker exec "$container_name" mysql -u root -prootpassword -e "SHOW DATABASES;" 2>/dev/null | grep -q "$project_name"; then
        database_name="$project_name"
    fi
    
    log_message "INFO" "  └─ Base de données: $database_name"
    
    # Effectuer le backup
    if docker exec "$container_name" mysqldump \
        -u root -prootpassword \
        --single-transaction \
        --routines \
        --triggers \
        --default-character-set=utf8mb4 \
        --add-drop-database \
        --databases "$database_name" > "$backup_file" 2>/dev/null; then
        
        # Vérifier la taille du backup
        local file_size=$(stat -c%s "$backup_file" 2>/dev/null || echo "0")
        local size_mb=$((file_size / 1024 / 1024))
        
        if [ $file_size -gt 1024 ]; then  # Plus de 1KB
            log_message "SUCCESS" "✅ Backup MySQL $project_name réussi (${size_mb}MB)"
            
            # Compresser le backup si > 1MB
            if [ $size_mb -gt 1 ]; then
                gzip "$backup_file"
                log_message "INFO" "  └─ Backup compressé: ${backup_file}.gz"
            fi
            
            return 0
        else
            log_message "ERROR" "❌ Backup MySQL $project_name échoué (fichier trop petit)"
            rm -f "$backup_file"
            return 1
        fi
    else
        log_message "ERROR" "❌ Erreur lors du backup MySQL de $project_name"
        rm -f "$backup_file"
        return 1
    fi
}

# Backup MongoDB pour un projet
backup_mongodb_project() {
    local project_name="$1"
    local container_name="${project_name}_mongodb_1"
    local timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_dir="$BACKUP_DIR/mongodb/${project_name}_${timestamp}"
    
    log_message "INFO" "🍃 Backup MongoDB pour $project_name"
    
    # Vérifier que le conteneur existe et est actif
    if ! docker ps --format "{{.Names}}" | grep -q "$container_name"; then
        log_message "ERROR" "❌ Conteneur $container_name non trouvé ou inactif"
        return 1
    fi
    
    # Créer le dossier de backup
    mkdir -p "$backup_dir"
    
    # Effectuer le backup avec mongodump
    if docker exec "$container_name" mongodump \
        --username admin \
        --password adminpassword \
        --authenticationDatabase admin \
        --db "$project_name" \
        --out /tmp/backup &>/dev/null; then
        
        # Copier le backup depuis le conteneur
        docker cp "$container_name:/tmp/backup/$project_name" "$backup_dir/"
        
        # Nettoyer le conteneur
        docker exec "$container_name" rm -rf /tmp/backup
        
        # Vérifier que le backup contient des données
        if [ -d "$backup_dir/$project_name" ] && [ "$(ls -A "$backup_dir/$project_name")" ]; then
            # Compresser le backup
            cd "$BACKUP_DIR/mongodb"
            tar -czf "${project_name}_${timestamp}.tar.gz" "$(basename "$backup_dir")"
            rm -rf "$backup_dir"
            
            local file_size=$(stat -c%s "${project_name}_${timestamp}.tar.gz" 2>/dev/null || echo "0")
            local size_mb=$((file_size / 1024 / 1024))
            
            log_message "SUCCESS" "✅ Backup MongoDB $project_name réussi (${size_mb}MB)"
            return 0
        else
            log_message "ERROR" "❌ Backup MongoDB $project_name échoué (pas de données)"
            rm -rf "$backup_dir"
            return 1
        fi
    else
        log_message "ERROR" "❌ Erreur lors du backup MongoDB de $project_name"
        rm -rf "$backup_dir"
        return 1
    fi
}

# Nettoyer les anciens backups
cleanup_old_backups() {
    log_message "INFO" "🧹 Nettoyage des anciens backups"
    
    # Nettoyer les backups MySQL
    if [ -d "$BACKUP_DIR/mysql" ]; then
        # Supprimer les backups de plus de RETENTION_DAYS jours
        find "$BACKUP_DIR/mysql" -name "*.sql*" -mtime +$RETENTION_DAYS -exec rm -f {} \;
        
        # Garder seulement les MAX_BACKUPS_PER_PROJECT backups les plus récents par projet
        for project in $(ls "$BACKUP_DIR/mysql" | sed 's/_[0-9]*_[0-9]*\.sql.*$//' | sort -u); do
            ls -t "$BACKUP_DIR/mysql/${project}_"*.sql* 2>/dev/null | tail -n +$((MAX_BACKUPS_PER_PROJECT + 1)) | xargs -r rm -f
        done
    fi
    
    # Nettoyer les backups MongoDB
    if [ -d "$BACKUP_DIR/mongodb" ]; then
        # Supprimer les backups de plus de RETENTION_DAYS jours
        find "$BACKUP_DIR/mongodb" -name "*.tar.gz" -mtime +$RETENTION_DAYS -exec rm -f {} \;
        
        # Garder seulement les MAX_BACKUPS_PER_PROJECT backups les plus récents par projet
        for project in $(ls "$BACKUP_DIR/mongodb" | sed 's/_[0-9]*_[0-9]*\.tar\.gz$//' | sort -u); do
            ls -t "$BACKUP_DIR/mongodb/${project}_"*.tar.gz 2>/dev/null | tail -n +$((MAX_BACKUPS_PER_PROJECT + 1)) | xargs -r rm -f
        done
    fi
    
    log_message "INFO" "✅ Nettoyage terminé"
}

# Générer un rapport de backup
generate_backup_report() {
    log_message "INFO" "📊 Génération du rapport de backup"
    
    local report_file="$BACKUP_DIR/backup_report_$(date '+%Y%m%d_%H%M%S').txt"
    
    cat > "$report_file" << EOF
=== RAPPORT DE BACKUP AUTOMATIQUE ===
Date: $(date)
Serveur: $LOCAL_IP

=== RÉSUMÉ DES BACKUPS ===
EOF
    
    # Compter les backups MySQL
    local mysql_count=$(find "$BACKUP_DIR/mysql" -name "*.sql*" 2>/dev/null | wc -l)
    local mongodb_count=$(find "$BACKUP_DIR/mongodb" -name "*.tar.gz" 2>/dev/null | wc -l)
    
    echo "Backups MySQL: $mysql_count fichiers" >> "$report_file"
    echo "Backups MongoDB: $mongodb_count fichiers" >> "$report_file"
    echo "" >> "$report_file"
    
    # Lister les backups MySQL
    echo "=== BACKUPS MySQL ===" >> "$report_file"
    if [ -d "$BACKUP_DIR/mysql" ]; then
        ls -lh "$BACKUP_DIR/mysql"/ >> "$report_file" 2>/dev/null
    fi
    echo "" >> "$report_file"
    
    # Lister les backups MongoDB
    echo "=== BACKUPS MongoDB ===" >> "$report_file"
    if [ -d "$BACKUP_DIR/mongodb" ]; then
        ls -lh "$BACKUP_DIR/mongodb"/ >> "$report_file" 2>/dev/null
    fi
    
    log_message "INFO" "📋 Rapport généré: $report_file"
}

# Fonction principale
main() {
    local start_time=$(date +%s)
    
    log_message "INFO" "🚀 === DÉBUT DU BACKUP AUTOMATIQUE ==="
    
    # Initialiser le système
    init_backup_system
    
    # Statistiques
    local mysql_success=0
    local mysql_total=0
    local mongodb_success=0
    local mongodb_total=0
    
    # Backup des bases MySQL
    log_message "INFO" "🗄️ === BACKUP MYSQL ==="
    mysql_containers=$(detect_mysql_containers)
    if [ ! -z "$mysql_containers" ]; then
        # Convertir en tableau pour éviter les problèmes de pipe
        mysql_array=()
        while IFS= read -r project; do
            if [ ! -z "$project" ]; then
                mysql_array+=("$project")
            fi
        done <<< "$mysql_containers"
        
        # Backup de chaque projet MySQL
        for project in "${mysql_array[@]}"; do
            mysql_total=$((mysql_total + 1))
            if backup_mysql_project "$project"; then
                mysql_success=$((mysql_success + 1))
            fi
        done
    else
        log_message "INFO" "ℹ️ Aucun conteneur MySQL actif trouvé"
    fi
    
    # Backup des bases MongoDB
    log_message "INFO" "🍃 === BACKUP MONGODB ==="
    mongodb_containers=$(detect_mongodb_containers)
    if [ ! -z "$mongodb_containers" ]; then
        # Convertir en tableau pour éviter les problèmes de pipe
        mongodb_array=()
        while IFS= read -r project; do
            if [ ! -z "$project" ]; then
                mongodb_array+=("$project")
            fi
        done <<< "$mongodb_containers"
        
        # Backup de chaque projet MongoDB
        for project in "${mongodb_array[@]}"; do
            mongodb_total=$((mongodb_total + 1))
            if backup_mongodb_project "$project"; then
                mongodb_success=$((mongodb_success + 1))
            fi
        done
    else
        log_message "INFO" "ℹ️ Aucun conteneur MongoDB actif trouvé"
    fi
    
    # Nettoyage des anciens backups
    cleanup_old_backups
    
    # Génération du rapport
    generate_backup_report
    
    # Statistiques finales
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log_message "INFO" "📊 === RÉSUMÉ DU BACKUP ==="
    log_message "INFO" "MySQL: $mysql_success/$mysql_total projets sauvegardés"
    log_message "INFO" "MongoDB: $mongodb_success/$mongodb_total projets sauvegardés"
    log_message "INFO" "Durée totale: ${duration}s"
    log_message "INFO" "🏁 === FIN DU BACKUP AUTOMATIQUE ==="
    
    # Code de sortie
    if [ $((mysql_success + mongodb_success)) -eq $((mysql_total + mongodb_total)) ]; then
        exit 0
    else
        exit 1
    fi
}

# Gestion des arguments
case "${1:-}" in
    "test")
        log_message "INFO" "🧪 Mode test - Détection des conteneurs uniquement"
        init_backup_system
        detect_mysql_containers
        detect_mongodb_containers
        ;;
    "mysql-only")
        log_message "INFO" "🗄️ Mode MySQL uniquement"
        init_backup_system
        mysql_containers=$(detect_mysql_containers)
        if [ ! -z "$mysql_containers" ]; then
            mysql_array=()
            while IFS= read -r project; do
                if [ ! -z "$project" ]; then
                    mysql_array+=("$project")
                fi
            done <<< "$mysql_containers"
            
            for project in "${mysql_array[@]}"; do
                backup_mysql_project "$project"
            done
        fi
        ;;
    "mongodb-only")
        log_message "INFO" "🍃 Mode MongoDB uniquement"
        init_backup_system
        mongodb_containers=$(detect_mongodb_containers)
        if [ ! -z "$mongodb_containers" ]; then
            mongodb_array=()
            while IFS= read -r project; do
                if [ ! -z "$project" ]; then
                    mongodb_array+=("$project")
                fi
            done <<< "$mongodb_containers"
            
            for project in "${mongodb_array[@]}"; do
                backup_mongodb_project "$project"
            done
        fi
        ;;
    "cleanup")
        log_message "INFO" "🧹 Mode nettoyage uniquement"
        init_backup_system
        cleanup_old_backups
        ;;
    "report")
        log_message "INFO" "📊 Mode rapport uniquement"
        init_backup_system
        generate_backup_report
        ;;
    *)
        main
        ;;
esac 