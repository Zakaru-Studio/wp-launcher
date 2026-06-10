# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
