# Documentation : Mise en place d'un projet de déploiement

> Guide de configuration et d'utilisation de la fonctionnalité **Déploiements** de WP Launcher.
> Ce document est une ressource éditable — adaptez les chemins, noms et exemples à vos projets.

---

## Sommaire

1. [Vue d'ensemble](#vue-densemble)
2. [Comment ça marche](#comment-ça-marche)
3. [Prérequis](#prérequis)
4. [Préparer le serveur cible (une seule fois)](#préparer-le-serveur-cible-une-seule-fois)
5. [Mise en place dans WP Launcher](#mise-en-place-dans-wp-launcher)
6. [Déployer et suivre](#déployer-et-suivre)
7. [Le chemin de déploiement](#le-chemin-de-déploiement)
8. [Sécurité](#sécurité)
9. [Dépannage](#dépannage)
10. [Référence rapide](#référence-rapide)

---

## Vue d'ensemble

La fonctionnalité **Déploiements** permet de pousser le code d'un projet vers un
serveur distant (staging ou production) **en un clic**, via Git et SSH.

Organisation de la vue :

```
Déploiements
└── Projet (dossier)              ← 1 dossier par projet launcher
    ├── Colonne STAGING           ← connexion(s) vers le(s) serveur(s) de test
    └── Colonne PRODUCTION        ← connexion(s) vers le(s) serveur(s) de prod
```

- **Projet** : un dossier qui regroupe les environnements d'un projet launcher.
- **Connexion** : un environnement concret = un **serveur** + une **branche** Git.
  L'étiquette *Staging* / *Production* est héritée de l'environnement du serveur.
- **Serveur** : une cible SSH (hôte, utilisateur, clé privée, empreinte épinglée,
  chemin de base de déploiement).

---

## Comment ça marche

À chaque déploiement, WP Launcher ouvre une connexion SSH vers le serveur et
exécute **exactement** ce script dans le dossier de déploiement :

```bash
set -e
cd <chemin_de_déploiement>
git fetch --prune origin
git reset --hard origin/<branche>
git rev-parse HEAD
```

Points importants :

- Le déploiement est un **`git reset --hard`** : le dossier distant est aligné à
  l'identique sur la branche du dépôt. **Toute modification locale non commitée
  côté serveur est écrasée.**
- WP Launcher **ne clone pas** le dépôt : le dossier de déploiement doit **déjà
  être un clone Git** avec le remote `origin` configuré (voir prérequis).
- La sortie est **streamée en direct** dans la fenêtre de log et enregistrée dans
  `logs/deployments/<id>.log`.
- Timeout global : **10 minutes** par déploiement.
- Un seul déploiement à la fois par couple (projet × serveur).

---

## Prérequis

### 1. Un dépôt Git contenant le code à déployer

Exemple typique WordPress : un dépôt qui **est** le dossier `wp-content`
(thème, plugins, mu-plugins…), hébergé sur GitHub/GitLab.

> Exemple réel : `AK-Digital-Ltd/numerike-wp-content` correspond au dossier
> `wp-content` du site.

### 2. Un accès en lecture au dépôt depuis le serveur

Une **clé de déploiement** (deploy key) ou un token permettant au serveur de
faire `git fetch` sur le dépôt.

### 3. Une clé SSH pour que le launcher se connecte au serveur

Une **clé privée SSH** (format OpenSSH) dont la clé publique est autorisée sur le
serveur cible (`~/.ssh/authorized_keys` de l'utilisateur de déploiement).

### 4. Le rôle adéquat dans le launcher

- **Admin** : peut déployer tous les projets.
- **Développeur** : peut déployer uniquement les projets où il possède une
  instance de dev active.

---

## Préparer le serveur cible (une seule fois)

WP Launcher fait `git fetch` + `git reset --hard`, **pas** de `git clone`. Le
dossier de déploiement doit donc être initialisé **manuellement** la première fois.

Sur le serveur (exemple Plesk) :

```bash
# 1. Se placer dans le dossier web du site
cd /var/www/vhosts/mon-site.exemple.dev/httpdocs

# 2. Cloner le dépôt dans le dossier voulu (ici wp-content)
#    (sauvegarder / vider wp-content au préalable si besoin)
git clone git@github.com:mon-org/mon-repo-wp-content.git wp-content

# 3. Vérifier que le remote et la branche sont bons
cd wp-content
git remote -v
git status

# 4. Vérifier que la deploy key fonctionne
git fetch --prune origin
```

Notes :
- L'utilisateur SSH utilisé par le launcher doit avoir les **droits d'écriture**
  sur ce dossier (c'est lui qui exécute `git reset --hard`).
- La deploy key doit être associée à cet utilisateur/dossier (ex. via
  `~/.ssh/config` ou l'agent SSH côté serveur).

---

## Mise en place dans WP Launcher

### Étape 1 — Créer le projet

1. Aller sur la page **Déploiements**.
2. Cliquer **« Créer un projet »**.
3. Choisir le projet launcher concerné dans la liste → **Créer**.
   → Un dossier apparaît (avec le favicon du site si disponible).

### Étape 2 — Ouvrir le projet

Cliquer sur le dossier. La vue dédiée s'ouvre :
- le titre en haut devient le nom du projet ;
- deux colonnes : **Staging** (gauche) et **Production** (droite).

### Étape 3 — Ajouter une connexion

Dans la colonne voulue (vide), cliquer **« Paramétrer »**. Le modal de connexion
s'ouvre.

**a) Créer le serveur (si pas encore fait)**

Cliquer **« ＋ Ajouter un serveur »** sous le sélecteur de serveur, puis renseigner :

| Champ | Description | Exemple |
|---|---|---|
| **Label** | Nom lisible du serveur | `numerike-staging` |
| **Environnement** | `staging` ou `production` (définit l'étiquette de la colonne) | `staging` |
| **Hostname** | Hôte SSH (souvent le domaine du site) | `numerike.zakaru.dev` |
| **SSH port** | Port SSH | `22` |
| **SSH user** | Utilisateur de déploiement | `numerike.zakaru.dev_xxxx` |
| **Private key** | Clé privée SSH (OpenSSH) | `-----BEGIN OPENSSH…` |
| **Deploy base path** | Chemin de base (voir section dédiée) | `/var/www/vhosts/…/httpdocs` |

Cliquer **« Tester la connexion »** : si tout est bon, l'**empreinte SSH est
épinglée** (obligatoire pour pouvoir déployer). Puis **Enregistrer**.

→ Retour automatique au modal de connexion avec le nouveau serveur pré-sélectionné.

**b) Compléter la connexion**

| Champ | Description |
|---|---|
| **Nom de la connexion** | Auto-suggéré (`projet → env`), modifiable |
| **Serveur** | Le serveur créé/choisi |
| **Branche** | Branche à déployer (vide = branche par défaut du projet, souvent `main`) |

**Enregistrer** → la connexion apparaît en carte dans sa colonne.

---

## Déployer et suivre

### Redéployer en un clic

Sur la carte de connexion, cliquer **« Redéployer »** → confirmation légère →
la fenêtre de log s'ouvre et streame la sortie en direct.

Une fois terminé, un message confirme le résultat :
- ✓ **Déploiement réussi.**
- ✗ **Une erreur s'est produite pendant le déploiement.**
- *Déploiement annulé.*

Il n'y a **pas** de bouton « Déployer » dans cette fenêtre : le déploiement se
lance automatiquement. Cliquer **« Fermer »** quand c'est fini.

### Historique par connexion

Sur chaque carte, le bouton **« Historique (N) »** déplie les **5 derniers**
déploiements de cette connexion, avec un **« Voir plus »** pour dérouler le reste.
Chaque ligne donne accès aux **logs** de ce run.

### Activité récente du projet

En bas de la vue projet, le panneau **« Activité récente »** liste les derniers
déploiements **toutes connexions confondues** (statut, serveur/env, branche,
commit, date, logs).

---

## Le chemin de déploiement

Le dossier où s'exécute `git reset --hard` est résolu ainsi :

1. **Override personnalisé** pour le couple (projet × serveur), s'il existe ;
2. sinon, par défaut : **`<deploy_base_path>/<nom_du_projet>`**.

> Exemple : base `/.../httpdocs` + projet `numerik` → `/.../httpdocs/numerik`.
> Si votre clone Git est ailleurs (ex. `/.../httpdocs/wp-content`), définissez le
> **deploy base path** en conséquence, ou posez un override de chemin.

⚠️ **Ce dossier doit être le clone Git préparé à l'étape serveur.** Sinon le
déploiement échoue (`not a git repository`).

---

## Sécurité

- **Clé privée chiffrée** : la clé SSH du serveur est stockée chiffrée (Fernet,
  dérivée du `SECRET_KEY` de l'app).
- **Empreinte épinglée** : le déploiement refuse de partir tant que l'empreinte
  d'hôte n'a pas été validée via *Tester la connexion* (protection MITM).
- **Branche validée** : le nom de branche est filtré (pas de `..`, pas de `-` en
  tête, charset restreint) avant interpolation shell.
- **Logs nettoyés** : toute clé privée détectée dans la sortie est masquée avant
  affichage/enregistrement.

---

## Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| « Deployment is already running… » | Un déploiement est déjà en cours sur ce couple projet/serveur | Attendre la fin, ou annuler le run en cours |
| Échec immédiat « SSH connect failed » | Hôte/port/user/clé incorrects, ou clé publique non autorisée | Vérifier les infos serveur + `authorized_keys` |
| « no pinned host fingerprint » | Empreinte non validée | Ouvrir le serveur → **Tester la connexion** → Enregistrer |
| `not a git repository` dans les logs | Le chemin de déploiement n'est pas un clone Git | Cloner le dépôt dans ce dossier (voir prérequis serveur) |
| `Permission denied` sur `git reset` | L'utilisateur SSH n'a pas les droits d'écriture | Ajuster les droits du dossier de déploiement |
| `fatal: could not read from remote` | La deploy key ne fonctionne pas côté serveur | Configurer la deploy key / l'accès au dépôt |
| Déploiement en « timeout » | > 10 min (gros dépôt, réseau lent) | Réduire la taille du dépôt / vérifier le réseau |
| Statut bloqué « running » après un crash app | Le worker a été tué | Le launcher marque ces runs en « failed » au redémarrage |

Les logs complets de chaque run sont dans `logs/deployments/<id>.log` (et via
**Voir les logs**).

---

## Référence rapide

**Flux complet d'un nouveau projet :**

```
1. (Serveur)  Cloner le dépôt dans le dossier de déploiement + deploy key
2. (Launcher) Déploiements → Créer un projet → choisir le projet
3. (Launcher) Ouvrir le projet → colonne Staging → Paramétrer
4. (Launcher) Ajouter un serveur → infos SSH → Tester la connexion → Enregistrer
5. (Launcher) Nom + branche → Enregistrer la connexion
6. (Launcher) Redéployer → suivre le log → ✓
7. (Prod)     Répéter l'étape connexion dans la colonne Production
```

**Ce que fait un déploiement (rappel) :**

```bash
cd <chemin_de_déploiement>
git fetch --prune origin
git reset --hard origin/<branche>
```

---

*Document à adapter selon vos serveurs et conventions. Dernière mise à jour :
à compléter.*
