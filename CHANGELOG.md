# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- The site list could briefly show **zero sites** while a project was being
  created or started. The routes resolved `projets/` and `containers/` as
  *relative* paths, while `docker_service` calls `os.chdir()` around every
  compose command and the app runs a single worker — so a concurrent request
  evaluated those paths from inside a container directory, found nothing, and
  returned `200` with an empty list. All route modules, `port_utils`,
  `Project` and `wordpress_type_service` now use absolute paths.
  The same race silently skipped occupied ports during allocation.
- A missing projects folder now answers `500` instead of an empty list, so the
  UI keeps the previous list instead of rendering "no sites" on a broken
  install.
- A newly created site appears immediately: the server broadcasts
  `project_created` over Socket.IO, and the client also retries the listing
  with growing back-off instead of a single fixed one-second reload.

## [1.4.1] - 2026-08-03

### Added
- Pre-commit hook blocking secrets before they reach a commit, instead of
  only catching them in CI

### Changed
- `cryptography` 48.0.1 → 50.0.0

### Removed
- One-off migration and retrofit scripts, all already applied: dev-instance
  layout, unified database, WordPress type detection, WP-CLI protection and
  Docker limits. Several hardcoded absolute paths and client project names.
- `init_multidev_system.py` — redundant with the `CREATE TABLE IF NOT EXISTS`
  the services already run at startup
- `dev-instances.js` — never loaded by any template, superseded by
  `instances-ui-manager.js`

## [1.4.0] - 2026-08-03

### ⚠️ Upgrading from 1.3.0

`SECRET_KEY` is now **required** — the app refuses to start without it, and an
existing install that relied on the removed fallback will not come back up
after the update. Generate one and add it to `.env` before restarting:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

If you already registered deployment servers, their stored SSH keys were
encrypted with the old fallback key. Re-encrypt them rather than losing them:

```bash
WPL_OLD_SECRET_KEY=dev-secret-key-change-me python3 scripts/rotate_secret_key.py
```

On a laptop or LAN box, add `WPL_LOCAL_MODE=true` to `.env` to keep the previous
behaviour (services on `0.0.0.0`, cookies over plain HTTP). Otherwise everything
binds to loopback and expects a reverse proxy in front.

### Added
- Profile menu at the bottom of the sidebar (pattern borrowed from
  `boilerplate-saas`), gathering profile, user management, theme, language,
  application restart and logout, with collapsible Theme/Language submenus
- The mobile top bar now reuses the same menu, so language switching and
  application restart — previously desktop-only — are available on mobile

### Changed
- The service now runs under gunicorn (single worker, eventlet) instead of
  the Werkzeug development server, bound to loopback by default.
- `scripts/start.sh` is a service entrypoint only: it no longer installs
  dependencies or runs `chmod -R` over the project tree at boot. Both
  belong to `install.sh`, and the `chmod` reset POSIX ACL masks, silently
  revoking www-data's write access to `wp-config.php`.
- `eventlet` 0.33.3 → 0.40.3: the old pin imported `distutils` and was
  unusable on Python 3.12, silently degrading Socket.IO to threading mode.
- Removed the desktop top bar (`.app-topbar`); its actions moved to the
  sidebar profile menu, freeing ~64px of vertical space
- Dark theme is now the default; the system preference is no longer
  consulted and only an explicit user choice switches to light
- Notification bell moved next to each page's primary action buttons
- Notifications panel now floats above the content instead of shrinking it
- Sites page: fixed viewport height, only the site list scrolls
- Sidebar narrowed by 10% (256px → 230px)
- Sites navigation entry now uses the WordPress icon
- Server Telemetry: refresh interval selector moved to the right of the tabs
- Sidebar: the brand block is separated from the menu by a full-width border,
  and the sidebar itself gained a right border

### Removed
- `docs/` — `DEPLOIEMENTS.md` and `DEV_INSTANCES.md` were French, unreferenced
  and out of date (the latter documented a dev-instance layout the code no
  longer uses). Remote deployments are covered in English in the README.

### Fixed
- Port reallocation and repair routes matched a hardcoded `0.0.0.0:` prefix
  and would have silently stopped matching on newly created projects.
- Stopping a project no longer removes its Docker network. Doing so left the
  stopped containers pointing at a dead network id, and the next start failed
  with `network <id> not found`. Docker's address pool is configured through
  `/etc/docker/daemon.json` instead — see the Deployment section.
- Site list height no longer relies on a hardcoded `calc(100vh - 153px)`,
  which was calibrated for the removed top bar
- `performAppRestart()` now updates every restart trigger present in the
  page instead of a single hardcoded id

### Security
- **Self-hosting is now a supported deployment mode.** Defaults target an
  internet-facing VPS: services bind to loopback, session cookies are
  HTTPS-only and sessions last 12 h. Set `WPL_LOCAL_MODE=true` to restore
  the previous permissive local behaviour. See the Deployment section of
  the README.
- Project side-cars (phpMyAdmin, Mailpit, MySQL, Mongo Express) no longer
  bind `0.0.0.0` in hardened mode. They ship with static credentials and no
  TLS, so they were directly reachable from the internet on a public host.
- Each new project now gets its own random 24-char MySQL/Mongo passwords
  instead of the shared `wordpress` / `rootpassword`. Existing projects keep
  working: credentials are read back from the running container, falling
  back to the compose file and finally to the historical values.
- `SECRET_KEY` is mandatory — startup aborts on a missing, too-short or
  placeholder value instead of falling back to a public constant. It signs
  session cookies *and* derives the encryption key for stored SSH
  deployment keys, so a known value meant forgeable sessions.
  `scripts/rotate_secret_key.py` re-encrypts stored keys when rotating.
