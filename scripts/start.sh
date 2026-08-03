#!/bin/bash
#
# Point d'entrée du service WP Launcher (voir wp-launcher.service).
#
# Ce script démarre l'application, il n'installe rien. Toute la mise en place
# — venv, dépendances, dossiers, permissions — appartient à install.sh.
#
# Pourquoi cette séparation est importante : l'unité systemd est
# `Restart=always` avec `StartLimitIntervalSec=0`. Une étape d'installation
# ici s'exécuterait à chaque démarrage, et le moindre échec (DNS absent au
# boot, PyPI injoignable) partirait en boucle de redémarrage. Un
# `chmod -R` sur l'arborescence des projets y réinitialisait en prime le
# masque ACL à r-x, ce qui retire à www-data le droit d'écrire wp-config.php.

set -u

cd "$(dirname "$0")/.." || exit 1

APP_ROOT="$(pwd)"
VENV_PY="$APP_ROOT/venv/bin/python3"
VENV_GUNICORN="$APP_ROOT/venv/bin/gunicorn"

echo "🚀 WP Launcher — démarrage"
echo "📂 Répertoire de travail : $APP_ROOT"

# ─── Vérifications ────────────────────────────────────────────────────────
# Bloquantes uniquement si l'app ne peut objectivement pas tourner. Docker
# est volontairement non bloquant : au boot, docker.service peut démarrer
# après nous, et échouer ici enverrait le service en boucle.

if [ ! -x "$VENV_PY" ]; then
    echo "❌ Environnement virtuel absent ou incomplet ($VENV_PY)"
    echo "   Lancez ./install.sh d'abord."
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "⚠️  Docker introuvable dans le PATH — l'app démarre, mais la"
    echo "    gestion des projets échouera tant qu'il n'est pas disponible."
fi

# ─── Environnement ────────────────────────────────────────────────────────
# .env n'est chargé que par python-dotenv côté application : on lit donc
# nous-mêmes les quelques clés nécessaires ici. Lecture ciblée plutôt que
# `source .env`, pour ne pas exécuter le contenu du fichier.
env_value() {
    [ -f .env ] || return 0
    grep -E "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" .env | tail -1 |
        cut -d= -f2- |
        sed -e 's/[[:space:]]\+#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
            -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

: "${APP_PORT:=$(env_value APP_PORT)}"
: "${APP_PORT:=5000}"
: "${WPL_BIND:=$(env_value WPL_BIND)}"
: "${WPL_LOCAL_MODE:=$(env_value WPL_LOCAL_MODE)}"

# Adresse d'écoute : loopback par défaut, l'exposition passe par un reverse
# proxy qui termine le TLS. Les valeurs acceptées pour le mode local suivent
# celles de app/utils/security_config.py:_env_flag — sans quoi WPL_LOCAL_MODE=1
# ferait écouter les sites sur 0.0.0.0 pendant que l'app reste en loopback.
if [ -n "$WPL_BIND" ]; then
    BIND_ADDR="$WPL_BIND"
else
    case "${WPL_LOCAL_MODE,,}" in
        1|true|yes|on) BIND_ADDR="0.0.0.0" ;;
        *)             BIND_ADDR="127.0.0.1" ;;
    esac
fi

export FLASK_APP=run.py
export FLASK_ENV=production
export PYTHONUNBUFFERED=1

echo ""
echo "🌐 Écoute sur http://${BIND_ADDR}:${APP_PORT}"
if [ "$BIND_ADDR" = "127.0.0.1" ]; then
    echo "   (loopback — placez un reverse proxy HTTPS devant, ou définissez"
    echo "    WPL_LOCAL_MODE=true pour écouter sur toutes les interfaces)"
fi
echo ""

# ─── Démarrage ────────────────────────────────────────────────────────────
# Toujours UN SEUL worker : les rooms Socket.IO et le compteur d'échecs de
# login vivent en mémoire du processus et ne sont pas partagés entre workers.
if [ -x "$VENV_GUNICORN" ]; then
    if "$VENV_PY" -c "import eventlet" 2>/dev/null; then
        # eventlet dispo : Socket.IO l'utilise et gère le WebSocket nativement
        WORKER_ARGS=(--worker-class eventlet --workers 1)
        echo "🚀 gunicorn (worker eventlet)"
    else
        # Repli threads. Socket.IO tourne alors en async_mode 'threading' ;
        # le WebSocket reste disponible grâce à simple-websocket.
        WORKER_ARGS=(--worker-class gthread --workers 1 --threads 16)
        echo "🚀 gunicorn (worker gthread)"
    fi

    exec "$VENV_GUNICORN" "${WORKER_ARGS[@]}" \
        --bind "${BIND_ADDR}:${APP_PORT}" \
        --timeout 300 \
        --graceful-timeout 30 \
        --access-logfile - \
        --error-logfile - \
        run:app
else
    # Repli : serveur de développement Werkzeug. Acceptable en local
    # uniquement — il n'est pas prévu pour encaisser du trafic hostile.
    echo "⚠️  gunicorn absent du venv — repli sur le serveur de développement."
    echo "    Relancez ./install.sh avant toute exposition réseau."
    exec "$VENV_PY" run.py
fi
