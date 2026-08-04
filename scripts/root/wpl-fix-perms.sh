#!/bin/bash
#
# Applique un profil de permissions à un projet. Lancé en root via sudo.
#
#     wpl-fix-perms.sh <projet> <profil> [sous-chemin]
#
# Ce script existe pour retirer `NOPASSWD: ALL` à l'utilisateur applicatif.
# L'app faisait 71 appels `sudo chown/chmod/find/setfacl/chgrp` sur des chemins
# qu'elle composait elle-même ; chacun était une porte ouverte si une injection
# de commande atteignait l'un d'eux. Ils se ramènent tous aux quelques profils
# ci-dessous, sur un chemin qui ne peut pas sortir de l'arborescence du projet.
#
# Règles de sûreté, dans l'ordre où elles s'appliquent :
#   1. le nom de projet est validé sur une liste de caractères stricte ;
#   2. le sous-chemin optionnel est validé et ne peut contenir « .. » ;
#   3. le chemin final est résolu puis vérifié comme étant SOUS la racine des
#      projets — un lien symbolique pointant ailleurs est donc rejeté ;
#   4. le profil est choisi dans une liste fermée, jamais construit.
#
# Ce fichier doit appartenir à root et ne pas être modifiable par l'utilisateur
# applicatif, sinon il suffirait de le réécrire pour obtenir un shell root.

set -euo pipefail
. "$(dirname "$0")/wpl-common.sh"

[ $# -ge 2 ] || die "usage: $0 <projet> <profil> [sous-chemin] [--containers]"

# --containers cible l'arborescence Docker du projet plutôt que ses fichiers
# éditables. Deux racines distinctes, jamais concaténées : le drapeau choisit
# l'une des deux valeurs connues, il ne construit pas de chemin.
ROOT_DIR="$PROJECTS_DIR"
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --containers) ROOT_DIR="$CONTAINERS_DIR" ;;
        *) ARGS+=("$arg") ;;
    esac
done
set -- "${ARGS[@]}"

[ $# -ge 2 ] || die "usage: $0 <projet> <profil> [sous-chemin] [--containers]"

PROJECT="$1"
PROFILE="$2"
SUBPATH="${3:-}"

valid_name "$PROJECT" "nom de projet"
if [ -n "$SUBPATH" ]; then
    valid_subpath "$SUBPATH"
    TARGET="$ROOT_DIR/$PROJECT/$SUBPATH"
else
    TARGET="$ROOT_DIR/$PROJECT"
fi

# Le chemin résolu doit rester sous la racine choisie : un wp-content remplacé
# par un lien vers /etc est écarté ici, avant le chown.
RESOLVED="$(resolve_under "$TARGET" "$ROOT_DIR")"

# ─── 4. profils ───────────────────────────────────────────────────────────
# Modes symboliques et `chmod -R` plutôt que `find -type f -exec chmod` :
#
#   — sûreté. `chmod` suit les liens symboliques qu'on lui passe, et toute
#     l'arborescence traitée ici est inscriptible par l'application. Entre le
#     moment où find décide qu'un chemin est un dossier et celui où chmod
#     s'exécute, ce chemin peut être devenu un lien vers un binaire de root :
#     un `chmod g+s` dessus donnait un exécutable setgid root. `chmod -R`,
#     lui, ignore les liens rencontrés pendant la descente (vérifié).
#   — vitesse. C'est aussi un seul processus au lieu d'un par lot, là où un
#     fork par fichier sur des uploads volumineux prenait des heures et
#     bloquait le démarrage d'Apache.
#
# `X` (majuscule) donne le bit d'exécution aux dossiers seulement — et aux
# fichiers qui l'avaient déjà, ce qui préserve les scripts livrés par un
# thème ou un plugin, là où un 664 en dur les cassait.
apply() {
    local owner="$1" mode="$2" setgid="${3:-}"
    chown -R "$owner" "$RESOLVED"
    chmod -R "$mode" "$RESOLVED"
    # setgid : les fichiers créés ensuite héritent du groupe du répertoire
    # plutôt que du groupe primaire de qui les crée. Sans ça, un fichier
    # déposé par le conteneur sort du groupe partagé et redevient
    # inaccessible en écriture depuis l'hôte. Le bit atterrit aussi sur les
    # fichiers, ce que la passe `find` évitait ; c'est le prix de la sûreté
    # ci-dessus, et il est modeste — un setgid dont le groupe est www-data ou
    # le développeur ne donne rien de plus que ce que l'appelant a déjà.
    if [ -n "$setgid" ]; then
        chmod -R g+s "$RESOLVED"
    fi
}

case "$PROFILE" in
    # Le développeur possède, www-data écrit via le groupe. Profil courant.
    shared)      apply "$DEV_USER:$WWW_USER" u=rwX,g=rwX,o=rX setgid ;;
    # Tout à www-data : le conteneur écrit, l'hôte lit.
    www)         apply "$WWW_USER:$WWW_USER" u=rwX,g=rwX,o=rX setgid ;;
    # Tout au développeur : édition depuis l'hôte.
    dev)         apply "$DEV_USER:$DEV_USER" u=rwX,g=rX,o=rX ;;
    # wp-content côté conteneur, plus restrictif.
    container)   apply "$WWW_USER:$WWW_USER" u=rwX,g=rX,o=rX ;;
    # Uploads : www-data doit pouvoir créer des fichiers.
    uploads)     apply "$DEV_USER:$WWW_USER" u=rwX,g=rwX,o=rX setgid ;;

    # wp-config.php seul : lisible par le conteneur uniquement.
    wp-config-lock)
        [ -f "$RESOLVED" ] || die "wp-config-lock attend un fichier"
        chown "$WWW_USER:$WWW_USER" "$RESOLVED"
        chmod 600 "$RESOLVED"
        ;;
    # wp-config.php seul : éditable depuis l'hôte.
    wp-config-dev)
        [ -f "$RESOLVED" ] || die "wp-config-dev attend un fichier"
        chown "$DEV_USER:$WWW_USER" "$RESOLVED"
        chmod 664 "$RESOLVED"
        ;;

    # ACL pour que www-data conserve l'écriture sur les fichiers créés
    # ensuite. Le masque est réaffirmé : un chmod le rabat sinon à r-x et
    # retire silencieusement le droit d'écriture (bug récurrent).
    acl)
        command -v setfacl >/dev/null || die "setfacl absent"
        setfacl -R -m "u:$DEV_USER:rwx" -m "g:$WWW_USER:rwx" -m "m::rwX" "$RESOLVED"
        setfacl -R -d -m "u:$DEV_USER:rwx" -m "g:$WWW_USER:rwx" -m "m::rwX" "$RESOLVED"
        ;;

    *) die "profil inconnu: $PROFILE" ;;
esac

echo "wpl-fix-perms: $PROFILE appliqué à $RESOLVED"
