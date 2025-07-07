#!/usr/bin/env python3
"""
Modèle Project - Gestion des projets WordPress
"""

import os
import json
import shutil
import tempfile
from werkzeug.utils import secure_filename
from utils.file_utils import extract_zip

class Project:
    """Modèle pour la gestion des projets WordPress"""
    
    def __init__(self, name, projects_folder='projets'):
        self.name = name
        self.projects_folder = projects_folder
        self.path = os.path.join(projects_folder, name)
    
    @property
    def exists(self):
        """Vérifie si le projet existe"""
        return os.path.exists(self.path)
    
    @property
    def is_valid(self):
        """Vérifie si le projet est valide (a un docker-compose.yml)"""
        return os.path.exists(os.path.join(self.path, 'docker-compose.yml'))
    
    @property
    def hostname(self):
        """Récupère l'hostname du projet"""
        hostname_file = os.path.join(self.path, '.hostname')
        if os.path.exists(hostname_file):
            try:
                with open(hostname_file, 'r') as f:
                    return f.read().strip()
            except:
                pass
        return f"{self.name}.local"
    
    @hostname.setter
    def hostname(self, value):
        """Définit l'hostname du projet"""
        hostname_file = os.path.join(self.path, '.hostname')
        with open(hostname_file, 'w') as f:
            f.write(value)
    
    @property
    def port(self):
        """Récupère le port WordPress du projet"""
        return self._get_port('.port', 8080)
    
    @port.setter
    def port(self, value):
        """Définit le port WordPress du projet"""
        self._set_port('.port', value)
    
    @property
    def pma_port(self):
        """Récupère le port phpMyAdmin du projet"""
        return self._get_port('.pma_port')
    
    @pma_port.setter
    def pma_port(self, value):
        """Définit le port phpMyAdmin du projet"""
        self._set_port('.pma_port', value)
    
    @property
    def mailpit_port(self):
        """Récupère le port Mailpit du projet"""
        return self._get_port('.mailpit_port')
    
    @mailpit_port.setter
    def mailpit_port(self, value):
        """Définit le port Mailpit du projet"""
        self._set_port('.mailpit_port', value)
    
    @property
    def smtp_port(self):
        """Récupère le port SMTP du projet"""
        return self._get_port('.smtp_port')
    
    @smtp_port.setter
    def smtp_port(self, value):
        """Définit le port SMTP du projet"""
        self._set_port('.smtp_port', value)
    
    @property
    def nextjs_port(self):
        """Récupère le port Next.js du projet"""
        return self._get_port('.nextjs_port')
    
    @nextjs_port.setter
    def nextjs_port(self, value):
        """Définit le port Next.js du projet"""
        self._set_port('.nextjs_port', value)
    
    @property
    def has_nextjs(self):
        """Vérifie si le projet a Next.js configuré"""
        return os.path.exists(os.path.join(self.path, '.nextjs_port'))
    
    def _get_port(self, port_file, default=None):
        """Récupère un port depuis un fichier"""
        port_path = os.path.join(self.path, port_file)
        if os.path.exists(port_path):
            try:
                with open(port_path, 'r') as f:
                    return int(f.read().strip())
            except:
                pass
        return default
    
    def _set_port(self, port_file, value):
        """Définit un port dans un fichier"""
        port_path = os.path.join(self.path, port_file)
        with open(port_path, 'w') as f:
            f.write(str(value))
    
    def create_directory(self):
        """Crée le répertoire du projet"""
        if not self.exists:
            os.makedirs(self.path, exist_ok=True)
    
    def create_wp_content(self, wp_content_source=None):
        """Crée le dossier wp-content"""
        wp_content_dest = os.path.join(self.path, 'wordpress', 'wp-content')
        os.makedirs(wp_content_dest, exist_ok=True)
        
        if wp_content_source and os.path.exists(wp_content_source):
            # Copier le wp-content depuis la source
            shutil.copytree(wp_content_source, wp_content_dest, dirs_exist_ok=True)
        else:
            # Créer un wp-content vierge
            self._create_default_wp_content(wp_content_dest)
    
    def _create_default_wp_content(self, wp_content_dest):
        """Crée un wp-content vierge avec les éléments de base"""
        # Créer les dossiers de base
        os.makedirs(os.path.join(wp_content_dest, 'themes'), exist_ok=True)
        os.makedirs(os.path.join(wp_content_dest, 'plugins'), exist_ok=True)
        os.makedirs(os.path.join(wp_content_dest, 'uploads'), exist_ok=True)
        
        # Créer un fichier index.php de sécurité
        index_content = "<?php\n// Silence is golden.\n"
        
        for subfolder in ['', 'themes', 'plugins', 'uploads']:
            index_path = os.path.join(wp_content_dest, subfolder, 'index.php')
            with open(index_path, 'w') as f:
                f.write(index_content)
    
    def setup_nextjs(self):
        """Configure Next.js pour le projet"""
        if not self.has_nextjs:
            return False
        
        nextjs_path = os.path.join(self.path, 'nextjs')
        os.makedirs(nextjs_path, exist_ok=True)
        
        # Créer package.json
        package_json = {
            "name": f"{self.name}-frontend",
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
                "eslint": "^8",
                "eslint-config-next": "14.0.0"
            }
        }
        
        with open(os.path.join(nextjs_path, 'package.json'), 'w') as f:
            json.dump(package_json, f, indent=2)
        
        # Créer une page d'exemple
        pages_dir = os.path.join(nextjs_path, 'pages')
        os.makedirs(pages_dir, exist_ok=True)
        
        index_js_content = f"""import React from 'react';

export default function Home() {{
  return (
    <div style={{{{ 
      padding: '2rem', 
      fontFamily: 'Arial, sans-serif',
      maxWidth: '800px',
      margin: '0 auto'
    }}}}>
      <h1>🚀 Frontend Next.js - {self.name}</h1>
      <p>Bienvenue sur votre frontend Next.js headless connecté à WordPress !</p>
      
      <div style={{{{ 
        backgroundColor: '#f5f5f5', 
        padding: '1rem', 
        borderRadius: '8px',
        marginTop: '2rem'
      }}}}>
        <h2>📋 Prochaines étapes</h2>
        <ul>
          <li>Configurez l'API WordPress REST dans <code>pages/api/</code></li>
          <li>Créez vos composants React dans <code>components/</code></li>
          <li>Ajoutez vos styles dans <code>styles/</code></li>
        </ul>
      </div>
    </div>
  );
}}"""
        
        with open(os.path.join(pages_dir, 'index.js'), 'w') as f:
            f.write(index_js_content)
        
        # Créer README
        readme_content = f"""# {self.name} Frontend (Next.js)

Ce dossier contient le frontend Next.js pour le projet {self.name}.

## Démarrage rapide

1. Le conteneur Next.js va automatiquement installer les dépendances
2. Votre application sera disponible sur http://192.168.1.21:{self.nextjs_port}
3. Modifiez les fichiers dans ce dossier pour développer votre frontend

## Structure recommandée

```
nextjs/
├── pages/
│   ├── index.js      # Page d'accueil
│   └── api/          # API routes
├── components/       # Composants React
├── styles/           # Fichiers CSS
└── public/          # Assets statiques
```

## Configuration WordPress Headless

Pour connecter Next.js à WordPress, utilisez l'API REST WordPress :

```javascript
// Exemple de récupération des posts
const response = await fetch('http://192.168.1.21:{self.port}/wp-json/wp/v2/posts');
const posts = await response.json();
```
"""
        
        with open(os.path.join(nextjs_path, 'README.md'), 'w') as f:
            f.write(readme_content)
        
        return True
    
    def remove_nextjs(self):
        """Supprime Next.js du projet"""
        nextjs_port_file = os.path.join(self.path, '.nextjs_port')
        nextjs_path = os.path.join(self.path, 'nextjs')
        
        # Supprimer le fichier de port
        if os.path.exists(nextjs_port_file):
            os.remove(nextjs_port_file)
        
        # Supprimer le dossier nextjs
        if os.path.exists(nextjs_path):
            shutil.rmtree(nextjs_path)
        
        return True
    
    def process_wp_migrate_archive(self, archive_path, upload_folder):
        """Traite une archive WP Migrate Pro ou WP Umbrella"""
        temp_extract_path = os.path.join(upload_folder, f'temp_extract_{self.name}')
        os.makedirs(temp_extract_path, exist_ok=True)
        
        print(f"📦 [EXTRACT] Début de l'extraction de l'archive: {archive_path}")
        print(f"📦 [EXTRACT] Répertoire temporaire: {temp_extract_path}")
        
        # Extraire l'archive
        try:
            extract_zip(archive_path, temp_extract_path)
            print(f"✅ [EXTRACT] Archive extraite avec succès")
        except Exception as e:
            print(f"❌ [EXTRACT] Erreur lors de l'extraction: {e}")
            raise e
        
        # Vérifier le contenu extrait
        extracted_items = os.listdir(temp_extract_path)
        print(f"📦 [EXTRACT] Nombre d'éléments extraits: {len(extracted_items)}")
        
        # Afficher la structure pour débug
        print("🔍 [EXTRACT] Structure de l'archive extraite:")
        for root, dirs, files in os.walk(temp_extract_path):
            level = root.replace(temp_extract_path, '').count(os.sep)
            indent = ' ' * 2 * level
            print(f"{indent}{os.path.basename(root)}/")
            subindent = ' ' * 2 * (level + 1)
            for file in files[:5]:  # Limiter l'affichage
                print(f"{subindent}{file}")
            if len(files) > 5:
                print(f"{subindent}... et {len(files) - 5} autres fichiers")
        
        wp_content_path = None
        db_path = None
        
        # Chercher wp-content et fichier SQL dans toute l'arborescence
        print("🔍 [SEARCH] Recherche de wp-content et fichiers SQL...")
        
        for root, dirs, files in os.walk(temp_extract_path):
            # Chercher wp-content
            if 'wp-content' in dirs:
                potential_wp_content = os.path.join(root, 'wp-content')
                print(f"🔍 [SEARCH] wp-content trouvé à: {potential_wp_content}")
                
                # Vérifier que c'est bien un wp-content valide
                themes_dir = os.path.join(potential_wp_content, 'themes')
                plugins_dir = os.path.join(potential_wp_content, 'plugins')
                uploads_dir = os.path.join(potential_wp_content, 'uploads')
                
                themes_exists = os.path.exists(themes_dir)
                plugins_exists = os.path.exists(plugins_dir)
                uploads_exists = os.path.exists(uploads_dir)
                
                print(f"🔍 [SEARCH] Validation wp-content:")
                print(f"   - themes/: {'✅' if themes_exists else '❌'}")
                print(f"   - plugins/: {'✅' if plugins_exists else '❌'}")
                print(f"   - uploads/: {'✅' if uploads_exists else '❌'}")
                
                if themes_exists or plugins_exists:
                    wp_content_path = potential_wp_content
                    print(f"✅ [SEARCH] wp-content validé: {wp_content_path}")
                    
                    # Compter les éléments
                    if themes_exists:
                        theme_count = len([d for d in os.listdir(themes_dir) if os.path.isdir(os.path.join(themes_dir, d))])
                        print(f"📊 [SEARCH] Nombre de thèmes: {theme_count}")
                    
                    if plugins_exists:
                        plugin_count = len([d for d in os.listdir(plugins_dir) if os.path.isdir(os.path.join(plugins_dir, d))])
                        print(f"📊 [SEARCH] Nombre de plugins: {plugin_count}")
                    
                    break
                else:
                    print(f"⚠️ [SEARCH] wp-content non valide (pas de themes/ ni plugins/)")
            
            # Chercher fichiers SQL
            for file in files:
                if file.endswith('.sql'):
                    potential_sql = os.path.join(root, file)
                    print(f"🔍 [SEARCH] Fichier SQL trouvé: {potential_sql}")
                    print(f"📊 [SEARCH] Taille: {os.path.getsize(potential_sql)} bytes")
                    
                    # Vérifier que le fichier SQL contient du contenu WordPress
                    try:
                        with open(potential_sql, 'r', encoding='utf-8') as f:
                            first_lines = f.read(1000).lower()
                            keywords = ['wordpress', 'wp_options', 'wp_posts', 'create table', 'insert into']
                            found_keywords = [kw for kw in keywords if kw in first_lines]
                            
                            print(f"🔍 [SEARCH] Analyse du contenu SQL:")
                            print(f"   - Mots-clés trouvés: {found_keywords}")
                            
                            if found_keywords:
                                db_path = potential_sql
                                print(f"✅ [SEARCH] Fichier SQL WordPress validé: {db_path}")
                                break
                            else:
                                print(f"⚠️ [SEARCH] Fichier SQL ne semble pas être WordPress")
                    except UnicodeDecodeError:
                        print(f"⚠️ [SEARCH] Erreur UTF-8, test avec latin-1...")
                        try:
                            with open(potential_sql, 'r', encoding='latin-1') as f:
                                first_lines = f.read(1000).lower()
                                keywords = ['wordpress', 'wp_options', 'wp_posts', 'create table', 'insert into']
                                found_keywords = [kw for kw in keywords if kw in first_lines]
                                
                                print(f"🔍 [SEARCH] Analyse du contenu SQL (latin-1):")
                                print(f"   - Mots-clés trouvés: {found_keywords}")
                                
                                if found_keywords:
                                    db_path = potential_sql
                                    print(f"✅ [SEARCH] Fichier SQL WordPress validé (latin-1): {db_path}")
                                    break
                                else:
                                    print(f"⚠️ [SEARCH] Fichier SQL ne semble pas être WordPress (latin-1)")
                        except Exception as e:
                            print(f"❌ [SEARCH] Erreur lors de l'analyse du fichier SQL: {e}")
                            continue
                    except Exception as e:
                        print(f"❌ [SEARCH] Erreur lors de l'analyse du fichier SQL: {e}")
                        continue
        
        # Si on n'a pas trouvé wp-content, chercher des variantes
        if not wp_content_path:
            print("⚠️ [SEARCH] wp-content standard non trouvé, recherche de variantes...")
            for root, dirs, files in os.walk(temp_extract_path):
                # Chercher des dossiers qui contiennent themes/ et plugins/
                has_themes = 'themes' in dirs
                has_plugins = 'plugins' in dirs
                has_uploads = 'uploads' in dirs
                
                if has_themes or has_plugins:
                    print(f"🔍 [SEARCH] Dossier alternatif trouvé: {root}")
                    print(f"   - themes/: {'✅' if has_themes else '❌'}")
                    print(f"   - plugins/: {'✅' if has_plugins else '❌'}")
                    print(f"   - uploads/: {'✅' if has_uploads else '❌'}")
                    
                    # Ce dossier semble être un wp-content
                    wp_content_path = root
                    print(f"✅ [SEARCH] wp-content alternatif validé: {wp_content_path}")
                    break
        
        # Résumé final
        print("📋 [SUMMARY] Résumé de l'extraction:")
        if wp_content_path:
            print(f"✅ [SUMMARY] wp-content trouvé: {wp_content_path}")
        else:
            print(f"❌ [SUMMARY] wp-content non trouvé dans l'archive")
        
        if db_path:
            print(f"✅ [SUMMARY] Base de données trouvée: {db_path}")
            print(f"📊 [SUMMARY] Taille du fichier SQL: {os.path.getsize(db_path)} bytes")
        else:
            print(f"❌ [SUMMARY] Aucune base de données trouvée dans l'archive")
        
        return {
            'wp_content_path': wp_content_path,
            'db_path': db_path,
            'temp_extract_path': temp_extract_path
        }
    
    def cleanup_temp_files(self, temp_paths):
        """Nettoie les fichiers temporaires"""
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                if os.path.isdir(temp_path):
                    shutil.rmtree(temp_path)
                else:
                    os.remove(temp_path)
    
    def to_dict(self):
        """Retourne les informations du projet sous forme de dictionnaire"""
        return {
            'name': self.name,
            'path': self.path,
            'exists': self.exists,
            'is_valid': self.is_valid,
            'hostname': self.hostname,
            'port': self.port,
            'pma_port': self.pma_port,
            'mailpit_port': self.mailpit_port,
            'smtp_port': self.smtp_port,
            'nextjs_port': self.nextjs_port,
            'has_nextjs': self.has_nextjs
        }

    @classmethod
    def list_all(cls, projects_folder='projets'):
        """Liste tous les projets valides"""
        projects = []
        projects_to_cleanup = []
        
        if not os.path.exists(projects_folder):
            return projects, projects_to_cleanup
        
        for project_name in os.listdir(projects_folder):
            project_path = os.path.join(projects_folder, project_name)
            
            try:
                if not os.path.isdir(project_path):
                    continue
                
                # Test d'accès en lecture au dossier
                try:
                    os.listdir(project_path)
                except PermissionError:
                    projects_to_cleanup.append(project_path)
                    continue
                
                project = cls(project_name, projects_folder)
                
                if not project.is_valid:
                    projects_to_cleanup.append(project_path)
                    continue
                
                projects.append(project)
                
            except Exception as e:
                projects_to_cleanup.append(project_path)
                continue
        
        return projects, projects_to_cleanup 