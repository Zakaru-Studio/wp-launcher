#!/usr/bin/env python3
"""Re-encrypt stored SSH deployment keys under a new Flask ``SECRET_KEY``.

Why this exists
---------------
``SECRET_KEY`` does double duty: it signs session cookies *and* derives the
Fernet key protecting the SSH private keys in ``data/deployments.db``
(see :mod:`app.services.ssh_service`). Changing it therefore makes every
stored key undecryptable — including installs that ran on the old
``dev-secret-key-change-me`` fallback, whose keys are effectively
unprotected until rotated.

This script decrypts everything with the old key, re-encrypts under the new
one, and verifies the round-trip before committing. Nothing is written
unless every key decrypts first.

Usage
-----
Prefer the environment over ``--old-key``: anything in argv is readable by
every user on the box via ``ps``, and lands in shell history.

    # See what would happen (no writes)
    WPL_OLD_SECRET_KEY="$(grep ^SECRET_KEY= .env | cut -d= -f2-)" \\
        python3 scripts/rotate_secret_key.py --dry-run

    # Rotate away from the historical placeholder, generating a fresh key
    WPL_OLD_SECRET_KEY=dev-secret-key-change-me \\
        python3 scripts/rotate_secret_key.py

Stop the service first: a ``servers`` row created between the read and the
write would keep the old key and become undecryptable.

The new key is printed at the end — put it in ``.env`` as ``SECRET_KEY`` and
restart the service. Everyone gets logged out; that is expected.
"""
import argparse
import os
import secrets
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.ssh_service import decrypt_private_key, encrypt_private_key

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(_REPO_ROOT, 'data', 'deployments.db')
SELECT = (
    "SELECT id, label, ssh_private_key_enc FROM servers "
    "WHERE ssh_private_key_enc IS NOT NULL AND ssh_private_key_enc != ''"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--old-key',
                        help='Current SECRET_KEY. Omit it and the script reads '
                             'WPL_OLD_SECRET_KEY, then SECRET_KEY, from the '
                             'environment — argv is world-readable in `ps`.')
    parser.add_argument('--new-key',
                        help='New SECRET_KEY (default: generate a random 64-char one)')
    parser.add_argument('--db', default=DEFAULT_DB, help=f'Path to deployments.db (default: {DEFAULT_DB})')
    parser.add_argument('--dry-run', action='store_true',
                        help='Decrypt and report, but write nothing')
    args = parser.parse_args()

    old_key = (
        args.old_key
        or os.environ.get('WPL_OLD_SECRET_KEY')
        or os.environ.get('SECRET_KEY')
    )
    if not old_key:
        print("❌ No current key. Set WPL_OLD_SECRET_KEY (preferred) or pass "
              "--old-key.", file=sys.stderr)
        return 1

    if not os.path.exists(args.db):
        print(f"❌ Database not found: {args.db}", file=sys.stderr)
        return 1

    new_key = args.new_key or secrets.token_hex(32)
    if len(new_key) < 32:
        print("❌ New key must be at least 32 characters.", file=sys.stderr)
        return 1

    con = sqlite3.connect(args.db)
    rows = con.execute(SELECT).fetchall()
    if not rows:
        print("Nothing to migrate: no stored SSH keys.")
        print(f"\nNew SECRET_KEY:\n{new_key}")
        return 0

    # Phase 1 — decrypt everything before touching the database. A key that
    # fails here means the old key is wrong, and a partial rewrite would
    # leave the table split across two encryption keys.
    print(f"{len(rows)} stored key(s) in {args.db}\n")
    plaintexts = {}
    for server_id, label, blob in rows:
        try:
            pem = decrypt_private_key(old_key, bytes(blob))
        except Exception as exc:
            print(f"  ❌ #{server_id} {label!r}: {type(exc).__name__}: {exc}", file=sys.stderr)
            print("\nAborted — nothing was written. Is the current key correct?", file=sys.stderr)
            return 1
        plaintexts[server_id] = (label, pem)
        print(f"  ✅ #{server_id} {label!r}: decrypted ({len(pem)} bytes)")

    if args.dry_run:
        print("\n--dry-run: no changes written.")
        return 0

    backup = f"{args.db}.backup-rotate-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(args.db, backup)
    print(f"\nBackup: {backup}")

    # Phase 2 — re-encrypt
    for server_id, (_, pem) in plaintexts.items():
        con.execute(
            "UPDATE servers SET ssh_private_key_enc = ? WHERE id = ?",
            (encrypt_private_key(new_key, pem), server_id),
        )
    # Phase 3 — read back and confirm the round-trip BEFORE committing, so a
    # mismatch rolls back instead of leaving a half-encrypted table on disk.
    print("\nVerifying:")
    for server_id, label, blob in con.execute(SELECT):
        restored = decrypt_private_key(new_key, bytes(blob))
        if restored != plaintexts[server_id][1]:
            con.rollback()
            print(f"  ❌ #{server_id} {label!r}: round-trip mismatch — rolled back",
                  file=sys.stderr)
            return 1
        print(f"  ✅ #{server_id} {label!r}: re-encrypted and verified")

    con.commit()

    print(f"\nDone. Put this in .env as SECRET_KEY and restart:\n\n{new_key}\n")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
