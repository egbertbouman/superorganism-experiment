from __future__ import annotations

from datetime import datetime, timezone

from authentication.models.registration_models import (
    RegistrationResult,
    StoredRegistration,
)


def test_registration_result_defaults_optional_fields_to_none() -> None:
    result = RegistrationResult(
        success=False,
        public_key_hex="ab" * 32,
        reason="Transaction not found.",
    )

    assert result.success is False
    assert result.public_key_hex == "ab" * 32
    assert result.reason == "Transaction not found."
    assert result.txid is None
    assert result.registered_at is None


def test_stored_registration_preserves_constructor_values() -> None:
    registered_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    registration = StoredRegistration(
        public_key_hex="ab" * 32,
        private_key_hex="cd" * 32,
        txid="ef" * 32,
        registered_at=registered_at,
    )

    assert registration.public_key_hex == "ab" * 32
    assert registration.private_key_hex == "cd" * 32
    assert registration.txid == "ef" * 32
    assert registration.registered_at == registered_at
