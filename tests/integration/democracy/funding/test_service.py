from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import pytest

from democracy.funding.bitcoin_tx import parse_transaction
from democracy.funding.models import FundingCampaign, FundingPledge
from democracy.funding.service import FundingService
from democracy.models.issue import Issue
from democracy.models.solution import Solution
from democracy.storage.sqlite_repository import SQLiteDemocracyRepository
from tests.integration.regtest import RegtestBitcoinRpcClient


@pytest.fixture()
def repository() -> SQLiteDemocracyRepository:
    with TemporaryDirectory() as tmpdir:
        repo = SQLiteDemocracyRepository(Path(tmpdir) / "funding-service.sqlite3")
        try:
            yield repo
        finally:
            repo.close()


def _make_service(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
    *,
    network_id: bytes = b"regtest",
    min_confirmations: int = 1,
) -> FundingService:
    return FundingService(
        repository=repository,
        bitcoin_rpc=rpc_client,
        network_id=network_id,
        min_confirmations=min_confirmations,
    )


def _store_solution(repository: SQLiteDemocracyRepository) -> Solution:
    issue = Issue(
        title=f"Issue {uuid4().hex[:8]}",
        description="Funding integration issue",
        creator_id=uuid4(),
    )
    repository.add_issue(issue)

    solution = Solution(
        title=f"Solution {uuid4().hex[:8]}",
        description="Funding integration solution",
        creator_id=uuid4(),
        issue_id=issue.id,
    )
    repository.add_solution(solution)
    return solution


def _create_campaign(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
    *,
    asking_price_sats: int,
    deadline_height_offset: int = 20,
    min_confirmations: int = 1,
) -> FundingCampaign:
    service = _make_service(
        repository,
        rpc_client,
        min_confirmations=min_confirmations,
    )
    solution = _store_solution(repository)
    payout_address = rpc_client.get_new_address(f"developer-{uuid4().hex[:8]}")
    return service.create_campaign(
        solution=solution,
        developer_payout_address=payout_address,
        asking_price_sats=asking_price_sats,
        deadline_height_offset=deadline_height_offset,
    )


def _find_vout_for_address(
    rpc_client: RegtestBitcoinRpcClient,
    txid: str,
    address: str,
) -> int:
    decoded = rpc_client.get_raw_transaction(txid)

    for output in decoded["vout"]:
        script_pubkey = output.get("scriptPubKey", {})
        if script_pubkey.get("address") == address:
            return int(output["n"])

        addresses = script_pubkey.get("addresses")
        if isinstance(addresses, list) and address in addresses:
            return int(output["n"])

    raise AssertionError(f"Could not find output for address {address} in tx {txid}")


def _create_confirmed_utxo(
    rpc_client: RegtestBitcoinRpcClient,
    *,
    amount_sats: int,
    confirmations: int,
) -> tuple[str, int, str]:
    address = rpc_client.get_new_address(f"pledge-{uuid4().hex[:8]}")
    txid = rpc_client.send_to_address(address, amount_sats)

    if confirmations > 0:
        rpc_client.mine_blocks(confirmations)

    vout = _find_vout_for_address(rpc_client, txid, address)
    rpc_client.lock_unspent(
        False,
        [
            {
                "txid": txid,
                "vout": vout,
            }
        ],
    )
    return txid, vout, address


def _create_signed_pledge_request(
    service: FundingService,
    rpc_client: RegtestBitcoinRpcClient,
    campaign: FundingCampaign,
    *,
    amount_sats: int,
    confirmations: int,
    pledger_id: UUID | None = None,
) -> tuple[str, int, str]:
    txid, vout, _ = _create_confirmed_utxo(
        rpc_client,
        amount_sats=amount_sats,
        confirmations=confirmations,
    )
    request = service.create_pledge_request(
        campaign_id=campaign.id,
        pledger_id=pledger_id or uuid4(),
        txid=txid,
        vout=vout,
    )
    signed_psbt = rpc_client.sign_psbt_anyonecanpay(request.psbt_base64)
    return txid, vout, signed_psbt


def _submit_pledge(
    service: FundingService,
    rpc_client: RegtestBitcoinRpcClient,
    campaign: FundingCampaign,
    *,
    amount_sats: int,
    confirmations: int,
    pledger_id: UUID | None = None,
) -> FundingPledge:
    actual_pledger_id = pledger_id or uuid4()
    txid, vout, signed_psbt = _create_signed_pledge_request(
        service,
        rpc_client,
        campaign,
        amount_sats=amount_sats,
        confirmations=confirmations,
        pledger_id=actual_pledger_id,
    )
    return service.submit_signed_pledge(
        campaign_id=campaign.id,
        pledger_id=actual_pledger_id,
        txid=txid,
        vout=vout,
        signed_pledge_psbt=signed_psbt,
    )


