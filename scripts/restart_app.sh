#!/bin/bash

echo "🔄 Redémarrage de WordPress Launcher..."

# Arrêter les processus Python existants
echo "🛑 Arrêt des processus existants..."
pkill -f "python3.*run.py" || true
pkill -f "python.*run.py" || true

# Attendre que les processus se terminent
sleep 2

# Nettoyer les fichiers cache Python
echo "🧹 Nettoyage des fichiers cache..."
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Vérifier que le port 5000 est libre
echo "🔍 Vérification du port 5000..."
if lsof -i :5000 >/dev/null 2>&1; then
    echo "⚠️  Port 5000 encore occupé, forçage..."
    sudo fuser -k 5000/tcp 2>/dev/null || true
    sleep 1
fi

# Redémarrer l'application
echo "🚀 Redémarrage de l'application..."
cd /home/dev-server/Sites/wp-launcher

# Lancer l'application avec nohup et détacher complètement le processus
nohup python3 run.py >> /home/dev-server/Sites/wp-launcher/logs/app.log 2>&1 &

# Récupérer le PID
APP_PID=$!
echo "📝 PID de l'application: $APP_PID"

# Détacher complètement le processus
disown $APP_PID

# Attendre un peu pour que l'application démarre
sleep 3

# Vérifier si l'application a démarré
if pgrep -f "python3.*run.py" >/dev/null; then
    echo "✅ Application redémarrée avec succès!"
    echo "🌐 Accessible sur : http://192.168.1.21:5000"
    echo "📄 Logs disponibles dans: /home/dev-server/Sites/wp-launcher/logs/app.log"
else
    echo "❌ Erreur lors du redémarrage"
    echo "📄 Vérifiez les logs dans: /home/dev-server/Sites/wp-launcher/logs/app.log"
    exit 1
fi 