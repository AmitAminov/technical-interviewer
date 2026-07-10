"""Fernet encryption at rest (DESIGN.md §11).

The symmetric key is auto-generated on first use and stored at
``settings.secret_key_path`` (backend/data/secret.key). All ``*_enc`` DB
columns and the report content go through :func:`encrypt_text` /
:func:`decrypt_text`.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

logger = logging.getLogger(__name__)

_fernet: Optional[Fernet] = None
_lock = threading.Lock()


def get_fernet() -> Fernet:
    """Return the process-wide Fernet instance (auto-generating the key file)."""
    global _fernet
    if _fernet is not None:
        return _fernet
    with _lock:
        if _fernet is not None:
            return _fernet
        key_path = Path(settings.secret_key_path)
        if key_path.exists():
            key = key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_bytes(key)
            logger.info("Generated new Fernet key at %s", key_path)
        _fernet = Fernet(key)
        return _fernet


def encrypt_text(plain: Optional[str]) -> Optional[str]:
    """Encrypt a string; ``None`` passes through as ``None``."""
    if plain is None:
        return None
    token = get_fernet().encrypt(plain.encode("utf-8"))
    return token.decode("ascii")


def decrypt_text(token: Optional[str]) -> Optional[str]:
    """Decrypt a string produced by :func:`encrypt_text`.

    ``None`` passes through. Undecryptable input (corrupt row / rotated key)
    returns an empty string rather than raising, so a single bad row can never
    take down transcript or report endpoints.
    """
    if token is None:
        return None
    try:
        return get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        logger.warning("Failed to decrypt a stored value; returning empty string")
        return ""
