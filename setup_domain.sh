#!/bin/bash

# Configuration d'un domaine externe pour WordPress Launcher
# Usage: ./setup_domain.sh <domain> <project_name>

set -e

DOMAIN=$1
PROJECT_NAME=$2
NGINX_AVAILABLE="/etc/nginx/sites-available"
NGINX_ENABLED="/etc/nginx/sites-enabled"
DOCKER_IP="192.168.1.21"

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <domain> <project_name>"
    echo "Exemple: $0 eurasiapeace.akdigital.fr eurasiapeace"
    exit 1
fi

echo "🌐 Configuration du domaine $DOMAIN pour le projet $PROJECT_NAME"

# Vérifier si nginx est installé
if ! command -v nginx &> /dev/null; then
    echo "📦 Installation de nginx..."
    sudo apt update
    sudo apt install -y nginx
    sudo systemctl enable nginx
    sudo systemctl start nginx
fi

# Vérifier que le projet existe
PROJECT_DIR="projets/$PROJECT_NAME"
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ Erreur: Le projet $PROJECT_NAME n'existe pas dans $PROJECT_DIR"
    exit 1
fi

# Récupérer le port du projet
if [ -f "$PROJECT_DIR/.port" ]; then
    PROJECT_PORT=$(cat "$PROJECT_DIR/.port")
    echo "✅ Port du projet trouvé: $PROJECT_PORT"
else
    echo "❌ Erreur: Fichier .port non trouvé pour le projet $PROJECT_NAME"
    exit 1
fi

# Créer la configuration nginx
NGINX_CONFIG="$NGINX_AVAILABLE/$DOMAIN"

echo "📝 Création de la configuration nginx..."

sudo tee "$NGINX_CONFIG" > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;
    
    # Logs
    access_log /var/log/nginx/${DOMAIN}_access.log;
    error_log /var/log/nginx/${DOMAIN}_error.log;
    
    # Security headers
    add_header X-Frame-Options SAMEORIGIN;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    
    # Proxy vers le conteneur WordPress
    location / {
        proxy_pass http://$DOCKER_IP:$PROJECT_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Buffer settings
        proxy_buffering on;
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
        proxy_busy_buffers_size 256k;
    }
    
    # Gestion des fichiers statiques
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|pdf|txt)$ {
        proxy_pass http://$DOCKER_IP:$PROJECT_PORT;
        proxy_set_header Host \$host;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # wp-admin avec sécurité renforcée
    location /wp-admin/ {
        proxy_pass http://$DOCKER_IP:$PROJECT_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # Protection contre les attaques
        client_max_body_size 100M;
    }
    
    # Protection des fichiers sensibles
    location ~ /\. {
        deny all;
    }
    
    location ~ ~$ {
        deny all;
    }
}
EOF

# Activer le site
echo "🔗 Activation du site..."
sudo ln -sf "$NGINX_CONFIG" "$NGINX_ENABLED/"

# Tester la configuration nginx
echo "🧪 Test de la configuration nginx..."
if sudo nginx -t; then
    echo "✅ Configuration nginx valide"
    
    # Recharger nginx
    echo "🔄 Rechargement de nginx..."
    sudo systemctl reload nginx
    
    echo ""
    echo "🎉 Configuration terminée !"
    echo ""
    echo "📋 ÉTAPES SUIVANTES :"
    echo "1. 📡 Configurer votre DNS pour pointer $DOMAIN vers votre IP publique"
    echo "2. 🏠 Vérifier que votre box redirige le port 80 vers $DOCKER_IP:80"
    echo "3. 🔐 Optionnel: Configurer HTTPS avec Let's Encrypt"
    echo ""
    echo "🔍 TESTS :"
    echo "- Local: curl -H 'Host: $DOMAIN' http://localhost"
    echo "- Externe: curl http://$DOMAIN"
    echo ""
    echo "📁 Configuration sauvée dans: $NGINX_CONFIG"
    
else
    echo "❌ Erreur dans la configuration nginx"
    exit 1
fi 