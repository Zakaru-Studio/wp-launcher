#!/usr/bin/env python3
"""
Routes pour la maintenance et diagnostics des projets
"""

import os
import subprocess
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from app.utils.logger import wp_logger
from app.utils.project_utils import secure_project_name
from app.models.project import Project
from app.utils.port_conflict_resolver import PortConflictResolver
from app.config.docker_config import DockerConfig

project_maintenance_bp = Blueprint('project_maintenance', __name__)

# Configuration des constantes
PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'

@project_maintenance_bp.route('/fix_permissions_old/<project_name>', methods=['POST'])
def fix_project_permissions(project_name):
    """Applique les permissions correctes à un projet existant (ancienne version)"""
    try:
        print(f"🔧 Correction permissions pour le projet: {project_name}")
        
        # Sécuriser le nom du projet
        from app.utils.project_utils import secure_project_name
        project_name = secure_project_name(project_name)
        
        # Vérifier que le projet existe
        editable_path = os.path.join(current_app.config['PROJECTS_FOLDER'], project_name)
        if not os.path.exists(editable_path):
            return jsonify({'success': False, 'message': f'Projet {project_name} non trouvé'})
        
        # Déterminer le type de projet
        from app.utils.project_utils import get_project_type
        project_type = get_project_type(editable_path)
        
        # Appliquer les permissions
        from app.utils.project_utils import apply_automatic_project_permissions
        success = apply_automatic_project_permissions(editable_path, project_type)
        
        if success:
            print(f"✅ Permissions corrigées pour {project_name}")
            return jsonify({
                'success': True, 
                'message': f'Permissions corrigées pour {project_name}',
                'project_name': project_name
            })
        else:
            print(f"❌ Échec de la correction des permissions pour {project_name}")
            return jsonify({
                'success': False, 
                'message': f'Échec de la correction des permissions pour {project_name}'
            })
            
    except Exception as e:
        print(f"❌ Erreur lors de la correction des permissions: {e}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@project_maintenance_bp.route('/cleanup_containers', methods=['POST'])
def cleanup_containers():
    """Nettoie les conteneurs orphelins"""
    try:
        subprocess.run(['docker', 'container', 'prune', '-f'], 
                      capture_output=True, text=True)
        
        return jsonify({
            'success': True,
            'message': 'Conteneurs orphelins nettoyés'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        }) 

@project_maintenance_bp.route('/resolve_port_conflicts', methods=['POST'])
def resolve_port_conflicts():
    """Résout automatiquement les conflits de ports"""
    try:
        data = request.get_json() or {}
        project_name = data.get('project_name')
        
        resolver = PortConflictResolver()
        
        if project_name:
            # Résoudre les conflits pour un projet spécifique
            result = resolver.resolve_project_conflicts(project_name)
            return jsonify(result)
        else:
            # Diagnostic général
            report = resolver.get_diagnostic_report()
            return jsonify({
                'success': True,
                'diagnostic': report
            })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erreur lors de la résolution des conflits: {str(e)}'
        }), 500

@project_maintenance_bp.route('/port_diagnostic', methods=['GET'])
def port_diagnostic():
    """Obtient un diagnostic complet des ports"""
    try:
        resolver = PortConflictResolver()
        report = resolver.get_diagnostic_report()
        
        return jsonify({
            'success': True,
            'report': report
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erreur lors du diagnostic: {str(e)}'
        }), 500 

@project_maintenance_bp.route('/fix_docker_compose_ports/<project_name>', methods=['POST'])
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


