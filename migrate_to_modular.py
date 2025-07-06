#!/usr/bin/env python3
"""
Script de migration vers l'architecture modulaire
Sauvegarde l'ancien app.py et active le nouveau système
"""

import os
import shutil
import datetime

def main():
    print("🔄 Migration vers l'architecture modulaire")
    print("=" * 50)
    
    # 1. Sauvegarder l'ancien app.py
    if os.path.exists('app.py'):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f'app_backup_{timestamp}.py'
        
        print(f"💾 Sauvegarde de l'ancien app.py vers {backup_name}")
        shutil.copy2('app.py', backup_name)
        
        print(f"🗑️ Suppression de l'ancien app.py")
        os.remove('app.py')
    
    # 2. Renommer le nouveau fichier
    if os.path.exists('app_modular.py'):
        print("📝 Activation du nouveau app.py modulaire")
        shutil.move('app_modular.py', 'app.py')
    
    # 3. Vérifier les dépendances
    print("\n📦 Vérification des dépendances...")
    
    required_packages = [
        'flask',
        'flask-socketio',
        'werkzeug',
        'chardet'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - MANQUANT")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n⚠️ Packages manquants: {', '.join(missing_packages)}")
        print("Installez-les avec:")
        print(f"pip install {' '.join(missing_packages)}")
    
    # 4. Vérifier la structure des dossiers
    print("\n📁 Vérification de la structure...")
    
    required_dirs = [
        'models',
        'services', 
        'routes',
        'templates',
        'static/css',
        'static/js',
        'static/images',
        'utils'
    ]
    
    for dir_path in required_dirs:
        if os.path.exists(dir_path):
            print(f"✅ {dir_path}/")
        else:
            print(f"❌ {dir_path}/ - MANQUANT")
    
    # 5. Vérifier les fichiers essentiels
    print("\n📄 Vérification des fichiers...")
    
    required_files = [
        'models/__init__.py',
        'models/project.py',
        'services/__init__.py',
        'services/port_service.py',
        'services/docker_service.py',
        'services/database_service.py',
        'routes/__init__.py',
        'routes/main.py',
        'routes/projects.py',
        'utils/__init__.py',
        'utils/file_utils.py',
        'templates/base.html',
        'templates/index.html',
        'static/css/style.css',
        'static/js/main.js',
        'static/js/projects.js',
        'static/js/upload.js'
    ]
    
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path} - MANQUANT")
    
    print("\n" + "=" * 50)
    print("✅ Migration terminée !")
    print("\n📋 Prochaines étapes:")
    print("1. Installer les packages manquants si nécessaire")
    print("2. Vérifier que docker-template/ existe avec vos templates")
    print("3. Redémarrer le service wp-launcher:")
    print("   sudo systemctl restart wp-launcher")
    print("4. Vérifier les logs:")
    print("   sudo systemctl status wp-launcher")
    print("   sudo journalctl -u wp-launcher -f")
    
    print("\n🎉 Avantages de la nouvelle architecture:")
    print("- Code organisé en modules logiques")
    print("- Templates HTML séparés")
    print("- CSS avec zone d'upload anthracite")
    print("- Loaders pour start/stop des projets")
    print("- Meilleure maintenabilité")
    print("- Réduction des tokens LLM")

if __name__ == '__main__':
    main() 