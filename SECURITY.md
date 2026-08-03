# Security Policy

## Scope & design assumptions

WP Launcher can be self-hosted on a VPS. Defaults target that case: services
bind to loopback, session cookies are HTTPS-only, `SECRET_KEY` is mandatory,
each project gets a random database password, and the login form is rate
limited. See the Deployment section of the [README](README.md#deployment).

**The structural caveat:** the app drives Docker and `sudo` on its host, so
an authenticated session is effectively root on the machine. The network is
the real security boundary — put the instance behind a VPN or an IP
allow-list. The login form is defence in depth, not the perimeter.

Setting `WPL_LOCAL_MODE=true` restores the permissive local-development
behaviour (services on `0.0.0.0`, cookies over plain HTTP, 30-day sessions).
Vulnerabilities that require that mode, or that require host-level access
already, may be documented rather than fixed.

Still true regardless of mode:

- Generated WordPress admin accounts default to `admin`/`admin` unless
  `WP_ADMIN_PASSWORD` is set
- Auto-login helpers for WordPress admin
- `sudo` invocations for file permissions on bind-mounted WordPress files
- phpMyAdmin and Mailpit have no authentication of their own and rely
  entirely on being unreachable from outside the host

## Supported versions

Only the `main` branch receives security updates. There is no LTS branch.

| Version | Supported |
|---------|-----------|
| `main`  | ✅ |
| Other   | ❌ |

## Reporting a vulnerability

**Do not open a public GitHub issue for security reports.**

Please report privately via one of:

1. GitHub's private vulnerability reporting:
   <https://github.com/Zakaru-Studio/wp-launcher/security/advisories/new>
2. Email: **security@zakaru.studio**

Include:

- A description of the vulnerability and its impact
- Steps to reproduce (a minimal PoC is ideal)
- Affected commit SHA or version
- Your disclosure timeline expectations, if any

## Response timeline

- **Acknowledgement**: within 5 business days
- **Initial assessment**: within 10 business days
- **Fix & disclosure**: coordinated, typically within 30–90 days depending on
  severity and complexity

## Things already known

The following are documented design choices, not bugs to report:

- Default WordPress admin credentials are `admin` / `admin` unless
  `WP_ADMIN_PASSWORD` is set in `.env`
- Projects created before per-project credentials still use the shared
  `wordpress` / `rootpassword` values; they are read back from the running
  container so both generations keep working. Rotating them on an old
  project means editing its `docker-compose.yml`, its `wp-config.php` and
  the MySQL user itself
- The app requires `sudo` NOPASSWD for `chmod`, `chown`, `find` on WordPress
  directories (documented in `install.sh`) — this is what makes an
  authenticated session root-equivalent
- Docker publishes ports via its own iptables chain and bypasses `ufw`;
  container reachability is controlled by the bind addresses
  (`WPL_SITE_BIND`, `WPL_ADMIN_BIND`), not by the host firewall
- Changing `SECRET_KEY` invalidates every stored SSH deployment key. Use
  `scripts/rotate_secret_key.py` to re-encrypt them instead of losing them

## Keeping secrets out of the repository

Two layers, because content-based scanning alone has already failed here once:
a Let's Encrypt account key lived in this repository's history for a year as a
base64 blob inside a JSON field. It carried no PEM header, so gitleaks reported
"no leaks found" on every CI run. Its *filename* was unmistakable.

**Before a commit** — `.githooks/pre-commit` refuses staged files whose path
looks like key material (`acme.json`, `*.pem`, `*.key`, `.env`, `id_rsa`, …)
and then runs gitleaks over the staged diff. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

`install.sh` does this automatically. `--no-verify` bypasses it; if you use
that, say why in the commit message.

**In CI** — the `Secret scan` job scans the full history with
`.gitleaks.toml`, which extends the default rules with detection for key
material embedded in JSON and for secret-bearing paths.

**On GitHub** — enable secret scanning and push protection (free on public
repositories). They catch provider-issued tokens at push time, before the
secret ever reaches the remote:

```bash
gh api -X PATCH repos/<owner>/<repo> \
  -F security_and_analysis[secret_scanning][status]=enabled \
  -F security_and_analysis[secret_scanning_push_protection][status]=enabled
```

**If a secret does land in a commit**, rotate it. Do not add a fingerprint to
`.gitleaksignore` to silence the finding — a deletion commit does not remove
anything from history, and rewriting published history breaks every existing
clone while old objects stay reachable by SHA anyway.

## Hardening checklist for self-hosted instances

Most of this is now the default; the checklist is what to verify:

- [ ] Put it behind a VPN or an IP allow-list — this is the control that
      actually matters, since a session is root-equivalent
- [ ] `WPL_LOCAL_MODE` unset or `false`
- [ ] `SECRET_KEY` set to 32+ random bytes (startup aborts otherwise)
- [ ] Reverse proxy with TLS, and `WPL_TRUSTED_PROXIES` matching the chain
      length so the login throttle sees real client IPs
- [ ] `WP_ADMIN_PASSWORD` changed from `admin`
- [ ] `docker compose config` on a project shows no `0.0.0.0:` binding for
      phpMyAdmin, Mailpit, MySQL or Mongo Express
- [ ] Restrict GitHub OAuth `client_id` to the domain you control
- [ ] Review the `sudo` rules in `install.sh` before applying
- [ ] `data/` backed up privately — it holds SSH deployment keys encrypted
      with `SECRET_KEY`
- [ ] Keep Docker and the host kernel patched
