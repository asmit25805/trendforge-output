from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from flowbridge.core.models import Credential, CredentialType, AuthType

# ---------------------------------------------------------------------------
# Simple in‑memory credential vault (for demonstration only)
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)

@dataclass
class CredentialVault:
    """A very small credential store.

    In production this would be backed by an encrypted database or secret manager.
    """

    _store: Dict[str, Credential] = dataclass(init=False, default_factory=dict)
    _lock: threading.Lock = dataclass(init=False, default_factory=threading.Lock)

    def store_credential(self, credential: Credential) -> str:
        """Persist *credential* and return its identifier.
        """
        with self._lock:
            cred_id = credential.id or str(uuid.uuid4())
            credential.id = cred_id
            self._store[cred_id] = credential
            _logger.info("Stored credential %s of type %s", cred_id, credential.type)
            return cred_id

    def retrieve_credential(self, cred_id: str) -> Optional[Credential]:
        """Return the credential with *cred_id* if it exists and is not expired.
        """
        with self._lock:
            cred = self._store.get(cred_id)
            if cred is None:
                _logger.warning("Credential %s not found", cred_id)
                return None
            if cred.expires_at and cred.expires_at < datetime.utcnow():
                _logger.warning("Credential %s has expired", cred_id)
                del self._store[cred_id]
                return None
            return cred

# ---------------------------------------------------------------------------
# Module‑level convenience wrappers (mirroring the public API spec)
# ---------------------------------------------------------------------------

_vault = CredentialVault()

def store_credential(credential: Credential) -> str:
    """Store a credential using the global vault instance.
    """
    return _vault.store_credential(credential)

def retrieve_credential(cred_id: str) -> Optional[Credential]:
    """Retrieve a credential from the global vault instance.
    """
    return _vault.retrieve_credential(cred_id)
