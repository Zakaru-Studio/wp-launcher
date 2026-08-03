#!/bin/bash
# Point d'entrée du service systemd (voir wp-launcher.service).
#
# Délègue à scripts/start.sh, qui lance gunicorn sur l'adresse d'écoute
# résolue depuis .env. Lancer run.py directement ici démarrerait le serveur
# de développement Werkzeug, à ne pas exposer.
cd "$(dirname "$0")"
exec ./scripts/start.sh
