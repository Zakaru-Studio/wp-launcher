#!/bin/bash
set -e

echo "🔧 Activation de la configuration Apache personnalisée..."

# Activer la configuration si elle existe
if [ -f /etc/apache2/conf-available/phpmyadmin-custom.conf ]; then
    a2enconf phpmyadmin-custom >/dev/null 2>&1 || true
    a2enmod headers >/dev/null 2>&1 || true
    a2enmod expires >/dev/null 2>&1 || true
    a2enmod deflate >/dev/null 2>&1 || true
    echo "✅ Configuration Apache activée"
else
    echo "⚠️  Configuration Apache non trouvée"
fi

# Exécuter l'entrypoint original avec les arguments
exec /docker-entrypoint.sh "$@"
