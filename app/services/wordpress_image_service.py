#!/usr/bin/env python3
"""
Service pour vérifier et construire automatiquement l'image WordPress personnalisée
"""

import subprocess
import os
from pathlib import Path

class WordPressImageService:
    """Service de gestion de l'image Docker WordPress personnalisée"""
    
    def __init__(self):
        self.image_name = 'wp-launcher-wordpress:latest'
        self.dockerfile_path = 'docker-template/wordpress'
    
    def check_image_exists(self):
        """Vérifie si l'image wp-launcher-wordpress:latest existe"""
        try:
            result = subprocess.run([
                'docker', 'images', '--format', '{{.Repository}}:{{.Tag}}', 
                self.image_name
            ], capture_output=True, text=True, timeout=10)
            
            return self.image_name in result.stdout
        except Exception as e:
            print(f"❌ Erreur lors de la vérification de l'image: {e}")
            return False

    def build_wordpress_image(self):
        """Construit l'image WordPress personnalisée"""
        try:
            print("🚀 Construction de l'image WordPress personnalisée...")
            
            # Vérifier que le Dockerfile existe
            dockerfile = Path(self.dockerfile_path) / 'Dockerfile'
            if not dockerfile.exists():
                print(f"❌ Dockerfile non trouvé: {dockerfile}")
                return False
            
            # Changer vers le bon répertoire
            original_dir = os.getcwd()
            os.chdir(self.dockerfile_path)
            
            try:
                # Construire l'image
                result = subprocess.run([
                    'docker', 'build', '-t', self.image_name, '.'
                ], capture_output=True, text=True, timeout=300)  # 5 minutes max
                
                if result.returncode == 0:
                    print("✅ Image WordPress personnalisée construite avec succès!")
                    return self.test_wp_cli_in_image()
                else:
                    print(f"❌ Erreur lors de la construction de l'image:")
                    print(f"STDOUT: {result.stdout}")
                    print(f"STDERR: {result.stderr}")
                    return False
                    
            finally:
                os.chdir(original_dir)
                
        except Exception as e:
            print(f"❌ Erreur lors de la construction de l'image: {e}")
            return False

    def test_wp_cli_in_image(self):
        """Teste WP-CLI dans l'image construite selon les recommandations officielles"""
        try:
            print("🧪 Test de WP-CLI dans l'image...")
            # Utiliser docker-entrypoint.sh directement pour éviter notre script personnalisé
            result = subprocess.run([
                'docker', 'run', '--rm', '--entrypoint', 'wp',
                self.image_name, 
                '--info', '--allow-root'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("✅ WP-CLI fonctionne correctement:")
                for line in result.stdout.strip().split('\n'):
                    if 'WP-CLI version' in line or 'PHP version' in line or 'OS:' in line:
                        print(f"   {line}")
                return True
            else:
                print(f"❌ WP-CLI ne fonctionne pas: {result.stderr}")
                return False
        except Exception as e:
            print(f"❌ Erreur lors du test WP-CLI: {e}")
            return False

    def ensure_wordpress_image(self):
        """S'assure que l'image WordPress personnalisée existe"""
        print("🔍 Vérification de l'image WordPress personnalisée...")
        
        if self.check_image_exists():
            print("✅ Image wp-launcher-wordpress:latest déjà disponible")
            # Tester WP-CLI même si l'image existe déjà
            return self.test_wp_cli_in_image()
        else:
            print("⚠️ Image wp-launcher-wordpress:latest non trouvée")
            return self.build_wordpress_image()


# Fonctions pour la rétrocompatibilité
def check_image_exists():
    """Fonction de compatibilité - utilise le service"""
    service = WordPressImageService()
    return service.check_image_exists()

def build_wordpress_image():
    """Fonction de compatibilité - utilise le service"""
    service = WordPressImageService()
    return service.build_wordpress_image()

def test_wp_cli_in_image():
    """Fonction de compatibilité - utilise le service"""
    service = WordPressImageService()
    return service.test_wp_cli_in_image()

def ensure_wordpress_image():
    """Fonction de compatibilité - utilise le service"""
    service = WordPressImageService()
    return service.ensure_wordpress_image()


if __name__ == "__main__":
    import sys
    service = WordPressImageService()
    success = service.ensure_wordpress_image()
    sys.exit(0 if success else 1)

