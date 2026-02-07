#!/bin/bash
set -e

# Script d'entrypoint personnalisé pour phpMyAdmin
# Active la configuration Apache personnalisée pour les limites d'en-têtes

echo "🔧 Configuration Apache personnalisée pour phpMyAdmin..."

# Copier et activer la configuration Apache personnalisée
if [ -f /etc/phpmyadmin-apache.conf ]; then
    echo "📋 Activation de la configuration Apache personnalisée..."
    
    # Copier la configuration dans le répertoire Apache
    cp /etc/phpmyadmin-apache.conf /etc/apache2/conf-available/phpmyadmin-custom.conf
    
    # Activer la configuration
    a2enconf phpmyadmin-custom
    
    # Activer les modules nécessaires
    a2enmod headers
    a2enmod expires
    a2enmod deflate
    
    echo "✅ Configuration Apache activée avec succès"
else
    echo "⚠️  Fichier de configuration Apache non trouvé, utilisation de la configuration par défaut"
fi

echo "🚀 Démarrage de phpMyAdmin avec configuration personnalisée..."

# Exécuter l'entrypoint original de phpMyAdmin
exec /docker-entrypoint.sh "$@"
