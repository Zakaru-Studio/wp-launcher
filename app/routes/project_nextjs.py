#!/usr/bin/env python3
"""
Routes pour la gestion Next.js des projets
"""

import os
import json
import subprocess
from flask import Blueprint, request, jsonify, current_app
from app.utils.logger import wp_logger
from app.models.project import Project
from app.config.docker_config import DockerConfig
from app.middleware.auth_middleware import login_required, admin_required

project_nextjs_bp = Blueprint('project_nextjs', __name__)

# Configuration des constantes
PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'

@project_nextjs_bp.route('/nextjs_npm/<project_name>/<command>', methods=['POST'])
@login_required
def nextjs_npm_command(project_name, command):
    """Exécute une commande npm pour un projet NextJS"""
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Ce projet n\'a pas NextJS activé'})
        
        # Vérifier que la commande est autorisée
        allowed_commands = ['install', 'dev', 'build', 'start']
        if command not in allowed_commands:
            return jsonify({'success': False, 'message': f'Commande non autorisée: {command}'})
        
        # Obtenir le service Docker
        docker_service = current_app.extensions.get('docker')
        if not docker_service:
            return jsonify({'success': False, 'message': 'Service Docker non disponible'})
        
        # Vérifier le statut du conteneur
        container_status = docker_service.get_container_status(project_name)
        if container_status != 'active':
            # Essayer de redémarrer le conteneur automatiquement
            print(f"🔄 Conteneur {project_name} inactif, tentative de redémarrage...")
            container_path = os.path.join(CONTAINERS_FOLDER, project_name)
            success, error = docker_service.start_containers(container_path)
            
            if not success:
                return jsonify({
                    'success': False, 
                    'message': f'Le conteneur doit être démarré pour exécuter des commandes npm. Erreur de démarrage: {error}'
                })
            
            # Attendre un peu que le conteneur soit prêt
            import time
            time.sleep(5)
        
        # Construire la commande npm
        container_name = f"{project_name}_nextjs_1"
        
        if command == 'install':
            npm_command = ['docker', 'exec', container_name, 'npm', 'install']
        elif command == 'dev':
            npm_command = ['docker', 'exec', '-d', container_name, 'npm', 'run', 'dev']
        elif command == 'build':
            npm_command = ['docker', 'exec', container_name, 'npm', 'run', 'build']
        elif command == 'start':
            npm_command = ['docker', 'exec', '-d', container_name, 'npm', 'start']
        
        # Exécuter la commande
        result = subprocess.run(npm_command, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            return jsonify({
                'success': True, 
                'message': f'Commande npm {command} exécutée avec succès',
                'output': result.stdout
            })
        else:
            return jsonify({
                'success': False, 
                'message': f'Erreur lors de l\'exécution de npm {command}',
                'error': result.stderr
            })
            
    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False, 
            'message': f'Timeout lors de l\'exécution de npm {command}'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@project_nextjs_bp.route('/check_nextjs_status/<project_name>')
@login_required
def check_nextjs_status(project_name):
    """Vérifie le statut npm dev d'un projet NextJS"""
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Ce projet n\'a pas NextJS activé'})
        
        # Obtenir le service Docker
        docker_service = current_app.extensions.get('docker')
        if not docker_service:
            return jsonify({'success': False, 'message': 'Service Docker non disponible'})
        
        # Vérifier le statut du conteneur
        container_status = docker_service.get_container_status(project_name)
        if container_status != 'active':
            return jsonify({
                'success': True,
                'dev_running': False,
                'message': 'Conteneur arrêté'
            })
        
        # Vérifier si npm run dev est en cours
        container_name = f"{project_name}_nextjs_1"
        check_command = ['docker', 'exec', container_name, 'pgrep', '-f', 'npm.*dev']
        
        result = subprocess.run(check_command, capture_output=True, text=True)
        dev_running = result.returncode == 0
        
        return jsonify({
            'success': True,
            'dev_running': dev_running,
            'message': 'npm run dev en cours' if dev_running else 'npm run dev arrêté'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@project_nextjs_bp.route('/stop_nextjs_dev/<project_name>', methods=['POST'])
@login_required
def stop_nextjs_dev(project_name):
    """Arrête npm run dev pour un projet NextJS"""
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Ce projet n\'a pas NextJS activé'})
        
        # Obtenir le service Docker
        docker_service = current_app.extensions.get('docker')
        if not docker_service:
            return jsonify({'success': False, 'message': 'Service Docker non disponible'})
        
        # Vérifier le statut du conteneur
        container_status = docker_service.get_container_status(project_name)
        if container_status != 'active':
            return jsonify({'success': False, 'message': 'Le conteneur n\'est pas actif'})
        
        # Arrêter npm run dev
        container_name = f"{project_name}_nextjs_1"
        stop_command = ['docker', 'exec', container_name, 'pkill', '-f', 'npm.*dev']
        
        result = subprocess.run(stop_command, capture_output=True, text=True)
        
        return jsonify({
            'success': True,
            'message': 'npm run dev arrêté avec succès'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@project_nextjs_bp.route('/start_nextjs_container/<project_name>', methods=['POST'])
@login_required
def start_nextjs_container(project_name):
    """Démarre le conteneur NextJS et lance npm run dev"""
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Ce projet n\'a pas NextJS activé'})
        
        # Obtenir le service Docker
        docker_service = current_app.extensions.get('docker')
        if not docker_service:
            return jsonify({'success': False, 'message': 'Service Docker non disponible'})
        
        # Démarrer le conteneur
        container_path = os.path.join(CONTAINERS_FOLDER, project_name)
        success, error = docker_service.start_containers(container_path)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Conteneur NextJS démarré avec succès'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Erreur lors du démarrage: {error}'
            })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@project_nextjs_bp.route('/fix_nextjs_package/<project_name>', methods=['POST'])
