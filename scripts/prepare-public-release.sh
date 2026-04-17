#!/usr/bin/env bash
#
# WP Launcher — prepare the repository for public GitHub release
#
# This script:
#   1. Removes premium/commercial WordPress plugins from `app/utils/docker-template/`
#      (they cannot be redistributed publicly)
#   2. Suggests a follow-up `git filter-repo` command to rewrite history
#
# It does NOT rewrite git history by itself — you should review the diff,
# commit the removal, then decide whether to also rewrite history.
#
# Usage:
#   ./scripts/prepare-public-release.sh            # dry-run
#   ./scripts/prepare-public-release.sh --apply    # actually delete
#

set -euo pipefail

PLUGIN_DIR="app/utils/docker-template/wordpress/wp-content/plugins"

# Plugins that are COMMERCIAL / cannot be redistributed publicly.
# Add more here if you identify others in your repo.
PREMIUM_PLUGINS=(
  "advanced-custom-fields-pro"
  "wp-migrate-db-pro"
)

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [[ ! -d "$PLUGIN_DIR" ]]; then
  echo -e "${YELLOW}No plugin directory at $PLUGIN_DIR — nothing to do.${NC}"
  exit 0
fi

echo "Scanning $PLUGIN_DIR for premium plugins..."
echo ""

to_remove=()
for plugin in "${PREMIUM_PLUGINS[@]}"; do
  path="$PLUGIN_DIR/$plugin"
  if [[ -e "$path" ]]; then
    size=$(du -sh "$path" 2>/dev/null | awk '{print $1}')
    echo -e "  ${RED}✗${NC} $plugin (${size}) — premium, cannot redistribute"
    to_remove+=("$path")
  else
    echo -e "  ${GREEN}✓${NC} $plugin — absent"
  fi
done

if [[ ${#to_remove[@]} -eq 0 ]]; then
  echo ""
  echo -e "${GREEN}Nothing to remove. The repo is clean of known premium plugins.${NC}"
  exit 0
fi

echo ""
if [[ $APPLY -eq 0 ]]; then
  echo -e "${YELLOW}Dry-run — nothing deleted.${NC}"
  echo "Re-run with ${GREEN}--apply${NC} to remove the plugins:"
  echo ""
  echo "  ./scripts/prepare-public-release.sh --apply"
  echo ""
  echo "Then commit:"
  echo ""
  echo "  git add -A \"$PLUGIN_DIR\""
  echo "  git commit -m 'chore: remove premium WordPress plugins (cannot redistribute)'"
  exit 0
fi

for path in "${to_remove[@]}"; do
  echo -e "Deleting ${RED}$path${NC}..."
  rm -rf "$path"
done

echo ""
echo -e "${GREEN}Done. ${#to_remove[@]} plugin(s) removed from the working tree.${NC}"
echo ""
echo "Next steps:"
echo ""
echo "  1. Commit the removal:"
echo "       git add -A \"$PLUGIN_DIR\""
echo "       git commit -m 'chore: remove premium WordPress plugins (cannot redistribute)'"
echo ""
echo -e "  2. ${YELLOW}(Strongly recommended)${NC} Rewrite git history so the plugins aren't"
echo "     recoverable from old commits. Use git-filter-repo:"
echo ""
echo "       pip install git-filter-repo"
for plugin in "${PREMIUM_PLUGINS[@]}"; do
  echo "       git filter-repo --path \"$PLUGIN_DIR/$plugin\" --invert-paths --force"
done
echo ""
echo -e "     ${RED}Warning:${NC} filter-repo rewrites every commit SHA. Coordinate with"
echo "     collaborators and force-push to origin once everyone is ready."
echo ""
echo "  3. Run gitleaks to double-check no secrets remain in history:"
echo ""
echo "       gitleaks detect --source . --no-banner --verbose"
