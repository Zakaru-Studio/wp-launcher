#!/bin/bash

# Script pour gérer automatiquement les entrées /etc/hosts pour WP Launcher
# Usage: ./manage_hosts.sh [add|remove|update|list] [hostname]

ACTION="$1"
HOSTNAME="$2"
HOSTS_FILE="/etc/hosts"
BACKUP_FILE="/etc/hosts.wp-launcher-backup"
IP_ADDRESS="127.0.0.1"
MARKER_START="# WP Launcher - START"
MARKER_END="# WP Launcher - END"

# Fonction pour vérifier les permissions
check_permissions() {
    if [ "$EUID" -ne 0 ]; then
        echo "❌ Ce script doit être exécuté avec sudo"
        echo "Usage: sudo $0 $ACTION $HOSTNAME"
        exit 1
    fi
}

# Fonction pour créer une sauvegarde
create_backup() {
    if [ ! -f "$BACKUP_FILE" ]; then
        cp "$HOSTS_FILE" "$BACKUP_FILE"
        echo "💾 Sauvegarde créée: $BACKUP_FILE"
    fi
}

# Fonction pour ajouter une entrée
add_entry() {
    local hostname="$1"
    
    if [ -z "$hostname" ]; then
        echo "❌ Hostname requis"
        echo "Usage: sudo $0 add <hostname>"
        exit 1
    fi
    
    check_permissions
    create_backup
    
    # Vérifier si l'entrée existe déjà
    if grep -q "$hostname" "$HOSTS_FILE"; then
        echo "⚠️ L'entrée pour $hostname existe déjà dans /etc/hosts"
        return 0
    fi
    
    # Ajouter la section WP Launcher si elle n'existe pas
    if ! grep -q "$MARKER_START" "$HOSTS_FILE"; then
        echo "" >> "$HOSTS_FILE"
        echo "$MARKER_START" >> "$HOSTS_FILE"
        echo "$MARKER_END" >> "$HOSTS_FILE"
        echo "📝 Section WP Launcher créée dans /etc/hosts"
    fi
    
    # Ajouter l'entrée avant le marqueur de fin
    sed -i "/$MARKER_END/i $IP_ADDRESS    $hostname" "$HOSTS_FILE"
    echo "✅ Ajouté: $IP_ADDRESS    $hostname"
}

# Fonction pour supprimer une entrée
remove_entry() {
    local hostname="$1"
    
    if [ -z "$hostname" ]; then
        echo "❌ Hostname requis"
        echo "Usage: sudo $0 remove <hostname>"
        exit 1
    fi
    
    check_permissions
    create_backup
    
    # Supprimer l'entrée
    sed -i "/$hostname/d" "$HOSTS_FILE"
    echo "🗑️ Supprimé: $hostname"
    
    # Nettoyer la section si elle est vide
    if grep -A1 "$MARKER_START" "$HOSTS_FILE" | grep -q "$MARKER_END"; then
        sed -i "/$MARKER_START/,/$MARKER_END/d" "$HOSTS_FILE"
        echo "🧹 Section WP Launcher vide supprimée"
    fi
}

# Fonction pour mettre à jour toutes les entrées basées sur les projets
update_all() {
    check_permissions
    create_backup
    
    echo "🔄 Mise à jour de toutes les entrées /etc/hosts..."
    
    # Supprimer toutes les entrées WP Launcher existantes
    if grep -q "$MARKER_START" "$HOSTS_FILE"; then
        sed -i "/$MARKER_START/,/$MARKER_END/d" "$HOSTS_FILE"
    fi
    
    # Ajouter la section
    echo "" >> "$HOSTS_FILE"
    echo "$MARKER_START" >> "$HOSTS_FILE"
    echo "# Hostnames générés automatiquement par WP Launcher" >> "$HOSTS_FILE"
    
    # Scanner tous les projets
    if [ -d "projets" ]; then
        for project_dir in projets/*/; do
            if [ -d "$project_dir" ]; then
                project_name=$(basename "$project_dir")
                hostname_file="$project_dir/.hostname"
                
                if [ -f "$hostname_file" ]; then
                    hostname=$(cat "$hostname_file")
                else
                    hostname="$project_name.local"
                fi
                
                echo "$IP_ADDRESS    $hostname" >> "$HOSTS_FILE"
                echo "✅ Ajouté: $hostname"
            fi
        done
    fi
    
    echo "$MARKER_END" >> "$HOSTS_FILE"
    echo "🎯 Mise à jour terminée"
}

# Fonction pour lister les entrées
list_entries() {
    echo "📋 Entrées WP Launcher dans /etc/hosts:"
    echo "======================================"
    
    if grep -q "$MARKER_START" "$HOSTS_FILE"; then
        sed -n "/$MARKER_START/,/$MARKER_END/p" "$HOSTS_FILE" | grep -v "^#" | grep -v "^$"
    else
        echo "Aucune entrée WP Launcher trouvée"
    fi
}

# Fonction pour restaurer la sauvegarde
restore_backup() {
    if [ -f "$BACKUP_FILE" ]; then
        check_permissions
        cp "$BACKUP_FILE" "$HOSTS_FILE"
        echo "🔄 Sauvegarde restaurée depuis $BACKUP_FILE"
    else
        echo "❌ Aucune sauvegarde trouvée"
    fi
}

# Menu principal
case "$ACTION" in
    "add")
        add_entry "$HOSTNAME"
        ;;
    "remove")
        remove_entry "$HOSTNAME"
        ;;
    "update")
        update_all
        ;;
    "list")
        list_entries
        ;;
    "restore")
        restore_backup
        ;;
    *)
        echo "🌐 WP Launcher - Gestionnaire /etc/hosts"
        echo "======================================="
        echo ""
        echo "Usage: sudo $0 [action] [hostname]"
        echo ""
        echo "Actions disponibles:"
        echo "  add <hostname>     - Ajouter un hostname"
        echo "  remove <hostname>  - Supprimer un hostname"
        echo "  update             - Mettre à jour tous les hostnames depuis les projets"
        echo "  list               - Lister toutes les entrées WP Launcher"
        echo "  restore            - Restaurer la sauvegarde /etc/hosts"
        echo ""
        echo "Exemples:"
        echo "  sudo $0 add monsite.local"
        echo "  sudo $0 remove monsite.local"
        echo "  sudo $0 update"
        echo "  sudo $0 list"
        exit 1
        ;;
esac 