@login_required
def fix_nextjs_package(project_name):
    """Répare ou crée le package.json manquant pour Next.js"""
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Ce projet n\'a pas NextJS activé'})
        
        # Chemin du dossier Next.js
        nextjs_path = os.path.join(project.path, 'client')
        package_json_path = os.path.join(nextjs_path, 'package.json')
        
        # Vérifier si le package.json existe déjà
        if os.path.exists(package_json_path):
            return jsonify({
                'success': True,
                'message': 'Le package.json existe déjà',
                'path': package_json_path
            })
        
        # Créer le package.json
        from app.utils.project_utils import create_nextjs_package_json
        success = create_nextjs_package_json(nextjs_path, project_name)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Package.json créé avec succès',
                'path': package_json_path
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Erreur lors de la création du package.json'
            })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@project_nextjs_bp.route('/fix_docker_compose_ports/<project_name>', methods=['POST'])
@login_required
def fix_docker_compose_ports(project_name):
    """Corrige les ports dans docker-compose.yml pour utiliser les valeurs des fichiers de ports"""
    try:
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Chemin du docker-compose.yml
        docker_compose_path = os.path.join(project.container_path, 'docker-compose.yml')
        if not os.path.exists(docker_compose_path):
            return jsonify({'success': False, 'message': 'docker-compose.yml non trouvé'})
        
        # Arrêter le projet d'abord
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            print(f"🛑 Arrêt du projet {project_name}")
            docker_service.stop_containers(project.container_path)
        
        # Lire le fichier docker-compose.yml
        with open(docker_compose_path, 'r') as f:
            content = f.read()
        
        # Récupérer les ports des fichiers
        ports = {}
        if project.port:
            ports['wordpress'] = project.port
        if project.pma_port:
            ports['phpmyadmin'] = project.pma_port
        if project.mailpit_port:
            ports['mailpit'] = project.mailpit_port
        if project.smtp_port:
            ports['smtp'] = project.smtp_port
        if project.nextjs_port:
            ports['nextjs'] = project.nextjs_port
        
        # Remplacer les ports dans le contenu
        changes = []
        if ports.get('wordpress'):
            old_pattern = f'0.0.0.0:{ports["wordpress"]}:80'
            if old_pattern in content:
                changes.append(f'WordPress: {ports["wordpress"]}')
        
        if ports.get('phpmyadmin'):
            old_pattern = f'0.0.0.0:{ports["phpmyadmin"]}:80'
            if old_pattern in content:
                changes.append(f'phpMyAdmin: {ports["phpmyadmin"]}')
        
        if ports.get('mailpit'):
            old_pattern = f'0.0.0.0:{ports["mailpit"]}:8025'
            if old_pattern in content:
                changes.append(f'Mailpit: {ports["mailpit"]}')
        
        if ports.get('smtp'):
            old_pattern = f'0.0.0.0:{ports["smtp"]}:1025'
            if old_pattern in content:
                changes.append(f'SMTP: {ports["smtp"]}')
        
        if ports.get('nextjs'):
            # Chercher et remplacer les ports incorrects pour Next.js
            import re
            nextjs_pattern = r'0\.0\.0\.0:(\d+):3000'
            matches = re.findall(nextjs_pattern, content)
            
            for match in matches:
                current_port = int(match)
                if current_port != ports['nextjs']:
                    old_port_config = f'0.0.0.0:{current_port}:3000'
                    new_port_config = f'0.0.0.0:{ports["nextjs"]}:3000'
                    content = content.replace(old_port_config, new_port_config)
                    changes.append(f'Next.js: {current_port} → {ports["nextjs"]}')
        
        # Écrire le fichier corrigé
        with open(docker_compose_path, 'w') as f:
            f.write(content)
        
        # Redémarrer le projet
        if docker_service:
            print(f"🚀 Redémarrage du projet {project_name}")
            success, error = docker_service.start_containers(project.container_path)
            if not success:
                return jsonify({'success': False, 'message': f'Erreur lors du redémarrage: {error}'})
        
        return jsonify({
            'success': True,
            'message': f'Ports corrigés pour {project_name}',
            'changes': changes
        })
        
    except Exception as e:
                return jsonify({'success': False, 'message': f'Erreur: {str(e)}'}) 