# =========================================================
# FundingService.create_campaign()
# =========================================================
def test_create_campaign_persists_campaign_with_chain_derived_deadline(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    service = _make_service(repository, rpc_client)
    solution = _store_solution(repository)
    payout_address = rpc_client.get_new_address("developer-create-campaign")
    current_height = rpc_client.get_block_count()

    campaign = service.create_campaign(
        solution=solution,
        developer_payout_address=payout_address,
        asking_price_sats=125_000,
        deadline_height_offset=12,
    )

    assert campaign.solution_id == solution.id
    assert campaign.solution_hash == solution.compute_hash()
    assert campaign.developer_payout_address == payout_address
    assert campaign.asking_price_sats == 125_000
    assert campaign.deadline_height == current_height + 12
    assert repository.get_campaign(campaign.id) == campaign


# =========================================================
# FundingService.create_pledge_request()
# =========================================================
def test_create_pledge_request_builds_unsigned_anyonecanpay_psbt(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    service = _make_service(repository, rpc_client, min_confirmations=1)
    campaign = _create_campaign(
        repository,
        rpc_client,
        asking_price_sats=100_000,
        min_confirmations=1,
    )
    txid, vout, _ = _create_confirmed_utxo(
        rpc_client,
        amount_sats=150_000,
        confirmations=1,
    )

    request = service.create_pledge_request(
        campaign_id=campaign.id,
        pledger_id=uuid4(),
        txid=txid,
        vout=vout,
    )

    assert request.campaign_id == campaign.id
    assert request.txid == txid
    assert request.vout == vout
    assert request.value_sats == 150_000
    assert request.psbt_base64
    assert request.sighash_type == "ALL|ANYONECANPAY"
    assert request.campaign_commitment_hex == campaign.compute_campaign_commitment_hex(
        b"regtest"
    )
    assert request.developer_payout_address == campaign.developer_payout_address
    assert request.asking_price_sats == campaign.asking_price_sats
    assert request.deadline_height == campaign.deadline_height


# =========================================================
# FundingService.submit_signed_pledge()
# =========================================================
def test_submit_signed_pledge_stores_valid_pledge(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    service = _make_service(repository, rpc_client, min_confirmations=1)
    campaign = _create_campaign(
        repository,
        rpc_client,
        asking_price_sats=100_000,
        min_confirmations=1,
    )
    pledger_id = uuid4()
    txid, vout, signed_psbt = _create_signed_pledge_request(
        service,
        rpc_client,
        campaign,
        amount_sats=130_000,
        confirmations=1,
        pledger_id=pledger_id,
    )

    pledge = service.submit_signed_pledge(
        campaign_id=campaign.id,
        pledger_id=pledger_id,
        txid=txid,
        vout=vout,
        signed_pledge_psbt=signed_psbt,
    )

    assert pledge.campaign_id == campaign.id
    assert pledge.pledger_id == pledger_id
    assert pledge.txid == txid
    assert pledge.vout == vout
    assert pledge.value_sats == 130_000
    assert repository.get_pledge(pledge.id) == pledge


# =========================================================
# FundingService.validate_pledge()
# =========================================================
def test_validate_pledge_accepts_stored_valid_pledge(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    service = _make_service(repository, rpc_client, min_confirmations=1)
    campaign = _create_campaign(
        repository,
        rpc_client,
        asking_price_sats=90_000,
        min_confirmations=1,
    )
    pledge = _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=120_000,
        confirmations=1,
    )

    validation = service.validate_pledge(pledge)

    assert validation.valid is True
    assert validation.reason is None


def test_validate_pledge_rejects_pledge_when_stored_value_differs_from_chain(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    service = _make_service(repository, rpc_client, min_confirmations=1)
    campaign = _create_campaign(
        repository,
        rpc_client,
        asking_price_sats=90_000,
        min_confirmations=1,
    )
    pledge = _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=120_000,
        confirmations=1,
    )

    tampered_pledge = FundingPledge(
        campaign_id=pledge.campaign_id,
        pledger_id=pledge.pledger_id,
        txid=pledge.txid,
        vout=pledge.vout,
        value_sats=pledge.value_sats + 1,
        signed_pledge_psbt=pledge.signed_pledge_psbt,
    )

    validation = service.validate_pledge(tampered_pledge)

    assert validation.valid is False
    assert validation.reason == "Stored pledge value does not match UTXO."


# =========================================================
# FundingService.get_valid_pledges()
# =========================================================
def test_get_valid_pledges_filters_out_pledges_below_confirmation_threshold(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    submit_service = _make_service(repository, rpc_client, min_confirmations=1)
    read_service = _make_service(repository, rpc_client, min_confirmations=2)
    campaign = _create_campaign(
        repository,
        rpc_client,
        asking_price_sats=100_000,
        min_confirmations=1,
    )

    older_pledge = _submit_pledge(
        submit_service,
        rpc_client,
        campaign,
        amount_sats=70_000,
        confirmations=2,
    )
    newer_pledge = _submit_pledge(
        submit_service,
        rpc_client,
        campaign,
        amount_sats=50_000,
        confirmations=1,
    )

    valid_pledges = read_service.get_valid_pledges(campaign.id)

    assert valid_pledges == [older_pledge]
    assert newer_pledge not in valid_pledges


# =========================================================
# FundingService.compute_funding_status()
# =========================================================
def test_compute_funding_status_sums_currently_valid_pledges(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    service = _make_service(repository, rpc_client, min_confirmations=1)
    campaign = _create_campaign(
        repository,
        rpc_client,
        asking_price_sats=100_000,
        min_confirmations=1,
    )
    _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=60_000,
        confirmations=1,
    )
    _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=50_000,
        confirmations=1,
    )

    status = service.compute_funding_status(campaign.id, fee_buffer_sats=5_000)

    assert status.campaign_id == campaign.id
    assert status.asking_price_sats == 100_000
    assert status.valid_pledge_total_sats == 110_000
    assert status.required_total_sats == 105_000
    assert status.valid_pledge_count == 2
    assert status.is_expired is False
    assert status.is_fundable is True


# =========================================================
# FundingService.prepare_final_transaction()
# =========================================================
def test_prepare_final_transaction_selects_pledges_using_service_heuristic(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    service = _make_service(repository, rpc_client, min_confirmations=1)
    campaign = _create_campaign(
        repository,
        rpc_client,
        asking_price_sats=100_000,
        min_confirmations=1,
    )
    pledge_a = _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=80_000,
        confirmations=1,
    )
    _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=40_000,
        confirmations=1,
    )
    pledge_c = _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=30_000,
        confirmations=1,
    )

    plan = service.prepare_final_transaction(campaign.id, fee_buffer_sats=10_000)
    parsed = parse_transaction(plan.final_raw_tx_hex)

    assert plan.campaign_id == campaign.id
    assert plan.selected_pledges == [pledge_a, pledge_c]
    assert plan.selected_total_sats == 110_000
    assert plan.required_total_sats == 110_000
    assert len(parsed.inputs) == 2
    assert parsed.txid()


# =========================================================
# FundingService.build_final_transaction()
# =========================================================
def test_build_final_transaction_returns_same_raw_transaction_as_prepared_plan(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    service = _make_service(repository, rpc_client, min_confirmations=1)
    campaign = _create_campaign(
        repository,
        rpc_client,
        asking_price_sats=100_000,
        min_confirmations=1,
    )
    _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=80_000,
        confirmations=1,
    )
    _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=40_000,
        confirmations=1,
    )
    _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=30_000,
        confirmations=1,
    )

    expected = service.prepare_final_transaction(
        campaign.id,
        fee_buffer_sats=10_000,
    ).final_raw_tx_hex

    actual = service.build_final_transaction(
        campaign.id,
        fee_buffer_sats=10_000,
    )

    assert actual == expected


