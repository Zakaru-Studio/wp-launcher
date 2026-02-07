#!/bin/bash
#
# WP Launcher - Script d'installation
# Clone le repo puis lance ce script pour tout configurer
#
# Usage: ./install.sh
#

set -e

# Couleurs
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
CURRENT_USER=$(whoami)

echo "=========================================="
echo "  WP Launcher - Installation"
echo "=========================================="
echo ""

# 1. Vérification des prérequis
echo -e "${YELLOW}[1/6] Vérification des prérequis...${NC}"

for cmd in python3 docker docker-compose; do
    if ! command -v "$cmd" &> /dev/null; then
        echo -e "${RED}❌ $cmd n'est pas installé${NC}"
        exit 1
    fi
    echo -e "  ✅ $cmd"
done

if ! systemctl is-active --quiet docker; then
    echo -e "${RED}❌ Le service Docker n'est pas actif${NC}"
    exit 1
fi
echo -e "  ✅ Docker service actif"

# 2. Création des dossiers de données
echo ""
echo -e "${YELLOW}[2/6] Création des dossiers de données...${NC}"

for dir in projets containers uploads data data/avatars logs snapshots; do
    mkdir -p "$APP_DIR/$dir"
    echo -e "  ✅ $dir/"
done

# 3. Création des symlinks
echo ""
echo -e "${YELLOW}[3/6] Création des symlinks...${NC}"

# Symlink projets dans app/utils/
if [ ! -L "$APP_DIR/app/utils/projets" ]; then
    ln -s "$APP_DIR/projets" "$APP_DIR/app/utils/projets"
    echo -e "  ✅ app/utils/projets -> projets/"
else
    echo -e "  ⏭️  app/utils/projets (existe déjà)"
fi

# Symlink containers à la racine -> app/utils/containers
if [ ! -L "$APP_DIR/containers" ]; then
    ln -s "app/utils/containers" "$APP_DIR/containers"
    echo -e "  ✅ containers -> app/utils/containers/"
else
    echo -e "  ⏭️  containers (existe déjà)"
fi

# 4. Environnement virtuel Python
echo ""
echo -e "${YELLOW}[4/6] Configuration de l'environnement Python...${NC}"

if [ ! -d "$APP_DIR/venv" ]; then
    echo "  Création du virtualenv..."
    python3 -m venv "$APP_DIR/venv"
fi

source "$APP_DIR/venv/bin/activate"
echo "  Installation des dépendances..."
pip install --upgrade pip -q
pip install -r "$APP_DIR/requirements.txt" -q
echo -e "  ✅ Dépendances installées"

# 5. Fichier .env
echo ""
echo -e "${YELLOW}[5/6] Configuration .env...${NC}"

if [ ! -f "$APP_DIR/.env" ]; then
    LOCAL_IP=$(hostname -I | awk '{print $1}')
    cat > "$APP_DIR/.env" <<EOF
APP_HOST=$LOCAL_IP
APP_PORT=5000
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
EOF
    echo -e "  ✅ .env créé (IP: $LOCAL_IP)"
else
    echo -e "  ⏭️  .env existe déjà"
fi

# 6. Service systemd
echo ""
echo -e "${YELLOW}[6/6] Service systemd...${NC}"

read -p "  Installer le service systemd wp-launcher ? (o/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Oo]$ ]]; then
    # Adapt service template to current install
    sed "s|__APP_DIR__|$APP_DIR|g; s|__APP_USER__|$CURRENT_USER|g" \
        "$APP_DIR/wp-launcher.service" | sudo tee /etc/systemd/system/wp-launcher.service > /dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable wp-launcher
    echo -e "  ✅ Service installé et activé"
    echo -e "  Démarrer avec : ${GREEN}sudo systemctl start wp-launcher${NC}"
else
    echo -e "  ⏭️  Service non installé"
fi

# Résumé
echo ""
echo "=========================================="
echo -e "${GREEN}  ✅ Installation terminée !${NC}"
echo "=========================================="
echo ""
echo "  Lancer l'app manuellement :"
echo -e "    ${GREEN}cd $APP_DIR && source venv/bin/activate && python3 run.py${NC}"
echo ""
echo "  Ou via le service :"
echo -e "    ${GREEN}sudo systemctl start wp-launcher${NC}"
echo ""
echo "  L'app sera accessible sur : http://$(hostname -I | awk '{print $1}'):5000"
echo ""
