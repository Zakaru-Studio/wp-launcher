"""Server model (remote deployment target)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Server:
    """A registered remote deployment target.

    `ssh_private_key_enc` is always the Fernet-encrypted blob. It is
    never exposed by the HTTP API — the `to_public_dict` method strips
    it and swaps in a `has_private_key` boolean.
    """

    label: str
    env: str                        # 'staging' or 'production'
    hostname: str
    ssh_user: str
    deploy_base_path: str
    ssh_port: int = 22
    ssh_private_key_enc: Optional[bytes] = field(default=None, repr=False)
    host_fingerprint: Optional[str] = None
    id: Optional[int] = None
    created_by: Optional[int] = None
    created_at: Optional[str] = None

    def to_public_dict(self) -> dict:
        """Safe shape to return via the HTTP API."""
        return {
            "id": self.id,
            "label": self.label,
            "env": self.env,
            "hostname": self.hostname,
            "ssh_port": self.ssh_port,
            "ssh_user": self.ssh_user,
            "deploy_base_path": self.deploy_base_path,
            "host_fingerprint": self.host_fingerprint,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "has_private_key": bool(self.ssh_private_key_enc),
        }
