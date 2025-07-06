#!/bin/bash

# Script de diagnostic pour WP Launcher
echo "🔍 Diagnostic WP Launcher"
echo "========================"

echo "📊 État général du système :"
echo "----------------------------"

# Vérifier les dossiers
echo "📁 Vérification des dossiers :"
echo "  - uploads/ : $(ls -la uploads/ 2>/dev/null | wc -l) fichiers"
echo "  - projets/ : $(ls -la projets/ 2>/dev/null | wc -l) projets"
echo "  - templates/ : $(ls -la templates/ 2>/dev/null | wc -l) fichiers"
echo "  - docker-template/ : $(ls -la docker-template/ 2>/dev/null | wc -l) fichiers"

echo ""
echo "🐳 État Docker :"
echo "  - Service Docker : $(systemctl is-active docker 2>/dev/null || echo 'inconnu')"
echo "  - Conteneurs actifs : $(docker ps -q 2>/dev/null | wc -l)"
echo "  - Images disponibles : $(docker images -q 2>/dev/null | wc -l)"

echo ""
echo "🔧 Conteneurs des projets :"
if [ -d "projets" ] && [ "$(ls -A projets)" ]; then
    for project in projets/*/; do
        if [ -d "$project" ]; then
            project_name=$(basename "$project")
            echo "  📂 $project_name :"
            
            # Vérifier docker-compose.yml
            if [ -f "$project/docker-compose.yml" ]; then
                echo "    ✅ docker-compose.yml présent"
            else
                echo "    ❌ docker-compose.yml manquant"
            fi
            
            # Vérifier les conteneurs
            cd "$project" 2>/dev/null || continue
            containers=$(docker-compose ps -q 2>/dev/null | wc -l)
            echo "    🐳 Conteneurs : $containers"
            
            # Vérifier les logs des conteneurs
            mysql_container="${project_name}_mysql_1"
            wp_container="${project_name}_wordpress_1"
            
            if docker ps --format '{{.Names}}' | grep -q "$mysql_container"; then
                echo "    ✅ MySQL actif"
            else
                echo "    ❌ MySQL arrêté"
            fi
            
            if docker ps --format '{{.Names}}' | grep -q "$wp_container"; then
                echo "    ✅ WordPress actif"
            else
                echo "    ❌ WordPress arrêté"
            fi
            
            cd - > /dev/null
        fi
    done
else
    echo "  📂 Aucun projet trouvé"
fi

echo ""
echo "🌐 Vérification des ports :"
echo "  - Port 5000 (Flask) : $(ss -tuln 2>/dev/null | grep :5000 > /dev/null && echo 'occupé' || echo 'libre')"
echo "  - Port 8080 (WordPress) : $(ss -tuln 2>/dev/null | grep :8080 > /dev/null && echo 'occupé' || echo 'libre')"

echo ""
echo "🐍 Environnement Python :"
if [ -d "venv" ]; then
    echo "  ✅ Environnement virtuel présent"
    source venv/bin/activate
    echo "  📦 Packages installés : $(pip list 2>/dev/null | wc -l)"
    echo "  🐍 Version Python : $(python --version 2>/dev/null || echo 'erreur')"
else
    echo "  ❌ Environnement virtuel manquant"
fi

echo ""
echo "💾 Espace disque :"
echo "  - Espace disponible : $(df -h . | tail -1 | awk '{print $4}')"
echo "  - Taille uploads/ : $(du -sh uploads/ 2>/dev/null | awk '{print $1}' || echo '0')"
echo "  - Taille projets/ : $(du -sh projets/ 2>/dev/null | awk '{print $1}' || echo '0')"

echo ""
echo "📋 Recommandations :"
echo "-------------------"

# Recommandations basées sur l'état
if ! systemctl is-active docker &>/dev/null; then
    echo "  ⚠️  Démarrer Docker: sudo systemctl start docker"
fi

if [ ! -d "venv" ]; then
    echo "  ⚠️  Créer l'environnement virtuel: python3 -m venv venv"
fi

if ! ss -tuln 2>/dev/null | grep :5000 > /dev/null; then
    echo "  ✅ Prêt à démarrer l'application sur le port 5000"
fi

echo ""
echo "🚀 Pour démarrer en mode debug :"
echo "  ./debug_start.sh"
echo ""
echo "🧪 Pour tester l'installation :"
echo "  ./test_install.sh" 