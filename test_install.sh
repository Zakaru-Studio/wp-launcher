#!/bin/bash

# Script de test pour WP Launcher
echo "🧪 Test d'installation de WP Launcher"
echo "====================================="

# Test Python
echo -n "🐍 Python 3 : "
if command -v python3 &> /dev/null; then
    echo "✅ $(python3 --version)"
else
    echo "❌ Non installé"
    exit 1
fi

# Test pip
echo -n "📦 pip3 : "
if command -v pip3 &> /dev/null; then
    echo "✅ Disponible"
else
    echo "❌ Non installé"
    exit 1
fi

# Test Docker
echo -n "🐳 Docker : "
if command -v docker &> /dev/null; then
    echo "✅ $(docker --version)"
else
    echo "❌ Non installé"
    exit 1
fi

# Test Docker Compose
echo -n "🐙 Docker Compose : "
if command -v docker-compose &> /dev/null; then
    echo "✅ $(docker-compose --version)"
else
    echo "❌ Non installé"
    exit 1
fi

# Test service Docker
echo -n "🔧 Service Docker : "
if systemctl is-active --quiet docker; then
    echo "✅ Actif"
else
    echo "⚠️  Arrêté - Démarrage..."
    sudo systemctl start docker
    if systemctl is-active --quiet docker; then
        echo "✅ Démarré"
    else
        echo "❌ Impossible de démarrer"
        exit 1
    fi
fi

# Test des permissions Docker
echo -n "🔐 Permissions Docker : "
if docker ps &> /dev/null; then
    echo "✅ OK"
else
    echo "⚠️  Problème de permissions"
    echo "   Vous devez ajouter votre utilisateur au groupe docker :"
    echo "   sudo usermod -aG docker $USER"
    echo "   Puis redémarrer votre session"
fi

# Test structure des fichiers
echo -n "📁 Structure des fichiers : "
if [[ -f "app.py" && -f "requirements.txt" && -f "templates/index.html" ]]; then
    echo "✅ OK"
else
    echo "❌ Fichiers manquants"
    exit 1
fi

# Test environnement virtuel
echo -n "🐍 Environnement virtuel : "
if [ ! -d "venv" ]; then
    echo "⚠️  Création de l'environnement virtuel..."
    python3 -m venv venv
fi

if [ -d "venv" ]; then
    echo "✅ OK"
else
    echo "❌ Impossible de créer l'environnement virtuel"
    exit 1
fi

# Test installation des dépendances
echo -n "📚 Dépendances Python : "
source venv/bin/activate
if pip install -r requirements.txt --quiet --dry-run &> /dev/null; then
    echo "✅ OK"
else
    echo "❌ Erreur d'installation"
    exit 1
fi

# Test port 5000
echo -n "🌐 Port 5000 : "
if ss -tuln | grep :5000 &> /dev/null; then
    echo "⚠️  Occupé - L'application est peut-être déjà en cours d'exécution"
else
    echo "✅ Disponible"
fi

# Test réseau
echo -n "🔗 Adresse IP : "
IP=$(hostname -I | awk '{print $1}')
if [[ -n "$IP" ]]; then
    echo "✅ $IP"
else
    echo "⚠️  Impossible de déterminer l'IP"
fi

echo ""
echo "✅ Test terminé avec succès !"
echo ""
echo "🚀 Pour démarrer l'application :"
echo "   ./start.sh"
echo ""
echo "🌐 L'application sera accessible sur :"
echo "   - Local : http://localhost:5000"
echo "   - Réseau : http://$IP:5000" 