from __future__ import annotations

from authentication.transaction_verification.models import (
    NormalizedTransaction,
    TransactionVerificationRequest,
)
from tests.integration.regtest import create_regtest_payment_with_op_return


def _amount_paid_to_address(tx: NormalizedTransaction, address: str) -> int:
    return sum(output.value_sats for output in tx.outputs if output.address == address)


def _contains_op_return_commitment(
    tx: NormalizedTransaction,
    commitment_hex: str,
) -> bool:
    normalized_commitment = commitment_hex.lower()
    return any(
        output.address is None
        and output.value_sats == 0
        and output.script_hex.lower().startswith("6a")
        and output.script_hex.lower().endswith(normalized_commitment)
        for output in tx.outputs
    )


def test_fetch_transaction_returns_none_for_unknown_txid(verifier) -> None:
    assert verifier._fetch_transaction("00" * 32) is None


def test_fetch_transaction_normalizes_real_regtest_transaction(
    verifier,
    rpc_client,
) -> None:
    treasury_address = rpc_client.get_new_address("treasury-normalized")
    commitment_hex = "0123abcddeadbeef"
    fee_sats = 50_000

    txid = create_regtest_payment_with_op_return(
        treasury_address=treasury_address,
        amount_sats=fee_sats,
        commitment_hex=commitment_hex,
    )

    tx = verifier._fetch_transaction(txid)

    assert tx is not None
    assert tx.txid == txid
    assert tx.confirmations == 0
    assert _amount_paid_to_address(tx, treasury_address) == fee_sats
    assert _contains_op_return_commitment(tx, commitment_hex) is True


def test_verify_succeeds_for_real_confirmed_transaction(verifier, rpc_client) -> None:
    treasury_address = rpc_client.get_new_address("treasury-verified")
    commitment_hex = "beadfeed01234567"
    fee_sats = 25_000

    txid = create_regtest_payment_with_op_return(
        treasury_address=treasury_address,
        amount_sats=fee_sats,
        commitment_hex=commitment_hex,
    )
    rpc_client.mine_blocks(1)

    request = TransactionVerificationRequest(
        txid=txid,
        expected_treasury_address=treasury_address,
        expected_fee_sats=fee_sats,
        expected_registration_commitment=commitment_hex,
    )

    result = verifier.verify(request)

    assert result.success is True
    assert result.reason is None
    assert result.amount_paid_sats == fee_sats
    assert result.confirmations >= 1
