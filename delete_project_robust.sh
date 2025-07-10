#!/bin/bash

# Script de suppression robuste des projets WordPress
# Utilise plusieurs méthodes pour s'assurer de la suppression complète

PROJECT_NAME="$1"
FORCE_MODE="${2:-false}"

if [ -z "$PROJECT_NAME" ]; then
    echo "❌ Usage: $0 <nom_du_projet> [force]"
    echo "   Exemples:"
    echo "     $0 monprojet"
    echo "     $0 monprojet force"
    exit 1
fi

PROJECT_PATH="/home/dev-server/Sites/wp-launcher/projets/$PROJECT_NAME"
CONTAINER_PATH="/home/dev-server/Sites/wp-launcher/containers/$PROJECT_NAME"

echo "🗑️  Script de suppression robuste pour: $PROJECT_NAME"
echo "📁 Chemin projets: $PROJECT_PATH"
echo "🐳 Chemin containers: $CONTAINER_PATH"
echo "🔧 Mode force: $FORCE_MODE"
echo "=============================================="

# Fonction pour logger avec timestamp
log() {
    echo "$(date '+%H:%M:%S') $1"
}

# Fonction pour exécuter une commande avec timeout et log
execute_with_timeout() {
    local cmd="$1"
    local timeout_sec="${2:-30}"
    local description="$3"
    
    log "🔧 $description..."
    
    if timeout $timeout_sec bash -c "$cmd" 2>/dev/null; then
        log "✅ $description - OK"
        return 0
    else
        log "⚠️  $description - ÉCHEC"
        return 1
    fi
}

# ÉTAPE 1: Vérifier que le projet existe
if [ ! -d "$PROJECT_PATH" ]; then
    log "❌ Projet non trouvé: $PROJECT_PATH"
    exit 1
fi

log "✅ Projet trouvé, début de la suppression"

# ÉTAPE 2: Arrêter tous les processus qui utilisent le répertoire
log "🛑 Arrêt des processus utilisant le répertoire..."

# Tuer tous les processus qui utilisent des fichiers dans ce répertoire
if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof +D "$PROJECT_PATH" 2>/dev/null | awk 'NR>1 {print $2}' | sort -u)
    if [ -n "$PIDS" ]; then
        log "🔫 Arrêt des processus: $PIDS"
        echo $PIDS | xargs -r kill -15 2>/dev/null
        sleep 2
        echo $PIDS | xargs -r kill -9 2>/dev/null
    fi
fi

# ÉTAPE 3: Démontage des volumes Docker
log "💾 Démontage des volumes Docker..."
MOUNTS=$(mount | grep "$PROJECT_PATH" | awk '{print $3}' | sort -r)
if [ -n "$MOUNTS" ]; then
    echo "$MOUNTS" | while read mount_point; do
        execute_with_timeout "umount -l '$mount_point'" 5 "Démontage $mount_point"
    done
fi

# ÉTAPE 4: Suppression complète des conteneurs Docker
log "🐳 Suppression des conteneurs Docker..."

# Méthode 1: docker-compose down (essayer les deux emplacements)
if [ -f "$CONTAINER_PATH/docker-compose.yml" ]; then
    execute_with_timeout "cd '$CONTAINER_PATH' && docker-compose down -v --remove-orphans --timeout 10" 30 "Docker-compose down (containers/)"
elif [ -f "$PROJECT_PATH/docker-compose.yml" ]; then
    execute_with_timeout "cd '$PROJECT_PATH' && docker-compose down -v --remove-orphans --timeout 10" 30 "Docker-compose down (projets/)"
fi

