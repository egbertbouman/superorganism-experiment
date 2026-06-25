from __future__ import annotations

from authentication.identity.models import ApplicationIdentity


# =========================================================
# ApplicationIdentity.registration_commitment_hex
# =========================================================
def test_registration_commitment_hex_returns_expected_digest_for_known_public_key() -> (
    None
):
    identity = ApplicationIdentity(
        public_key_hex="11" * 32,
        private_key_hex="22" * 32,
    )

    result = identity.registration_commitment_hex

    assert result == "0be3b47653ec2e43ca79beb221c78e998823df03b41284501eceedb94610f58c"
