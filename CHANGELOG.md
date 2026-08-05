# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.0] - 2026-08-05

### Added
- Running sites carry an "Open in VS Code" button that opens their editable
  folder in the editor. The files live on the machine hosting WP Launcher, so
  when the browser is somewhere else the button builds a Remote-SSH URI
  (`vscode://vscode-remote/ssh-remote+host/path`) instead of a local one that
  would point at a directory the client machine doesn't have. The server
  decides which of the two applies from the requesting address, and the SSH
  target is `WPL_VSCODE_SSH_HOST` (defaults to the current user @ `APP_HOST`).
  `WPL_VSCODE_SCHEME` switches the URI scheme for VS Code forks.

### Changed
- Everything that reaches a database now asks where it lives instead of
  assuming. Roughly thirty call sites built the container name as
  `f"{project}_mysql_1"` and half of them authenticated with a literal
  `-u wordpress -pwordpress`, which is why a project created after password
  randomisation worked in some features and failed in others. A single
  resolver (`app/utils/db_target.py`) now answers with the container, the
  schema, the user and the password, walking a `.db.json` sidecar, then
  `docker inspect`, then docker-compose, then `wp-config.php`, then the
  historical defaults. `docker_service.container_for()` and
  `push_common.container_name()` route the `mysql` service through it, so
  their callers were fixed without being touched. Behaviour is unchanged —
  every project still runs its own MySQL container — but the layout is no
  longer hardcoded, which is what a shared database server needs.
  `_compose_env` also reads `WORDPRESS_DB_*` and not only `MYSQL_*`: a stack
  with no `mysql:` service would otherwise resolve to `wordpress`/`wordpress`
  while stopped and bake that into a rewritten `wp-config.php`.
- The database import no longer raises the MySQL container's memory limit for
  the duration of the run. `docker update --memory` is a property of the
  container, not of the import, so a crash left the limit raised, and on a
  shared server it would resize the database every other site is using. The
  import account is also dropped and recreated rather than patched with
  `CREATE IF NOT EXISTS` + `ALTER`, which kept whatever grants a previous
  configuration had handed out.
- Site rows are down to four controls. The instance selector and the
  deployment shortcut moved into the row menu, which became a three-dot button
  and sits last, after Stop/Start — leaving VS Code, WP Admin and Stop/Start
  as the only always-visible actions. The instance selector opens as a
  submenu, the same floating pattern WP Debug and WP-CLI already use, since
  Bootstrap 5 cannot nest dropdowns. A chip next to the status pill still
  reports which instance a row points at, because switching instances changes
  every port on that row and the old selector button carried that signal.
- The notification panel no longer opens by itself. It used to pop open on
  every task *and* every one-line message — including tasks started from
  another session — covering the page the user was working on. Notifications
  now split across two channels: short-lived messages go to a toaster
  ([sonner](https://github.com/emilkowalski/sonner), vendored under
  `static/vendor/sonner/` so the channel that reports failures doesn't depend
  on a CDN), and the bell keeps the history, opening only when clicked. A
  long-running task raises exactly one toast — its outcome — carrying a "Voir"
  button back to the panel, instead of a toast per progress tick.
  Messages worth keeping (backup, snapshot, deletion, import, account changes)
  go to both via `showToast(..., { persist: true })`; validation errors and
  "list refreshed" acknowledgements stay toast-only.
- New sites are created on the latest supported PHP version (8.5 today)
  instead of 8.4. The default is now derived from `SUPPORTED_PHP_VERSIONS`
  rather than hardcoded, so adding a version to that list is enough for new
  projects to pick it up. The compose template also stops pointing at the
  `latest` image tag, which tracked whenever the images were last built and
  drifted from the declared default; it now uses an explicit `php<version>`
  tag, falling back to the newest version whose image actually exists on the
  machine. Creation records the chosen version in `.php_version` so a later
  rebuild keeps it.

### Removed
- `services/mysql_manager.py` (509 lines), `config/database_config.py` and
  thirteen of the fifteen helpers in `utils/database_utils.py`. All of them
  hardcoded the per-project container name and the legacy credentials, all of
  them predated credential randomisation, and none was reachable: `MySQLManager`
  was registered into `app.extensions` and never called, and the two
  `database_utils` helpers still imported by `routes/project_lifecycle.py` were
  imported but never invoked. `export_database_with_db_name` /
  `import_database_with_db_name` went too — they authenticated with a password
  spelled `root_password` that exists nowhere in the repository. Net −866 lines.

### Fixed
- "Erreur lors du chargement des projets" on the monitoring, backups, servers
  and logs pages, which list no projects at all. `project-management.js` ships
  on every page and two separate entry points called `loadProjects()` at
  startup; the fetch succeeded, then `updateStats()` threw writing to counter
  elements that only exist on the home page, and the surrounding `catch`
  reported that as a load failure. The load now returns early when there is no
  project grid to fill — which also stops four pages from polling the API
  every 30 seconds for data they never display.
- `projects.js` bound a submit handler to `#update-db-form` without checking it
  exists. On every page except the home page that threw, aborting the rest of
  the script — including the import-modal setup that follows it.
- Concurrent operations stole each other's working directory. Several Docker
  routines ran `os.chdir` into a project folder and restored it in a `finally`,
  but the working directory belongs to the *process*, and the app serves every
  request from a single eventlet worker. One task's cleanup reset the directory
  while another sat between its own `chdir` and its `docker-compose` call, which
  then failed with "Can't find a suitable configuration file" — that was the
  PHP version switch. Deleting a project was worse: it removed the very
  directory it was standing in, so the next relative path raised
  `No such file or directory: 'logs'`, the deletion aborted halfway, and the
  site stayed in the list. Every `os.chdir` is gone; subprocesses get `cwd=`
  instead, and a test fails the build if one comes back.
- Paths that only worked from the repository root are now absolute: the log
  directories, the pre-import database backups, a project's snapshots (deleting
  a project silently kept them), the container folder used when changing the
  WordPress type or the PHP limits, and the parent-project check when creating
  a dev instance.