# Méthode 2: Suppression manuelle des conteneurs
for pattern in "${PROJECT_NAME}_" "${PROJECT_NAME}-" "_${PROJECT_NAME}_" "-${PROJECT_NAME}-"; do
    CONTAINERS=$(docker ps -a --format "{{.Names}}" | grep -F -- "$pattern" | tr '\n' ' ')
    if [ -n "$CONTAINERS" ]; then
        log "🛑 Arrêt des conteneurs: $CONTAINERS"
        docker stop $CONTAINERS 2>/dev/null || true
        docker rm -f $CONTAINERS 2>/dev/null || true
    fi
done

# ÉTAPE 5: Suppression des volumes Docker
log "💾 Suppression des volumes Docker..."
for pattern in "${PROJECT_NAME}_" "${PROJECT_NAME}-" "_${PROJECT_NAME}" "-${PROJECT_NAME}"; do
    VOLUMES=$(docker volume ls --format "{{.Name}}" | grep -F -- "$pattern" | tr '\n' ' ')
    if [ -n "$VOLUMES" ]; then
        log "💾 Suppression des volumes: $VOLUMES"
        docker volume rm -f $VOLUMES 2>/dev/null || true
    fi
done

# ÉTAPE 6: Suppression des images Docker personnalisées
log "🗑️ Suppression des images Docker..."
IMAGES=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep -i -- "$PROJECT_NAME" | tr '\n' ' ')
if [ -n "$IMAGES" ]; then
    log "🗑️ Suppression des images: $IMAGES"
    docker rmi -f $IMAGES 2>/dev/null || true
fi

# ÉTAPE 7: Suppression des réseaux Docker
log "🌐 Suppression des réseaux Docker..."
NETWORKS=$(docker network ls --format "{{.Name}}" | grep -i -- "$PROJECT_NAME" | tr '\n' ' ')
if [ -n "$NETWORKS" ]; then
    log "🌐 Suppression des réseaux: $NETWORKS"
    docker network rm $NETWORKS 2>/dev/null || true
fi

# ÉTAPE 8: Correction des permissions et propriétaires (amélioré pour www-data)
log "🔑 Correction des permissions et propriétaires..."

# Étape 8.1: Identifier les fichiers problématiques www-data
log "🔍 Identification des fichiers www-data..."
WWW_DATA_FILES=$(find "$PROJECT_PATH" -user www-data 2>/dev/null | wc -l)
if [ "$WWW_DATA_FILES" -gt 0 ]; then
    log "📊 Trouvé $WWW_DATA_FILES fichiers appartenant à www-data"
fi

# Étape 8.2: Supprimer les permissions spéciales (ACL, attributs étendus)
log "🔑 Suppression des permissions spéciales..."
if command -v setfacl >/dev/null 2>&1; then
    sudo setfacl -R -b "$PROJECT_PATH" 2>/dev/null || true
    log "✅ ACL supprimées"
fi

if command -v chattr >/dev/null 2>&1; then
    sudo chattr -R -i "$PROJECT_PATH" 2>/dev/null || true
    sudo chattr -R -a "$PROJECT_PATH" 2>/dev/null || true
    log "✅ Attributs immutables supprimés"
fi

# Étape 8.3: Forcer la prise de propriété avec plusieurs méthodes
log "🔑 Changement du propriétaire (méthode 1)..."
if sudo chown -R dev-server:dev-server "$PROJECT_PATH" 2>/dev/null; then
    log "✅ Propriétaire changé vers dev-server"
else
    log "⚠️ Erreur changement propriétaire, tentative alternative..."
    
    # Méthode alternative : forcer avec l'utilisateur courant
    log "🔑 Changement du propriétaire (méthode 2)..."
    sudo chown -R $(whoami):$(whoami) "$PROJECT_PATH" 2>/dev/null || true
    
    # Méthode alternative : forcer avec root puis dev-server
    log "🔑 Changement du propriétaire (méthode 3)..."
    sudo chown -R root:root "$PROJECT_PATH" 2>/dev/null || true
    sudo chown -R dev-server:dev-server "$PROJECT_PATH" 2>/dev/null || true
fi

