#!/usr/bin/env python3
"""
Script de migration des instances de développement
Migre de projets/.dev-instances/ vers projets/{project}/.dev-instances/
Et simplifie les noms de dossiers
"""

import os
import shutil
import sqlite3
import json
import subprocess
from datetime import datetime

# Chemins
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD_INSTANCES_DIR = os.path.join(BASE_DIR, 'projets', '.dev-instances')
PROJECTS_DIR = os.path.join(BASE_DIR, 'projets')
DB_PATH = os.path.join(BASE_DIR, 'data', 'dev_instances.db')

def log(message):
    """Log avec timestamp"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def get_instances_from_db():
    """Récupérer toutes les instances de la base de données"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, parent_project, owner_username, port, ports, db_name, created_at, status
        FROM dev_instances
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def parse_instance_name(name):
    """Parser le nom d'instance pour extraire le parent et le slug
    Ex: test-dev-pancin -> (test, pancin)
    """
    if '-dev-' in name:
        parts = name.split('-dev-')
        return parts[0], parts[1]
    return None, None

def stop_container(container_name):
    """Arrêter un conteneur Docker"""
    try:
        subprocess.run(['docker', 'stop', container_name], 
                      capture_output=True, timeout=30)
        log(f"  ✓ Conteneur {container_name} arrêté")
        return True
    except Exception as e:
        log(f"  ⚠ Erreur arrêt conteneur {container_name}: {e}")
        return False

def remove_container(container_name):
    """Supprimer un conteneur Docker"""
    try:
        subprocess.run(['docker', 'rm', container_name], 
                      capture_output=True, timeout=30)
        log(f"  ✓ Conteneur {container_name} supprimé")
        return True
    except Exception as e:
        log(f"  ⚠ Erreur suppression conteneur {container_name}: {e}")
        return False

