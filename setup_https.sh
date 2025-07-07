#!/bin/bash

# Configuration HTTPS avec Let's Encrypt pour un domaine
# Usage: ./setup_https.sh <domain> <email>

set -e

DOMAIN=$1
EMAIL=$2
NGINX_AVAILABLE="/etc/nginx/sites-available"
NGINX_ENABLED="/etc/nginx/sites-enabled"

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <domain> <email>"
    echo "Exemple: $0 eurasiapeace.akdigital.fr contact@akdigital.fr"
    exit 1
fi

echo "🔐 Configuration HTTPS pour $DOMAIN"

# Vérifier que le domaine est configuré
if [ ! -f "$NGINX_AVAILABLE/$DOMAIN" ]; then
    echo "❌ Erreur: Configuration nginx pour $DOMAIN non trouvée"
    echo "Exécutez d'abord: ./setup_domain.sh $DOMAIN <project_name>"
    exit 1
fi

# Installer certbot si nécessaire
if ! command -v certbot &> /dev/null; then
    echo "📦 Installation de certbot..."
    sudo apt update
    sudo apt install -y certbot python3-certbot-nginx
fi

# Obtenir le certificat SSL
echo "🎫 Obtention du certificat SSL..."
sudo certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive

# Configurer le renouvellement automatique
echo "🔄 Configuration du renouvellement automatique..."
if ! sudo crontab -l 2>/dev/null | grep -q "certbot renew"; then
    (sudo crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet") | sudo crontab -
fi

echo ""
echo "🎉 HTTPS configuré avec succès !"
echo ""
echo "✅ Votre site est maintenant accessible via:"
echo "   - https://$DOMAIN"
echo "   - https://www.$DOMAIN"
echo ""
echo "🔄 Le certificat se renouvellera automatiquement"
echo "🧪 Testez votre configuration: https://www.ssllabs.com/ssltest/" 