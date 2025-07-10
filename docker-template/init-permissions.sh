#!/bin/bash

# Script d'initialisation des permissions WordPress
# S'assure que les permissions sont correctes au démarrage du conteneur

echo "🔧 Initialisation des permissions WordPress..."

# Attendre que les volumes soient montés
sleep 2

# S'assurer que wp-content existe
if [ -d "/var/www/html/wp-content" ]; then
    echo "✅ Dossier wp-content trouvé"
    
    # Créer le dossier uploads s'il n'existe pas
    if [ ! -d "/var/www/html/wp-content/uploads" ]; then
        echo "📁 Création du dossier uploads..."
        mkdir -p /var/www/html/wp-content/uploads
    fi
    
    # Appliquer les bonnes permissions sur wp-content et uploads
    echo "🔒 Application des permissions sur wp-content..."
    chown -R www-data:www-data /var/www/html/wp-content
    chmod -R 2775 /var/www/html/wp-content
    
    # Permissions spécifiques pour uploads
    if [ -d "/var/www/html/wp-content/uploads" ]; then
        echo "🔒 Application des permissions sur uploads..."
        chown -R www-data:www-data /var/www/html/wp-content/uploads
        chmod -R 2775 /var/www/html/wp-content/uploads
    fi
    
    # Permissions pour .htaccess
    if [ -f "/var/www/html/.htaccess" ]; then
        echo "🔒 Application des permissions sur .htaccess..."
        chown www-data:www-data /var/www/html/.htaccess
        chmod 664 /var/www/html/.htaccess
    fi
    
    # Permissions pour wp-config.php
    if [ -f "/var/www/html/wp-config.php" ]; then
        echo "🔒 Application des permissions sur wp-config.php..."
        chown www-data:www-data /var/www/html/wp-config.php
        chmod 664 /var/www/html/wp-config.php
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
    
    echo "✅ Permissions initialisées avec succès"
else
    echo "⚠️  Dossier wp-content non trouvé - permissions non appliquées"
fi

echo "🚀 Démarrage de WordPress..."

# Exécuter le script d'entrée original de WordPress
exec docker-entrypoint.sh "$@" 