@project_nextjs_bp.route('/fix_permissions/<project_name>', methods=['POST'])
@login_required
def fix_permissions(project_name):
    """Corrige les permissions d'un projet pour permettre l'édition libre des fichiers"""
    try:
        # Si c'est une instance dev, appliquer les permissions au projet parent
        target_project = project_name
        if '_dev_' in project_name:
            parts = project_name.split('_dev_')
            if len(parts) >= 2:
                target_project = parts[0]
                print(f"🔧 [FIX_PERMISSIONS_NEXTJS] Instance dev détectée: {project_name} → application au projet parent: {target_project}")
        
        # Vérifier que le projet existe
        project = Project(target_project, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        print(f"🔧 [FIX_PERMISSIONS_NEXTJS] Correction des permissions pour: {target_project}")
        
        # Obtenir l'utilisateur actuel
        import pwd
        import os
        current_user = pwd.getpwuid(os.getuid()).pw_name
        print(f"📋 [FIX_PERMISSIONS] Utilisateur actuel: {current_user}")
        
        # Chemin du projet
        project_path = project.path
        print(f"📂 [FIX_PERMISSIONS] Chemin du projet: {project_path}")
        
        # Arrêter COMPLÈTEMENT le projet pour éviter les conflits
        docker_service = current_app.extensions.get('docker')
        was_running = False
        if docker_service:
            container_status = docker_service.get_container_status(project_name)
            if container_status == 'active':
                print(f"🛑 [FIX_PERMISSIONS] Arrêt COMPLET du projet...")
                docker_service.stop_containers(project.container_path)
                was_running = True
                
                # Attendre un peu que Docker libère complètement les fichiers
                import time
                time.sleep(2)
                print(f"⏳ [FIX_PERMISSIONS] Attente de libération des fichiers...")
        
        # Fonction pour corriger les permissions d'un dossier
        def fix_directory_permissions(path, description):
            try:
                print(f"🔧 [FIX_PERMISSIONS] Correction de {description}: {path}")
                
                # Première méthode : chown simple
                result = subprocess.run([
                    'sudo', 'chown', '-R', f'{current_user}:{current_user}', path
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    print(f"✅ [FIX_PERMISSIONS] Propriétaire modifié pour {description}")
                else:
                    print(f"⚠️ [FIX_PERMISSIONS] Erreur chown pour {description}: {result.stderr}")
                    return False
                
                # Définir les permissions appropriées
                # Dossiers : 755 (rwxr-xr-x) - lecture/écriture pour le propriétaire, lecture pour les autres
                # Fichiers : 644 (rw-r--r--) - lecture/écriture pour le propriétaire, lecture pour les autres
                
                # Permissions des dossiers
                result = subprocess.run([
                    'find', path, '-type', 'd', '-exec', 'chmod', '755', '{}', '+'
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    print(f"✅ [FIX_PERMISSIONS] Permissions dossiers modifiées pour {description}")
                else:
                    print(f"⚠️ [FIX_PERMISSIONS] Erreur permissions dossiers: {result.stderr}")
                
                # Permissions des fichiers
                result = subprocess.run([
                    'find', path, '-type', 'f', '-exec', 'chmod', '644', '{}', '+'
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    print(f"✅ [FIX_PERMISSIONS] Permissions fichiers modifiées pour {description}")
                else:
                    print(f"⚠️ [FIX_PERMISSIONS] Erreur permissions fichiers: {result.stderr}")
                
                # Permissions spéciales pour les dossiers d'uploads (775 pour permettre l'écriture web)
                uploads_path = os.path.join(path, 'wp-content', 'uploads')
                if os.path.exists(uploads_path):
                    subprocess.run(['chmod', '-R', '775', uploads_path], 
                                 capture_output=True, text=True, timeout=10)
                    print(f"✅ [FIX_PERMISSIONS] Permissions uploads spéciales appliquées")
                
                return True
                
            except subprocess.TimeoutExpired:
                print(f"❌ [FIX_PERMISSIONS] Timeout lors de la correction de {description}")
                return False
            except Exception as e:
                print(f"❌ [FIX_PERMISSIONS] Erreur lors de la correction de {description}: {e}")
                return False
        
        # Corriger les permissions du projet
        success = fix_directory_permissions(project_path, f"projet {project_name}")
        
        # Redémarrer le projet s'il était en cours d'exécution
        if was_running and docker_service:
            print(f"🚀 [FIX_PERMISSIONS] Redémarrage du projet...")
            start_success, start_error = docker_service.start_containers(project.container_path)
            if not start_success:
                print(f"⚠️ [FIX_PERMISSIONS] Erreur lors du redémarrage: {start_error}")
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Permissions corrigées avec succès pour {project_name}',
                'details': {
                    'project_path': project_path,
                    'owner': current_user,
                    'restarted': was_running
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Erreur lors de la correction des permissions pour {project_name}'
            })
        
    except Exception as e:
        print(f"❌ [FIX_PERMISSIONS] Erreur critique: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@project_nextjs_bp.route('/fix_permissions_simple/<project_name>', methods=['POST'])
@login_required
def fix_permissions_simple(project_name):
    """Corrige simplement les permissions d'un projet sans vérifications Docker"""
    try:
        # Chemin direct du projet (chemin absolu)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        app_root = os.path.dirname(current_dir)
        project_path = os.path.join(app_root, PROJECTS_FOLDER, project_name)
        print(f"📂 [FIX_PERMISSIONS_SIMPLE] Chemin testé: {project_path}")
        
        if not os.path.exists(project_path):
            return jsonify({'success': False, 'message': f'Projet {project_name} non trouvé'})
        
        print(f"🔧 [FIX_PERMISSIONS_SIMPLE] Correction des permissions pour: {project_name}")
        
        # Obtenir l'utilisateur actuel
        import pwd
        current_user = pwd.getpwuid(os.getuid()).pw_name
        print(f"📋 [FIX_PERMISSIONS_SIMPLE] Utilisateur: {current_user}")
        
        # Appliquer les permissions directement
        from app.utils.project_utils import set_project_permissions
        success = set_project_permissions(project_path, current_user)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Permissions corrigées avec succès pour {project_name}',
                'details': {
                    'project_path': project_path,
                    'owner': current_user
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Erreur lors de la correction des permissions pour {project_name}'
            })
        
    except Exception as e:
        print(f"❌ [FIX_PERMISSIONS_SIMPLE] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


 
@project_nextjs_bp.route('/add_nextjs/<project_name>', methods=['POST'])
@login_required
def add_nextjs(project_name):
    """Ajoute Next.js à un projet WordPress existant"""
    try:
        print(f"🚀 Ajout de Next.js au projet: {project_name}")
        
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier que c'est un projet WordPress
        if project.project_type != 'wordpress':
            return jsonify({'success': False, 'message': 'Next.js ne peut être ajouté qu\'aux projets WordPress'})
        
        # Vérifier que Next.js n'est pas déjà activé
        if project.has_nextjs:
            return jsonify({'success': False, 'message': 'Next.js est déjà activé pour ce projet'})
        
        # Arrêter le projet d'abord
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            print(f"🛑 Arrêt des conteneurs...")
            docker_service.stop_containers(project.container_path)
        
        # Allouer un port pour Next.js
        print(f"🔌 Allocation d'un port pour Next.js...")
        nextjs_port = find_free_port_for_project()
        
        # Sauvegarder le port Next.js
        nextjs_port_file = os.path.join(project.container_path, '.nextjs_port')
        with open(nextjs_port_file, 'w') as f:
            f.write(str(nextjs_port))
        print(f"💾 Port Next.js sauvegardé: {nextjs_port}")
        
        # Mettre à jour le docker-compose.yml pour inclure Next.js
        docker_compose_path = os.path.join(project.container_path, 'docker-compose.yml')
        if os.path.exists(docker_compose_path):
            print(f"🔧 Mise à jour du docker-compose.yml...")
            
            # Lire le fichier actuel
            with open(docker_compose_path, 'r') as f:
                compose_content = f.read()
            
            # Ajouter la section Next.js si elle n'existe pas déjà
            if 'nextjs:' not in compose_content:
                nextjs_service = f"""
  nextjs:
    image: node:18-alpine
    container_name: {project_name}_nextjs_1
    working_dir: /app
    volumes:
      - ../projets/{project_name}/client:/app
    ports:
      - "{nextjs_port}:3000"
    environment:
      - NODE_ENV=development
    command: sh -c "npm install && npm run dev"
    depends_on:
      - wordpress
    networks:
      - {project_name}_network
"""
                # Ajouter le service Next.js à la fin du fichier
                compose_content = compose_content.rstrip() + nextjs_service
                
                # Écrire le fichier mis à jour
                with open(docker_compose_path, 'w') as f:
                    f.write(compose_content)
                
                print(f"✅ Service Next.js ajouté au docker-compose.yml")
        
        # Créer la structure Next.js dans le dossier projet
        nextjs_path = os.path.join(project.path, 'nextjs')
        if not os.path.exists(nextjs_path):
            print(f"📦 Création de la structure Next.js...")
            os.makedirs(nextjs_path, exist_ok=True)
            
            # Créer package.json basique pour Next.js
            package_json = {
                "name": f"{project_name}-nextjs",
                "version": "0.1.0",
                "private": True,
                "scripts": {
                    "dev": "next dev",
                    "build": "next build",
                    "start": "next start",
                    "lint": "next lint"
                },
                "dependencies": {
                    "next": "14.0.0",
                    "react": "^18",
                    "react-dom": "^18"
                },
                "devDependencies": {
                    "@types/node": "^20",
                    "@types/react": "^18",
                    "@types/react-dom": "^18",
                    "eslint": "^8",
                    "eslint-config-next": "14.0.0",
                    "typescript": "^5"
                }
            }
            
            package_json_path = os.path.join(nextjs_path, 'package.json')
            with open(package_json_path, 'w') as f:
                json.dump(package_json, f, indent=2)
            
            # Créer une page d'exemple
            pages_path = os.path.join(nextjs_path, 'pages')
            os.makedirs(pages_path, exist_ok=True)
            
            index_page = """import Head from 'next/head'

export default function Home() {
  return (
    <div>
      <Head>
        <title>{project_name} - Next.js</title>
        <meta name="description" content="Next.js frontend for {project_name}" />
        <link rel="icon" href="/favicon.png" />
      </Head>

      <main style={{ padding: '2rem', textAlign: 'center' }}>
        <h1>Welcome to {project_name} Next.js Frontend</h1>
        <p>This is a headless frontend for your WordPress site.</p>
        <div style={{ marginTop: '2rem' }}>
          <a href="http://{DockerConfig.LOCAL_IP}:{project.port}" target="_blank" rel="noopener noreferrer">
            ← Back to WordPress
          </a>
        </div>
      </main>
    </div>
  )
}
""".replace('{project_name}', project_name).replace('{project.port}', str(project.port))
            
            index_page_path = os.path.join(pages_path, 'index.js')
            with open(index_page_path, 'w') as f:
                f.write(index_page)
            
            print(f"✅ Structure Next.js créée")
        
        # Redémarrer le projet avec Next.js
        if docker_service:
            print(f"🚀 Redémarrage des conteneurs avec Next.js...")
            success, error = docker_service.start_containers(project.container_path)
            if not success:
                return jsonify({'success': False, 'message': f'Erreur lors du redémarrage: {error}'})
        
        return jsonify({
            'success': True,
            'message': f'Next.js ajouté avec succès au projet {project_name}',
            'nextjs_port': nextjs_port,
            'nextjs_url': f'http://{DockerConfig.LOCAL_IP}:{nextjs_port}'
        })
        
    except Exception as e:
        print(f"❌ Erreur lors de l'ajout de Next.js: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@project_nextjs_bp.route('/remove_nextjs/<project_name>', methods=['POST'])
@login_required
def remove_nextjs(project_name):
    """Supprime Next.js d'un projet WordPress"""
    try:
        print(f"🗑️ Suppression de Next.js du projet: {project_name}")
        
        # Vérifier que le projet existe
        project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        if not project.exists:
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        # Vérifier que Next.js est activé
        if not project.has_nextjs:
            return jsonify({'success': False, 'message': 'Next.js n\'est pas activé pour ce projet'})
        
        # Arrêter le projet d'abord
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            print(f"🛑 Arrêt des conteneurs...")
            docker_service.stop_containers(project.container_path)
        
        # Supprimer le port Next.js
        nextjs_port_file = os.path.join(project.container_path, '.nextjs_port')
        if os.path.exists(nextjs_port_file):
            os.remove(nextjs_port_file)
            print(f"🗑️ Fichier de port Next.js supprimé")
        
        # Mettre à jour le docker-compose.yml pour supprimer Next.js
        docker_compose_path = os.path.join(project.container_path, 'docker-compose.yml')
        if os.path.exists(docker_compose_path):
            print(f"🔧 Mise à jour du docker-compose.yml...")
            
            # Lire le fichier actuel
            with open(docker_compose_path, 'r') as f:
                lines = f.readlines()
            
            # Supprimer la section Next.js
            new_lines = []
            skip_section = False
            
            for line in lines:
                if line.strip().startswith('nextjs:'):
                    skip_section = True
                    continue
                elif skip_section and line.startswith('  ') and not line.strip() == '':
                    # On est toujours dans la section Next.js
                    continue
                elif skip_section and (not line.startswith('  ') or line.strip() == ''):
                    # Fin de la section Next.js
                    skip_section = False
                    if line.strip() == '':
                        continue  # Ignorer les lignes vides
                
                if not skip_section:
                    new_lines.append(line)
            
            # Écrire le fichier mis à jour
            with open(docker_compose_path, 'w') as f:
                f.writelines(new_lines)
            
            print(f"✅ Service Next.js supprimé du docker-compose.yml")
        
        # Supprimer le dossier Next.js (optionnel - demander confirmation)
        nextjs_path = os.path.join(project.path, 'nextjs')
        if os.path.exists(nextjs_path):
            import shutil
            shutil.rmtree(nextjs_path)
            print(f"🗑️ Dossier Next.js supprimé")
        
        # Redémarrer le projet sans Next.js
        if docker_service:
            print(f"🚀 Redémarrage des conteneurs sans Next.js...")
            success, error = docker_service.start_containers(project.container_path)
            if not success:
                return jsonify({'success': False, 'message': f'Erreur lors du redémarrage: {error}'})
        
        return jsonify({
            'success': True,
            'message': f'Next.js supprimé avec succès du projet {project_name}'
        })
        
    except Exception as e:
        print(f"❌ Erreur lors de la suppression de Next.js: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'}) 

