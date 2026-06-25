from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from democracy.funding.models import FundingCampaign, FundingPledge
from democracy.models.solution import Solution
from democracy.funding.service import (
    PLEDGE_INPUT_SEQUENCE,
    FundingService,
    PreparedPledge,
)


def _make_service(
    *, network_id: bytes = b"regtest", min_confirmations: int = 2
) -> FundingService:
    return FundingService(
        repository=object(),
        bitcoin_rpc=object(),
        network_id=network_id,
        min_confirmations=min_confirmations,
    )


def _make_solution() -> Solution:
    return Solution(
        id=UUID("00000000-0000-0000-0000-000000000010"),
        issue_id=UUID("00000000-0000-0000-0000-000000000014"),
        creator_id=UUID("00000000-0000-0000-0000-000000000015"),
        title="Solution title",
        description="Solution description",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_active_campaign(
    *,
    asking_price_sats: int = 100,
    deadline_height: int = 200,
) -> FundingCampaign:
    return FundingCampaign(
        id=UUID("00000000-0000-0000-0000-000000000011"),
        solution_id=UUID("00000000-0000-0000-0000-000000000012"),
        solution_hash="ab" * 32,
        developer_payout_address="bcrt1qexampleaddress",
        asking_price_sats=asking_price_sats,
        deadline_height=deadline_height,
    )


def _make_inactive_campaign() -> FundingCampaign:
    return FundingCampaign(
        id=UUID("00000000-0000-0000-0000-000000000021"),
        solution_id=UUID("00000000-0000-0000-0000-000000000022"),
        solution_hash="ab" * 32,
        developer_payout_address=None,
        asking_price_sats=0,
        deadline_height=None,
    )


def _make_pledge(
    *,
    txid_byte: int,
    vout: int,
    value_sats: int,
    created_at: datetime,
) -> FundingPledge:
    return FundingPledge(
        id=UUID(f"00000000-0000-0000-0000-0000000000{vout + 31:02d}"),
        campaign_id=UUID("00000000-0000-0000-0000-000000000011"),
        pledger_id=UUID("00000000-0000-0000-0000-000000000013"),
        txid=f"{txid_byte:02x}" * 32,
        vout=vout,
        value_sats=value_sats,
        signed_pledge_psbt="cHNidP8BAAoCAAAAAQ==",
        created_at=created_at,
    )


def _make_prepared_pledge(
    *,
    txid_byte: int,
    vout: int,
    value_sats: int,
    created_at: datetime,
    finalized_raw_tx_hex: str = "deadbeef",
) -> PreparedPledge:
    return PreparedPledge(
        pledge=_make_pledge(
            txid_byte=txid_byte,
            vout=vout,
            value_sats=value_sats,
            created_at=created_at,
        ),
        finalized_raw_tx_hex=finalized_raw_tx_hex,
    )


# =========================================================
# FundingService.__init__()
# =========================================================
@pytest.mark.parametrize("network_id", [b"", "regtest", None])
def test_funding_service_init_rejects_invalid_network_id(network_id: object) -> None:
    with pytest.raises(ValueError, match="network_id must be non-empty bytes"):
        FundingService(
            repository=object(),
            bitcoin_rpc=object(),
            network_id=network_id,  # type: ignore[arg-type]
            min_confirmations=0,
        )


@pytest.mark.parametrize("min_confirmations", [-1, -10])
def test_funding_service_init_rejects_negative_min_confirmations(
    min_confirmations: int,
) -> None:
    with pytest.raises(ValueError, match="min_confirmations must be non-negative"):
        FundingService(
            repository=object(),
            bitcoin_rpc=object(),
            network_id=b"regtest",
            min_confirmations=min_confirmations,
        )


# =========================================================
# FundingService.create_campaign()
# =========================================================
@pytest.mark.parametrize("asking_price_sats", [-1, -10])
def test_create_campaign_rejects_negative_asking_price_before_dependency_access(
    asking_price_sats: int,
) -> None:
    service = _make_service()

    with pytest.raises(ValueError, match="asking_price_sats must be non-negative"):
        service.create_campaign(
            solution=_make_solution(),
            developer_payout_address="bcrt1qexampleaddress",
            asking_price_sats=asking_price_sats,
            deadline_height_offset=10,
        )


def test_create_campaign_rejects_payout_address_for_zero_price_before_dependency_access() -> (
    None
):
    service = _make_service()

    with pytest.raises(
        ValueError,
        match="developer_payout_address must be omitted when asking_price_sats is 0",
    ):
        service.create_campaign(
            solution=_make_solution(),
            developer_payout_address="bcrt1qexampleaddress",
            asking_price_sats=0,
            deadline_height_offset=None,
        )


def test_create_campaign_rejects_deadline_offset_for_zero_price_before_dependency_access() -> (
    None
):
    service = _make_service()

    with pytest.raises(
        ValueError,
        match="deadline_height_offset must be omitted when asking_price_sats is 0",
    ):
        service.create_campaign(
            solution=_make_solution(),
            developer_payout_address=None,
            asking_price_sats=0,
            deadline_height_offset=10,
        )


def test_create_campaign_rejects_missing_payout_address_before_dependency_access() -> (
    None
):
    service = _make_service()

    with pytest.raises(
        ValueError,
        match="developer_payout_address is required when asking_price_sats is positive",
    ):
        service.create_campaign(
            solution=_make_solution(),
            developer_payout_address="   ",
            asking_price_sats=10,
            deadline_height_offset=10,
        )


def test_create_campaign_rejects_missing_deadline_offset_before_dependency_access() -> (
    None
):
    service = _make_service()

    with pytest.raises(
        ValueError,
        match="deadline_height_offset is required when asking_price_sats is positive",
    ):
        service.create_campaign(
            solution=_make_solution(),
            developer_payout_address="bcrt1qexampleaddress",
            asking_price_sats=10,
            deadline_height_offset=None,
        )


@pytest.mark.parametrize("deadline_height_offset", [0, -1])
def test_create_campaign_rejects_non_positive_deadline_offset_before_dependency_access(
    deadline_height_offset: int,
) -> None:
    service = _make_service()

    with pytest.raises(ValueError, match="deadline_height_offset must be positive"):
        service.create_campaign(
            solution=_make_solution(),
            developer_payout_address="bcrt1qexampleaddress",
            asking_price_sats=10,
            deadline_height_offset=deadline_height_offset,
        )


# =========================================================
# FundingService.create_pledge_request()
# =========================================================
@pytest.mark.parametrize("txid", ["", "   ", "ab", "g" * 64])
def test_create_pledge_request_rejects_invalid_txid_before_dependency_access(
    txid: str,
) -> None:
    service = _make_service()

    with pytest.raises(ValueError, match="txid"):
        service.create_pledge_request(
            campaign_id=UUID("00000000-0000-0000-0000-000000000011"),
            pledger_id=UUID("00000000-0000-0000-0000-000000000013"),
            txid=txid,
            vout=0,
        )


# =========================================================
# FundingService.submit_signed_pledge()
# =========================================================
@pytest.mark.parametrize("txid", ["", "   ", "ab", "g" * 64])
def test_submit_signed_pledge_rejects_invalid_txid_before_dependency_access(
    txid: str,
) -> None:
    service = _make_service()

    with pytest.raises(ValueError, match="txid"):
        service.submit_signed_pledge(
            campaign_id=UUID("00000000-0000-0000-0000-000000000011"),
            pledger_id=UUID("00000000-0000-0000-0000-000000000013"),
            txid=txid,
            vout=0,
            signed_pledge_psbt="cHNidP8BAAoCAAAAAQ==",
        )


# =========================================================
# FundingService.compute_funding_status()
# =========================================================
@pytest.mark.parametrize("fee_buffer_sats", [-1, -10])
def test_compute_funding_status_rejects_negative_fee_buffer_before_dependency_access(
    fee_buffer_sats: int,
) -> None:
    service = _make_service()

    with pytest.raises(ValueError, match="fee_buffer_sats must be non-negative"):
        service.compute_funding_status(
            campaign_id=UUID("00000000-0000-0000-0000-000000000011"),
            fee_buffer_sats=fee_buffer_sats,
        )


# =========================================================
# FundingService.prepare_final_transaction()
# =========================================================
@pytest.mark.parametrize("fee_buffer_sats", [-1, -10])
def test_prepare_final_transaction_rejects_negative_fee_buffer_before_dependency_access(
    fee_buffer_sats: int,
) -> None:
    service = _make_service()

    with pytest.raises(ValueError, match="fee_buffer_sats must be non-negative"):
        service.prepare_final_transaction(
            campaign_id=UUID("00000000-0000-0000-0000-000000000011"),
            fee_buffer_sats=fee_buffer_sats,
        )


# =========================================================
# FundingService.build_final_transaction()
# =========================================================
@pytest.mark.parametrize("fee_buffer_sats", [-1, -10])
def test_build_final_transaction_rejects_negative_fee_buffer_before_dependency_access(
    fee_buffer_sats: int,
) -> None:
    service = _make_service()

    with pytest.raises(ValueError, match="fee_buffer_sats must be non-negative"):
        service.build_final_transaction(
            campaign_id=UUID("00000000-0000-0000-0000-000000000011"),
            fee_buffer_sats=fee_buffer_sats,
        )


# =========================================================
# FundingService.broadcast_final_transaction()
# =========================================================
@pytest.mark.parametrize("fee_buffer_sats", [-1, -10])
def test_broadcast_final_transaction_rejects_negative_fee_buffer_before_dependency_access(
    fee_buffer_sats: int,
) -> None:
    service = _make_service()

    with pytest.raises(ValueError, match="fee_buffer_sats must be non-negative"):
        service.broadcast_final_transaction(
            campaign_id=UUID("00000000-0000-0000-0000-000000000011"),
            fee_buffer_sats=fee_buffer_sats,
        )


# =========================================================
# FundingService._select_pledges()
# =========================================================
def test_select_pledges_prefers_largest_then_smallest_finishing_pledge() -> None:
    service = _make_service()
    campaign = _make_active_campaign(asking_price_sats=100)
    prepared_pledges = [
        _make_prepared_pledge(
            txid_byte=0x11,
            vout=0,
            value_sats=80,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            finalized_raw_tx_hex="11",
        ),
        _make_prepared_pledge(
            txid_byte=0x22,
            vout=1,
            value_sats=40,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            finalized_raw_tx_hex="22",
        ),
        _make_prepared_pledge(
            txid_byte=0x33,
            vout=2,
            value_sats=30,
            created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
            finalized_raw_tx_hex="33",
        ),
    ]

    selected = service._select_pledges(
        campaign=campaign,
        prepared_pledges=prepared_pledges,
        fee_buffer_sats=10,
    )

    assert selected == [prepared_pledges[0], prepared_pledges[2]]


def test_select_pledges_rejects_negative_fee_buffer() -> None:
    service = _make_service()

    with pytest.raises(ValueError, match="fee_buffer_sats must be non-negative"):
        service._select_pledges(
            campaign=_make_active_campaign(),
            prepared_pledges=[],
            fee_buffer_sats=-1,
        )


def test_select_pledges_rejects_insufficient_total_value() -> None:
    service = _make_service()
    campaign = _make_active_campaign(asking_price_sats=120)
    prepared_pledges = [
        _make_prepared_pledge(
            txid_byte=0x11,
            vout=0,
            value_sats=50,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        _make_prepared_pledge(
            txid_byte=0x22,
            vout=1,
            value_sats=40,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
    ]

    with pytest.raises(ValueError, match="Have 90 sats, need 120 sats"):
        service._select_pledges(
            campaign=campaign,
            prepared_pledges=prepared_pledges,
            fee_buffer_sats=0,
        )


# =========================================================
# FundingService._ensure_campaign_not_expired_at_height()
# =========================================================
def test_ensure_campaign_not_expired_at_height_allows_height_equal_to_deadline() -> (
    None
):
    service = _make_service()

    service._ensure_campaign_not_expired_at_height(
        _make_active_campaign(deadline_height=200),
        current_height=200,
    )


def test_ensure_campaign_not_expired_at_height_rejects_past_deadline() -> None:
    service = _make_service()

    with pytest.raises(
        ValueError, match="Campaign expired at height 200; current height is 201"
    ):
        service._ensure_campaign_not_expired_at_height(
            _make_active_campaign(deadline_height=200),
            current_height=201,
        )


# =========================================================
# FundingService._prepared_pledge_smallest_first_key()
# =========================================================
def test_prepared_pledge_smallest_first_key_orders_by_value_then_created_at() -> None:
    prepared = _make_prepared_pledge(
        txid_byte=0x44,
        vout=3,
        value_sats=25,
        created_at=datetime(2026, 1, 4, 5, 6, 7, tzinfo=timezone.utc),
    )

    assert FundingService._prepared_pledge_smallest_first_key(prepared) == (
        25,
        datetime(2026, 1, 4, 5, 6, 7, tzinfo=timezone.utc),
        "44" * 32,
        3,
    )


# =========================================================
# FundingService._prepared_pledge_largest_first_key()
# =========================================================
def test_prepared_pledge_largest_first_key_orders_by_negative_value_then_created_at() -> (
    None
):
    prepared = _make_prepared_pledge(
        txid_byte=0x55,
        vout=4,
        value_sats=25,
        created_at=datetime(2026, 1, 4, 5, 6, 7, tzinfo=timezone.utc),
    )

    assert FundingService._prepared_pledge_largest_first_key(prepared) == (
        -25,
        datetime(2026, 1, 4, 5, 6, 7, tzinfo=timezone.utc),
        "55" * 32,
        4,
    )


# =========================================================
# FundingService._ensure_utxo_has_min_confirmations()
# =========================================================
def test_ensure_utxo_has_min_confirmations_returns_confirmation_count() -> None:
    service = _make_service(min_confirmations=2)

    assert service._ensure_utxo_has_min_confirmations({"confirmations": "3"}) == 3


def test_ensure_utxo_has_min_confirmations_rejects_insufficient_confirmations() -> None:
    service = _make_service(min_confirmations=2)

    with pytest.raises(ValueError, match="UTXO has 1 confirmations, requires 2"):
        service._ensure_utxo_has_min_confirmations({"confirmations": 1})


# =========================================================
# FundingService._build_pledge_inputs()
# =========================================================
def test_build_pledge_inputs_returns_single_input_with_fixed_sequence() -> None:
    assert FundingService._build_pledge_inputs("ab" * 32, 7) == [
        {
            "txid": "ab" * 32,
            "vout": 7,
            "sequence": PLEDGE_INPUT_SEQUENCE,
        }
    ]


# =========================================================
# FundingService._build_campaign_outputs()
# =========================================================
def test_build_campaign_outputs_returns_payout_and_commitment_outputs_in_order() -> (
    None
):
    campaign = _make_active_campaign(asking_price_sats=12_345_678)

    assert FundingService._build_campaign_outputs(campaign, "deadbeef") == [
        {"bcrt1qexampleaddress": "0.12345678"},
        {"data": "deadbeef"},
    ]


def test_build_campaign_outputs_rejects_inactive_campaign() -> None:
    with pytest.raises(
        ValueError, match="Cannot build outputs for an inactive campaign"
    ):
        FundingService._build_campaign_outputs(_make_inactive_campaign(), "deadbeef")


def test_build_campaign_outputs_rejects_active_campaign_without_payout_address() -> (
    None
):
    campaign = _make_active_campaign()
    object.__setattr__(campaign, "developer_payout_address", None)

    with pytest.raises(
        ValueError, match="Active campaigns must define a payout address"
    ):
        FundingService._build_campaign_outputs(campaign, "deadbeef")


# =========================================================
# FundingService._require_active_campaign()
# =========================================================
def test_require_active_campaign_allows_active_campaign() -> None:
    FundingService._require_active_campaign(_make_active_campaign())


def test_require_active_campaign_rejects_inactive_campaign() -> None:
    campaign = _make_inactive_campaign()

    with pytest.raises(ValueError, match=f"Campaign {campaign.id} is inactive"):
        FundingService._require_active_campaign(campaign)


# =========================================================
# FundingService._extract_single_input_sequence()
# =========================================================
def test_extract_single_input_sequence_returns_single_input_sequence() -> None:
    assert (
        FundingService._extract_single_input_sequence({"vin": [{"sequence": 12345}]})
        == 12345
    )


@pytest.mark.parametrize(
    "decoded_tx",
    [
        {},
        {"vin": []},
        {"vin": [{}, {}]},
    ],
)
def test_extract_single_input_sequence_rejects_transactions_without_exactly_one_input(
    decoded_tx: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="Transaction must have exactly one input"):
        FundingService._extract_single_input_sequence(decoded_tx)


@pytest.mark.parametrize("sequence", ["123", None, 1.5])
def test_extract_single_input_sequence_rejects_non_integer_sequence(
    sequence: object,
) -> None:
    with pytest.raises(
        ValueError,
        match="Transaction input does not contain an integer sequence",
    ):
        FundingService._extract_single_input_sequence({"vin": [{"sequence": sequence}]})
