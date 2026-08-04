#!/bin/bash
# Supprime une instance de dev.  wpl-delete-instance.sh <projet-parent> <slug>
set -euo pipefail
. "$(dirname "$0")/wpl-common.sh"

[ $# -eq 2 ] || die "usage: $0 <projet-parent> <slug>"
valid_name "$1" "projet parent"
valid_name "$2" "slug d'instance"

TARGET="$PROJECTS_DIR/$1/.dev-instances/$2"
[ -d "$TARGET" ] || { echo "${0##*/}: absent, rien à faire: $TARGET"; exit 0; }
RESOLVED="$(resolve_under "$TARGET" "$PROJECTS_DIR/$1/.dev-instances")"
echo "${0##*/}: suppression de $RESOLVED"
rm -rf -- "$RESOLVED"
