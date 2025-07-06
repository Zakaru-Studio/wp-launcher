#!/bin/bash

# Script de démarrage avec debug pour WP Launcher
echo "🐛 WP Launcher - Mode Debug"
echo "=========================="

# Activer l'environnement virtuel
source venv/bin/activate

# Variables d'environnement pour debug
export FLASK_DEBUG=1
export FLASK_ENV=development

# Démarrage avec logs
echo "🚀 Démarrage de l'application en mode debug..."
echo "📋 Tous les logs seront affichés en temps réel"
echo ""

# Démarrer l'application
python app.py 