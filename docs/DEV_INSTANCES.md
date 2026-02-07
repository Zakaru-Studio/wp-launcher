# Documentation : Système Multi-Développeurs

## Vue d'ensemble

Le système multi-dev permet à plusieurs développeurs de travailler simultanément sur le même projet WordPress avec des instances isolées.

### Caractéristiques principales

- **Authentification** : Connexion classique ou via GitHub OAuth
- **Instances isolées** : Chaque dev a sa propre instance Docker
- **MySQL partagé** : Un seul conteneur MySQL pour économiser la RAM
- **Gestion des rôles** : Admin (accès complet) et Developer (instances personnelles)
- **Git intégré** : Workflow branches pour le thème enfant
- **Mode compatibilité** : L'app fonctionne même sans authentification (branche main)

## Architecture

### Structure des fichiers

```
projets/
├── projet-principal/              # PROJET PARENT
│   └── wp-content/
│       ├── themes/
│       │   ├── theme-parent/     # Symlinké par instances dev
│       │   └── theme-enfant/     # Git agence (main)
│       ├── plugins/               # Copiés vers instances dev
│       └── uploads/               # Copiés vers instances dev
│
└── .dev-instances/
    └── projet-principal-dev-alice/
        ├── .metadata.json         # Infos: owner, parent, port, db_name
        └── wp-content/
            ├── themes/
            │   ├── theme-parent@  # SYMLINK vers parent
            │   └── theme-enfant/  # COPIE - Git perso (branche alice/feature-X)
            ├── plugins/           # COPIE complète
            └── uploads/           # COPIE complète

containers/
├── projet-principal/
│   └── docker-compose.yml        # MySQL + WordPress
└── .dev-instances/
    └── projet-principal-dev-alice/
        └── docker-compose.yml    # WordPress seulement (utilise MySQL du parent)

data/
├── users.db                      # Utilisateurs et OAuth
├── dev_instances.db              # Instances de dev
└── avatars/                      # Photos de profil
```

### Base de données MySQL partagée

Un seul conteneur MySQL héberge toutes les bases :

```
Conteneur MySQL (projet-principal_mysql)
├── DB: projet_principal          # Projet parent
├── DB: projet_principal_dev_alice
├── DB: projet_principal_dev_bob
├── DB: autre_projet
└── DB: autre_projet_dev_alice
```

**Avantages** :
- Économie RAM : 256MB au lieu de 256MB × nombre d'instances
- Simplicité : Une seule instance MySQL à maintenir
- Compatible : mysqldump/import fonctionnent déjà

## Installation et Configuration

### 1. Initialisation du système

```bash
cd /home/dev-server/Sites/wp-launcher
python3 scripts/init_multidev_system.py
```

Ce script va :
- Créer les bases de données (users.db, dev_instances.db)
- Créer un utilisateur admin
- Créer le dossier .dev-instances
- Générer un fichier .env avec SECRET_KEY

### 2. Configuration OAuth GitHub (optionnel)

1. Aller sur https://github.com/settings/developers
2. Créer une nouvelle OAuth App :
   - Application name: **WP Launcher**
   - Homepage URL: **http://192.168.1.21:5000**
   - Callback URL: **http://192.168.1.21:5000/login/github/callback**

3. Ajouter dans `.env` :
```env
GITHUB_CLIENT_ID=your_client_id_here
GITHUB_CLIENT_SECRET=your_client_secret_here
SECRET_KEY=your_generated_secret_key
```

### 3. Redémarrer l'application

```bash
python3 run.py
```

## Utilisation

### Connexion

Deux méthodes :
1. **Classique** : Username + mot de passe
2. **GitHub OAuth** : Importe automatiquement avatar et clés SSH

### Créer une instance de développement

1. Sur le dashboard, trouver le projet parent
2. Cliquer sur le dropdown "Instance" (à côté de "Commandes")
3. Sélectionner "Créer une instance"
4. Attendre la création (copie fichiers + clone DB + config Docker)
5. Accéder à l'instance via le port assigné

### Workflow Git recommandé

```bash
# Dans le thème enfant de votre instance dev
cd projets/.dev-instances/projet-dev-alice/wp-content/themes/theme-enfant

# Créer une branche pour votre feature
git checkout -b alice/feature-header

# Travailler et commiter
git add .
git commit -m "Ajout nouveau header"

# Pousser sur votre branche
git push origin alice/feature-header

# Sur GitHub : créer une Pull Request vers main
```

### Promotion de plugins

Si vous ajoutez des plugins via l'interface WordPress de votre instance :

1. Aller dans "Commandes" du projet
2. Sélectionner "Promouvoir plugins vers parent"
3. Choisir les plugins à copier
4. Les plugins sont copiés dans le projet parent

## Gestion des ressources

### Limites Docker par instance dev

- **Mémoire** : 256MB (WordPress)
- **CPU** : 1.0 (max)
- **MySQL** : Partagé avec le parent (pas de limite additionnelle)

