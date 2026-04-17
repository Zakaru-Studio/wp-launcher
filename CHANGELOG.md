# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
