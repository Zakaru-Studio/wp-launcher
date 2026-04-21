"""
SSH service — at-rest encryption of server private keys + paramiko wrapper.

Keys are encrypted with Fernet; the master key is derived from Flask's
SECRET_KEY via HKDF so private keys never hit disk in cleartext.
Rotating SECRET_KEY invalidates all stored keys (admins must re-enter
them).

A 1-byte version prefix is prepended to every token so future HKDF
parameter changes can coexist with already-persisted tokens during a
migration window.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import re
import socket
from dataclasses import dataclass
from typing import Optional, Tuple

import paramiko
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

log = logging.getLogger(__name__)

# Forbidden at rest: a private-key PEM block. Used in log-redaction paths.
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----",
    re.DOTALL,
)


def redact_private_keys(text: str) -> str:
    """Replace any PEM private-key block with a placeholder."""
    if not text:
        return text
    return _PRIVATE_KEY_RE.sub("<<REDACTED_PRIVATE_KEY>>", text)


# ────────────────────────────────────────────────────────────────────────
# Fernet key derivation
# ────────────────────────────────────────────────────────────────────────

_HKDF_SALT = b"wp-launcher-servers"
_HKDF_INFO = b"ssh-keys"

# Version byte prepended to ciphertext so we can rotate the HKDF
# parameters (salt / info / length) in the future without invalidating
# every stored key at once. Bump this *and* add a new derivation branch
# in ``_derive_fernet_for_version`` when you change the scheme.
_CURRENT_VERSION = 1


def _derive_fernet_for_version(secret_key: str, version: int) -> Fernet:
    if version != 1:
        raise RuntimeError(f"Unsupported key-derivation version: {version}")
    if not secret_key:
        raise RuntimeError("SSH service requires Flask SECRET_KEY to derive the encryption key.")
    raw = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(secret_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_private_key(secret_key: str, pem: str) -> bytes:
    """Encrypt a PEM private key string.

    Returns ``bytes(version) || fernet_token``.
    """
    if not pem or "PRIVATE KEY" not in pem:
        raise ValueError("Provided text does not look like a PEM private key.")
    token = _derive_fernet_for_version(secret_key, _CURRENT_VERSION).encrypt(
        pem.encode("utf-8")
    )
    return bytes([_CURRENT_VERSION]) + token


def decrypt_private_key(secret_key: str, token: bytes) -> str:
    """Decrypt a prefixed Fernet token back into a PEM string.

    Backwards-compat: tokens written before the version byte existed
    start with 'gAAAA' (Fernet's base64 marker). We detect that and
    fall back to version 1.
    """
    if not token:
        raise RuntimeError("Empty token.")
    # Legacy tokens start directly with Fernet's base64-url payload.
    if token[:1] == b"g":
        version = 1
        payload = bytes(token)
    else:
        version = token[0]
        payload = bytes(token[1:])
    try:
        return _derive_fernet_for_version(secret_key, version).decrypt(payload).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "Stored SSH key cannot be decrypted. "
            "Did SECRET_KEY change? Re-enter the server's private key."
        ) from exc


# ────────────────────────────────────────────────────────────────────────
# paramiko helpers
# ────────────────────────────────────────────────────────────────────────


def _load_pkey(pem: str) -> paramiko.PKey:
    """Parse a PEM blob into whichever paramiko key type matches.

    Password-protected keys surface as ``PasswordRequiredException``;
    we re-raise those verbatim so callers can show a targeted error
    rather than the generic "unsupported or malformed" message.
    """
    buf = io.StringIO(pem)
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey, paramiko.DSSKey):
        buf.seek(0)
        try:
            return cls.from_private_key(buf)
        except paramiko.PasswordRequiredException:
            raise paramiko.SSHException(
                "This private key is password-protected. Remove the passphrase before uploading."
            )
        except paramiko.SSHException:
            continue
    raise paramiko.SSHException("Unsupported or malformed private key format.")


def _fingerprint(key: paramiko.PKey) -> str:
    """Return a SHA256 fingerprint in OpenSSH-style (`SHA256:<b64>`)."""
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


@dataclass
class TestResult:
    ok: bool
    fingerprint: Optional[str] = None
    error: Optional[str] = None


class HostKeyMismatchError(paramiko.SSHException):
    """Raised when the remote host key does not match the pinned one.

    We don't use ``paramiko.BadHostKeyException`` directly because its
    constructor requires a ``PKey`` for the "expected" argument — and
    we only have the expected *fingerprint*, not the full key bytes.
    """

    def __init__(self, hostname: str, observed: str, expected: str):
        super().__init__(
            f"Host key mismatch for {hostname}: got {observed}, expected {expected}."
        )
        self.hostname = hostname
        self.observed = observed
        self.expected = expected


class _PinnedHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Reject hosts unless their key matches ``expected_fingerprint``.

    If ``expected_fingerprint`` is None we accept whatever the host
    presents and record it — used by ``test_connection`` so the UI can
    surface the new fingerprint for the admin to approve.
    """

    def __init__(self):
        self.expected_fingerprint: Optional[str] = None
        self.observed_fingerprint: Optional[str] = None

    def missing_host_key(self, client, hostname, key):  # noqa: D401
        self.observed_fingerprint = _fingerprint(key)
        if self.expected_fingerprint is None:
            # First contact: accept and record.
            return
        if self.observed_fingerprint != self.expected_fingerprint:
            raise HostKeyMismatchError(
                hostname=hostname,
                observed=self.observed_fingerprint,
                expected=self.expected_fingerprint,
            )


def _build_client(
    pem: str,
    hostname: str,
    ssh_port: int,
    ssh_user: str,
    expected_fingerprint: Optional[str],
    timeout: int = 15,
) -> Tuple[paramiko.SSHClient, _PinnedHostKeyPolicy]:
    """Open an authenticated paramiko SSHClient. Raises on failure."""
    client = paramiko.SSHClient()
    policy = _PinnedHostKeyPolicy()
    policy.expected_fingerprint = expected_fingerprint
    client.set_missing_host_key_policy(policy)

    pkey = _load_pkey(pem)
    client.connect(
        hostname=hostname,
        port=int(ssh_port),
        username=ssh_user,
        pkey=pkey,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
        allow_agent=False,
        look_for_keys=False,
    )
    return client, policy


def test_connection(
    *,
    pem: str,
    hostname: str,
    ssh_port: int = 22,
    ssh_user: str,
    expected_fingerprint: Optional[str] = None,
    timeout: int = 10,
) -> TestResult:
    """Open a short-lived SSH connection and return the observed fingerprint.

    Used by the "Test connection" button in the Add-server modal BEFORE
    the server record is saved: the admin sees the fingerprint and
    explicitly confirms it.
    """
    try:
        client, policy = _build_client(
            pem, hostname, ssh_port, ssh_user, expected_fingerprint, timeout
        )
    except HostKeyMismatchError as exc:
        return TestResult(False, error=str(exc))
    except paramiko.BadHostKeyException:
        return TestResult(False, error="Host key fingerprint does not match the stored one.")
    except paramiko.AuthenticationException:
        return TestResult(False, error="Authentication failed — check the SSH user / private key.")
    except (paramiko.SSHException, socket.error, socket.gaierror, socket.timeout) as exc:
        return TestResult(False, error=f"SSH error: {exc}")
    except Exception as exc:  # noqa: BLE001 — paramiko can raise odd types
        return TestResult(False, error=f"Unexpected error: {exc}")

    try:
        stdin, stdout, _ = client.exec_command("uname -a", timeout=timeout)
        stdout.channel.recv_exit_status()
    except Exception as exc:  # noqa: BLE001 — non-fatal, we still have the fingerprint
        log.warning("test_connection exec 'uname -a' failed on %s: %s", hostname, exc)
    finally:
        client.close()

    return TestResult(True, fingerprint=policy.observed_fingerprint)


def open_client(
    *,
    pem: str,
    hostname: str,
    ssh_port: int,
    ssh_user: str,
    expected_fingerprint: Optional[str],
    timeout: int = 15,
) -> paramiko.SSHClient:
    """Open a fully-verified SSH client ready for exec_command."""
    if not expected_fingerprint:
        raise RuntimeError(
            "Cannot open SSH client without a pinned fingerprint. "
            "Call test_connection first and store the fingerprint on the server record."
        )
    client, _ = _build_client(
        pem, hostname, ssh_port, ssh_user, expected_fingerprint, timeout
    )
    return client
