#!/usr/bin/env python3
"""
Script d'intégration automatique des hostnames avec WP Launcher
Intègre DNS local et reverse proxy avec la création/suppression de projets
"""

import os
import subprocess
import sys
from pathlib import Path

class HostnameManager:
    """Gestionnaire des hostnames pour WP Launcher"""
    
    def __init__(self):
        self.server_ip = "192.168.1.21"
        self.wp_launcher_dir = Path("/home/dev-server/Sites/wp-launcher")
        self.projects_dir = self.wp_launcher_dir / "projets"
        
    def is_dnsmasq_installed(self):
        """Vérifie si dnsmasq est installé"""
        try:
            result = subprocess.run(['which', 'dnsmasq'], capture_output=True)
            return result.returncode == 0
        except:
            return False
    
    def is_nginx_installed(self):
        """Vérifie si nginx est installé"""
        try:
            result = subprocess.run(['which', 'nginx'], capture_output=True)
            return result.returncode == 0
        except:
            return False
    
    def add_project_to_dns(self, project_name, hostname):
        """Ajoute un projet au DNS local"""
        if not self.is_dnsmasq_installed():
            print("⚠️ dnsmasq non installé, DNS local non configuré")
            return False
        
        try:
            # Ajouter au fichier hosts local
            hosts_file = Path("/etc/hosts.wp-launcher")
            if hosts_file.exists():
                with open(hosts_file, 'a') as f:
                    f.write(f"{self.server_ip} {hostname}\n")
                
                # Redémarrer dnsmasq
                subprocess.run(['sudo', 'systemctl', 'restart', 'dnsmasq'], check=True)
                print(f"✅ DNS: {hostname} ajouté")
                return True
        except Exception as e:
            print(f"❌ Erreur DNS: {e}")
            return False
    
    def remove_project_from_dns(self, hostname):
        """Supprime un projet du DNS local"""
        if not self.is_dnsmasq_installed():
            return False
        
        try:
            hosts_file = Path("/etc/hosts.wp-launcher")
            if hosts_file.exists():
                # Lire le fichier et supprimer la ligne
                with open(hosts_file, 'r') as f:
                    lines = f.readlines()
                
                # Réécrire sans la ligne du hostname
                with open(hosts_file, 'w') as f:
                    for line in lines:
                        if not line.strip().endswith(hostname):
                            f.write(line)
                
                # Redémarrer dnsmasq
                subprocess.run(['sudo', 'systemctl', 'restart', 'dnsmasq'], check=True)
                print(f"✅ DNS: {hostname} supprimé")
                return True
        except Exception as e:
            print(f"❌ Erreur DNS: {e}")
            return False
    
    def add_project_to_proxy(self, project_name, hostname, port):
        """Ajoute un projet au reverse proxy"""
        if not self.is_nginx_installed():
            print("⚠️ nginx non installé, reverse proxy non configuré")
            return False
        
        try:
            # Utiliser le script wp-launcher-proxy
            result = subprocess.run([
                'sudo', 'wp-launcher-proxy', 'add', 
                project_name, hostname, str(port)
            ], check=True, capture_output=True, text=True)
            
            print(f"✅ Proxy: {hostname} → port {port}")
            return True
        except Exception as e:
            print(f"❌ Erreur Proxy: {e}")
            return False
    
    def remove_project_from_proxy(self, hostname):
        """Supprime un projet du reverse proxy"""
        if not self.is_nginx_installed():
            return False
        
        try:
            subprocess.run([
                'sudo', 'wp-launcher-proxy', 'remove', hostname
            ], check=True)
            
            print(f"✅ Proxy: {hostname} supprimé")
            return True
        except Exception as e:
            print(f"❌ Erreur Proxy: {e}")
            return False
    
    def sync_all_projects(self):
        """Synchronise tous les projets existants"""
        print("🔄 Synchronisation de tous les projets...")
        
        if not self.projects_dir.exists():
            print("❌ Dossier projets non trouvé")
            return
        
        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir():
                project_name = project_dir.name
                
                # Lire l'hostname
                hostname_file = project_dir / ".hostname"
                if hostname_file.exists():
                    hostname = hostname_file.read_text().strip()
                else:
                    hostname = f"{project_name}.local"
                
                # Lire le port
                port_file = project_dir / ".port"
                if port_file.exists():
                    port = int(port_file.read_text().strip())
                else:
                    port = 8080
                
                # Ajouter au DNS et proxy
                self.add_project_to_dns(project_name, hostname)
                self.add_project_to_proxy(project_name, hostname, port)
        
        print("✅ Synchronisation terminée")
    
    def generate_hosts_file(self):
        """Génère le fichier hosts pour Windows"""
        print("📝 Génération du fichier hosts pour Windows...")
        
        hosts_content = [
            f"# Entrées hosts pour WP Launcher - Généré automatiquement",
            f"# Copiez ces lignes dans C:\\Windows\\System32\\drivers\\etc\\hosts",
            ""
        ]
        
        if self.projects_dir.exists():
            for project_dir in self.projects_dir.iterdir():
                if project_dir.is_dir():
                    project_name = project_dir.name
                    
                    hostname_file = project_dir / ".hostname"
                    if hostname_file.exists():
                        hostname = hostname_file.read_text().strip()
                    else:
                        hostname = f"{project_name}.local"
                    
                    hosts_content.append(f"{self.server_ip} {hostname}")
        
        hosts_content.extend(["", "# Fin des entrées WP Launcher"])
        
        # Écrire le fichier
        with open("hosts_entries_windows.txt", "w") as f:
            f.write("\n".join(hosts_content))
        
        print("✅ Fichier hosts_entries_windows.txt généré")

def main():
    """Fonction principale"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python integrate_hostname_automation.py add PROJECT_NAME HOSTNAME PORT")
        print("  python integrate_hostname_automation.py remove PROJECT_NAME HOSTNAME")
        print("  python integrate_hostname_automation.py sync")
        print("  python integrate_hostname_automation.py generate-hosts")
        return
    
    manager = HostnameManager()
    command = sys.argv[1]
    
    if command == "add":
        if len(sys.argv) != 5:
            print("❌ Usage: add PROJECT_NAME HOSTNAME PORT")
            return
        
        project_name = sys.argv[2]
        hostname = sys.argv[3]
        port = int(sys.argv[4])
        
        print(f"➕ Ajout du projet {project_name} ({hostname}:{port})")
        manager.add_project_to_dns(project_name, hostname)
        manager.add_project_to_proxy(project_name, hostname, port)
        manager.generate_hosts_file()
    
    elif command == "remove":
        if len(sys.argv) != 4:
            print("❌ Usage: remove PROJECT_NAME HOSTNAME")
            return
        
        project_name = sys.argv[2]
        hostname = sys.argv[3]
        
        print(f"➖ Suppression du projet {project_name} ({hostname})")
        manager.remove_project_from_dns(hostname)
        manager.remove_project_from_proxy(hostname)
        manager.generate_hosts_file()
    
    elif command == "sync":
        manager.sync_all_projects()
        manager.generate_hosts_file()
    
    elif command == "generate-hosts":
        manager.generate_hosts_file()
    
    else:
        print(f"❌ Commande inconnue: {command}")

if __name__ == "__main__":
    main() 