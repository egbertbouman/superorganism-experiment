from __future__ import annotations

from authentication.identity.ed25519_identity_generator import Ed25519IdentityGenerator
from authentication.services.registration_service import RegistrationService
from authentication.storage.json_registration_store import JsonRegistrationStore
from tests.integration.regtest import create_regtest_payment_with_op_return_via_rpc


def test_register_persists_successful_registration_in_json_store(
    verifier,
    rpc_client,
    tmp_path,
) -> None:
    treasury_address = rpc_client.get_new_address("treasury-registration-success")
    identity = Ed25519IdentityGenerator().generate_identity()
    fee_sats = 25_000
    store_path = tmp_path / "authentication" / "registrations.json"
    registration_store = JsonRegistrationStore(store_path)
    service = RegistrationService(
        transaction_verifier=verifier,
        registration_store=registration_store,
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

    result = service.register(identity, txid)

    assert result.success is True
    assert result.reason is None
    assert result.public_key_hex == identity.public_key_hex
    assert result.txid == txid
    assert result.registered_at is not None

    reloaded_store = JsonRegistrationStore(store_path)
    stored = reloaded_store.get(identity.public_key_hex)

    assert stored is not None
    assert stored.public_key_hex == identity.public_key_hex
    assert stored.private_key_hex == identity.private_key_hex
    assert stored.txid == txid
    assert stored.registered_at == result.registered_at


def test_register_returns_existing_registration_when_store_already_contains_key(
    verifier,
    rpc_client,
    tmp_path,
) -> None:
    treasury_address = rpc_client.get_new_address("treasury-registration-duplicate")
    identity = Ed25519IdentityGenerator().generate_identity()
    fee_sats = 30_000
    store_path = tmp_path / "authentication" / "registrations.json"
    registration_store = JsonRegistrationStore(store_path)
    service = RegistrationService(
        transaction_verifier=verifier,
        registration_store=registration_store,
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

    first_result = service.register(identity, txid)
    duplicate_result = service.register(identity, txid)

    assert first_result.success is True
    assert duplicate_result.success is False
    assert duplicate_result.reason == "Public key is already registered."
    assert duplicate_result.public_key_hex == identity.public_key_hex
    assert duplicate_result.txid == txid
    assert duplicate_result.registered_at == first_result.registered_at
