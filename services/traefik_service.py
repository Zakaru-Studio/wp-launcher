#!/usr/bin/env python3
"""
Service de gestion Traefik pour l'exposition des sites avec SSL automatique
"""

import os
import json
import subprocess
from typing import Dict, List, Optional
import time
from utils.database_utils import update_wordpress_urls


class TraefikService:
    """Service pour gérer l'exposition des sites via Traefik avec SSL automatique"""
    
    def __init__(self, base_domain='akdigital.fr', projects_folder='projets', containers_folder='containers'):
        self.base_domain = base_domain
        self.dev_domain = f'dev.{base_domain}'
        self.exposed_sites_file = 'exposed_sites.json'
        self.projects_folder = projects_folder
        self.containers_folder = containers_folder
        self.traefik_network = 'traefik-network'
        
        # Configuration Docker
        self.docker_client = None
    
    def ensure_traefik_network(self) -> bool:
        """S'assure que le réseau Traefik existe"""
        try:
            # Vérifier si le réseau existe
            result = subprocess.run([
                'docker', 'network', 'ls', '--format', '{{.Name}}'
            ], capture_output=True, text=True)
            
            networks = result.stdout.strip().split('\n')
            
            if self.traefik_network not in networks:
                # Créer le réseau
                result = subprocess.run([
                    'docker', 'network', 'create', self.traefik_network
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    print(f"✅ Réseau {self.traefik_network} créé")
                    return True
                else:
                    print(f"❌ Erreur création réseau: {result.stderr}")
                    return False
            else:
                print(f"✅ Réseau {self.traefik_network} existe déjà")
                return True
                
        except Exception as e:
            print(f"❌ Erreur vérification réseau: {e}")
            return False
    
    def update_certificates(self) -> Dict:
        """Met à jour les certificats SSL depuis Let's Encrypt"""
        try:
            traefik_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'traefik')
            update_script = os.path.join(traefik_dir, 'update-certificates.sh')
            
            if not os.path.exists(update_script):
                return {
                    'success': False,
                    'message': 'Script de mise à jour des certificats non trouvé'
                }
            
            # Exécuter le script de mise à jour
            result = subprocess.run([
                'bash', update_script
            ], capture_output=True, text=True, cwd=traefik_dir)
            
            if result.returncode == 0:
                return {
                    'success': True,
                    'message': 'Certificats mis à jour avec succès'
                }
            else:
                return {
                    'success': False,
                    'message': f'Erreur lors de la mise à jour: {result.stderr}'
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }
    
    def is_traefik_running(self) -> bool:
        """Vérifie si Traefik est en cours d'exécution"""
        try:
            result = subprocess.run([
                'docker', 'ps', '--format', '{{.Names}}'
            ], capture_output=True, text=True)
            
            running_containers = result.stdout.strip().split('\n')
            return 'traefik' in running_containers
            
        except Exception as e:
            print(f"❌ Erreur vérification Traefik: {e}")
            return False
    
    def start_traefik(self) -> Dict:
        """Démarre Traefik si nécessaire"""
        try:
            if self.is_traefik_running():
                return {
                    'success': True,
                    'message': 'Traefik est déjà en cours d\'exécution'
                }
            
            # S'assurer que le réseau existe
            if not self.ensure_traefik_network():
                return {
                    'success': False,
                    'message': 'Impossible de créer le réseau Traefik'
                }
            
            # Démarrer Traefik
            traefik_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'traefik')
            
            if not os.path.exists(traefik_dir):
                return {
                    'success': False,
                    'message': f'Répertoire Traefik non trouvé: {traefik_dir}'
                }
            
            os.chdir(traefik_dir)
            result = subprocess.run([
                'docker-compose', 'up', '-d'
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                return {
                    'success': True,
                    'message': 'Traefik démarré avec succès'
                }
            else:
                return {
                    'success': False,
                    'message': f'Erreur lors du démarrage: {result.stderr}'
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }
    
    def expose_site(self, project_name: str, hostname: str, port: int, ip: str = '192.168.1.21') -> Dict:
        """Expose un site via Traefik avec SSL automatique"""
        try:
            # Valider le hostname
            if not self._validate_hostname(hostname):
                return {
                    'success': False,
                    'message': f'Hostname invalide. Utilisez un sous-domaine de {self.dev_domain}'
                }
            
            # Vérifier si le hostname est déjà utilisé
            exposed_sites = self.get_exposed_sites()
            for site_data in exposed_sites.values():
                if site_data.get('hostname') == hostname:
                    return {
                        'success': False,
                        'message': f'Le hostname {hostname} est déjà utilisé'
                    }
            
            # Vérifier que Traefik est en cours d'exécution
            if not self.is_traefik_running():
                start_result = self.start_traefik()
                if not start_result['success']:
                    return {
                        'success': False,
                        'message': f'Impossible de démarrer Traefik: {start_result["message"]}'
                    }
            
            # Ajouter le projet au réseau Traefik
            network_result = self._add_project_to_traefik_network(project_name)
            if not network_result['success']:
                return {
                    'success': False,
                    'message': f'Impossible d\'ajouter le projet au réseau Traefik: {network_result["message"]}'
                }
            
            # Mettre à jour les labels Traefik du projet
            labels_result = self._update_project_traefik_labels(project_name, hostname)
            if not labels_result['success']:
                return {
                    'success': False,
                    'message': f'Impossible de mettre à jour les labels Traefik: {labels_result["message"]}'
                }
            
            # Recharger la configuration Docker Compose pour Traefik
            reload_result = self._reload_project_compose(project_name)
            if not reload_result['success']:
                print(f"⚠️ Avertissement: {reload_result['message']}")
                # On continue car Traefik peut détecter les changements automatiquement
            
            # Sauvegarder dans le fichier JSON
            exposed_sites[project_name] = {
                'hostname': hostname,
                'port': port,
                'ip': ip,
                'ssl_enabled': True,
                'ssl_forced': True,
                'ssl_type': 'wildcard_letsencrypt',
                'exposed_at': self._get_current_timestamp(),
                'traefik_setup': True
            }
            self.save_exposed_sites(exposed_sites)
            
            # Mettre à jour les URLs WordPress dans la base de données
            try:
                container_path = os.path.join(self.containers_folder, project_name)
                new_url = f'https://{hostname}'
                
                print(f"🔄 Mise à jour des URLs WordPress pour {project_name}...")
                update_success = update_wordpress_urls(container_path, project_name, new_url)
                
                if update_success:
                    print(f"✅ URLs WordPress mises à jour avec succès")
                else:
                    print(f"⚠️ Erreur lors de la mise à jour des URLs WordPress")
                    
            except Exception as e:
                print(f"⚠️ Erreur lors de la mise à jour des URLs WordPress: {e}")
                # On continue car l'exposition est réussie même si la mise à jour échoue
            
            return {
                'success': True,
                'message': f'Site exposé avec succès sur https://{hostname}',
                'url': f'https://{hostname}',
                'ssl_info': 'Certificat SSL wildcard Let\'s Encrypt utilisé automatiquement'
            }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur lors de l\'exposition du site: {str(e)}'
            }
    
    def unexpose_site(self, project_name: str) -> Dict:
        """Retire l'exposition d'un site"""
        try:
            exposed_sites = self.get_exposed_sites()
            
            if project_name not in exposed_sites:
                return {
                    'success': False,
                    'message': 'Site non exposé'
                }
            
            # Supprimer les labels Traefik du projet
            labels_result = self._remove_project_traefik_labels(project_name)
            if not labels_result['success']:
                return {
                    'success': False,
                    'message': f'Impossible de supprimer les labels Traefik: {labels_result["message"]}'
                }
            
            # Recharger la configuration Docker Compose pour Traefik (sans redémarrage)
            reload_result = self._reload_project_compose(project_name)
            if not reload_result['success']:
                print(f"⚠️ Erreur lors du rechargement, utilisation du mode sécurisé: {reload_result['message']}")
                # En cas d'échec, utiliser le mode forcé sécurisé
                return self.force_unexpose_site(project_name)
            
            # Supprimer du fichier JSON
            del exposed_sites[project_name]
            self.save_exposed_sites(exposed_sites)
            
            return {
                'success': True,
                'message': f'Site retiré d\'internet avec succès'
            }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur lors du retrait du site: {str(e)}'
            }
    
    def force_unexpose_site(self, project_name: str) -> Dict:
        """Force le retrait d'exposition sans toucher aux conteneurs (mode sécurisé)"""
        try:
            exposed_sites = self.get_exposed_sites()
            
            if project_name not in exposed_sites:
                return {
                    'success': False,
                    'message': 'Site non exposé'
                }
            
            # Supprimer seulement du fichier JSON sans toucher aux conteneurs
            del exposed_sites[project_name]
            self.save_exposed_sites(exposed_sites)
            
            return {
                'success': True,
                'message': f'Site {project_name} retiré du registre (les labels Docker restent actifs)',
                'warning': 'Les labels Traefik sont toujours présents dans docker-compose.yml. Redémarrez manuellement le projet si nécessaire.'
            }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur lors du retrait forcé: {str(e)}'
            }
    
    def _add_project_to_traefik_network(self, project_name: str) -> Dict:
        """Ajoute un projet au réseau Traefik"""
        try:
            container_path = os.path.join(self.containers_folder, project_name)
            compose_file = os.path.join(container_path, 'docker-compose.yml')
            
            if not os.path.exists(compose_file):
                return {
                    'success': False,
                    'message': f'Fichier docker-compose.yml non trouvé: {compose_file}'
                }
            
            # Lire le fichier docker-compose.yml
            with open(compose_file, 'r') as f:
                content = f.read()
            
            # Ajouter le réseau Traefik s'il n'existe pas
            if 'traefik-network:' not in content:
                # Ajouter le réseau externe
                if 'networks:' in content:
                    content = content.replace(
                        'networks:',
                        f'networks:\n  {self.traefik_network}:\n    external: true'
                    )
                else:
                    content += f'\n\nnetworks:\n  {self.traefik_network}:\n    external: true'
                
                # Connecter les services au réseau Traefik
                lines = content.split('\n')
                new_lines = []
                in_service = False
                service_name = None
                
                for line in lines:
                    new_lines.append(line)
                    
                    # Détecter le début d'un service
                    if line.strip().endswith(':') and not line.startswith(' ') and line.strip() not in ['version:', 'services:', 'volumes:', 'networks:']:
                        in_service = True
                        service_name = line.strip().replace(':', '')
                    
                    # Ajouter le réseau Traefik aux services web
                    if in_service and 'networks:' in line and service_name in ['wordpress', 'nextjs', 'api']:
                        # Ajouter le réseau Traefik
                        indent = len(line) - len(line.lstrip())
                        new_lines.append(' ' * indent + f'- {self.traefik_network}')
                
                content = '\n'.join(new_lines)
                
                # Sauvegarder le fichier modifié
                with open(compose_file, 'w') as f:
                    f.write(content)
                
                print(f"✅ Réseau Traefik ajouté au projet {project_name}")
            
            return {
                'success': True,
                'message': 'Projet ajouté au réseau Traefik'
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }
    
    def _update_project_traefik_labels(self, project_name: str, hostname: str) -> Dict:
        """Met à jour les labels Traefik d'un projet"""
        try:
            container_path = os.path.join(self.containers_folder, project_name)
            compose_file = os.path.join(container_path, 'docker-compose.yml')
            
            if not os.path.exists(compose_file):
                return {
                    'success': False,
                    'message': f'Fichier docker-compose.yml non trouvé: {compose_file}'
                }
            
            # Lire le fichier docker-compose.yml
            with open(compose_file, 'r') as f:
                content = f.read()
            
            # Générer les labels Traefik pour WordPress
            traefik_labels = self._generate_traefik_labels(project_name, hostname, 'wordpress')
            
            # Ajouter les labels au service WordPress
            content = self._add_labels_to_service(content, 'wordpress', traefik_labels)
            
            # Sauvegarder le fichier modifié
            with open(compose_file, 'w') as f:
                f.write(content)
            
            return {
                'success': True,
                'message': 'Labels Traefik mis à jour'
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }
    
    def _remove_project_traefik_labels(self, project_name: str) -> Dict:
        """Supprime les labels Traefik d'un projet"""
        try:
            container_path = os.path.join(self.containers_folder, project_name)
            compose_file = os.path.join(container_path, 'docker-compose.yml')
            
            if not os.path.exists(compose_file):
                return {
                    'success': False,
                    'message': f'Fichier docker-compose.yml non trouvé: {compose_file}'
                }
            
            # Lire le fichier docker-compose.yml
            with open(compose_file, 'r') as f:
                content = f.read()
            
            # Supprimer les labels Traefik
            lines = content.split('\n')
            new_lines = []
            in_labels = False
            
            for line in lines:
                if 'labels:' in line:
                    in_labels = True
                    new_lines.append(line)
                elif in_labels and line.strip().startswith('- "traefik.'):
                    # Ignorer les labels Traefik
                    continue
                elif in_labels and (line.strip() == '' or not line.startswith('  ')):
                    # Fin de la section labels
                    in_labels = False
                    new_lines.append(line)
                else:
                    new_lines.append(line)
            
            content = '\n'.join(new_lines)
            
            # Sauvegarder le fichier modifié
            with open(compose_file, 'w') as f:
                f.write(content)
            
            return {
                'success': True,
                'message': 'Labels Traefik supprimés'
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }
    
    def _generate_traefik_labels(self, project_name: str, hostname: str, service_name: str) -> List[str]:
        """Génère les labels Traefik pour un service avec certificat wildcard"""
        labels = [
            f'"traefik.enable=true"',
            f'"traefik.http.routers.{project_name}-{service_name}.rule=Host(`{hostname}`)"',
            f'"traefik.http.routers.{project_name}-{service_name}.entrypoints=websecure"',
            f'"traefik.http.routers.{project_name}-{service_name}.tls=true"',
            f'"traefik.http.services.{project_name}-{service_name}.loadbalancer.server.port=80"',
            f'"traefik.http.routers.{project_name}-{service_name}.middlewares=default-headers"',
            f'"traefik.docker.network={self.traefik_network}"'
        ]
        
        return labels
    
    def _add_labels_to_service(self, content: str, service_name: str, labels: List[str]) -> str:
        """Ajoute des labels à un service dans le docker-compose.yml"""
        lines = content.split('\n')
        new_lines = []
        in_service = False
        service_found = False
        labels_added = False
        
        for i, line in enumerate(lines):
            # Détecter le début du service
            if line.strip() == f'{service_name}:':
                in_service = True
                service_found = True
                new_lines.append(line)
                continue
            
            # Détecter la fin du service
            if in_service and line.strip() and not line.startswith(' '):
                in_service = False
                
                # Ajouter les labels si pas encore fait
                if not labels_added:
                    new_lines.append('    labels:')
                    for label in labels:
                        new_lines.append(f'      - {label}')
                    labels_added = True
                
                new_lines.append(line)
                continue
            
            # Si on est dans le service et on trouve une section labels
            if in_service and 'labels:' in line:
                new_lines.append(line)
                # Ajouter nos labels
                for label in labels:
                    new_lines.append(f'      - {label}')
                labels_added = True
                continue
            
            new_lines.append(line)
        
        # Si on a trouvé le service mais pas ajouté les labels
        if service_found and not labels_added:
            # Ajouter les labels à la fin du service
            for i in range(len(new_lines) - 1, -1, -1):
                if new_lines[i].strip().startswith(service_name + ':'):
                    # Trouver la fin du service
                    j = i + 1
                    while j < len(new_lines) and (new_lines[j].startswith('  ') or new_lines[j].strip() == ''):
                        j += 1
                    
                    # Insérer les labels
                    labels_lines = ['    labels:']
                    for label in labels:
                        labels_lines.append(f'      - {label}')
                    
                    new_lines = new_lines[:j] + labels_lines + new_lines[j:]
                    break
        
        return '\n'.join(new_lines)
    
    def _reload_project_compose(self, project_name: str) -> Dict:
        """Recharge la configuration Docker Compose sans redémarrer les conteneurs"""
        try:
            container_path = os.path.join(self.containers_folder, project_name)
            
            if not os.path.exists(container_path):
                return {
                    'success': False,
                    'message': f'Projet non trouvé: {container_path}'
                }
            
            # Changer de répertoire
            original_cwd = os.getcwd()
            os.chdir(container_path)
            
            try:
                # Recharger la configuration en mode sécurisé
                result = subprocess.run([
                    'docker-compose', 'up', '-d'
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    return {
                        'success': True,
                        'message': 'Configuration rechargée'
                    }
                else:
                    return {
                        'success': False,
                        'message': f'Erreur rechargement: {result.stderr}'
                    }
                    
            finally:
                os.chdir(original_cwd)
                
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'message': 'Timeout lors du rechargement'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }

    def _restart_project_containers(self, project_name: str) -> Dict:
        """Redémarre les conteneurs d'un projet (restart simple)"""
        try:
            container_path = os.path.join(self.containers_folder, project_name)
            
            if not os.path.exists(container_path):
                return {
                    'success': False,
                    'message': f'Projet non trouvé: {container_path}'
                }
            
            # Changer de répertoire
            original_cwd = os.getcwd()
            os.chdir(container_path)
            
            try:
                # Redémarrer les conteneurs sans recréation forcée
                result = subprocess.run([
                    'docker-compose', 'restart'
                ], capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    return {
                        'success': True,
                        'message': 'Conteneurs redémarrés'
                    }
                else:
                    # Si le restart échoue, essayer juste d'arrêter et redémarrer
                    print(f"⚠️ Restart failed, trying stop/start: {result.stderr}")
                    
                    # Arrêter
                    stop_result = subprocess.run([
                        'docker-compose', 'stop'
                    ], capture_output=True, text=True, timeout=30)
                    
                    # Redémarrer sans forcer la recréation
                    start_result = subprocess.run([
                        'docker-compose', 'up', '-d'
                    ], capture_output=True, text=True, timeout=60)
                    
                    if start_result.returncode == 0:
                        return {
                            'success': True,
                            'message': 'Conteneurs redémarrés après stop/start'
                        }
                    else:
                        return {
                            'success': False,
                            'message': f'Erreur redémarrage: {start_result.stderr}'
                        }
                    
            finally:
                os.chdir(original_cwd)
                
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'message': 'Timeout lors du redémarrage des conteneurs'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }
    
    def get_exposed_sites(self) -> Dict:
        """Récupère la liste des sites exposés depuis le fichier JSON"""
        if os.path.exists(self.exposed_sites_file):
            try:
                with open(self.exposed_sites_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}
    
    def save_exposed_sites(self, sites: Dict):
        """Sauvegarde la liste des sites exposés dans le fichier JSON"""
        with open(self.exposed_sites_file, 'w') as f:
            json.dump(sites, f, indent=2)
    
    def _validate_hostname(self, hostname: str) -> bool:
        """Valide que le hostname est un sous-domaine valide"""
        return hostname.endswith(f'.{self.dev_domain}') and len(hostname) > len(self.dev_domain) + 1
    
    def _get_current_timestamp(self) -> str:
        """Retourne le timestamp actuel"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def get_traefik_status(self) -> Dict:
        """Récupère le statut de Traefik"""
        try:
            is_running = self.is_traefik_running()
            network_exists = self.traefik_network in subprocess.run([
                'docker', 'network', 'ls', '--format', '{{.Name}}'
            ], capture_output=True, text=True).stdout
            
            return {
                'success': True,
                'status': {
                    'traefik_running': is_running,
                    'network_exists': network_exists,
                    'dashboard_url': 'http://localhost:8080' if is_running else None,
                    'secure_dashboard_url': f'https://traefik.{self.dev_domain}' if is_running else None
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            } 