# Étape 8.4: Forcer les permissions en plusieurs étapes
log "🔑 Modification des permissions (étape 1)..."
sudo chmod -R u+rwX "$PROJECT_PATH" 2>/dev/null || true

log "🔑 Modification des permissions (étape 2)..."
sudo chmod -R go+rwX "$PROJECT_PATH" 2>/dev/null || true

log "🔑 Modification des permissions (étape 3)..."
if sudo chmod -R 777 "$PROJECT_PATH" 2>/dev/null; then
    log "✅ Permissions modifiées"
else
    log "⚠️ Erreur modification permissions, forçage fichier par fichier..."
    # Forcer fichier par fichier si nécessaire
    sudo find "$PROJECT_PATH" -type f -exec chmod 666 {} + 2>/dev/null || true
    sudo find "$PROJECT_PATH" -type d -exec chmod 777 {} + 2>/dev/null || true
fi

# Étape 8.5: Vérification finale des permissions
REMAINING_PROTECTED=$(find "$PROJECT_PATH" ! -user dev-server 2>/dev/null | wc -l)
if [ "$REMAINING_PROTECTED" -gt 0 ]; then
    log "⚠️ $REMAINING_PROTECTED fichiers encore protégés, forçage final..."
    sudo find "$PROJECT_PATH" ! -user dev-server -exec chown dev-server:dev-server {} + 2>/dev/null || true
fi

# Forcer l'arrêt des processus qui pourraient encore bloquer les fichiers
log "🛑 Vérification finale des processus bloquants..."
if command -v lsof >/dev/null 2>&1; then
    BLOCKING_PIDS=$(lsof +D "$PROJECT_PATH" 2>/dev/null | awk 'NR>1 {print $2}' | sort -u)
    if [ -n "$BLOCKING_PIDS" ]; then
        log "🔫 Forçage arrêt des processus bloquants: $BLOCKING_PIDS"
        echo $BLOCKING_PIDS | xargs -r sudo kill -9 2>/dev/null || true
        sleep 1
    fi
fi

# ÉTAPE 9: Suppression physique avec plusieurs méthodes (renforcé)
log "📁 Suppression physique des fichiers..."

# Pré-étape: Vérification des derniers verrous
log "🔒 Vérification finale des verrous de fichiers..."
if command -v fuser >/dev/null 2>&1; then
    sudo fuser -k "$PROJECT_PATH" 2>/dev/null || true
    sleep 1
fi

# Méthode 1: Suppression directe avec sudo (plus efficace pour les fichiers www-data)
log "🔥 Tentative suppression directe avec sudo..."
if sudo rm -rf "$PROJECT_PATH" 2>/dev/null; then
    log "✅ Suppression directe avec sudo réussie"
