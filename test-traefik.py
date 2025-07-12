#!/usr/bin/env python3
"""
Script de test pour vérifier la configuration Traefik
"""

import os
import sys
import subprocess
import json

def check_traefik_running():
    """Vérifier que Traefik est en cours d'exécution"""
    try:
        result = subprocess.run([
            'docker', 'ps', '--format', '{{.Names}}'
        ], capture_output=True, text=True)
        
        running_containers = result.stdout.strip().split('\n')
        return 'traefik' in running_containers
    except Exception:
        return False

def check_traefik_network():
    """Vérifier que le réseau Traefik existe"""
    try:
        result = subprocess.run([
            'docker', 'network', 'ls', '--format', '{{.Name}}'
        ], capture_output=True, text=True)
        
        networks = result.stdout.strip().split('\n')
        return 'traefik-network' in networks
    except Exception:
        return False

def check_traefik_config():
    """Vérifier les fichiers de configuration Traefik"""
    config_files = [
        'traefik/traefik.yml',
        'traefik/dynamic.yml',
        'traefik/docker-compose.yml',
        'traefik/acme.json'
    ]
    
    missing_files = []
    for file_path in config_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    return missing_files

def check_exposed_sites():
    """Vérifier les sites exposés"""
    if os.path.exists('exposed_sites.json'):
        try:
            with open('exposed_sites.json', 'r') as f:
                sites = json.load(f)
            return sites
        except Exception:
            return {}
    return {}

def test_traefik_service():
    """Tester le service Traefik"""
    try:
        from services.traefik_service import TraefikService
        
        service = TraefikService()
        status = service.get_traefik_status()
        
        return status
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

def main():
    print("🔍 Test de configuration Traefik")
    print("=" * 40)
    
    # Vérifier que nous sommes dans le bon répertoire
    if not os.path.exists('app.py'):
        print("❌ Erreur: Ce script doit être exécuté depuis le répertoire wp-launcher")
        sys.exit(1)
    
    # Test 1: Traefik en cours d'exécution
    print("\n1. Vérification de Traefik...")
    if check_traefik_running():
        print("✅ Traefik est en cours d'exécution")
    else:
        print("❌ Traefik n'est pas en cours d'exécution")
        print("   Lancez: cd traefik && ./install.sh")
    
    # Test 2: Réseau Traefik
    print("\n2. Vérification du réseau...")
    if check_traefik_network():
        print("✅ Réseau traefik-network existe")
    else:
        print("❌ Réseau traefik-network manquant")
        print("   Créez-le: docker network create traefik-network")
    
    # Test 3: Fichiers de configuration
    print("\n3. Vérification des fichiers de configuration...")
    missing_files = check_traefik_config()
    if not missing_files:
        print("✅ Tous les fichiers de configuration sont présents")
    else:
        print("❌ Fichiers manquants:")
        for file_path in missing_files:
            print(f"   - {file_path}")
    
    # Test 4: Sites exposés
    print("\n4. Vérification des sites exposés...")
    exposed_sites = check_exposed_sites()
    if exposed_sites:
        print(f"📊 {len(exposed_sites)} site(s) exposé(s):")
        for project, data in exposed_sites.items():
            hostname = data.get('hostname', 'N/A')
            print(f"   - {project}: https://{hostname}")
    else:
        print("ℹ️ Aucun site exposé actuellement")
    
    # Test 5: Service Python
    print("\n5. Test du service Python...")
    service_result = test_traefik_service()
    if service_result.get('success'):
        status = service_result.get('status', {})
        if status.get('traefik_running'):
            print("✅ Service Traefik Python fonctionnel")
            print(f"   Dashboard: {status.get('dashboard_url', 'N/A')}")
        else:
            print("⚠️ Service Python OK mais Traefik non détecté")
    else:
        print(f"❌ Erreur du service Python: {service_result.get('error', 'Inconnue')}")
    
    print("\n" + "=" * 40)
    print("🎯 Test terminé")
    
    # Recommandations
    print("\n💡 Recommandations:")
    if not check_traefik_running():
        print("   1. Démarrez Traefik: cd traefik && ./install.sh")
    if missing_files:
        print("   2. Réinstallez la configuration Traefik")
    print("   3. Testez l'exposition d'un site via l'interface")
    print("   4. Vérifiez le dashboard: http://localhost:8080")

if __name__ == "__main__":
    main() 