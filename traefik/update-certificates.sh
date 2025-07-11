#!/bin/bash

echo "🔄 Mise à jour des certificats SSL pour Traefik"
echo "============================================="

# Répertoire de travail
TRAEFIK_DIR="/home/dev-server/Sites/wp-launcher/traefik"
CERT_SOURCE_DIR="/etc/letsencrypt/live/dev.akdigital.fr"

# Vérifier que les certificats sources existent
if [ ! -f "$CERT_SOURCE_DIR/fullchain.pem" ] || [ ! -f "$CERT_SOURCE_DIR/privkey.pem" ]; then
    echo "❌ Certificats source non trouvés dans $CERT_SOURCE_DIR"
    exit 1
fi

# Aller dans le répertoire Traefik
cd "$TRAEFIK_DIR" || exit 1

# Copier les certificats
echo "📄 Copie des certificats..."
sudo cp "$CERT_SOURCE_DIR/fullchain.pem" . || exit 1
sudo cp "$CERT_SOURCE_DIR/privkey.pem" . || exit 1

# Ajuster les permissions
echo "🔐 Ajustement des permissions..."
sudo chown $USER:$USER *.pem || exit 1
chmod 644 fullchain.pem || exit 1
chmod 600 privkey.pem || exit 1

# Redémarrer Traefik
echo "🔄 Redémarrage de Traefik..."
docker-compose restart traefik || exit 1

echo "✅ Certificats mis à jour avec succès!"
echo "🌐 Traefik utilise maintenant les certificats SSL à jour" 