else
    log "⚠️ Suppression directe échouée, tentative méthode normale..."
    
    # Méthode 2: Suppression normale (au cas où sudo aurait des problèmes)
    if rm -rf "$PROJECT_PATH" 2>/dev/null; then
        log "✅ Suppression normale réussie"
    else
        log "⚠️ Suppression normale échouée, essai méthode 3..."
        
        # Méthode 3: Suppression spécialisée www-data
        log "🔧 Suppression spécialisée pour fichiers www-data..."
        # D'abord supprimer les fichiers www-data spécifiquement
        sudo find "$PROJECT_PATH" -user www-data -type f -delete 2>/dev/null || true
        sudo find "$PROJECT_PATH" -user www-data -type d -delete 2>/dev/null || true
        
        # Puis suppression générale avec find
        if sudo find "$PROJECT_PATH" -type f -delete 2>/dev/null && sudo find "$PROJECT_PATH" -type d -delete 2>/dev/null; then
            log "✅ Suppression spécialisée réussie"
        else
            log "⚠️ Suppression spécialisée échouée, essai méthode 4..."
            
            # Méthode 4: Suppression avec permissions forcées avant suppression
            log "🔧 Suppression avec permissions forcées..."
            # Forcer les permissions une dernière fois avant suppression
            sudo find "$PROJECT_PATH" -type f -exec chmod 777 {} + 2>/dev/null || true
            sudo find "$PROJECT_PATH" -type d -exec chmod 777 {} + 2>/dev/null || true
            
            if sudo find "$PROJECT_PATH" -type f -exec rm -f {} + 2>/dev/null; then
                sudo find "$PROJECT_PATH" -type d -depth -exec rmdir {} + 2>/dev/null || true
                if [ ! -d "$PROJECT_PATH" ]; then
                    log "✅ Suppression avec permissions forcées réussie"
                else
                    log "⚠️ Suppression partielle, essai méthode 5..."
                    
                    # Méthode 5: Suppression par types de fichiers
                    log "🔧 Suppression par types de fichiers..."
                    # Supprimer d'abord les fichiers problématiques courants
                    sudo find "$PROJECT_PATH" -name ".htaccess" -delete 2>/dev/null || true
                    sudo find "$PROJECT_PATH" -name "*.log" -delete 2>/dev/null || true
                    sudo find "$PROJECT_PATH" -name "*.php" -delete 2>/dev/null || true
                    
                    # Puis tous les autres fichiers
                    sudo find "$PROJECT_PATH" -type f -delete 2>/dev/null || true
                    sudo find "$PROJECT_PATH" -type d -delete 2>/dev/null || true
                    
                    if [ ! -d "$PROJECT_PATH" ]; then
                        log "✅ Suppression par types réussie"
                    else
                        log "⚠️ Suppression par types partielle, essai méthode 6..."
                        
                        # Méthode 6: Suppression brutale avec mv puis rm en arrière-plan
                        TEMP_PATH="/tmp/delete_${PROJECT_NAME}_$(date +%s)"
                        log "🔄 Déplacement vers dossier temporaire: $TEMP_PATH"
                        if sudo mv "$PROJECT_PATH" "$TEMP_PATH" 2>/dev/null; then
                            log "✅ Déplacement réussi, suppression en arrière-plan..."
                            (sudo rm -rf "$TEMP_PATH" 2>/dev/null) &
                            log "✅ Suppression en arrière-plan démarrée"
                        else
                            log "❌ Déplacement impossible, essai méthode 7..."
                            
                            # Méthode 7: Dernière tentative avec truncate puis suppression
                            if [ "$FORCE_MODE" = "force" ]; then
                                log "🔥 Mode force activé - dernière tentative"
                                # Tronquer tous les fichiers puis supprimer
                                sudo find "$PROJECT_PATH" -type f -exec truncate -s 0 {} + 2>/dev/null || true
                                sudo find "$PROJECT_PATH" -mindepth 1 -delete 2>/dev/null || true
                                
                                # Si le dossier existe encore, le renommer pour masquer
                                if [ -d "$PROJECT_PATH" ]; then
                                    HIDDEN_PATH="${PROJECT_PATH}.deleted_$(date +%s)"
                                    sudo mv "$PROJECT_PATH" "$HIDDEN_PATH" 2>/dev/null || true
                                    log "⚠️ Dossier renommé en $HIDDEN_PATH pour masquage"
                                fi
                            else
                                log "❌ Toutes les méthodes ont échoué. Utilisez 'force' pour dernière tentative"
                            fi
                        fi
                    fi
                fi
            else
                log "❌ Suppression avec permissions forcées impossible"
            fi
        fi
    fi
fi

