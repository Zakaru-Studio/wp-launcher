# Traefik Configuration

Configuration Traefik pour le proxy inverse avec SSL automatique pour les projets WordPress et Next.js.

## Installation

```bash
cd traefik
./install.sh
```

## Configuration

### Dashboard
- URL locale: http://localhost:8080
- URL sécurisée: https://traefik.dev.akdigital.fr
- Utilisateur: admin
- Mot de passe: admin

### Certificats SSL
- Générés automatiquement via Let's Encrypt
- Stockés dans `acme.json`
- Renouvellement automatique

### Réseau
- Nom du réseau: `traefik-network`
- Tous les projets doivent être connectés à ce réseau

## Utilisation

### Pour un projet WordPress
Les labels Traefik sont automatiquement ajoutés lors de la création du projet.

### Pour un projet Next.js
Les labels Traefik sont configurés pour chaque service (frontend, API, etc.).

## Commandes utiles

```bash
# Démarrer Traefik
docker-compose up -d

# Arrêter Traefik
docker-compose down

# Voir les logs
docker-compose logs -f traefik

# Redémarrer Traefik
docker-compose restart traefik

# Supprimer les certificats (forcer le renouvellement)
rm acme.json && touch acme.json && chmod 600 acme.json
```

## Sécurité

- Force HTTPS pour tous les sites
- Headers de sécurité configurés
- Limitation du taux de requêtes
- Compression activée

## Middleware disponibles

- `default-headers`: Headers de sécurité de base
- `secure-headers`: Headers de sécurité avancés
- `compress`: Compression gzip
- `rate-limit`: Limitation du taux de requêtes 