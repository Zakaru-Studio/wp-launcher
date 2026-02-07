#!/usr/bin/env python3
"""
Initialization script for multi-dev system
"""
import os
import sys
import sqlite3

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.docker_config import DockerConfig
from app.services.user_service import UserService


def init_databases():
    """Initialize databases"""
    print("Initialisation des bases de données...")
    
    # Create data directory
    os.makedirs('data', exist_ok=True)
    os.makedirs('data/avatars', exist_ok=True)
    
    # Initialize users.db (UserService creates tables automatically)
    print("  - users.db")
    user_service = UserService()
    
    # Initialize dev_instances.db
    print("  - dev_instances.db")
    conn = sqlite3.connect('data/dev_instances.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dev_instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            parent_project TEXT NOT NULL,
            owner_username TEXT NOT NULL,
            port INTEGER UNIQUE NOT NULL,
            db_name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'stopped'
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_owner ON dev_instances(owner_username)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_parent ON dev_instances(parent_project)')
    conn.commit()
    conn.close()
    
    print("✅ Bases de données créées")


def create_admin_user():
    """Create admin user"""
    print("\n" + "="*60)
    print("CRÉATION DE L'UTILISATEUR ADMINISTRATEUR")
    print("="*60)
    
    username = input("\nUsername admin (défaut: admin): ").strip() or "admin"
    email = input("Email admin (défaut: admin@localhost): ").strip() or "admin@localhost"
    
    # Get password
    import getpass
    while True:
        password = getpass.getpass("Mot de passe admin: ")
        if len(password) < 6:
            print("❌ Le mot de passe doit contenir au moins 6 caractères")
            continue
        password_confirm = getpass.getpass("Confirmez le mot de passe: ")
        if password != password_confirm:
            print("❌ Les mots de passe ne correspondent pas")
            continue
        break
    
    # Create user
    user_service = UserService()
    try:
        user = user_service.create_user(username, email, password, role='admin')
        print(f"\n✅ Utilisateur admin '{username}' créé avec succès!")
    except Exception as e:
        print(f"\n❌ Erreur lors de la création de l'utilisateur: {e}")
        sys.exit(1)


def create_dev_instances_folder():
    """Create .dev-instances folder"""
    print("\nCréation du dossier .dev-instances...")
    os.makedirs('projets/.dev-instances', exist_ok=True)
    print("✅ Dossier créé: projets/.dev-instances/")


def display_github_oauth_instructions():
    """Display GitHub OAuth configuration instructions"""
    print("\n" + "="*60)
    print("CONFIGURATION OAUTH GITHUB (OPTIONNEL)")
    print("="*60)
    print("\nPour activer la connexion via GitHub :")
    print("\n1. Aller sur: https://github.com/settings/developers")
    print("2. Cliquer sur 'New OAuth App'")
    print("3. Remplir le formulaire :")
    print("   - Application name: WP Launcher")
    print(f"   - Homepage URL: http://{DockerConfig.LOCAL_IP}:5000")
    print(f"   - Authorization callback URL: http://{DockerConfig.LOCAL_IP}:5000/login/github/callback")
    print("\n4. Après création, copier le Client ID et Client Secret")
    print("\n5. Créer un fichier .env à la racine du projet (s'il n'existe pas):")
    print("   GITHUB_CLIENT_ID=your_client_id_here")
    print("   GITHUB_CLIENT_SECRET=your_client_secret_here")
    print("   SECRET_KEY=your_random_secret_key_here")
    print("\n6. Générer un SECRET_KEY aléatoire:")
    print("   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'")
    print("\n" + "="*60)


def check_env_file():
    """Check if .env file exists"""
    if not os.path.exists('.env'):
        print("\n⚠️  Fichier .env non trouvé. Création d'un fichier .env template...")
        with open('.env', 'w') as f:
            import secrets
            secret_key = secrets.token_urlsafe(32)
            f.write(f"# Flask secret key (généré automatiquement)\n")
            f.write(f"SECRET_KEY={secret_key}\n\n")
            f.write("# GitHub OAuth (à configurer)\n")
            f.write("#GITHUB_CLIENT_ID=your_client_id\n")
            f.write("#GITHUB_CLIENT_SECRET=your_client_secret\n")
        print("✅ Fichier .env créé avec SECRET_KEY généré")
        print("   Modifiez-le pour ajouter vos clés GitHub OAuth si nécessaire")


def main():
    """Main initialization"""
    print("\n" + "="*60)
    print("   INITIALISATION DU SYSTÈME MULTI-DEV WP LAUNCHER")
    print("="*60)
    
    # Check we're in the right directory
    if not os.path.exists('app'):
        print("\n❌ Erreur: Ce script doit être exécuté depuis la racine du projet wp-launcher")
        print("   cd /home/dev-server/Sites/wp-launcher")
        print("   python3 scripts/init_multidev_system.py")
        sys.exit(1)
    
    # Initialize
    init_databases()
    create_admin_user()
    create_dev_instances_folder()
    check_env_file()
    display_github_oauth_instructions()
    
    print("\n" + "="*60)
    print("✅ INITIALISATION TERMINÉE !")
    print("="*60)
    print("\nProchaines étapes :")
    print("1. Redémarrer l'application Flask")
    print("2. Se connecter avec le compte admin créé")
    print("3. (Optionnel) Configurer GitHub OAuth dans .env")
    print("\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Installation annulée par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Erreur inattendue: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)