# ÉTAPE 10: Suppression du dossier containers/ 
if [ -d "$CONTAINER_PATH" ]; then
    log "🐳 Suppression du dossier containers/..."
    
    # Appliquer les mêmes corrections de permissions
    sudo chown -R dev-server:dev-server "$CONTAINER_PATH" 2>/dev/null || true
    sudo chmod -R 777 "$CONTAINER_PATH" 2>/dev/null || true
    
    # Tentative de suppression
    if sudo rm -rf "$CONTAINER_PATH" 2>/dev/null; then
        log "✅ Dossier containers/ supprimé"
    else
        # Méthode alternative pour containers/
        log "⚠️ Suppression directe containers/ échouée, méthode alternative..."
        sudo find "$CONTAINER_PATH" -type f -delete 2>/dev/null || true
        sudo find "$CONTAINER_PATH" -type d -delete 2>/dev/null || true
        
        if [ ! -d "$CONTAINER_PATH" ]; then
            log "✅ Dossier containers/ supprimé (méthode alternative)"
        else
            log "⚠️ Dossier containers/ partiellement supprimé"
        fi
    fi
else
    log "📁 Dossier containers/ déjà absent"
fi

# ÉTAPE 11: Vérification finale
if [ -d "$PROJECT_PATH" ]; then
    log "⚠️ Le dossier projets/ existe encore, mais il peut être vidé"
    log "📊 Contenu restant:"
    ls -la "$PROJECT_PATH" 2>/dev/null || echo "  (inaccessible)"
else
    log "✅ Dossier projets/ complètement supprimé"
fi

if [ -d "$CONTAINER_PATH" ]; then
    log "⚠️ Le dossier containers/ existe encore"
    log "📊 Contenu restant containers/:"
    ls -la "$CONTAINER_PATH" 2>/dev/null || echo "  (inaccessible)"
else
    log "✅ Dossier containers/ complètement supprimé"
fi

# ÉTAPE 12: Nettoyage des fichiers de configuration
log "🧹 Nettoyage des fichiers de configuration..."

# Marquer comme supprimé dans les fichiers de configuration
DELETED_PROJECTS_FILE="/home/dev-server/Sites/wp-launcher/projets/.deleted_projects"
if ! grep -q "^$PROJECT_NAME$" "$DELETED_PROJECTS_FILE" 2>/dev/null; then
    echo "$PROJECT_NAME" >> "$DELETED_PROJECTS_FILE"
    log "✅ Projet marqué comme supprimé dans la configuration"
fi

# Supprimer l'hostname des hosts
log "🌐 Suppression de l'hostname des hosts..."
HOSTNAME="${PROJECT_NAME}.local"
if grep -q "$HOSTNAME" /etc/hosts 2>/dev/null; then
    sudo sed -i "/$HOSTNAME/d" /etc/hosts 2>/dev/null
    log "✅ Hostname supprimé des hosts"
fi

# ÉTAPE 13: Nettoyage Docker global
log "🧹 Nettoyage Docker global..."
docker system prune -f 2>/dev/null || true

# ÉTAPE 14: Résumé final
log "=============================================="
log "🎯 RÉSUMÉ DE LA SUPPRESSION:"
log "   Projet: $PROJECT_NAME"
log "   Chemin projets/: $PROJECT_PATH"
log "   Chemin containers/: $CONTAINER_PATH"
log "   État projets/: $([ -d "$PROJECT_PATH" ] && echo "PARTIELLEMENT SUPPRIMÉ" || echo "COMPLÈTEMENT SUPPRIMÉ")"
log "   État containers/: $([ -d "$CONTAINER_PATH" ] && echo "PARTIELLEMENT SUPPRIMÉ" || echo "COMPLÈTEMENT SUPPRIMÉ")"
log "   Docker: Conteneurs, volumes, images et réseaux supprimés"
log "   Config: Marqué comme supprimé"
log "   Hosts: Hostname supprimé"
log "=============================================="

# Code de sortie
if [ -d "$PROJECT_PATH" ] || [ -d "$CONTAINER_PATH" ]; then
    log "⚠️ Suppression partielle - le projet n'apparaîtra plus dans l'interface"
    exit 2
else
    log "✅ Suppression complète réussie"
    exit 0
fi 