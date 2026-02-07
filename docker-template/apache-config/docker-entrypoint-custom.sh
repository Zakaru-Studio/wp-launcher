#!/bin/bash
set -e

echo "🔧 Configuration Apache personnalisée pour WordPress..."

# Copier et activer la configuration Apache personnalisée
if [ -f /etc/apache2/conf-available/wordpress-custom.conf ]; then
    echo "📋 Activation de la configuration Apache personnalisée..."
    
    # Activer la configuration
    a2enconf wordpress-custom >/dev/null 2>&1 || true
    
    # Activer les modules nécessaires
    a2enmod headers >/dev/null 2>&1 || true
    a2enmod expires >/dev/null 2>&1 || true
    a2enmod deflate >/dev/null 2>&1 || true
    a2enmod rewrite >/dev/null 2>&1 || true
    
    echo "✅ Configuration Apache activée avec succès"
else
    echo "⚠️  Fichier de configuration Apache non trouvé, utilisation de la configuration par défaut"
fi

echo "🔧 Initialisation des permissions WordPress..."

# Exécuter le script d'initialisation des permissions s'il existe
if [ -f /usr/local/bin/init-permissions.sh ]; then
    chmod +x /usr/local/bin/init-permissions.sh
    /usr/local/bin/init-permissions.sh
else
    echo "⚠️  Script de permissions non trouvé"
fi

echo "🚀 Démarrage de WordPress avec configuration personnalisée..."

# Exécuter l'entrypoint original de WordPress
exec /usr/local/bin/docker-entrypoint.sh "$@"
