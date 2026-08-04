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

# Hook pre-commit anti-secrets — uniquement dans un clone git, pas dans une
# archive de release. core.hooksPath pointe sur un dossier versionné, donc le
# hook suit le dépôt au lieu de vivre dans .git/hooks/ non versionné.
if [ -d "$APP_DIR/.git" ] && [ -x "$APP_DIR/.githooks/pre-commit" ]; then
    git -C "$APP_DIR" config core.hooksPath .githooks
    echo -e "  ✅ Hook pre-commit activé (blocage des secrets avant commit)"
fi

# Helpers exécutés en root via sudo.
#
# Déployés HORS du dépôt et en root:root, délibérément : le dépôt appartient à
# l'utilisateur applicatif, qui peut donc y écrire. Y laisser un script que
# sudo l'autorise à lancer en root reviendrait à lui donner root — on n'aurait
# fait que déplacer le problème.
WPL_ROOT_DIR="/opt/wp-launcher-root"
if [ -d "$APP_DIR/scripts/root" ]; then
    echo ""
    echo -e "${YELLOW}Installation des helpers racine dans $WPL_ROOT_DIR...${NC}"
    sudo install -d -o root -g root -m 0755 "$WPL_ROOT_DIR"
    sudo install -o root -g root -m 0755 "$APP_DIR"/scripts/root/wpl-*.sh "$WPL_ROOT_DIR/"
    echo -e "  ✅ $(ls "$APP_DIR"/scripts/root/wpl-*.sh | wc -l) scripts installés en root:root"
    echo -e "     ${YELLOW}Les règles sudo correspondantes sont dans"
    echo -e "     scripts/root/sudoers.wp-launcher — à installer une fois que"
    echo -e "     l'application les utilise réellement.${NC}"
fi

# 5. Fichier .env
echo ""
echo -e "${YELLOW}[5/6] Configuration .env...${NC}"

if [ ! -f "$APP_DIR/.env" ]; then
    LOCAL_IP=$(hostname -I | awk '{print $1}')

    # Machine locale ou VPS ? Détermine si l'app et les sites écoutent sur
    # toutes les interfaces ou seulement sur la loopback.
    echo ""
    echo "  Ce serveur est-il accessible depuis Internet (VPS, IP publique) ?"
    # `|| REPLY=""` : sous `set -e`, un read sans tty (curl | bash, CI)
    # renvoie 1 et avorterait l'installation sans écrire de .env.
    REPLY=""
    read -p "  Répondre o installe des défauts durcis (écoute en loopback). (o/N) " -n 1 -r || REPLY=""
    echo ""
    if [ ! -t 0 ]; then
        # Pas d'interaction possible : on choisit le défaut sûr.
        echo "  (pas de terminal — mode durci par défaut)"
        LOCAL_MODE=false
    elif [[ $REPLY =~ ^[Oo]$ ]]; then
        LOCAL_MODE=false
    else
        LOCAL_MODE=true
    fi

    WP_ADMIN_PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(18))")

    cat > "$APP_DIR/.env" <<EOF
APP_HOST=$LOCAL_IP
APP_PORT=5000
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# false = tout écoute en loopback, cookie de session en HTTPS uniquement.
# À laisser à false dès que la machine est joignable depuis Internet.
WPL_LOCAL_MODE=$LOCAL_MODE

# Compte admin WordPress créé pour les nouveaux projets. Valeur globale,
# partagée par tous les projets et transmise à l'autologin dans l'URL :
# à ne jamais réutiliser ailleurs.
WP_ADMIN_USER=admin
WP_ADMIN_PASSWORD=$WP_ADMIN_PW
WP_ADMIN_EMAIL=admin@example.com
EOF
    chmod 600 "$APP_DIR/.env"

    if [ "$LOCAL_MODE" = "false" ]; then
        echo -e "  ✅ .env créé en mode durci (IP: $LOCAL_IP)"
        echo -e "     ${YELLOW}L'app n'écoutera que sur 127.0.0.1.${NC}"
        echo -e "     Placez un reverse proxy HTTPS devant, et n'ouvrez au"
        echo -e "     pare-feu que 22 et 443. Voir la section Deployment du README."
    else
        echo -e "  ✅ .env créé en mode local (IP: $LOCAL_IP)"
    fi
    echo -e "     Admin WordPress des nouveaux projets : ${YELLOW}admin${NC} / ${YELLOW}${WP_ADMIN_PW}${NC}"
    echo -e "     (également stocké dans .env — modifiable avant le 1er projet)"
else
    echo -e "  ⏭️  .env existe déjà"
fi

# 6. Service systemd
echo ""
echo -e "${YELLOW}[6/6] Service systemd...${NC}"

REPLY=""
read -p "  Installer le service systemd wp-launcher ? (o/N) " -n 1 -r || REPLY=""
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
