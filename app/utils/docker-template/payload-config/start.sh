#!/bin/sh
# Démarrage de l'app Payload en dev (conteneur <projet>_payload_1).
#
# Tourne en root juste le temps de donner les volumes nommés (node_modules,
# .next, cache npm) à l'utilisateur de l'hôte, puis lui rend la main : tout ce
# que l'app écrit dans projets/<projet>/app (types générés, migrations,
# médias) lui appartient, comme s'il avait lancé `npm run dev` lui-même.
set -e
: "${HOST_UID:=1000}"
: "${HOST_GID:=1000}"
export HOME=/home/app
mkdir -p "$HOME" /app/node_modules /app/.next
chown "$HOST_UID:$HOST_GID" "$HOME" /app/node_modules /app/.next
cd /app
exec setpriv --reuid="$HOST_UID" --regid="$HOST_GID" --clear-groups \
    sh -c 'npm install --no-audit --no-fund && exec npm run dev'