# =========================================================
# FundingService.broadcast_final_transaction()
# =========================================================
def test_broadcast_final_transaction_broadcasts_and_confirms_combined_funding_tx(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    service = _make_service(repository, rpc_client, min_confirmations=1)
    campaign = _create_campaign(
        repository,
        rpc_client,
        asking_price_sats=100_000,
        min_confirmations=1,
    )
    _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=60_000,
        confirmations=1,
    )
    _submit_pledge(
        service,
        rpc_client,
        campaign,
        amount_sats=50_000,
        confirmations=1,
    )

    final_txid = service.broadcast_final_transaction(
        campaign.id,
        fee_buffer_sats=0,
    )
    before_mine = rpc_client.get_raw_transaction(final_txid)

    rpc_client.mine_blocks(1)
    after_mine = rpc_client.get_raw_transaction(final_txid)

    assert before_mine["txid"] == final_txid
    assert after_mine["txid"] == final_txid
    assert after_mine["confirmations"] >= 1


# =========================================================
# End-to-end flow
# =========================================================
def test_paid_campaign_end_to_end_flow_from_campaign_to_broadcast(
    repository: SQLiteDemocracyRepository,
    rpc_client: RegtestBitcoinRpcClient,
) -> None:
    service = _make_service(repository, rpc_client, min_confirmations=1)
    solution = _store_solution(repository)
    payout_address = rpc_client.get_new_address("developer-end-to-end")

    campaign = service.create_campaign(
        solution=solution,
        developer_payout_address=payout_address,
        asking_price_sats=100_000,
        deadline_height_offset=20,
    )

    pledger_one = uuid4()
    txid_one, vout_one, signed_psbt_one = _create_signed_pledge_request(
        service,
        rpc_client,
        campaign,
        amount_sats=80_000,
        confirmations=1,
        pledger_id=pledger_one,
    )
    pledge_one = service.submit_signed_pledge(
        campaign_id=campaign.id,
        pledger_id=pledger_one,
        txid=txid_one,
        vout=vout_one,
        signed_pledge_psbt=signed_psbt_one,
    )

    pledger_two = uuid4()
    txid_two, vout_two, signed_psbt_two = _create_signed_pledge_request(
        service,
        rpc_client,
        campaign,
        amount_sats=40_000,
        confirmations=1,
        pledger_id=pledger_two,
    )
    pledge_two = service.submit_signed_pledge(
        campaign_id=campaign.id,
        pledger_id=pledger_two,
        txid=txid_two,
        vout=vout_two,
        signed_pledge_psbt=signed_psbt_two,
    )

    pledger_three = uuid4()
    txid_three, vout_three, signed_psbt_three = _create_signed_pledge_request(
        service,
        rpc_client,
        campaign,
        amount_sats=30_000,
        confirmations=1,
        pledger_id=pledger_three,
    )
    pledge_three = service.submit_signed_pledge(
        campaign_id=campaign.id,
        pledger_id=pledger_three,
        txid=txid_three,
        vout=vout_three,
        signed_pledge_psbt=signed_psbt_three,
    )

    with pytest.raises(
        ValueError,
        match=(
            f"Pledge already exists for outpoint {pledge_one.txid}:{pledge_one.vout} "
            f"in campaign {campaign.id}"
        ),
    ):
        service.submit_signed_pledge(
            campaign_id=campaign.id,
            pledger_id=pledger_one,
            txid=txid_one,
            vout=vout_one,
            signed_pledge_psbt=signed_psbt_one,
        )

    validation = service.validate_pledge(pledge_one)
    valid_pledges = service.get_valid_pledges(campaign.id)
    status = service.compute_funding_status(campaign.id, fee_buffer_sats=10_000)
    plan = service.prepare_final_transaction(campaign.id, fee_buffer_sats=10_000)
    built_raw_tx_hex = service.build_final_transaction(
        campaign.id,
        fee_buffer_sats=10_000,
    )
    parsed_final_tx = parse_transaction(plan.final_raw_tx_hex)

    final_txid = service.broadcast_final_transaction(
        campaign.id,
        fee_buffer_sats=10_000,
    )
    rpc_client.mine_blocks(1)
    confirmed_final_tx = rpc_client.get_raw_transaction(final_txid)

    assert repository.get_campaign(campaign.id) == campaign
    assert repository.get_pledges_for_campaign(campaign.id) == [
        pledge_one,
        pledge_two,
        pledge_three,
    ]
    assert validation.valid is True
    assert validation.reason is None
    assert valid_pledges == [pledge_one, pledge_two, pledge_three]
    assert status.valid_pledge_total_sats == 150_000
    assert status.required_total_sats == 110_000
    assert status.valid_pledge_count == 3
    assert status.is_expired is False
    assert status.is_fundable is True
    assert plan.selected_pledges == [pledge_one, pledge_three]
    assert plan.selected_total_sats == 110_000
    assert plan.required_total_sats == 110_000
    assert built_raw_tx_hex == plan.final_raw_tx_hex
    assert len(parsed_final_tx.inputs) == 2
    assert confirmed_final_tx["txid"] == final_txid
    assert confirmed_final_tx["confirmations"] >= 1
