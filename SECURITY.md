# Security Policy

## Scope & design assumptions

WP Launcher is designed for **local development environments only**.

By design, it ships with convenience defaults that are **not** suitable for
production or internet-exposed use:

- Weak default credentials on generated WordPress/MySQL containers
  (`admin/admin`, `wordpress/wordpress`, `rootpassword`)
- Auto-login helpers for WordPress admin
- `sudo` invocations for file permissions on bind-mounted WordPress files
- No rate limiting on the web UI

Running WP Launcher on a public network is out of scope. Vulnerabilities that
can only be exploited in that configuration will be documented but may not be
prioritised.

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
   <https://github.com/AK-Digital-Ltd/wp-launcher/security/advisories/new>
2. Email: **security@akdigital.fr**

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

- Default WordPress admin credentials are `admin` / `admin`
- Default MySQL root password is `rootpassword`
- Session cookies default to `SESSION_COOKIE_SECURE=false` for local HTTP
  convenience — set it to `true` in any HTTPS deployment
- The app requires `sudo` NOPASSWD for `chmod`, `chown`, `find` on WordPress
  directories (documented in `install.sh`)

## Hardening checklist for non-default deployments

If you must run WP Launcher in an environment that isn't your local machine:

- [ ] Put it behind a VPN or SSH tunnel
- [ ] Change all default WordPress/MySQL credentials
- [ ] Export `SESSION_COOKIE_SECURE=true`
- [ ] Export a strong `SECRET_KEY` (≥ 32 random bytes)
- [ ] Restrict GitHub OAuth `client_id` to the domain you control
- [ ] Review the `sudo` rules in `install.sh` before applying
- [ ] Keep Docker and the host kernel patched