- The Update button stayed visible after a successful update. The check only
  ever *showed* it, never hid it — harmless while the page reloaded afterwards,
  but the sidebar version is now refreshed live over Socket.IO, so nothing made
  the button go away. The check is symmetric, and it re-runs when the server
  announces a different version, bypassing the one-hour cache that would
  otherwise replay the pre-restart answer.

### Security
- The application no longer needs `NOPASSWD: ALL`. It used to run 81 `sudo
  chown/chmod/find/rm/rsync/cp` calls on paths it composed itself, so a single
  controllable value anywhere in that surface was a root shell. Those calls now
  go through six root-owned helper scripts (`scripts/root/`, installed to
  `/opt/wp-launcher-root` — outside the repository, which the app can rewrite)
  that take an intention and a project name rather than a command. Each one
  revalidates its arguments and resolves the final path with `realpath` before
  checking it still sits under `projets/` or `containers/`, so a directory
  swapped for a symlink is refused instead of followed. `scripts/root/sudoers.wp-launcher`
  ships the closed command list that replaces the blanket rule, along with the
  switchover order.
- Deleting a dev instance whose slug resolved to the empty string expanded to
  `rm -rf projets/<parent>/.dev-instances/`, taking every instance of that
  project with it. `clean_username_for_slug` can return an empty string for a
  sufficiently unusual username, and the existence check passed on the
  truncated path. The helper rejects an empty name.
- Reviewing the helpers turned up three ways back to root that the rewiring had
  left open, all fixed before the sudoers switch: `resolve_under` validated its
  target but never its *root*, so a derived root the app could replace with a
  symlink (`.dev-instances`, `wp-content`) made the prefix check pass against
  the link's target — enough to turn deleting an instance into `rm -rf /etc/ssl`;
  the rsync destination in `wpl-copy-wp-content.sh` was unvalidated, so a
  symlinked `plugins` directory let root overwrite the helper scripts
  themselves; and `wpl-write-wp-config.sh` took a source *path*, which the
  caller could swap for a symlink after the check, so the content now arrives
  on stdin and lands via `rename` rather than `cp`.

## [1.5.1] - 2026-08-04

### Added
- Pushing a `v*` tag now publishes the GitHub release automatically: the source
  archive is built with `git archive`, the notes are taken from this file's
  matching section, and the job only runs once the tests, the secret scan and
  the version check have passed.

### Fixed
- New sites were installed with an outdated WordPress. `build_wordpress_images.sh`
  built without `--pull`, so Docker reused the locally cached
  `wordpress:phpX.Y-apache` layer — over a year old on the development box, and
  carrying **WordPress 6.8.1 while 6.8.3 was already deployed**. Rebuilding the
  image therefore moved the version *backwards*, which is why the problem
  survived every rebuild. The base image is now pulled on every build.

## [1.5.0] - 2026-08-04

### Added
- Deployments page aligned with the Sites page: clickable stat cards acting as
  filters, a search box, and a sort toggle. The servers table uses explicit
  column widths with horizontal scrolling instead of squeezing, and action
  buttons gained a `:focus-visible` state.

### Security
- `/api/monitoring/processes` no longer lists every process on the host. It
  returned all 754 of them — names, owning accounts, the machine's general
  shape — which is an inventory handed to anyone who obtains a session on a
  self-hosted instance. Processes are now matched to the launcher's own
  containers through their cgroup, leaving only what the app actually manages.
- `kill-process` accepted **any** PID and sent it a SIGTERM, so an admin
  session could stop `sshd`, the firewall, or another tenant's application.
  The route now validates the PID against that same scope and answers `403`
  otherwise. Process, account and container names are HTML-escaped before
  rendering — they come from the host.

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
- Creation progress is now reported. The client had always listened for
  `project_creation`, but the server never emitted it, so the notification sat
  at 10% with a spinner until the whole synchronous request returned — long
  after the site was usable. Seven steps are broadcast, and the final one
  completes the task without waiting for the HTTP response.
- Deleting a site no longer blocks unrelated actions. Task exclusivity was a
  single global flag, so one slow delete left every other project's task
  "pending"; it is now scoped per project, and the queue drains every task
  whose own project is free.
- Deleting a site is confirmed through the application's modal instead of the
  browser's `confirm()`. The markup already existed in `index.html`, fully
  translated — nothing referenced it.
- The CPU / Memory / Disk icons were unreadable in dark mode: a light accent
  on an equally light `-fixed` background, measuring 1.31:1, 1.32:1 and
  1.32:1. They now use the design system's `-container` colours, the dark
  counterparts intended for those accents, reaching 10.8:1, 5.5:1 and 8.5:1.
  Light mode was already correct and is untouched. Same cause for the
  `PID · user` line under each process, which used Bootstrap's `text-muted`.
- Section headings on /monitoring had no class and inherited the browser's
  default size; they now use a `.section-title` matching the design system.

### Removed
- The "Active Node Topology" panel on /monitoring — a mock-up whose nodes
  (`DB-Primary`, `WEB-01`, `WEB-02`) were hardcoded in the template and
  reflected no real data — along with its 115 lines of CSS.

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
