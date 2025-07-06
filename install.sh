#!/bin/bash

# Script d'installation automatique pour WP Launcher
echo "🛠️  Installation automatique de WP Launcher"
echo "============================================="

# Mise à jour des paquets
echo "📦 Mise à jour des paquets système..."
sudo apt update

# Installation des prérequis
echo "🔧 Installation des prérequis..."

# Python et pip
if ! command -v python3 &> /dev/null; then
    echo "  • Installation de Python 3..."
    sudo apt install python3 python3-pip -y
fi

# Python venv
if ! python3 -m venv --help &> /dev/null; then
    echo "  • Installation de python3-venv..."
    sudo apt install python3.12-venv -y
fi

# Docker
if ! command -v docker &> /dev/null; then
    echo "  • Installation de Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "  ⚠️  Vous devez redémarrer votre session pour utiliser Docker"
fi

# Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "  • Installation de Docker Compose..."
    sudo apt install docker-compose -y
fi

# Vérification du service Docker
echo "🔧 Vérification du service Docker..."
if ! systemctl is-active --quiet docker; then
    echo "  • Démarrage du service Docker..."
    sudo systemctl start docker
    sudo systemctl enable docker
fi

# Création de l'environnement virtuel
echo "🐍 Création de l'environnement virtuel..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activation et installation des dépendances
echo "📚 Installation des dépendances Python..."
source venv/bin/activate
pip install -r requirements.txt

# Création des dossiers
echo "📁 Création des dossiers..."
mkdir -p uploads projets
chmod -R 755 projets uploads

# Permissions sur les scripts
echo "🔐 Configuration des permissions..."
chmod +x start.sh test_install.sh install.sh

echo ""
echo "✅ Installation terminée avec succès !"
echo ""
echo "🧪 Pour tester l'installation :"
echo "   ./test_install.sh"
echo ""
echo "🚀 Pour démarrer l'application :"
echo "   ./start.sh"
echo ""
echo "🌐 L'application sera accessible sur :"
echo "   - Local : http://localhost:5000"
echo "   - Réseau : http://$(hostname -I | awk '{print $1}'):5000"
echo ""

# Test final
echo "🧪 Test final de l'installation..."
./test_install.sh 