def create_new_container(parent_project, slug, port, db_name):
    """Créer le nouveau conteneur avec le nom simplifié"""
    new_container_name = f"{parent_project}_{slug}_wordpress"
    instance_path = os.path.join(PROJECTS_DIR, parent_project, '.dev-instances', slug)
    
    # Créer un docker-compose.yml simple pour l'instance
    docker_compose_content = f"""version: '3.8'
services:
  wordpress:
    image: wp-launcher-wordpress:php8.2
    container_name: {new_container_name}
    restart: unless-stopped
    ports:
      - "{port}:80"
    environment:
      WORDPRESS_DB_HOST: {parent_project}_mysql_1
      WORDPRESS_DB_USER: root
      WORDPRESS_DB_PASSWORD: rootpassword
      WORDPRESS_DB_NAME: {db_name}
      WORDPRESS_DEBUG: 0
    volumes:
      - ../../wp-content:/var/www/html/wp-content:rw
      - ./wp-content:/var/www/html/wp-content-instance:rw
    networks:
      - {parent_project}_wordpress_network

networks:
  {parent_project}_wordpress_network:
    external: true
"""
    
    docker_compose_path = os.path.join(instance_path, 'docker-compose.yml')
    with open(docker_compose_path, 'w') as f:
        f.write(docker_compose_content)
    
    log(f"  ✓ docker-compose.yml créé pour {new_container_name}")
    
    # Démarrer le nouveau conteneur
    try:
        os.chdir(instance_path)
        result = subprocess.run(['docker-compose', 'up', '-d'], 
                              capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            log(f"  ✓ Conteneur {new_container_name} démarré")
            return True
        else:
            log(f"  ✗ Erreur démarrage {new_container_name}: {result.stderr}")
            return False
    except Exception as e:
        log(f"  ✗ Exception démarrage {new_container_name}: {e}")
        return False
    finally:
        os.chdir(BASE_DIR)

def migrate_instance(instance_data):
    """Migrer une instance individuelle"""
    id, name, parent_project, owner_username, port, ports_json, db_name, created_at, status = instance_data
    
    log(f"\n{'='*60}")
    log(f"Migration de l'instance: {name}")
    log(f"  Parent: {parent_project}")
    log(f"  Owner: {owner_username}")
    log(f"  Port: {port}")
    log(f"  DB: {db_name}")
    
    # Parser le nom pour obtenir le slug
    parent, slug = parse_instance_name(name)
    if not parent or not slug:
        log(f"  ✗ Impossible de parser le nom {name}, skip")
        return False
    
    # Utiliser owner_username comme slug si différent
    slug = owner_username
    new_name = f"{parent}_dev_{slug}"  # Nouveau nom pour conteneur
    
    log(f"  Nouveau slug: {slug}")
    log(f"  Nouveau nom conteneur: {new_name}_wordpress")
    
    # 1. Créer le nouveau chemin de destination
    old_path = os.path.join(OLD_INSTANCES_DIR, name)
    new_path = os.path.join(PROJECTS_DIR, parent_project, '.dev-instances', slug)
    
    if not os.path.exists(old_path):
        log(f"  ✗ Ancien dossier {old_path} introuvable, skip")
        return False
    
    # Créer le dossier .dev-instances du projet si nécessaire
    dev_instances_dir = os.path.join(PROJECTS_DIR, parent_project, '.dev-instances')
    os.makedirs(dev_instances_dir, exist_ok=True)
    
    # 2. Arrêter et supprimer l'ancien conteneur
    old_container = f"{name}_wordpress"
    log(f"  Arrêt de l'ancien conteneur {old_container}...")
    stop_container(old_container)
    remove_container(old_container)
    
    # 3. Déplacer les fichiers
    if os.path.exists(new_path):
        log(f"  ⚠ Le dossier {new_path} existe déjà, suppression...")
        shutil.rmtree(new_path)
    
    log(f"  Déplacement {old_path} -> {new_path}...")
    shutil.move(old_path, new_path)
    log(f"  ✓ Fichiers déplacés")
    
    # 4. Mettre à jour .metadata.json
    metadata_path = os.path.join(new_path, '.metadata.json')
    if os.path.exists(metadata_path):
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
        
        metadata['slug'] = slug
        metadata['name'] = new_name
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        log(f"  ✓ .metadata.json mis à jour")
    
    # 5. Créer le nouveau conteneur
    log(f"  Création du nouveau conteneur...")
    create_new_container(parent_project, slug, port, db_name)
    
    # 6. Mettre à jour la base de données
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE dev_instances
        SET name = ?
        WHERE id = ?
    """, (new_name, id))
    conn.commit()
    conn.close()
    log(f"  ✓ Base de données mise à jour")
    
    log(f"✅ Migration de {name} terminée avec succès!")
    return True

def main():
    """Fonction principale de migration"""
    log("="*60)
    log("MIGRATION DES INSTANCES DE DÉVELOPPEMENT")
    log("="*60)
    
    # Vérifier que le dossier source existe
    if not os.path.exists(OLD_INSTANCES_DIR):
        log(f"✗ Dossier {OLD_INSTANCES_DIR} introuvable, rien à migrer")
        return
    
    # Récupérer toutes les instances
    instances = get_instances_from_db()
    log(f"\n{len(instances)} instance(s) trouvée(s) dans la base de données")
    
    # Compter les succès/échecs
    success_count = 0
    fail_count = 0
    
    # Migrer chaque instance
    for instance_data in instances:
        try:
            if migrate_instance(instance_data):
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            log(f"✗ ERREUR lors de la migration: {e}")
            fail_count += 1
    
    # Résumé
    log("\n" + "="*60)
    log("RÉSUMÉ DE LA MIGRATION")
    log("="*60)
    log(f"✓ Succès: {success_count}")
    log(f"✗ Échecs: {fail_count}")
    
    # Nettoyer le dossier .dev-instances s'il est vide
    if os.path.exists(OLD_INSTANCES_DIR) and not os.listdir(OLD_INSTANCES_DIR):
        os.rmdir(OLD_INSTANCES_DIR)
        log(f"✓ Dossier {OLD_INSTANCES_DIR} vide supprimé")
    
    log("\n✅ Migration terminée!")

if __name__ == '__main__':
    main()






