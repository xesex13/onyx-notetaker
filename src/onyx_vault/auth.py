"""Hardware fingerprinting for machine-locked license binding.

get_machine_id() derives a stable, non-reversible identifier for the current
device from its network MAC address (uuid.getnode()), so the license worker
can bind a key to one machine without us transmitting the raw MAC.
"""

from __future__ import annotations

import hashlib
import uuid


def get_machine_id() -> str:
    """Return a stable 16-character SHA-256-derived id for this machine."""
    raw = str(uuid.getnode()).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]
