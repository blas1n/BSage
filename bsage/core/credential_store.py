"""CredentialStore — JSON file-backed credential storage for Skills.

Supports optional symmetric encryption at rest via Fernet (AES-128-CBC + HMAC).
Encryption is enabled by passing ``primary_key`` (and optionally ``retired_keys``
for rotation). When no key is supplied the store falls back to plaintext JSON
for backward compatibility — production deployments must configure a key via
``Settings.credential_encryption_key``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import structlog
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from bsage.core.exceptions import CredentialNotFoundError

logger = structlog.get_logger(__name__)

ENVELOPE_VERSION = 1


def _build_multi(primary: str, retired: list[str]) -> MultiFernet:
    """Build a MultiFernet from base64 keys. Primary first → used for new
    encryptions. Retired keys after → accepted for decryption only."""
    fernets: list[Fernet] = []
    try:
        fernets.append(Fernet(primary.encode("ascii")))
        for k in retired:
            if not k:
                continue
            fernets.append(Fernet(k.encode("ascii")))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Invalid Fernet encryption key — must be a 32-byte url-safe base64 "
            "value as produced by Fernet.generate_key()."
        ) from exc
    return MultiFernet(fernets)


class CredentialStore:
    """Stores and loads credentials from .credentials/{name}.json.

    Skills access credentials via context.credentials.get("service-name")
    to authenticate with external APIs. Each service's credentials are
    stored as a separate JSON file.

    When ``primary_key`` is supplied, payloads are encrypted with Fernet
    before being written to disk. Older ciphertexts from rotated keys
    decrypt transparently if those keys are passed via ``retired_keys``.
    """

    def __init__(
        self,
        credentials_dir: Path,
        *,
        primary_key: str | None = None,
        retired_keys: list[str] | None = None,
    ) -> None:
        self._dir = credentials_dir
        self._primary_key = primary_key or None
        self._retired_keys = list(retired_keys or [])
        self._cipher: MultiFernet | None = None
        if self._primary_key:
            self._cipher = _build_multi(self._primary_key, self._retired_keys)

    @property
    def encryption_enabled(self) -> bool:
        return self._cipher is not None

    async def get(self, name: str) -> dict[str, Any]:
        """Load credentials for a named service.

        Args:
            name: Service identifier (e.g. "google-calendar").

        Returns:
            Dict of credential data.

        Raises:
            CredentialNotFoundError: If no credentials exist for the service.
        """
        path = self._dir / f"{name}.json"
        if not path.exists():
            logger.warning("credential_not_found", service=name)
            raise CredentialNotFoundError(f"No credentials for '{name}'")

        raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
        data = self._decode(raw, service=name)
        logger.debug("credential_loaded", service=name, encrypted=self.encryption_enabled)
        return data

    async def store(self, name: str, data: dict[str, Any]) -> None:
        """Save credentials for a named service.

        Args:
            name: Service identifier.
            data: Credential data to persist.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{name}.json"
        content = self._encode(data)
        await asyncio.to_thread(path.write_text, content, encoding="utf-8")
        logger.info("credential_stored", service=name, encrypted=self.encryption_enabled)

    async def delete(self, name: str) -> None:
        """Remove credentials for a named service.

        Args:
            name: Service identifier.

        Raises:
            CredentialNotFoundError: If no credentials exist for the service.
        """
        path = self._dir / f"{name}.json"
        if not path.exists():
            raise CredentialNotFoundError(f"No credentials for '{name}'")
        path.unlink()
        logger.info("credential_deleted", service=name)

    def list_services(self) -> list[str]:
        """Return names of all services with stored credentials."""
        if not self._dir.is_dir():
            return []
        return sorted(p.stem for p in self._dir.glob("*.json"))

    async def rotate_keys(self) -> int:
        """Re-encrypt every stored credential with the current primary key.

        Used after rotating ``credential_encryption_key`` to clear out
        ciphertexts produced by retired keys. Caller should subsequently
        drop entries from ``credential_encryption_retired_keys``.

        Returns:
            Number of credential files re-written.
        """
        if not self.encryption_enabled:
            return 0
        names = self.list_services()
        for name in names:
            data = await self.get(name)
            await self.store(name, data)
        if names:
            logger.info("credential_rotation_complete", count=len(names))
        return len(names)

    # --- Encoding helpers --------------------------------------------------

    def _encode(self, data: dict[str, Any]) -> str:
        """Encode payload for disk. Encrypts when a primary key is set,
        otherwise emits plaintext JSON for backward compatibility."""
        if not self._cipher:
            return json.dumps(data, indent=2)
        plaintext = json.dumps(data).encode("utf-8")
        ciphertext = self._cipher.encrypt(plaintext).decode("ascii")
        envelope = {"v": ENVELOPE_VERSION, "ct": ciphertext}
        return json.dumps(envelope, indent=2)

    def _decode(self, raw: str, *, service: str) -> dict[str, Any]:
        """Decode payload from disk. Handles three cases:

        1. Encrypted envelope ({v, ct}) — decrypt with current key set.
        2. Legacy plaintext payload — return as-is.
        3. Encrypted envelope but no key configured — raise.
        """
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed.get("v") == ENVELOPE_VERSION and "ct" in parsed:
            if not self._cipher:
                raise RuntimeError(
                    f"Credential '{service}' is encrypted on disk but no "
                    "credential_encryption_key is configured."
                )
            try:
                plaintext = self._cipher.decrypt(parsed["ct"].encode("ascii"))
            except InvalidToken as exc:
                logger.error("credential_decrypt_failed", service=service)
                raise InvalidToken(
                    f"Failed to decrypt credential '{service}' — wrong or rotated key."
                ) from exc
            return json.loads(plaintext.decode("utf-8"))
        # Legacy plaintext file (pre-encryption rollout).
        return parsed
