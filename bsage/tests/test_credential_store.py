"""Tests for bsage.core.credential_store — CredentialStore."""

import json

import pytest
from cryptography.fernet import Fernet

from bsage.core.credential_store import CredentialStore
from bsage.core.exceptions import CredentialNotFoundError


def _make_key() -> str:
    return Fernet.generate_key().decode("ascii")


class TestCredentialStoreGet:
    """Test credential loading."""

    async def test_get_returns_stored_data(self, tmp_path) -> None:
        creds_dir = tmp_path / ".credentials"
        creds_dir.mkdir()
        (creds_dir / "google-calendar.json").write_text(
            json.dumps({"client_id": "abc", "client_secret": "xyz"})
        )
        store = CredentialStore(creds_dir)
        result = await store.get("google-calendar")
        assert result == {"client_id": "abc", "client_secret": "xyz"}

    async def test_get_missing_raises(self, tmp_path) -> None:
        store = CredentialStore(tmp_path / ".credentials")
        with pytest.raises(CredentialNotFoundError, match="No credentials for 'missing'"):
            await store.get("missing")


class TestCredentialStoreStore:
    """Test credential saving."""

    async def test_store_creates_file(self, tmp_path) -> None:
        creds_dir = tmp_path / ".credentials"
        store = CredentialStore(creds_dir)
        await store.store("notion", {"token": "secret-token"})

        path = creds_dir / "notion.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data == {"token": "secret-token"}

    async def test_store_overwrites_existing(self, tmp_path) -> None:
        creds_dir = tmp_path / ".credentials"
        creds_dir.mkdir()
        (creds_dir / "svc.json").write_text(json.dumps({"old": "data"}))

        store = CredentialStore(creds_dir)
        await store.store("svc", {"new": "data"})

        data = json.loads((creds_dir / "svc.json").read_text())
        assert data == {"new": "data"}

    async def test_store_creates_parent_dir(self, tmp_path) -> None:
        creds_dir = tmp_path / "nested" / ".credentials"
        store = CredentialStore(creds_dir)
        await store.store("test", {"key": "value"})
        assert (creds_dir / "test.json").exists()


class TestCredentialStoreDelete:
    """Test credential deletion."""

    async def test_delete_removes_file(self, tmp_path) -> None:
        creds_dir = tmp_path / ".credentials"
        creds_dir.mkdir()
        (creds_dir / "svc.json").write_text("{}")

        store = CredentialStore(creds_dir)
        await store.delete("svc")
        assert not (creds_dir / "svc.json").exists()

    async def test_delete_missing_raises(self, tmp_path) -> None:
        store = CredentialStore(tmp_path / ".credentials")
        with pytest.raises(CredentialNotFoundError):
            await store.delete("nonexistent")


class TestCredentialStoreListServices:
    """Test listing stored credentials."""

    async def test_list_services_empty(self, tmp_path) -> None:
        store = CredentialStore(tmp_path / "no-dir")
        assert store.list_services() == []

    async def test_list_services_returns_sorted_names(self, tmp_path) -> None:
        creds_dir = tmp_path / ".credentials"
        creds_dir.mkdir()
        (creds_dir / "notion.json").write_text("{}")
        (creds_dir / "google-calendar.json").write_text("{}")
        (creds_dir / "telegram.json").write_text("{}")

        store = CredentialStore(creds_dir)
        assert store.list_services() == ["google-calendar", "notion", "telegram"]


class TestCredentialStoreEncryption:
    """Encryption + key rotation support (Sprint 1 / H11)."""

    async def test_store_encrypts_payload_at_rest(self, tmp_path) -> None:
        """When primary_key is set, the on-disk file must NOT contain plaintext."""
        creds_dir = tmp_path / ".credentials"
        store = CredentialStore(creds_dir, primary_key=_make_key())
        secret = "sk-very-secret-token-xyz"

        await store.store("notion", {"token": secret})

        raw = (creds_dir / "notion.json").read_text()
        assert secret not in raw, "Plaintext secret found on disk; encryption did not happen"
        # Encrypted envelope is JSON with version + ciphertext fields.
        envelope = json.loads(raw)
        assert envelope.get("v") == 1
        assert "ct" in envelope
        assert envelope["ct"] != json.dumps({"token": secret})

    async def test_get_decrypts_round_trip(self, tmp_path) -> None:
        creds_dir = tmp_path / ".credentials"
        key = _make_key()
        store = CredentialStore(creds_dir, primary_key=key)

        payload = {"client_id": "abc", "client_secret": "xyz", "scopes": ["a", "b"]}
        await store.store("google-calendar", payload)

        # Fresh instance with same key — must decrypt.
        store2 = CredentialStore(creds_dir, primary_key=key)
        result = await store2.get("google-calendar")
        assert result == payload

    async def test_get_falls_back_to_plaintext_for_legacy_files(self, tmp_path) -> None:
        """Backward compatibility: plaintext .json files written before
        encryption rollout must remain readable when a key is configured."""
        creds_dir = tmp_path / ".credentials"
        creds_dir.mkdir()
        (creds_dir / "telegram.json").write_text(
            json.dumps({"bot_token": "legacy-plain"}, indent=2)
        )

        store = CredentialStore(creds_dir, primary_key=_make_key())
        result = await store.get("telegram")
        assert result == {"bot_token": "legacy-plain"}

    async def test_no_key_keeps_plaintext_behavior(self, tmp_path) -> None:
        """With no key configured, behavior is identical to legacy plaintext store."""
        creds_dir = tmp_path / ".credentials"
        store = CredentialStore(creds_dir)  # no primary_key
        await store.store("svc", {"k": "v"})

        raw = (creds_dir / "svc.json").read_text()
        assert json.loads(raw) == {"k": "v"}

    async def test_get_decrypts_with_retired_key_after_rotation(self, tmp_path) -> None:
        """A credential encrypted under an OLD key must still decrypt when
        the old key is moved to retired_keys after rotation."""
        creds_dir = tmp_path / ".credentials"
        old_key = _make_key()
        new_key = _make_key()

        # Step 1: store with old key as primary.
        old_store = CredentialStore(creds_dir, primary_key=old_key)
        await old_store.store("dropbox", {"token": "old-secret"})

        # Step 2: rotate — new key is primary, old key is retired.
        rotated = CredentialStore(creds_dir, primary_key=new_key, retired_keys=[old_key])
        result = await rotated.get("dropbox")
        assert result == {"token": "old-secret"}

    async def test_get_with_wrong_key_only_raises(self, tmp_path) -> None:
        """If only an unrelated key is supplied, decryption must fail loudly
        (not silently return cipherbytes)."""
        creds_dir = tmp_path / ".credentials"
        write_store = CredentialStore(creds_dir, primary_key=_make_key())
        await write_store.store("svc", {"token": "x"})

        wrong = CredentialStore(creds_dir, primary_key=_make_key())
        with pytest.raises(Exception):  # noqa: B017,PT011 — Fernet raises InvalidToken
            await wrong.get("svc")

    async def test_invalid_key_format_raises_at_construction(self, tmp_path) -> None:
        """Malformed Fernet key must fail fast at CredentialStore init,
        not silently disable encryption."""
        with pytest.raises(ValueError, match="encryption key"):
            CredentialStore(tmp_path / ".credentials", primary_key="not-a-real-fernet-key")

    async def test_rotate_re_encrypts_to_primary_key(self, tmp_path) -> None:
        """rotate_keys() walks all stored credentials, decrypts with any
        accepted key, and rewrites with the current primary key."""
        creds_dir = tmp_path / ".credentials"
        old_key = _make_key()
        new_key = _make_key()

        # Stage existing encrypted credentials under old key.
        seed_store = CredentialStore(creds_dir, primary_key=old_key)
        await seed_store.store("a", {"k": "1"})
        await seed_store.store("b", {"k": "2"})

        # Rotate with new key as primary.
        rotated = CredentialStore(creds_dir, primary_key=new_key, retired_keys=[old_key])
        count = await rotated.rotate_keys()
        assert count == 2

        # After rotation, retired key alone is no longer needed.
        new_only = CredentialStore(creds_dir, primary_key=new_key)
        assert await new_only.get("a") == {"k": "1"}
        assert await new_only.get("b") == {"k": "2"}

    async def test_rotate_keys_no_op_without_encryption(self, tmp_path) -> None:
        """rotate_keys() on an unencrypted store must be a safe no-op (returns 0)."""
        creds_dir = tmp_path / ".credentials"
        store = CredentialStore(creds_dir)
        await store.store("svc", {"k": "v"})
        assert await store.rotate_keys() == 0

    async def test_envelope_without_key_raises_clearly(self, tmp_path) -> None:
        """If on-disk file is encrypted but no key configured, fail loudly."""
        creds_dir = tmp_path / ".credentials"
        seeded = CredentialStore(creds_dir, primary_key=_make_key())
        await seeded.store("svc", {"k": "v"})

        no_key = CredentialStore(creds_dir)  # encryption disabled
        with pytest.raises(RuntimeError, match="encrypted on disk"):
            await no_key.get("svc")
