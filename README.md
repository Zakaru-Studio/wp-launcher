# WP Launcher

[![Open Source](https://img.shields.io/badge/Open%20Source-%E2%9D%A4-ff69b4.svg)](https://github.com/Zakaru-Studio/wp-launcher)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform: Linux](https://img.shields.io/badge/platform-Linux-lightgrey.svg)]()
[![Status: Dev tool](https://img.shields.io/badge/status-dev--tool-orange.svg)]()

**An open source project by [Zakaru Studio](https://github.com/Zakaru-Studio).**

![WP Launcher](app/static/images/screenshot.png)

A web application to create, manage, and maintain WordPress (and Next.js) projects via Docker containers.

Accessible through a real-time web interface on port 5000 with WebSocket support.

## Features

- **One-click WordPress project creation** with Docker
- **Multi-PHP support** — per-project PHP 7.4 / 8.3 / 8.4 / 8.5, swappable
  from the UI (auto-rebuilds the container)
- **Database import/export** (SQL, .sql.gz, .zip) streamed via stdin with
  byte-level progress, auto memory-bump to avoid OOM on large dumps, and
  a pre-import backup rotated in `logs/db-backups/`
- **Remote deployments** (`/deployments`) — register staging/production
  servers, pin SSH host fingerprints, ship via `git fetch && git reset
  --hard`, live log stream in the UI
- **Project cloning** and snapshots/restore
- **WordPress permissions management** (Docker-compatible)
- **WP-CLI integration** from the web UI
- **Container monitoring** and resource usage
- **Next.js support** with MongoDB or MySQL
- **WordPress debug mode** toggle (wp-config.php)
- **Real-time updates** via WebSocket — notifications popover, live
  deployment / import progress
- **Multi-developer instances** with Git integration
- **i18n** — English and French (browser locale auto-detected)

## Prerequisites

- **Python 3.10+**
- **Docker** and **Docker Compose**
- **sudo** access (for WordPress file permissions)
- Ubuntu/Debian recommended

## Quick Install

```bash
git clone https://github.com/Zakaru-Studio/wp-launcher.git
cd wp-launcher
chmod +x install.sh
./install.sh
```

The install script handles everything: prerequisites check, Python virtualenv, dependencies, data directories, symlinks, `.env` generation, and optional systemd service setup.

## Manual Install

```bash
# 1. Clone
git clone https://github.com/Zakaru-Studio/wp-launcher.git
cd wp-launcher

# 2. Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Create data directories (git-ignored)
mkdir -p projets containers uploads data/avatars logs snapshots

# 4. Create symlinks
ln -s "$(pwd)/projets" app/utils/projets
ln -s app/utils/containers containers

# 5. Configure
cp .env.example .env
# Edit .env with your local IP and preferences

# 6. Run
python3 run.py
```

## Usage

```bash
# Manual start
source venv/bin/activate
python3 run.py

# Via systemd (if installed)
sudo systemctl start wp-launcher
sudo journalctl -u wp-launcher -f
```

The web interface is available at `http://<YOUR_IP>:5000`.

## PHP versions

Each WordPress project picks its PHP version from the `Configuration PHP`
panel. Supported versions are defined in a single source of truth:
[`app/config/php_versions.py`](app/config/php_versions.py).

| Version | Ships as Docker image | Notes |
|---|---|---|
| 7.4 | `wp-launcher-wordpress:php7.4` | Legacy sites only |
| 8.3 | `wp-launcher-wordpress:php8.3` | |
| 8.4 | `wp-launcher-wordpress:php8.4` | **Default** for new sites |
| 8.5 | `wp-launcher-wordpress:php8.5` | Latest |

Build all images at install time (takes ~15 minutes on first run):

```bash
./scripts/build_wordpress_images.sh
# Or just one version:
./scripts/build_wordpress_images.sh 8.5
```

To add a new version, drop a `docker-template/wordpress/Dockerfile.phpX.Y`
file, append `'X.Y'` to `SUPPORTED_PHP_VERSIONS`, and re-run the build
script. The dropdown, validator and rebuild path all derive from the same
list — no other edits needed.

Sites already pinned on a retired version (e.g. 8.2) keep that option
visible in their dropdown until migrated, so an upgrade is never forced.

## Remote deployments

The `/deployments` page lets admins ship a project to a staging or
production server over SSH:

1. Register a server — label, hostname, SSH user, private key (stored
   Fernet-encrypted at rest, derived from `SECRET_KEY` via HKDF). Click
   **Test connection** to pin the host fingerprint.
2. Optional: set a custom deploy path per (project × server) pair; the
   default is `<server.deploy_base_path>/<project_name>`.
3. Click **Deploy**, pick project + server + branch. The remote runs
   `git fetch --prune origin && git reset --hard origin/<branch> &&
   git rev-parse HEAD`. Stdout/stderr stream live into the modal via
   Socket.IO.

Permission model: admins can deploy anything; a developer can deploy a
project only if they own an active dev-instance on it. Every `git`,
`deploy-path`, and `run` endpoint gates on this check.

Repos are expected to be cloned on the target server already (v1
deliberately does not bootstrap clones). If the project needs
composer/npm/wp-cli steps, add a `deploy.sh` at the repo root — it is
picked up automatically after the `git reset`.

## Configuration

All settings are in the `.env` file (not tracked by git):

```env
APP_HOST=192.168.1.100       # Your server's local IP
APP_PORT=5000                # Web interface port
SECRET_KEY=...               # Required — generated by install.sh

# Deployment mode. false (default) = everything listens on loopback and
# session cookies are HTTPS-only. true = permissive local behaviour.
WPL_LOCAL_MODE=false

# WordPress defaults for new projects
WP_ADMIN_USER=admin
WP_ADMIN_PASSWORD=admin
WP_ADMIN_EMAIL=admin@example.com
WP_LOCALE=en_US
```

See [.env.example](.env.example) for all available options.

## Architecture

```
wp-launcher/
├── run.py                     # Entry point
├── install.sh                 # Setup script
├── requirements.txt           # Python dependencies
├── wp-launcher.service        # systemd service template
├── docker-template/           # Docker Compose templates
│
├── app/                       # Main package
│   ├── __init__.py            # Flask factory
│   ├── config/                # Configuration
│   │   ├── docker_config.py   # Docker / paths / network
│   │   └── php_versions.py    # Single source of truth for PHP support
│   ├── models/                # Models (Project, User, DevInstance, Server)
│   ├── routes/                # Flask routes (API + pages)
│   │   ├── deployments.py     # /deployments — servers CRUD, run, log
│   │   ├── database.py        # DB import / export
│   │   └── ...
│   ├── services/              # Business logic
│   │   ├── deployment_service.py  # SSH-based deploy worker
│   │   ├── fast_import_service.py # Streaming SQL import
│   │   ├── server_service.py      # Remote server inventory
│   │   ├── ssh_service.py         # paramiko + Fernet-encrypted keys
│   │   └── ...
│   ├── middleware/            # Auth middleware
│   ├── utils/                 # Utilities
│   ├── static/                # CSS, JS, images
│   ├── translations/          # Flask-Babel catalogs (en, fr)
│   └── templates/             # Jinja2 templates
│
├── scripts/                   # Maintenance scripts
│   └── build_wordpress_images.sh  # Build all PHP-versioned images
│
├── projets/                   # WordPress project files (git-ignored)
├── containers/                # Docker configs per project (git-ignored)
├── data/                      # SQLite databases (git-ignored)
│   └── deployments.db         # Servers inventory + deployment history
├── logs/                      # Application logs (git-ignored)
│   ├── db-backups/            # Pre-import DB backups (rotation 5)
│   └── deployments/           # Per-deployment log files (rotation 500)
└── snapshots/                 # Project snapshots (git-ignored)
```

## Deployment

WP Launcher can be self-hosted on a VPS. Defaults are hardened for that case:
everything listens on loopback, session cookies are HTTPS-only, and each
project gets its own database password. On a laptop or LAN box, set
`WPL_LOCAL_MODE=true` in `.env` to get the permissive behaviour back.

### The one thing to understand first

The app drives Docker and `sudo` on its host. **An authenticated session is
effectively root on the machine.** The network is therefore the real security
boundary — the login form is defence in depth, not the perimeter. Put the app
behind a VPN (Tailscale, WireGuard) or a reverse proxy with an IP allow-list,
and never publish port 5000 directly.

### Reverse proxy

`scripts/start.sh` binds gunicorn to `127.0.0.1:5000`. Terminate TLS in front
of it and forward the proxy headers — without them the login throttle sees
every request as coming from the proxy:

```nginx
location / {
    proxy_pass         http://127.0.0.1:5000;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;

    # Socket.IO
    proxy_http_version 1.1;
    proxy_set_header   Upgrade    $http_upgrade;
    proxy_set_header   Connection "upgrade";
    proxy_read_timeout 300s;
}
```

Set `WPL_TRUSTED_PROXIES` to the number of proxies in the chain (default `1`).

### Reaching phpMyAdmin and Mailpit

Those side-cars ship with static credentials and no TLS, so they bind to
loopback and stay off the internet. Tunnel in instead:

```bash
ssh -L 8081:127.0.0.1:8081 user@your-vps   # then open http://localhost:8081
```

### Docker address pools

Each project gets its own bridge network, and Docker's stock pools only
allow around 30 of them. Past that, creating a project fails with
`all predefined address pools have been fully subnetted`. Stopping a project
does **not** free its network — that is deliberate, since removing it leaves
the stopped containers unable to restart.

If you plan to host more than a handful of sites, widen the pools in
`/etc/docker/daemon.json` and restart the daemon (this restarts every
container):

```json
{
  "default-address-pools": [
    { "base": "172.20.0.0/14", "size": 24 },
    { "base": "10.201.0.0/16", "size": 24 }
  ]
}
```

Avoid `192.168.0.0/16` here if your LAN lives in that range — the stock
pools use it and can collide.

`docker network prune` frees the networks of projects you have deleted.

### Firewall

```bash
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Docker publishes ports by writing iptables rules directly and **bypasses ufw**
— this is why the bind addresses above matter more than the firewall.

### Checklist before exposing an instance

- [ ] `SECRET_KEY` set to 32+ random bytes (the app refuses to start otherwise)
- [ ] `WPL_LOCAL_MODE` unset or `false`
- [ ] Reverse proxy with a valid certificate, `WPL_TRUSTED_PROXIES` matching
- [ ] `docker compose config` on a project shows no `0.0.0.0:` binding for
      phpMyAdmin / Mailpit / MySQL
- [ ] `WP_ADMIN_PASSWORD` changed from `admin` in `.env`
- [ ] Existing projects created before hardening have had their passwords
      rotated (new ones are random per project)
- [ ] `data/` backed up somewhere private — it holds SSH deployment keys,
      encrypted with `SECRET_KEY`
- [ ] Access gated at the network level (VPN or IP allow-list)

## Security

### Defaults

| Item | Default |
|---|---|
| MySQL root / wp user | random per project (24 chars) |
| WordPress admin | `admin` / `admin` — **change `WP_ADMIN_PASSWORD` in `.env`** |
| `SESSION_COOKIE_SECURE` | `true` unless `WPL_LOCAL_MODE=true` |
| Session lifetime | 12 h (30 days in local mode) |
| Flask `SECRET_KEY` | required; startup aborts if missing, short, or the shipped placeholder |
| Login throttle | 5 failed attempts per IP+username, then 1 → 5 → 15 → 60 min lockout |

Projects created before per-project credentials keep working: passwords are
read back from the running container, falling back to the historical
`wordpress` / `rootpassword` values.

### Required sudo rules

The app runs `sudo chown`, `sudo chmod`, `sudo find` and `sudo setfacl` on
WordPress bind-mounts (because Apache inside the container runs as
`www-data` UID 33 but files live on the host). `install.sh` configures the
NOPASSWD rules. Review them before use — they are the reason a session is
root-equivalent.

### Reporting vulnerabilities

Do not open public issues for security problems. See
[SECURITY.md](SECURITY.md) for the private reporting channels.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE)
