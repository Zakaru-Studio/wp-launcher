#!/bin/bash

echo "📋 Script de surveillance des logs d'import de base de données"
echo "============================================================"
echo ""
echo "Ce script affiche les logs en temps réel pendant la création de projet avec import SQL."
echo "Appuyez sur Ctrl+C pour arrêter."
echo ""
echo "🔍 Recherche des logs contenant :"
echo "  - [STARTUP] : Démarrage et vérification des conteneurs"
echo "  - [ARCHIVE] : Extraction des archives ZIP"
echo "  - [DATABASE] : Processus d'import de base de données"
echo "  - [IMPORT_ROBUST] : Import robuste avec mysql"
echo ""
echo "============================================================"
echo ""

# Fonction pour afficher les logs avec couleurs
watch_logs() {
    while true; do
        # Lire les dernières lignes du processus Python
        ps aux | grep "python app.py" | grep -v grep | head -1 | awk '{print $2}' | while read pid; do
            if [ -n "$pid" ]; then
                # Suivre les logs en utilisant journalctl si disponible, sinon dmesg
                timeout 1 journalctl -f --since "1 minute ago" 2>/dev/null | grep -E "\[(STARTUP|ARCHIVE|DATABASE|IMPORT_ROBUST)\]" --line-buffered || \
                timeout 1 dmesg -T | tail -20 | grep -E "\[(STARTUP|ARCHIVE|DATABASE|IMPORT_ROBUST)\]" || \
                echo "⏳ En attente de logs... (PID: $pid)"
            fi
        done
        sleep 2
    done
}

# Fonction alternative utilisant tail sur un fichier de log si il existe
watch_file_logs() {
    if [ -f "app.log" ]; then
        echo "📄 Surveillance du fichier app.log"
        tail -f app.log | grep -E "\[(STARTUP|ARCHIVE|DATABASE|IMPORT_ROBUST)\]" --line-buffered
    elif [ -f "/var/log/syslog" ]; then
        echo "📄 Surveillance de /var/log/syslog"
        tail -f /var/log/syslog | grep -E "\[(STARTUP|ARCHIVE|DATABASE|IMPORT_ROBUST)\]" --line-buffered
    else
        echo "⚠️ Aucun fichier de log trouvé, surveillance des processus..."
        watch_logs
    fi
}

# Fonction pour afficher les logs avec couleurs
colorize_logs() {
    while read line; do
        echo "$line" | sed \
            -e 's/\[STARTUP\]/\x1b[34m[STARTUP]\x1b[0m/g' \
            -e 's/\[ARCHIVE\]/\x1b[35m[ARCHIVE]\x1b[0m/g' \
            -e 's/\[DATABASE\]/\x1b[36m[DATABASE]\x1b[0m/g' \
            -e 's/\[IMPORT_ROBUST\]/\x1b[32m[IMPORT_ROBUST]\x1b[0m/g' \
            -e 's/✅/\x1b[32m✅\x1b[0m/g' \
            -e 's/❌/\x1b[31m❌\x1b[0m/g' \
            -e 's/⚠️/\x1b[33m⚠️\x1b[0m/g' \
            -e 's/🔧/\x1b[36m🔧\x1b[0m/g' \
            -e 's/🚀/\x1b[35m🚀\x1b[0m/g'
    done
}

# Démarrer la surveillance
echo "🎯 Création d'un projet maintenant pour voir les logs..."
echo ""

# Essayer différentes méthodes de surveillance
if command -v journalctl >/dev/null 2>&1; then
    echo "📊 Utilisation de journalctl pour les logs système"
    journalctl -f --since "now" | grep -E "\[(STARTUP|ARCHIVE|DATABASE|IMPORT_ROBUST)\]" --line-buffered | colorize_logs
elif [ -f "/var/log/syslog" ]; then
    echo "📊 Utilisation de /var/log/syslog"
    tail -f /var/log/syslog | grep -E "\[(STARTUP|ARCHIVE|DATABASE|IMPORT_ROBUST)\]" --line-buffered | colorize_logs
else
    echo "📊 Surveillance des processus Python"
    # Surveillance basique des processus
    while true; do
        pgrep -f "python app.py" >/dev/null 2>&1
        if [ $? -eq 0 ]; then
            echo "✅ Serveur Python actif - En attente de logs..."
            sleep 5
        else
            echo "❌ Serveur Python non trouvé"
            sleep 2
        fi
    done
fi 