#!/usr/bin/env python3

import os
import re

def fix_missing_mailpit_ports():
    """
    Vérifie et corrige tous les projets existants qui pourraient 
    avoir des ports Mailpit manquants
    """
    
    projects_folder = "projets"
    print("🔍 Vérification des ports Mailpit manquants...")
    
    if not os.path.exists(projects_folder):
        print("❌ Dossier projets non trouvé")
        return
    
    projects_fixed = []
    projects_ok = []
    
    for project_name in os.listdir(projects_folder):
        project_path = os.path.join(projects_folder, project_name)
        
        # Ignorer si ce n'est pas un dossier
        if not os.path.isdir(project_path):
            continue
            
        # Ignorer les projets supprimés
        if os.path.exists(os.path.join(project_path, '.DELETED_PROJECT')):
            continue
            
        print(f"\n📁 Vérification du projet: {project_name}")
        
        # Vérifier si docker-compose.yml existe
        compose_file = os.path.join(project_path, 'docker-compose.yml')
        if not os.path.exists(compose_file):
            print(f"  ⚠️ Pas de docker-compose.yml trouvé")
            continue
        
        # Lire le docker-compose.yml pour extraire les ports Mailpit
        try:
            with open(compose_file, 'r') as f:
                compose_content = f.read()
        except Exception as e:
            print(f"  ❌ Erreur lecture docker-compose.yml: {e}")
            continue
        
        # Chercher les ports Mailpit dans le docker-compose.yml
        mailpit_web_port = None
        smtp_port = None
        
        # Regex pour trouver les ports Mailpit
        mailpit_web_match = re.search(r'"0\.0\.0\.0:(\d+):8025"', compose_content)
        smtp_match = re.search(r'"0\.0\.0\.0:(\d+):1025"', compose_content)
        
        if mailpit_web_match:
            mailpit_web_port = mailpit_web_match.group(1)
        if smtp_match:
            smtp_port = smtp_match.group(1)
        
        if not mailpit_web_port or not smtp_port:
            print(f"  ⚠️ Mailpit pas configuré dans docker-compose.yml")
            continue
        
        print(f"  🔍 Ports trouvés dans docker-compose.yml:")
        print(f"    - Mailpit web: {mailpit_web_port}")
        print(f"    - SMTP: {smtp_port}")
        
        # Vérifier si les fichiers de ports existent
        mailpit_port_file = os.path.join(project_path, '.mailpit_port')
        smtp_port_file = os.path.join(project_path, '.smtp_port')
        
        mailpit_missing = not os.path.exists(mailpit_port_file)
        smtp_missing = not os.path.exists(smtp_port_file)
        
        if mailpit_missing or smtp_missing:
            print(f"  🔧 Correction nécessaire:")
            
            if mailpit_missing:
                with open(mailpit_port_file, 'w') as f:
                    f.write(mailpit_web_port)
                print(f"    ✅ Fichier .mailpit_port créé avec {mailpit_web_port}")
            
            if smtp_missing:
                with open(smtp_port_file, 'w') as f:
                    f.write(smtp_port)
                print(f"    ✅ Fichier .smtp_port créé avec {smtp_port}")
            
            projects_fixed.append(project_name)
        else:
            print(f"  ✅ Fichiers de ports Mailpit déjà présents")
            projects_ok.append(project_name)
    
    # Résumé
    print(f"\n🎉 Vérification terminée:")
    print(f"  ✅ Projets OK: {len(projects_ok)}")
    print(f"  🔧 Projets corrigés: {len(projects_fixed)}")
    
    if projects_fixed:
        print(f"\n📋 Projets corrigés:")
        for project in projects_fixed:
            print(f"  - {project}")
    
    if projects_ok:
        print(f"\n📋 Projets déjà OK:")
        for project in projects_ok:
            print(f"  - {project}")

if __name__ == "__main__":
    fix_missing_mailpit_ports() 