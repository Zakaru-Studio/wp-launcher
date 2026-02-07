#!/bin/bash

echo "🛑 Arrêt de WordPress Launcher..."

# Arrêter les processus Python existants
echo "🔄 Arrêt des processus..."
pkill -f "python3.*run.py" || true
pkill -f "python.*run.py" || true

# Attendre que les processus se terminent
sleep 2

# Forcer l'arrêt si nécessaire
if lsof -i :5000 >/dev/null 2>&1; then
    echo "⚠️  Processus encore actifs, forçage..."
    sudo fuser -k 5000/tcp 2>/dev/null || true
    sleep 1
fi

# Vérifier si l'application est arrêtée
if ! pgrep -f "python3.*run.py" >/dev/null; then
    echo "✅ Application arrêtée avec succès!"
else
    echo "❌ Erreur lors de l'arrêt"
    exit 1
fi 