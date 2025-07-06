#!/bin/bash

echo "🔧 Test de la correction de l'IP"
echo "================================"

# Attendre que l'application se lance
sleep 3

# Test 1: Vérifier l'API server_info
echo "🔍 Test 1: API server_info"
echo "-------------------------"
SERVER_INFO=$(curl -s http://localhost:5000/server_info)
if [ $? -eq 0 ]; then
    echo "✅ API server_info accessible"
    echo "📋 Réponse: $SERVER_INFO"
    
    # Extraire l'IP
    SERVER_IP=$(echo "$SERVER_INFO" | grep -o '"server_ip":"[^"]*"' | cut -d'"' -f4)
    WORDPRESS_PORT=$(echo "$SERVER_INFO" | grep -o '"wordpress_port":[^,}]*' | cut -d':' -f2)
    
    echo "🌐 IP détectée: $SERVER_IP"
    echo "🚪 Port WordPress: $WORDPRESS_PORT"
else
    echo "❌ Erreur: API server_info non accessible"
fi

echo ""

# Test 2: Vérifier l'API projects_with_status
echo "🔍 Test 2: API projects_with_status"
echo "-----------------------------------"
PROJECTS_INFO=$(curl -s http://localhost:5000/projects_with_status)
if [ $? -eq 0 ]; then
    echo "✅ API projects_with_status accessible"
    echo "📋 Réponse: $PROJECTS_INFO"
    
    # Extraire le hostname
    HOSTNAME=$(echo "$PROJECTS_INFO" | grep -o '"hostname":"[^"]*"' | cut -d'"' -f4)
    echo "🏠 Hostname: $HOSTNAME"
else
    echo "❌ Erreur: API projects_with_status non accessible"
fi

echo ""

# Test 3: Vérifier l'IP réelle du serveur
echo "🔍 Test 3: IP réelle du serveur"
echo "------------------------------"
REAL_IP=$(ip route get 1 | awk '{print $7}' | head -1)
echo "🌐 IP réelle: $REAL_IP"

if [ "$SERVER_IP" = "$REAL_IP" ]; then
    echo "✅ IP correctement détectée"
else
    echo "⚠️  IP différente: API=$SERVER_IP, Réelle=$REAL_IP"
fi

echo ""

# Test 4: Vérifier l'interface web
echo "🔍 Test 4: Interface web"
echo "-----------------------"
echo "🌐 Interface accessible à:"
echo "   - http://localhost:5000"
echo "   - http://$REAL_IP:5000"
echo ""

if [ "$HOSTNAME" ]; then
    echo "🏠 Site WordPress accessible à:"
    echo "   - http://$HOSTNAME:$WORDPRESS_PORT"
    echo "   - http://$REAL_IP:$WORDPRESS_PORT"
else
    echo "⚠️  Aucun projet trouvé"
fi

echo ""

# Test 5: Vérifier les conteneurs Docker
echo "🔍 Test 5: Conteneurs Docker"
echo "----------------------------"
CONTAINERS=$(docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep eurasiapeace)
if [ -n "$CONTAINERS" ]; then
    echo "✅ Conteneurs trouvés:"
    echo "$CONTAINERS"
else
    echo "⚠️  Aucun conteneur eurasiapeace trouvé"
fi

echo ""

# Résumé
echo "📊 Résumé des tests"
echo "===================="
echo "🔧 Correction IP: $([ "$SERVER_IP" = "$REAL_IP" ] && echo "✅ SUCCÈS" || echo "⚠️ PARTIEL")"
echo "🌐 API server_info: $([ -n "$SERVER_IP" ] && echo "✅ OK" || echo "❌ ERREUR")"
echo "📋 API projects: $([ -n "$HOSTNAME" ] && echo "✅ OK" || echo "❌ ERREUR")"
echo "🐳 Conteneurs: $([ -n "$CONTAINERS" ] && echo "✅ OK" || echo "❌ ERREUR")"

echo ""
echo "🎯 Prochaines étapes:"
echo "1. Ouvrir http://$REAL_IP:5000 dans votre navigateur"
echo "2. Vérifier que l'IP affichée est maintenant: $REAL_IP:$WORDPRESS_PORT"
echo "3. Vérifier que le hostname est: $HOSTNAME"
echo ""
echo "🎉 Test terminé !" 