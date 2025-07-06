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
        """Traite une archive WP Migrate Pro"""
        temp_extract_path = os.path.join(upload_folder, f'temp_extract_{self.name}')
        os.makedirs(temp_extract_path, exist_ok=True)
        
        # Extraire l'archive
        extract_zip(archive_path, temp_extract_path)
        
        # Vérifier la structure WP Migrate Pro
        expected_wp_content = os.path.join(temp_extract_path, 'app', 'public', 'wp-content')
        expected_sql = os.path.join(temp_extract_path, 'app', 'sql', 'local.sql')
        
        wp_content_path = None
        db_path = None
        
        if os.path.exists(expected_wp_content):
            wp_content_path = expected_wp_content
        
        if os.path.exists(expected_sql):
            db_path = expected_sql
        
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