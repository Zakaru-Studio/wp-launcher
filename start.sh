#!/bin/bash

# Script de démarrage pour WP Launcher
# Vérifie les prérequis et lance l'application

echo "🚀 WP Launcher - Démarrage..."
echo "=================================="

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
fi

# Activation de l'environnement virtuel
echo "🐍 Activation de l'environnement virtuel..."
source venv/bin/activate

# Installation des dépendances si nécessaire
echo "📦 Vérification des dépendances Python..."
pip install -r requirements.txt --quiet

# Création des dossiers nécessaires
echo "📁 Création des dossiers..."
mkdir -p uploads projets

# Permissions
chmod -R 755 projets uploads

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
python app.py 