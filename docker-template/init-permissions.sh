#!/bin/bash

# Script d'initialisation des permissions WordPress
# S'assure que les permissions sont correctes au démarrage du conteneur
# Compatible avec l'utilisateur dev-server (UID 1000) et www-data

echo "🔧 Initialisation des permissions WordPress..."

# Attendre que les volumes soient montés
sleep 2

# Fonction pour appliquer les permissions optimales
apply_permissions() {
    local path="$1"
    local is_file="$2"
    
    if [ "$is_file" = "true" ]; then
        # Fichiers : lecture/écriture pour propriétaire et groupe
        chown www-data:www-data "$path"
        chmod 664 "$path"
    else
        # Dossiers : setgid pour hériter du groupe, permissions larges
        chown www-data:www-data "$path"
        chmod 2775 "$path"
    fi
}

# S'assurer que wp-content existe
if [ -d "/var/www/html/wp-content" ]; then
    echo "✅ Dossier wp-content trouvé"
    
    # Créer le dossier uploads s'il n'existe pas
    if [ ! -d "/var/www/html/wp-content/uploads" ]; then
        echo "📁 Création du dossier uploads..."
        mkdir -p /var/www/html/wp-content/uploads
    fi
    
    # Appliquer les bonnes permissions sur wp-content et tous ses sous-éléments
    echo "🔒 Application des permissions sur wp-content..."
    
    # Permissions récursives pour tous les dossiers
    find /var/www/html/wp-content -type d -exec chown www-data:www-data {} \; 2>/dev/null || true
    find /var/www/html/wp-content -type d -exec chmod 2775 {} \; 2>/dev/null || true
    
    # Permissions récursives pour tous les fichiers
    find /var/www/html/wp-content -type f -exec chown www-data:www-data {} \; 2>/dev/null || true
    find /var/www/html/wp-content -type f -exec chmod 664 {} \; 2>/dev/null || true
    
    # Permissions spéciales pour certains fichiers
    if [ -d "/var/www/html/wp-content/uploads" ]; then
        echo "🔒 Application des permissions sur uploads..."
        find /var/www/html/wp-content/uploads -type d -exec chmod 2775 {} \; 2>/dev/null || true
        find /var/www/html/wp-content/uploads -type f -exec chmod 664 {} \; 2>/dev/null || true
    fi
    
    echo "✅ wp-content configuré avec succès"
else
    echo "⚠️  Dossier wp-content non trouvé - création en cours..."
    mkdir -p /var/www/html/wp-content/uploads
    chown -R www-data:www-data /var/www/html/wp-content
    chmod -R 2775 /var/www/html/wp-content
fi

# Permissions pour .htaccess
if [ -f "/var/www/html/.htaccess" ]; then
    echo "🔒 Application des permissions sur .htaccess..."
    apply_permissions "/var/www/html/.htaccess" "true"
fi

# Permissions pour wp-config.php
if [ -f "/var/www/html/wp-config.php" ]; then
    echo "🔒 Application des permissions sur wp-config.php..."
    apply_permissions "/var/www/html/wp-config.php" "true"
fi

# Créer les dossiers d'upload pour l'année courante
CURRENT_YEAR=$(date +%Y)
CURRENT_MONTH=$(date +%m)
if [ ! -d "/var/www/html/wp-content/uploads/$CURRENT_YEAR" ]; then
    echo "📁 Création des dossiers d'upload pour $CURRENT_YEAR/$CURRENT_MONTH..."
    mkdir -p "/var/www/html/wp-content/uploads/$CURRENT_YEAR/$CURRENT_MONTH"
    chown -R www-data:www-data "/var/www/html/wp-content/uploads/$CURRENT_YEAR"
    chmod -R 2775 "/var/www/html/wp-content/uploads/$CURRENT_YEAR"
fi

# Nettoyer les permissions root éventuelles (problème lors de la suppression)
echo "🧹 Nettoyage des permissions root..."
if [ -d "/var/www/html/wp-content" ]; then
    find /var/www/html/wp-content -user root -exec chown www-data:www-data {} \; 2>/dev/null || true
fi

echo "✅ Permissions initialisées avec succès"
echo "👥 Utilisateurs autorisés : www-data, dev-server (groupe www-data)"

echo "🚀 Démarrage de WordPress..."

# Exécuter le script d'entrée original de WordPress
exec docker-entrypoint.sh "$@" 