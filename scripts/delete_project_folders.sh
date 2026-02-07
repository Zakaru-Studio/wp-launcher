#!/bin/bash
# Script de suppression sécurisée pour les projets WordPress Launcher
# Usage: sudo ./delete_project_folders.sh <project_name>

set -e

if [ "$EUID" -ne 0 ]; then 
    echo "❌ Ce script doit être exécuté avec sudo"
    exit 1
fi

if [ -z "$1" ]; then
    echo "❌ Usage: $0 <project_name>"
    exit 1
fi

PROJECT_NAME="$1"
BASE_DIR="/home/dev-server/Sites/wp-launcher"
PROJECTS_DIR="$BASE_DIR/projets/$PROJECT_NAME"
CONTAINERS_DIR="$BASE_DIR/containers/$PROJECT_NAME"

# Validation du nom de projet (sécurité)
if [[ ! "$PROJECT_NAME" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "❌ Nom de projet invalide (caractères alphanumériques, - et _ uniquement)"
    exit 1
fi

# Vérifier que les chemins sont bien dans le répertoire wp-launcher
if [[ ! "$PROJECTS_DIR" =~ ^$BASE_DIR/projets/ ]] || [[ ! "$CONTAINERS_DIR" =~ ^$BASE_DIR/containers/ ]]; then
    echo "❌ Chemins de suppression invalides (protection contre path traversal)"
    exit 1
fi

echo "🗑️  Suppression sécurisée du projet: $PROJECT_NAME"

# Supprimer le dossier projets
if [ -d "$PROJECTS_DIR" ]; then
    echo "🗑️  Suppression de: $PROJECTS_DIR"
    rm -rf "$PROJECTS_DIR"
    if [ $? -eq 0 ]; then
        echo "✅ Dossier projets supprimé"
    else
        echo "❌ Erreur lors de la suppression du dossier projets"
        exit 1
    fi
else
    echo "⚠️  Dossier projets introuvable: $PROJECTS_DIR"
fi

# Supprimer le dossier containers
if [ -d "$CONTAINERS_DIR" ]; then
    echo "🗑️  Suppression de: $CONTAINERS_DIR"
    rm -rf "$CONTAINERS_DIR"
    if [ $? -eq 0 ]; then
        echo "✅ Dossier containers supprimé"
    else
        echo "❌ Erreur lors de la suppression du dossier containers"
        exit 1
    fi
else
    echo "⚠️  Dossier containers introuvable: $CONTAINERS_DIR"
fi

echo "✅ Suppression terminée avec succès"
exit 0

