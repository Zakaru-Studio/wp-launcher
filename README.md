# WP Launcher

Application web pour créer, gérer et maintenir des projets WordPress (et Next.js) via Docker.

Interface web accessible sur le port 5000 avec gestion en temps réel via WebSocket.

## Prérequis

- **Python 3.10+**
- **Docker** et **Docker Compose**
- **sudo** sans mot de passe (pour les permissions WordPress)
- Ubuntu/Debian recommandé

## Installation rapide

```bash
git clone git@github.com:AK-Digital-Ltd/wp-launcher.git
cd wp-launcher
chmod +x install.sh
./install.sh
```

Le script `install.sh` s'occupe de :
- Vérifier les prérequis (Python, Docker)
- Créer les dossiers de données (`projets/`, `containers/`, `data/`, `logs/`, etc.)
- Créer les symlinks nécessaires
- Installer le virtualenv Python et les dépendances
- Générer le fichier `.env`
- Optionnellement installer le service systemd

## Installation manuelle

```bash
# 1. Cloner le repo
git clone git@github.com:AK-Digital-Ltd/wp-launcher.git
cd wp-launcher

# 2. Virtualenv + dépendances
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Créer les dossiers de données (ignorés par git)
mkdir -p projets containers uploads data/avatars logs snapshots

# 4. Créer les symlinks
ln -s "$(pwd)/projets" app/utils/projets
ln -s app/utils/containers containers

# 5. Configurer l'environnement
cp .env.example .env  # ou créer manuellement
# Editer .env avec votre IP locale et un SECRET_KEY

# 6. Lancer
python3 run.py
```

## Démarrage

```bash
# Manuellement
source venv/bin/activate
python3 run.py

# Via systemd (si installé)
sudo systemctl start wp-launcher
sudo systemctl status wp-launcher

# Logs
sudo journalctl -u wp-launcher -f
```

L'application est accessible sur `http://<IP>:5000`.

## Configuration

Le fichier `.env` (non versionné) contient :

```env
APP_HOST=192.168.1.21    # IP locale du serveur
APP_PORT=5000            # Port de l'application
SECRET_KEY=...           # Clé secrète Flask
```

## Architecture

```
wp-launcher/
├── run.py                  # Point d'entrée
├── install.sh              # Script d'installation
├── requirements.txt        # Dépendances Python
├── wp-launcher.service     # Service systemd
├── docker-template/        # Templates docker-compose
│
├── app/                    # Package principal
│   ├── __init__.py         # Factory Flask
│   ├── config/             # Configuration (Docker, DB, ports)
│   ├── models/             # Modèles (Project, User, DevInstance)
│   ├── routes/             # Routes Flask (API + pages)
│   ├── services/           # Logique métier
│   ├── middleware/         # Auth middleware
│   ├── utils/              # Utilitaires
│   ├── static/             # CSS, JS, images
│   └── templates/          # Templates Jinja2
│
├── scripts/                # Scripts de maintenance
│
├── projets/                # Fichiers WordPress des projets (gitignored)
├── containers/             # Configs Docker des projets (gitignored)
├── data/                   # Bases SQLite (gitignored)
├── logs/                   # Logs applicatifs (gitignored)
└── snapshots/              # Snapshots de projets (gitignored)
```

## Fonctionnalités

- Création de projets WordPress avec Docker (un clic)
- Import/export de bases de données
- Clonage de projets
- Snapshots et restauration
- Gestion des permissions WordPress
- WP-CLI intégré
- Monitoring des conteneurs
- Support Next.js + MongoDB/MySQL
- Debug WordPress (wp-config.php)
- Interface web temps réel (WebSocket)

## Licence

Propriétaire - AK Digital Ltd
