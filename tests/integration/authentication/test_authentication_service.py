from __future__ import annotations

from authentication.crypto.ed25519_signature_verifier import Ed25519SignatureVerifier
from authentication.identity.ed25519_identity_generator import Ed25519IdentityGenerator
from authentication.models.authentication_models import VerifyRequest
from authentication.services.authentication_service import AuthenticationService
from authentication.storage.in_memory_challenge_store import InMemoryChallengeStore
from tests.integration.regtest import create_regtest_payment_with_op_return_via_rpc


def test_verify_login_succeeds_with_real_signature_and_real_rpc_transaction_check(
    verifier,
    rpc_client,
) -> None:
    treasury_address = rpc_client.get_new_address("treasury-auth-success")
    identity = Ed25519IdentityGenerator().generate_identity()
    fee_sats = 35_000
    challenge_store = InMemoryChallengeStore()
    service = AuthenticationService(
        challenge_store=challenge_store,
        signature_verifier=Ed25519SignatureVerifier,
        transaction_verifier=verifier,
        expected_treasury_address=treasury_address,
        expected_fee_sats=fee_sats,
    )

    txid = create_regtest_payment_with_op_return_via_rpc(
        rpc_client=rpc_client,
        treasury_address=treasury_address,
        amount_sats=fee_sats,
        commitment_hex=identity.registration_commitment_hex,
    )
    rpc_client.mine_blocks(1)

    message = service.create_challenge_message(identity.public_key_hex)
    signature = service.sign_outstanding_challenge(
        identity.public_key_hex,
        identity.private_key_hex,
    )
    result = service.verify_login(
        VerifyRequest(
            public_key_hex=identity.public_key_hex,
            txid=txid,
            signature=signature,
        )
    )

    assert "action=login" in message
    assert result.success is True
    assert result.reason is None
    assert challenge_store.get(identity.public_key_hex) is None


def test_verify_login_rejects_real_transaction_for_different_identity_commitment(
    verifier,
    rpc_client,
) -> None:
    treasury_address = rpc_client.get_new_address("treasury-auth-mismatch")
    authenticating_identity = Ed25519IdentityGenerator().generate_identity()
    paid_identity = Ed25519IdentityGenerator().generate_identity()
    fee_sats = 40_000
    challenge_store = InMemoryChallengeStore()
    service = AuthenticationService(
        challenge_store=challenge_store,
        signature_verifier=Ed25519SignatureVerifier,
        transaction_verifier=verifier,
        expected_treasury_address=treasury_address,
        expected_fee_sats=fee_sats,
    )

    txid = create_regtest_payment_with_op_return_via_rpc(
        rpc_client=rpc_client,
        treasury_address=treasury_address,
        amount_sats=fee_sats,
        commitment_hex=paid_identity.registration_commitment_hex,
    )
    rpc_client.mine_blocks(1)

    service.create_challenge_message(authenticating_identity.public_key_hex)
    signature = service.sign_outstanding_challenge(
        authenticating_identity.public_key_hex,
        authenticating_identity.private_key_hex,
    )
    result = service.verify_login(
        VerifyRequest(
            public_key_hex=authenticating_identity.public_key_hex,
            txid=txid,
            signature=signature,
        )
    )

    assert result.success is False
    assert (
        result.reason
        == "Transaction does not contain the expected registration commitment."
    )
    assert challenge_store.get(authenticating_identity.public_key_hex) is not None
