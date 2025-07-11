#!/bin/bash

echo "🔒 Configuration SSL automatique pour WordPress Launcher"
echo "======================================================"

# Configuration
TRAEFIK_DIR="/home/dev-server/Sites/wp-launcher/traefik"
TEMPLATE_DIR="/home/dev-server/Sites/wp-launcher/docker-template"
CONTAINERS_DIR="/home/dev-server/Sites/wp-launcher/containers"

# Vérifier que Traefik est installé
if [ ! -d "$TRAEFIK_DIR" ]; then
    echo "❌ Traefik n'est pas installé. Veuillez d'abord installer Traefik."
    exit 1
fi

# Créer le répertoire de template s'il n'existe pas
mkdir -p "$TEMPLATE_DIR"

echo "📋 Étape 1: Mise à jour des certificats SSL"
echo "-------------------------------------------"

# Exécuter le script de mise à jour des certificats
cd "$TRAEFIK_DIR"
if [ -f "update-certificates.sh" ]; then
    chmod +x update-certificates.sh
    ./update-certificates.sh
    if [ $? -eq 0 ]; then
        echo "✅ Certificats mis à jour avec succès"
    else
        echo "❌ Erreur lors de la mise à jour des certificats"
    fi
else
    echo "⚠️ Script de mise à jour des certificats non trouvé"
fi

echo ""
echo "📋 Étape 2: Vérification de Traefik"
echo "-----------------------------------"

# Vérifier que Traefik est en cours d'exécution
if docker ps | grep -q traefik; then
    echo "✅ Traefik est en cours d'exécution"
    
    # Vérifier les logs pour les erreurs
    if docker-compose logs traefik 2>/dev/null | grep -q "ERROR"; then
        echo "⚠️ Traefik a des erreurs, mais continue à fonctionner"
    else
        echo "✅ Traefik fonctionne sans erreurs"
    fi
else
    echo "🚀 Démarrage de Traefik..."
    docker-compose up -d
    if [ $? -eq 0 ]; then
        echo "✅ Traefik démarré avec succès"
    else
        echo "❌ Erreur lors du démarrage de Traefik"
        exit 1
    fi
fi

echo ""
echo "📋 Étape 3: Mise à jour des projets existants"
echo "-------------------------------------------"

# Parcourir tous les projets existants
if [ -d "$CONTAINERS_DIR" ]; then
    for project_dir in "$CONTAINERS_DIR"/*; do
        if [ -d "$project_dir" ]; then
            project_name=$(basename "$project_dir")
            echo "🔄 Mise à jour du projet: $project_name"
            
            # Vérifier si le projet a un docker-compose.yml
            if [ -f "$project_dir/docker-compose.yml" ]; then
                # Vérifier si le projet utilise encore certresolver
                if grep -q "certresolver=letsencrypt" "$project_dir/docker-compose.yml"; then
                    echo "  📝 Mise à jour des labels SSL pour $project_name"
                    
                    # Remplacer certresolver par tls=true
                    sed -i 's/traefik\.http\.routers\.\([^.]*\)\.tls\.certresolver=letsencrypt/traefik.http.routers.\1.tls=true/g' "$project_dir/docker-compose.yml"
                    
                    # Supprimer le middleware compress s'il existe
                    sed -i 's/,compress//g' "$project_dir/docker-compose.yml"
                    
                    # Redémarrer le projet
                    cd "$project_dir"
                    docker-compose restart wordpress 2>/dev/null || echo "  ⚠️ Impossible de redémarrer le service WordPress"
                    
                    echo "  ✅ Projet $project_name mis à jour"
                else
                    echo "  ✅ Projet $project_name déjà à jour"
                fi
            else
                echo "  ⚠️ Pas de docker-compose.yml trouvé pour $project_name"
            fi
        fi
    done
else
    echo "ℹ️ Aucun projet existant trouvé"
fi

echo ""
echo "📋 Étape 4: Configuration du template"
echo "------------------------------------"

# Mettre à jour le template docker-compose.yml
if [ -f "$TEMPLATE_DIR/docker-compose.yml" ]; then
    echo "🔄 Mise à jour du template docker-compose.yml"
    
    # S'assurer que le template utilise les bons labels
    if grep -q "certresolver=letsencrypt" "$TEMPLATE_DIR/docker-compose.yml"; then
        sed -i 's/traefik\.http\.routers\.\([^.]*\)\.tls\.certresolver=letsencrypt/traefik.http.routers.\1.tls=true/g' "$TEMPLATE_DIR/docker-compose.yml"
        sed -i 's/,compress//g' "$TEMPLATE_DIR/docker-compose.yml"
        echo "✅ Template mis à jour"
    else
        echo "✅ Template déjà à jour"
    fi
else
    echo "⚠️ Template docker-compose.yml non trouvé"
fi

echo ""
echo "📋 Étape 5: Test de configuration"
echo "--------------------------------"

# Tester la configuration SSL
echo "🧪 Test de la configuration SSL..."

# Vérifier que les certificats sont bien montés
if docker exec traefik ls -la /fullchain.pem /privkey.pem >/dev/null 2>&1; then
    echo "✅ Certificats SSL correctement montés dans Traefik"
else
    echo "❌ Certificats SSL non montés dans Traefik"
fi

# Vérifier que les domaines répondent
echo "🌐 Test des domaines configurés..."
if curl -s -I https://traefik.dev.akdigital.fr --resolve traefik.dev.akdigital.fr:443:127.0.0.1 | grep -q "HTTP/"; then
    echo "✅ Dashboard Traefik accessible"
else
    echo "⚠️ Dashboard Traefik non accessible"
fi

echo ""
echo "🎉 Configuration SSL automatique terminée!"
echo "=========================================="
echo ""
echo "📊 Résumé:"
echo "- Traefik utilise maintenant votre certificat wildcard *.dev.akdigital.fr"
echo "- Tous les nouveaux projets auront automatiquement SSL"
echo "- Les projets existants ont été mis à jour"
echo ""
echo "🌐 Accès:"
echo "- Dashboard Traefik: https://traefik.dev.akdigital.fr"
echo "- Nouveaux projets: https://[nom-projet].dev.akdigital.fr"
echo ""
echo "🔄 Mise à jour des certificats:"
echo "- Exécutez: cd traefik && ./update-certificates.sh"
echo "- Ou utilisez l'interface WordPress Launcher" 