@project_maintenance_bp.route('/fix_permissions/<project_name>', methods=['POST'])
def fix_permissions(project_name):
    """Corrige les permissions d'un projet pour permettre l'édition libre des fichiers"""
    try:
        print(f"🔧 [FIX_PERMISSIONS] Entrée dans fix_permissions avec project_name={project_name}")
        
        # Détecter si c'est une instance dev
        is_dev_instance = '_dev_' in project_name
        target_project = project_name
        instance_slug = None
        
        if is_dev_instance:
            parts = project_name.split('_dev_')
            if len(parts) >= 2:
                target_project = parts[0]
                instance_slug = parts[1]
                print(f"🔧 [FIX_PERMISSIONS] Instance dev détectée: {project_name}")
                print(f"🔧 [FIX_PERMISSIONS] → Parent: {target_project}, Slug: {instance_slug}")
        
        print(f"🔧 [FIX_PERMISSIONS] target_project={target_project}, PROJECTS_FOLDER={PROJECTS_FOLDER}, CONTAINERS_FOLDER={CONTAINERS_FOLDER}")
        
        # Vérifier que le projet parent existe
        project = Project(target_project, PROJECTS_FOLDER, CONTAINERS_FOLDER)
        print(f"🔧 [FIX_PERMISSIONS] project.path={project.path}, project.container_path={project.container_path}, project.exists={project.exists}")
        
        if not project.exists:
            print(f"❌ [FIX_PERMISSIONS] Projet non trouvé!")
            return jsonify({'success': False, 'message': 'Projet non trouvé'})
        
        print(f"🔧 [FIX_PERMISSIONS] Correction des permissions pour: {target_project}")
        
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
            container_status = docker_service.get_container_status(target_project)
            if container_status == 'active':
                print(f"🛑 [FIX_PERMISSIONS] Arrêt COMPLET du projet {target_project}...")
                docker_service.stop_containers(project.container_path)
                was_running = True
                
                # Attendre un peu que Docker libère complètement les fichiers
                import time
                time.sleep(2)
                print(f"⏳ [FIX_PERMISSIONS] Attente de libération des fichiers...")
        
        # Fonction pour corriger les permissions d'un dossier (sans suivre les symlinks)
        def fix_directory_permissions(path, description, follow_symlinks=False):
            try:
                print(f"🔧 [FIX_PERMISSIONS] Correction de {description}: {path}")
                
                # Option -h pour chown : ne pas suivre les symlinks
                chown_cmd = ['sudo', 'chown', '-R']
                if not follow_symlinks:
                    chown_cmd.append('-h')
                chown_cmd.extend([f'{current_user}:{current_user}', path])
                
                result = subprocess.run(chown_cmd, capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    print(f"✅ [FIX_PERMISSIONS] Propriétaire modifié pour {description}")
                else:
                    print(f"⚠️ [FIX_PERMISSIONS] Erreur chown pour {description}: {result.stderr}")
                    return False
                
                # Utiliser -P pour ne pas suivre les symlinks dans find
                # Permissions des dossiers : 755
                result = subprocess.run([
                    'find', '-P', path, '-type', 'd', '-exec', 'chmod', '755', '{}', '+'
                ], capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    print(f"✅ [FIX_PERMISSIONS] Permissions dossiers modifiées pour {description}")
                else:
                    print(f"⚠️ [FIX_PERMISSIONS] Erreur permissions dossiers: {result.stderr}")
                
                # Permissions des fichiers : 644
                result = subprocess.run([
                    'find', '-P', path, '-type', 'f', '-exec', 'chmod', '644', '{}', '+'
                ], capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    print(f"✅ [FIX_PERMISSIONS] Permissions fichiers modifiées pour {description}")
                else:
                    print(f"⚠️ [FIX_PERMISSIONS] Erreur permissions fichiers: {result.stderr}")
                
                # Permissions spéciales pour les dossiers d'uploads (775 pour permettre l'écriture web)
                # Seulement si c'est un vrai dossier (pas un symlink)
                uploads_path = os.path.join(path, 'wp-content', 'uploads')
                if os.path.exists(uploads_path) and not os.path.islink(uploads_path):
                    subprocess.run(['chmod', '-R', '775', uploads_path], 
                                 capture_output=True, text=True, timeout=30)
                    print(f"✅ [FIX_PERMISSIONS] Permissions uploads spéciales appliquées")
                elif os.path.islink(uploads_path):
                    print(f"ℹ️ [FIX_PERMISSIONS] uploads est un symlink, permissions gérées par le parent")
                
                return True
                
            except subprocess.TimeoutExpired:
                print(f"❌ [FIX_PERMISSIONS] Timeout lors de la correction de {description}")
                return False
            except Exception as e:
                print(f"❌ [FIX_PERMISSIONS] Erreur lors de la correction de {description}: {e}")
                return False
        
        # Corriger les permissions du projet parent
        success = fix_directory_permissions(project_path, f"projet {target_project}")
        
        # Si c'est une instance dev, corriger aussi les permissions de l'instance elle-même
        instances_fixed = []
        if is_dev_instance and instance_slug:
            instance_path = os.path.join(project_path, '.dev-instances', instance_slug)
            if os.path.exists(instance_path):
                print(f"🔧 [FIX_PERMISSIONS] Correction instance dev: {instance_path}")
                fix_directory_permissions(instance_path, f"instance {instance_slug}")
                instances_fixed.append(instance_slug)
        else:
            # Corriger toutes les instances dev du projet
            dev_instances_path = os.path.join(project_path, '.dev-instances')
            if os.path.exists(dev_instances_path):
                for slug in os.listdir(dev_instances_path):
                    instance_path = os.path.join(dev_instances_path, slug)
                    if os.path.isdir(instance_path):
                        print(f"🔧 [FIX_PERMISSIONS] Correction instance dev: {slug}")
                        fix_directory_permissions(instance_path, f"instance {slug}")
                        instances_fixed.append(slug)
        
        # Redémarrer le projet s'il était en cours d'exécution
        if was_running and docker_service:
            print(f"🚀 [FIX_PERMISSIONS] Redémarrage du projet...")
            start_success, start_error = docker_service.start_containers(project.container_path)
            if not start_success:
                print(f"⚠️ [FIX_PERMISSIONS] Erreur lors du redémarrage: {start_error}")
        
        if success:
            message = f'Permissions corrigées avec succès pour {target_project}'
            if instances_fixed:
                message += f' (+ {len(instances_fixed)} instance(s) dev)'
            return jsonify({
                'success': True,
                'message': message,
                'details': {
                    'project_path': project_path,
                    'owner': current_user,
                    'restarted': was_running,
                    'instances_fixed': instances_fixed
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Erreur lors de la correction des permissions pour {target_project}'
            })
        
    except Exception as e:
        print(f"❌ [FIX_PERMISSIONS] Erreur critique: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})


@project_maintenance_bp.route('/fix_permissions_simple/<project_name>', methods=['POST'])
def fix_permissions_simple(project_name):
    """Corrige simplement les permissions d'un projet sans vérifications Docker"""
    try:
        # Chemin direct du projet (chemin absolu)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        app_dir = os.path.dirname(current_dir)  # app/
        root_dir = os.path.dirname(app_dir)      # racine du projet
        project_path = os.path.join(root_dir, PROJECTS_FOLDER, project_name)
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


 
@project_maintenance_bp.route('/add_nextjs/<project_name>', methods=['POST'])
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


@project_maintenance_bp.route('/remove_nextjs/<project_name>', methods=['POST'])
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


@project_maintenance_bp.route('/fix_wordpress_permissions/<project_name>', methods=['POST'])
def fix_wordpress_permissions(project_name):
    """Corrige les permissions WordPress pour www-data (wp-content, uploads, plugins, themes)"""
    try:
        # Sécuriser le nom du projet
        original_name = project_name
        project_name = secure_project_name(project_name)
        
        # Chemin du projet (remonter de routes/ vers app/ puis vers la racine)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        app_dir = os.path.dirname(current_dir)  # app/
        root_dir = os.path.dirname(app_dir)      # racine du projet
        
        # Détecter si c'est une instance dev
        is_dev_instance = '_dev_' in project_name
        parent_project = project_name
        instance_slug = None
        
        if is_dev_instance:
            parts = project_name.split('_dev_')
            if len(parts) >= 2:
                parent_project = parts[0]
                instance_slug = parts[1]
                print(f"🔧 [FIX_WP_PERMISSIONS] Instance dev détectée: {project_name}")
                print(f"🔧 [FIX_WP_PERMISSIONS] → Parent: {parent_project}, Slug: {instance_slug}")
        
        # Construire les chemins
        parent_path = os.path.join(root_dir, PROJECTS_FOLDER, parent_project)
        
        print(f"🔧 [FIX_WP_PERMISSIONS] Correction permissions WordPress pour: {project_name}")
        print(f"📂 [FIX_WP_PERMISSIONS] Chemin parent: {parent_path}")
        
        if not os.path.exists(parent_path):
            return jsonify({
                'success': False,
                'message': f'Projet {parent_project} non trouvé'
            })
        
        # Obtenir l'utilisateur courant pour les permissions
        import pwd
        current_user = pwd.getpwuid(os.getuid()).pw_name
        
        # Fonction helper pour corriger les permissions d'un wp-content
        def fix_wp_content_permissions(wp_content_path, label, commands_executed, errors):
            """Corrige les permissions d'un dossier wp-content sans suivre les symlinks
            Utilise current_user:www-data pour permettre l'édition ET l'accès WordPress"""
            if not os.path.exists(wp_content_path):
                print(f"⚠️ [{label}] wp-content non trouvé: {wp_content_path}")
                return
            
            print(f"🔧 [{label}] Correction: {wp_content_path}")
            
            # Propriétaire: current_user:www-data (dev-server peut éditer, www-data peut lire/écrire via groupe)
            ownership = f'{current_user}:www-data'
            
            # 1. Corriger le propriétaire de wp-content (sans suivre symlinks)
            result = subprocess.run(
                ['sudo', 'chown', '-h', ownership, wp_content_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                commands_executed.append(f'{label}: chown {ownership} wp-content')
                print(f"✅ [{label}] Propriétaire wp-content changé → {ownership}")
            else:
                errors.append(f'{label} chown wp-content: {result.stderr}')
            
            # 2. Chmod wp-content
            result = subprocess.run(
                ['sudo', 'chmod', '775', wp_content_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                commands_executed.append(f'{label}: chmod 775 wp-content')
            else:
                errors.append(f'{label} chmod wp-content: {result.stderr}')
            
            # Corriger les sous-dossiers (seulement si ce ne sont pas des symlinks)
            for subdir in ['uploads', 'plugins', 'themes']:
                subdir_path = os.path.join(wp_content_path, subdir)
                if os.path.exists(subdir_path):
                    # Vérifier si c'est un symlink
                    if os.path.islink(subdir_path):
                        print(f"ℹ️ [{label}] {subdir} est un symlink, ignoré")
                        continue
                    
                    # chown récursif sans suivre les symlinks
                    result = subprocess.run(
                        ['sudo', 'chown', '-R', '-h', ownership, subdir_path],
                        capture_output=True, text=True, timeout=60
                    )
                    if result.returncode == 0:
                        commands_executed.append(f'{label}: chown -R {ownership} {subdir}')
                        print(f"✅ [{label}] Propriétaire {subdir} changé → {ownership}")
                    else:
                        errors.append(f'{label} chown {subdir}: {result.stderr}')
                    
                    # chmod récursif
                    result = subprocess.run(
                        ['sudo', 'chmod', '-R', '775', subdir_path],
                        capture_output=True, text=True, timeout=60
                    )
                    if result.returncode == 0:
                        commands_executed.append(f'{label}: chmod -R 775 {subdir}')
                    else:
                        errors.append(f'{label} chmod {subdir}: {result.stderr}')
        
        # Exécuter les commandes de correction de permissions
        commands_executed = []
        errors = []
        
        try:
            # 1. Corriger le projet parent
            parent_wp_content = os.path.join(parent_path, 'wp-content')
            fix_wp_content_permissions(parent_wp_content, 'PARENT', commands_executed, errors)
            
            # 2. Corriger les instances dev
            instances_fixed = []
            dev_instances_path = os.path.join(parent_path, '.dev-instances')
            
            if is_dev_instance and instance_slug:
                # Corriger seulement l'instance spécifiée
                instance_path = os.path.join(dev_instances_path, instance_slug)
                if os.path.exists(instance_path):
                    instance_wp_content = os.path.join(instance_path, 'wp-content')
                    fix_wp_content_permissions(instance_wp_content, f'INSTANCE:{instance_slug}', commands_executed, errors)
                    instances_fixed.append(instance_slug)
            else:
                # Corriger toutes les instances du projet
                if os.path.exists(dev_instances_path):
                    for slug in os.listdir(dev_instances_path):
                        instance_path = os.path.join(dev_instances_path, slug)
                        if os.path.isdir(instance_path):
                            instance_wp_content = os.path.join(instance_path, 'wp-content')
                            fix_wp_content_permissions(instance_wp_content, f'INSTANCE:{slug}', commands_executed, errors)
                            instances_fixed.append(slug)
            
            # Résumé
            if errors:
                print(f"⚠️ [FIX_WP_PERMISSIONS] Corrections avec erreurs: {len(errors)} erreur(s)")
                return jsonify({
                    'success': False,
                    'message': f'Permissions partiellement corrigées avec {len(errors)} erreur(s)',
                    'commands_executed': commands_executed,
                    'errors': errors,
                    'instances_fixed': instances_fixed
                })
            else:
                message = f'Permissions WordPress corrigées avec succès pour {parent_project}'
                if instances_fixed:
                    message += f' (+ {len(instances_fixed)} instance(s) dev)'
                print(f"✅ [FIX_WP_PERMISSIONS] {message}")
                return jsonify({
                    'success': True,
                    'message': message,
                    'commands_executed': commands_executed,
                    'instances_fixed': instances_fixed
                })
        
        except subprocess.TimeoutExpired:
            return jsonify({
                'success': False,
                'message': 'Timeout lors de la correction des permissions'
            })
        except Exception as e:
            print(f"❌ [FIX_WP_PERMISSIONS] Erreur: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': f'Erreur lors de la correction: {str(e)}'
            })
    
    except Exception as e:
        print(f"❌ [FIX_WP_PERMISSIONS] Erreur globale: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })

