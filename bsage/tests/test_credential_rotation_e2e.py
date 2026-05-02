"""End-to-end Credential Store rotation regression — Sprint 4.

Sprint 1 (H11) wrapped the credential store with Fernet encryption and
added the ``bsage rotate-credentials`` CLI. The existing
``test_credential_store.py`` and ``test_cli.py`` cover individual
mechanics:

* the encryption envelope on a single payload,
* a one-shot rotation through the CLI,
* the retired-key fallback for a single legacy ciphertext.

Sprint 4 adds the **end-to-end** scenario the audit (§5 / H11) actually
calls out: in real usage we rotate the ``CREDENTIAL_ENCRYPTION_KEY``
*more than once* over a credential's lifetime, while a long-running
agent already has live ciphertexts written under different generations
of keys. The store must:

1. Accept any payload encrypted under any retired key.
2. Re-encrypt every payload with the *current* primary key on rotation.
3. After the retired key is removed from configuration, all
   credentials must still decrypt — proving rotation actually
   converted them.
4. Mid-rotation crash safety: a partial rotation must leave the store
   in a state where every file is still readable (either old or new
   key chain).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from cryptography.fernet import Fernet, InvalidToken

from bsage.cli import main
from bsage.core.credential_store import CredentialStore


def _key() -> str:
    return Fernet.generate_key().decode("ascii")


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _isolate_event_loop():
    """Click invokes asyncio.run, which closes the running loop. Restore
    a fresh default loop afterward so sibling tests aren't disturbed."""
    import asyncio
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        try:
            yield
        finally:
            asyncio.set_event_loop(asyncio.new_event_loop())

    return _ctx()


# ---------------------------------------------------------------------------
# Multi-generation rotation chain (key0 → key1 → key2)
# ---------------------------------------------------------------------------


class TestMultiGenerationRotation:
    """Chain rotations across multiple credentials, multiple generations."""

    @patch("bsage.cli.get_settings")
    def test_two_consecutive_rotations_preserve_all_payloads(
        self, mock_settings, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Generation 0 → 1 → 2. Each rotation re-encrypts under the
        new primary key while accepting payloads from the prior key.

        After both rotations, configuring only key2 must decrypt every
        credential — proving the data was actually re-encrypted, not
        just papered over by retained-key fallbacks."""
        creds_dir = tmp_path / ".credentials"
        key0 = _key()
        key1 = _key()
        key2 = _key()

        # --- Stage 0: seed credentials under key0 -----------------------------
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            seed = CredentialStore(creds_dir, primary_key=key0)
            loop.run_until_complete(seed.store("notion", {"token": "n0"}))
            loop.run_until_complete(seed.store("telegram", {"bot_token": "t0"}))
            loop.run_until_complete(
                seed.store("google-calendar", {"client_id": "g0", "secret": "x"})
            )
        finally:
            loop.close()

        # --- Stage 1: rotate key0 → key1 via CLI ------------------------------
        s = MagicMock()
        s.credentials_dir = creds_dir
        s.credential_encryption_key = key1
        s.credential_encryption_retired_keys = [key0]
        mock_settings.return_value = s
        with _isolate_event_loop():
            r1 = runner.invoke(main, ["rotate-credentials"])
        assert r1.exit_code == 0, r1.output
        assert "Re-encrypted 3" in r1.output

        # --- Stage 2: rotate key1 → key2 via CLI ------------------------------
        s.credential_encryption_key = key2
        s.credential_encryption_retired_keys = [key1]  # key0 already retired-out
        with _isolate_event_loop():
            r2 = runner.invoke(main, ["rotate-credentials"])
        assert r2.exit_code == 0, r2.output
        assert "Re-encrypted 3" in r2.output

        # --- Stage 3: only key2 — all credentials must decrypt ----------------
        loop = asyncio.new_event_loop()
        try:
            current = CredentialStore(creds_dir, primary_key=key2)
            assert loop.run_until_complete(current.get("notion")) == {"token": "n0"}
            assert loop.run_until_complete(current.get("telegram")) == {"bot_token": "t0"}
            assert loop.run_until_complete(current.get("google-calendar")) == {
                "client_id": "g0",
                "secret": "x",
            }
        finally:
            loop.close()

        # And key0 / key1 alone must NOT decrypt anymore — proving rotation happened.
        loop = asyncio.new_event_loop()
        try:
            stale_old = CredentialStore(creds_dir, primary_key=key0)
            with pytest.raises(InvalidToken):
                loop.run_until_complete(stale_old.get("notion"))
            stale_mid = CredentialStore(creds_dir, primary_key=key1)
            with pytest.raises(InvalidToken):
                loop.run_until_complete(stale_mid.get("telegram"))
        finally:
            loop.close()

    @patch("bsage.cli.get_settings")
    def test_rotation_re_encrypts_legacy_plaintext(
        self, mock_settings, runner: CliRunner, tmp_path: Path
    ) -> None:
        """A pre-encryption legacy ``.json`` plaintext file must be
        re-written as a ciphertext envelope by ``rotate-credentials`` —
        the rotation pass is also our migration path."""
        creds_dir = tmp_path / ".credentials"
        creds_dir.mkdir()
        # Legacy plaintext on disk (pre-Sprint-1 era).
        legacy_path = creds_dir / "legacy-plaintext.json"
        legacy_path.write_text(
            json.dumps({"api_key": "very-secret"}, indent=2),
            encoding="utf-8",
        )

        new_key = _key()
        s = MagicMock()
        s.credentials_dir = creds_dir
        s.credential_encryption_key = new_key
        s.credential_encryption_retired_keys = []
        mock_settings.return_value = s

        with _isolate_event_loop():
            result = runner.invoke(main, ["rotate-credentials"])
        assert result.exit_code == 0, result.output

        # On-disk file must NOW be an encrypted envelope.
        raw = legacy_path.read_text()
        envelope = json.loads(raw)
        assert envelope.get("v") == 1, "Legacy file was not migrated to envelope"
        assert "ct" in envelope
        assert "very-secret" not in raw

        # And the new key alone must decrypt it.
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            store = CredentialStore(creds_dir, primary_key=new_key)
            data = loop.run_until_complete(store.get("legacy-plaintext"))
            assert data == {"api_key": "very-secret"}
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# Mid-rotation crash safety
# ---------------------------------------------------------------------------


class TestRotationCrashSafety:
    """If the process crashes part-way through ``rotate_keys``, every
    on-disk file must still be readable — either with the old key
    (un-rotated) or with the new key (rotated). The store must NEVER
    leave a file unreadable from both."""

    async def test_partial_rotation_leaves_files_readable(self, tmp_path: Path) -> None:
        creds_dir = tmp_path / ".credentials"
        old_key = _key()
        new_key = _key()

        # Seed three credentials under old key.
        seed = CredentialStore(creds_dir, primary_key=old_key)
        await seed.store("a", {"k": 1})
        await seed.store("b", {"k": 2})
        await seed.store("c", {"k": 3})

        # Simulate a partial rotation: rotate only "a" by hand, then
        # crash before "b" / "c" are touched.
        rotating = CredentialStore(creds_dir, primary_key=new_key, retired_keys=[old_key])
        a_data = await rotating.get("a")
        await rotating.store("a", a_data)  # re-encrypt only "a"

        # Read every file with the post-crash configuration:
        # primary=new_key, retired=[old_key]. ALL credentials must still
        # decrypt — "a" via primary, "b" / "c" via retired key.
        post_crash = CredentialStore(creds_dir, primary_key=new_key, retired_keys=[old_key])
        assert await post_crash.get("a") == {"k": 1}
        assert await post_crash.get("b") == {"k": 2}
        assert await post_crash.get("c") == {"k": 3}

        # Resuming the rotation completes cleanly.
        count = await post_crash.rotate_keys()
        assert count == 3

        # And after resume + retiring the old key, all decrypts work.
        finalized = CredentialStore(creds_dir, primary_key=new_key)
        assert await finalized.get("a") == {"k": 1}
        assert await finalized.get("b") == {"k": 2}
        assert await finalized.get("c") == {"k": 3}


# ---------------------------------------------------------------------------
# CLI surface regressions
# ---------------------------------------------------------------------------


class TestRotateCredentialsCLISurface:
    """The CLI is the operator-facing surface — locking in its UX so
    runbook changes (or accidental refactors) cannot break ops."""

    @patch("bsage.cli.get_settings")
    def test_zero_credentials_reports_zero_rotated(
        self, mock_settings, runner: CliRunner, tmp_path: Path
    ) -> None:
        """An empty store + a configured key must succeed and report 0."""
        creds_dir = tmp_path / ".credentials"
        creds_dir.mkdir()

        s = MagicMock()
        s.credentials_dir = creds_dir
        s.credential_encryption_key = _key()
        s.credential_encryption_retired_keys = []
        mock_settings.return_value = s

        with _isolate_event_loop():
            result = runner.invoke(main, ["rotate-credentials"])
        assert result.exit_code == 0, result.output
        assert "Re-encrypted 0" in result.output

    @patch("bsage.cli.get_settings")
    def test_rotation_idempotent(self, mock_settings, runner: CliRunner, tmp_path: Path) -> None:
        """Running rotate-credentials twice in a row with the same key
        must not corrupt anything — the second pass is a no-op rewrite."""
        creds_dir = tmp_path / ".credentials"
        key = _key()

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            seed = CredentialStore(creds_dir, primary_key=key)
            loop.run_until_complete(seed.store("svc", {"data": "v1"}))
        finally:
            loop.close()

        s = MagicMock()
        s.credentials_dir = creds_dir
        s.credential_encryption_key = key
        s.credential_encryption_retired_keys = []
        mock_settings.return_value = s

        with _isolate_event_loop():
            r1 = runner.invoke(main, ["rotate-credentials"])
        assert r1.exit_code == 0
        with _isolate_event_loop():
            r2 = runner.invoke(main, ["rotate-credentials"])
        assert r2.exit_code == 0

        # Payload still decrypts cleanly.
        loop = asyncio.new_event_loop()
        try:
            store = CredentialStore(creds_dir, primary_key=key)
            assert loop.run_until_complete(store.get("svc")) == {"data": "v1"}
        finally:
            loop.close()
