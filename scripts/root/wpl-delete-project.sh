#!/bin/bash
# Supprime les dossiers d'un projet.  wpl-delete-project.sh <projet>
#
# Reprend delete_project_folders.sh, dont la validation était déjà correcte,
# mais qui vivait dans le dépôt — donc modifiable par l'application à qui
# sudo accordait le droit de le lancer en root.
set -euo pipefail
. "$(dirname "$0")/wpl-common.sh"

[ $# -eq 1 ] || die "usage: $0 <projet>"
valid_name "$1" "nom de projet"
PROJECT="$1"

for root in "$PROJECTS_DIR" "$CONTAINERS_DIR"; do
    target="$root/$PROJECT"
    [ -d "$target" ] || { echo "${0##*/}: absent, ignoré: $target"; continue; }
    resolved="$(resolve_under "$target" "$root")"
    echo "${0##*/}: suppression de $resolved"
    rm -rf -- "$resolved"
done
