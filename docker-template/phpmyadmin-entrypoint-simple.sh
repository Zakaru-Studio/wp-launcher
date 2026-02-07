#!/bin/bash
set -e

echo "🔧 Configuration Apache pour phpMyAdmin..."

# Copier et activer la configuration Apache si elle existe
if [ -f /etc/phpmyadmin-apache.conf ]; then
    echo "📋 Activation de la configuration Apache..."
    
    # Copier la configuration
    cp /etc/phpmyadmin-apache.conf /etc/apache2/conf-available/phpmyadmin-custom.conf
    
    # Activer la configuration et les modules nécessaires
    a2enconf phpmyadmin-custom >/dev/null 2>&1 || true
    a2enmod headers >/dev/null 2>&1 || true
    a2enmod expires >/dev/null 2>&1 || true
    a2enmod deflate >/dev/null 2>&1 || true
    
    echo "✅ Configuration Apache activée"
else
    echo "⚠️  Configuration Apache non trouvée, utilisation par défaut"
fi

echo "🚀 Démarrage de phpMyAdmin..."

# Exécuter l'entrypoint original
exec /docker-entrypoint.sh "$@"