- Login form is rate limited: 5 failures per (IP, username) and 20 per IP,
  then an escalating 1 → 5 → 15 → 60 min lockout.
- WordPress salts are now generated on the fallback project-creation path,
  which previously wrote the public `put your unique phrase here`
  placeholders — making auth cookies forgeable on affected sites.
- Session is reset on login (both password and GitHub OAuth paths) against
  session fixation; security headers added; `ProxyFix` is opt-in via
  `WPL_TRUSTED_PROXIES` so `X-Forwarded-For` can't be spoofed by default.
- Task notifications are HTML-escaped before rendering — remote stderr text
  reached `innerHTML` unescaped.

## [1.3.0] - 2026-06-24

### Added
- UI: contextual menus for stopped sites, a subtler notification design,
  and improved dev-instance UX

### Fixed
- Sites stuck unreachable ("Connection reset") despite the container being
  `Up`: `init-permissions.sh` ran a fork-per-file `chmod`/`setfacl` over the
  whole `wp-content/uploads` tree and blocked Apache from starting. It now
  runs in the background (Apache starts immediately), batches `chmod` with
  `-exec … +`, and performs the heavy recursive sweep only once (sentinel
  file `wp-content/.wp-launcher-perms-done`), re-applying only lightweight
  permissions + default ACLs on later boots
- Port allocation: live socket check during allocation and a broader Docker
  binding regex, avoiding ports wrongly reported as free

## [1.2.0] - 2026-06-10

### Added
- Backups: download endpoint for backup files (admin), real storage stats
  (disk usage + per-type breakdown) on the /backups page
- Backups: manual runs now execute in the background (HTTP 202 + status
  polling endpoint), with a single-flight lock (409 when already running)
- Deployments: running deployments can be cancelled (new `cancelled`
  status, stop button in the history table)
- Dev instances: the parent's WordPress image and table prefix are reused
  by the instance instead of hardcoded values

### Changed
- Backup script reads MySQL/MongoDB credentials from the container
  environment (with fallback), prunes its own report files, and matches
  container names exactly
- Dev instance creation copies ALL themes/plugins/mu-plugins/languages
  (previously only hardcoded `theme-enfant`/`theme-parent`)
- Dev instance docker-compose commands run with an explicit, unique
  `-p` project name (cross-project container collisions)

### Fixed
- Backups: DELETE endpoint was broken since day one (frontend/backend URL
  mismatch) and allowed path traversal; now strict (type, filename)
  whitelist + realpath confinement
- Deployments: concurrent deploys of the same (project, server) are now
  refused (409) instead of racing `git reset --hard` on the remote
- Dev instances: `slug` column persisted (with auto-migration and
  cleaned-username fallback) so start/stop/delete resolve the right folder
- Dev instances: ports of stopped instances are counted during allocation
  (fixed `UNIQUE constraint failed: dev_instances.port`)
- Dev instances: full rollback on failed creation (container, files,
  cloned DB) and fail-fast when the parent project is stopped
- Dev instances: `list_instances_by_user` alias added — developers could
  never deploy because the permission helper couldn't find it
- DB clone: mysql import via defaults-file + warning filtering so real
  errors surface; options table detected per prefix instead of hardcoded
  `wp_options`
- WordPress images: `php-soap` installed (Chronopost & carrier plugins)

### Security
- Dependency bumps covering all open Dependabot alerts: Werkzeug 3.1.8,
  requests 2.33.1, chardet 7.4.3, gunicorn 25.3.0, paramiko 4.0.0
  (DSA key support dropped upstream; ssh_service adapted)
- Deployments API no longer exposes the host-side log file path; project
  existence is only revealed to users allowed to deploy

## [1.1.0] - 2026-04-27

### Added
- CSRF protection via Flask-WTF on all mutating routes
- `SECURITY.md` with vulnerability reporting process
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1)
- `.github/` templates and CI workflow
- Arctic Void dark theme with `Outfit` + `JetBrains Mono` fonts
- Light theme with View Transition API circle-reveal animation
- Theme switcher with animated sun/moon morphing icons
- Smoke tests (`tests/test_smoke.py`)

### Changed
- Auth middleware no longer silently bypasses when `user_service` is missing
- Session cookies hardened: `SameSite=Strict`, `HttpOnly`, configurable
  `Secure` via env var
- `find ... -exec chmod` patterns now run under `sudo` when the preceding
  `chown` transferred ownership away from the current user
- MySQL containers: new `mysql.cnf` with ACID settings
  (`innodb_flush_log_at_trx_commit=1`, `innodb_doublewrite=ON`,
  `sync_binlog=1`, `O_DIRECT`)
- MySQL services now declare `stop_grace_period: 60s` in docker-compose to
  avoid InnoDB corruption on ungraceful shutdown
- `logger.py` is now the single source of truth;
  `debug_logger.py` becomes a thin shim
- `port_utils.py` absorbs `port_conflict_resolver.py` (shim kept for
  backward compatibility)

### Fixed
- Duplicated imports at line 640 of `routes/project_lifecycle.py` removed
- Shell injection via f-strings + `shell=True` in `database_service.py` and
  `database_utils.py` (5 call sites)
- Path traversal bypass in `routes/logs.py` (`startswith` → `commonpath`)
- InnoDB corruption on MySQL containers (added ACID settings and
  `stop_grace_period`)
- Missing `@admin_required` / `@login_required` on 80+ mutating routes

### Security
- All destructive routes (project create/start/stop/delete, permissions fix,
  WP-CLI, snapshots, backups, config) now require admin authentication
- SQL identifiers and values are validated/escaped before interpolation
- OAuth callback route explicitly exempted from CSRF (state param already
  enforces CSRF)
