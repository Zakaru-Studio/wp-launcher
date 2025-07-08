#!/bin/bash

echo "🔍 ===== TEST REDIRECTIONS - DIAGNOSTIC RAPIDE ====="
echo ""

# Obtenir l'IP locale
LOCAL_IP=$(hostname -I | awk '{print $1}')
echo "📡 IP du serveur : $LOCAL_IP"
echo ""

echo "🧪 TEST 1 : Réponses directes des ports"
echo "======================================="

# Test des ports principaux
for port in 8080 8085 8087 8090; do
    echo -n "Port $port : "
    response=$(curl -s -o /dev/null -w "%{http_code}" http://$LOCAL_IP:$port --connect-timeout 2)
    if [ "$response" = "200" ]; then
        echo "✅ Accessible (HTTP $response)"
    elif [ "$response" = "000" ]; then
        echo "❌ Inaccessible (timeout/refus)"
    else
        echo "⚠️ Code HTTP $response"
    fi
done

echo ""
echo "🧪 TEST 2 : Vérification des redirections"
echo "========================================"

# Test spécifique pour nonasolution (port 8087)
echo "📝 Test nonasolution (port 8087) :"
redirect_location=$(curl -s -I http://$LOCAL_IP:8087 | grep -i "location:" | cut -d' ' -f2 | tr -d '\r')

if [ -z "$redirect_location" ]; then
    echo "   ✅ Pas de redirection détectée"
    echo "   📄 Contenu servi directement depuis le port 8087"
else
    echo "   ⚠️ REDIRECTION DÉTECTÉE vers : $redirect_location"
    echo "   🔍 Cause probable : Configuration WordPress interne"
fi

echo ""
echo "🧪 TEST 3 : Headers de réponse"
echo "==============================="

echo "📝 Headers de nonasolution (8087) :"
curl -s -I http://$LOCAL_IP:8087 | head -5 | while read line; do
    echo "   $line"
done

echo ""
echo "🧪 TEST 4 : Test de l'API projet"
echo "================================"

api_response=$(curl -s http://localhost:5000/projects_with_status)
if [ $? -eq 0 ]; then
    echo "✅ API accessible"
    echo "📊 Ports configurés :"
    echo "$api_response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for project in data.get('projects', []):
        print(f\"   {project['name']} : WordPress {project['port']}, phpMyAdmin {project.get('pma_port', 'N/A')}\")
except:
    print('   ❌ Erreur de parsing JSON')
"
else
    echo "❌ API inaccessible"
fi

echo ""
echo "🎯 RÉSUMÉ DU DIAGNOSTIC :"
echo "=========================="
echo "1. ✅ Ports serveur : Vérifiés ci-dessus"
echo "2. 🔍 Redirections : Voir résultats du test 2"
echo "3. 📱 Si problème persiste :"
echo "   - Vider cache navigateur (Ctrl+Shift+Suppr)"
echo "   - Tester en navigation privée"
echo "   - Utiliser page debug : http://$LOCAL_IP:5000/debug"
echo "   - Tester depuis mobile sur même WiFi"
echo ""
echo "📋 LOGS DÉTAILLÉS SAUVÉS DANS : test_redirections.log"

# Sauvegarder les logs détaillés
{
    echo "=== Test de redirections - $(date) ==="
    echo ""
    echo "=== Test curl détaillé pour port 8087 ==="
    curl -v http://$LOCAL_IP:8087 2>&1 | head -20
    echo ""
    echo "=== Réponse API complète ==="
    curl -s http://localhost:5000/projects_with_status | python3 -m json.tool
    echo ""
} > test_redirections.log

echo "✅ Tests terminés ! Consultez le fichier de diagnostic complet :"
echo "   📄 DIAGNOSTIC_REDIRECTION_8080.md" 