### Ports

Les ports sont alloués automatiquement (généralement 8001, 8002, etc.)

## Administration

### Gestion des utilisateurs

**Admin seulement** : `/admin/users`

- Créer/supprimer des utilisateurs
- Changer les rôles (admin/developer)
- Voir les infos GitHub

### Gestion des instances

**Admin seulement** : `/admin/instances`

- Voir toutes les instances
- Statistiques par propriétaire
- Supprimer des instances orphelines

## Compatibilité et Migration

### Mode compatibilité

Le système est conçu pour fonctionner même sans authentification. Si vous revenez sur la branche `main` :

- L'app démarre normalement
- Les blueprints d'auth ne se chargent pas
- Aucune erreur critique

### Fichiers non versionnés

Attention lors du switch de branches Git :

**Persistent** (non supprimés au checkout) :
- `data/users.db`
- `data/dev_instances.db`
- `data/avatars/*`
- `projets/.dev-instances/*`
- Conteneurs Docker existants

**Action recommandée** : Faire un backup de `data/` avant de changer de branche la première fois.

## Dépannage

### L'application ne démarre pas

```bash
# Vérifier les logs
tail -f logs/app.log

# Vérifier que Python trouve les modules
python3 -c "from app.models.user import User; print('OK')"
```

### OAuth GitHub ne fonctionne pas

1. Vérifier les clés dans `.env`
2. Vérifier que le callback URL correspond exactement
3. Tester avec connexion classique d'abord

### Instance dev ne se crée pas

```bash
# Vérifier les permissions
ls -la projets/.dev-instances/

# Vérifier le réseau Docker du projet parent
docker network ls | grep projet-principal_wordpress_network

# Logs du service
tail -f logs/app.log
```

### Base de données non accessible

```bash
# Vérifier que MySQL du parent tourne
docker ps | grep projet-principal_mysql

# Tester la connexion
docker exec projet-principal_mysql mysql -uroot -proot_password -e "SHOW DATABASES;"
```

## Bonnes pratiques

### Pour les développeurs

1. **Toujours travailler dans une branche feature**
2. **Commiter régulièrement** (votre instance = votre environnement)
3. **Créer des snapshots** avant modifications importantes
4. **Ne pas modifier** les plugins/thèmes parents (sauf si explicite)
5. **Supprimer votre instance** quand la feature est mergée

### Pour les admins

1. **Faire des backups réguliers** de `data/`
2. **Monitor les ports** disponibles (range 8000-9000)
3. **Nettoyer les instances** inutilisées régulièrement
4. **Limiter les instances** par user si RAM limitée

## API Endpoints

### Authentification

- `POST /login` : Connexion classique
- `GET /login/github` : Redirection OAuth GitHub
- `GET /login/github/callback` : Callback OAuth
- `GET /logout` : Déconnexion
- `GET /profile` : Page profil
- `POST /api/profile/update` : MAJ profil
- `POST /api/profile/avatar` : Upload avatar
- `POST /api/profile/ssh-key` : MAJ clé SSH

### Instances de développement

- `POST /api/dev-instances/create` : Créer instance
- `GET /api/dev-instances/list` : Lister mes instances
- `GET /api/dev-instances/by-project/<name>` : Instances d'un projet
- `GET /api/dev-instances/<name>` : Détails instance
- `DELETE /api/dev-instances/<name>` : Supprimer instance

### Administration

- `GET /admin/users` : Page gestion utilisateurs
- `POST /admin/api/users/create` : Créer utilisateur
- `DELETE /admin/api/users/<username>` : Supprimer utilisateur
- `PUT /admin/api/users/<username>/role` : Changer rôle
- `GET /admin/instances` : Page gestion instances

## Sécurité

### Sessions

- Cookie httpOnly
- SameSite: Lax
- Durée: 30 jours
- Secret key aléatoire (généré à l'install)

### Permissions

- **Developer** : Accès uniquement à ses propres instances
- **Admin** : Accès à tout

### SSH

Les clés SSH sont stockées mais pas encore utilisées (prévu pour accès chroot futur)

## Roadmap

### À venir

- [ ] Accès SSH chroot aux instances dev
- [ ] Filtres UI (Mes instances / Tous les projets)
- [ ] Bouton "Promouvoir plugins" dans l'UI
- [ ] Synchronisation uploads parent → dev
- [ ] Limites par utilisateur (max instances)
- [ ] Notifications email (instance créée, mergée, etc.)

### En réflexion

- Multi-tenancy complet (agencies)
- Intégration CI/CD
- Preview URLs automatiques

## Support

Pour toute question ou problème :

1. Consulter les logs : `logs/app.log`
2. Vérifier la documentation : `docs/`
3. Tester en mode debug : `FLASK_ENV=development python3 run.py`

---

**Version** : 2.0 Multi-Dev avec OAuth  
**Date** : Décembre 2025  
**Auteur** : WP Launcher Team






