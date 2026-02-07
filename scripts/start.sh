#!/bin/bash

# Script de démarrage pour WP Launcher
# Vérifie les prérequis et lance l'application

# Définir le répertoire de travail
cd "$(dirname "$0")"

echo "🚀 WP Launcher - Démarrage..."
echo "=================================="
echo "📂 Répertoire de travail : $(pwd)"

# Vérification de Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 n'est pas installé"
    exit 1
fi

# Vérification de Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker n'est pas installé"
    exit 1
fi

# Vérification de Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose n'est pas installé"
    exit 1
fi

# Vérification du service Docker
if ! systemctl is-active --quiet docker; then
    echo "❌ Le service Docker n'est pas actif"
    exit 1
fi

# Vérification des dépendances Python
if [ ! -f "requirements.txt" ]; then
    echo "❌ Fichier requirements.txt manquant"
    exit 1
fi

echo "✅ Prérequis vérifiés"

# Vérification/création de l'environnement virtuel
if [ ! -d "venv" ]; then
    echo "🔧 Création de l'environnement virtuel..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "❌ Erreur lors de la création de l'environnement virtuel"
        exit 1
    fi
fi

# Activation de l'environnement virtuel
echo "🐍 Activation de l'environnement virtuel..."
source venv/bin/activate

if [ $? -ne 0 ]; then
    echo "❌ Erreur lors de l'activation de l'environnement virtuel"
    exit 1
fi

# Vérification que l'environnement virtuel est actif
if [ -z "$VIRTUAL_ENV" ]; then
    echo "❌ L'environnement virtuel n'est pas activé"
    exit 1
fi

echo "✅ Environnement virtuel activé : $VIRTUAL_ENV"

# Mise à jour de pip
echo "📦 Mise à jour de pip..."
pip install --upgrade pip

# Installation des dépendances
echo "📦 Installation des dépendances Python..."
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "❌ Erreur lors de l'installation des dépendances"
    echo "📄 Tentative de réinstallation complète..."
    pip install -r requirements.txt --force-reinstall
    if [ $? -ne 0 ]; then
        echo "❌ Erreur critique lors de l'installation des dépendances"
        exit 1
    fi
fi

# Vérifier que les modules critiques sont installés
echo "✅ Vérification des modules critiques..."
python3 -c "import flask, socketio, dotenv" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ Modules Python manquants, réinstallation forcée..."
    pip install -r requirements.txt --force-reinstall
    if [ $? -ne 0 ]; then
        echo "❌ Impossible d'installer les dépendances"
        exit 1
    fi
fi

# Création des dossiers nécessaires
echo "📁 Création des dossiers..."
mkdir -p uploads projets

# Permissions
chmod -R 755 projets uploads 2>/dev/null

# Vérification que le fichier run.py existe
if [ ! -f "run.py" ]; then
    echo "❌ Fichier run.py manquant"
    exit 1
fi

# Affichage des informations
echo ""
echo "🌐 L'application sera accessible sur :"
echo "   - Local : http://localhost:5000"
echo "   - Réseau : http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "📋 Projets WordPress créés seront accessibles sur le port 8080"
echo ""

# Démarrage de l'application
echo "🚀 Démarrage de l'application Flask..."

# S'assurer que les variables d'environnement sont correctes
export FLASK_APP=run.py
export FLASK_ENV=production
export PYTHONUNBUFFERED=1

# Démarrer l'application
exec python run.py