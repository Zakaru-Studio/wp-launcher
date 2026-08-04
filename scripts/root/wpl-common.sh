# Validations partagées par les helpers racine de WP Launcher.
# Fichier SOURCÉ, jamais exécuté — il ne figure donc pas dans sudoers.
#
# Tout ce qui suit part du principe que les arguments viennent d'un processus
# potentiellement compromis : l'intérêt de ces scripts est justement de rester
# sûrs même si l'application ne l'est plus.

BASE_DIR="${WPL_BASE_DIR:-/home/dev-server/Sites/wp-launcher}"
PROJECTS_DIR="$BASE_DIR/projets"
CONTAINERS_DIR="$BASE_DIR/containers"
DEV_USER="${WPL_DEV_USER:-dev-server}"
WWW_USER="www-data"

die() { echo "${0##*/}: $*" >&2; exit 1; }

# Nom de projet : jeu de caractères strict, première lettre alphanumérique.
# Le refus de commencer par un point écarte d'emblée « . » et « .. ».
valid_name() {
    local name="$1" label="${2:-nom}"
    [[ "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$ ]] || die "$label invalide: $name"
    [[ "$name" == *".."* ]] && die "$label invalide: $name"
    return 0
}

# Sous-chemin relatif : autorise les séparateurs, interdit la remontée.
valid_subpath() {
    local sub="$1"
    [[ "$sub" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,199}$ ]] || die "sous-chemin invalide: $sub"
    [[ "$sub" == *".."* ]] && die "sous-chemin invalide: $sub"
    return 0
}

# Résout le chemin et vérifie qu'il reste SOUS la racine attendue.
#
# C'est la garde qui compte : sans elle, un répertoire remplacé par un lien
# symbolique ferait appliquer l'opération ailleurs sur le système. realpath
# suit les liens, donc la comparaison porte sur la cible réelle.
#
# Affiche le chemin résolu sur stdout.
resolve_under() {
    local target="$1" root="$2"
    [ -e "$target" ] || die "chemin inexistant: $target"
    local resolved root_resolved
    resolved="$(realpath -- "$target")" || die "résolution impossible: $target"
    root_resolved="$(realpath -- "$root")" || die "racine introuvable: $root"
    case "$resolved" in
        "$root_resolved"/*) printf '%s\n' "$resolved" ;;
        *) die "chemin hors de $root_resolved: $resolved" ;;
    esac
}
