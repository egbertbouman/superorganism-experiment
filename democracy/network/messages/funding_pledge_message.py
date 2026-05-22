from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ipv8.messaging.payload_dataclass import DataClassPayload

from democracy.funding.models import FundingPledge
from democracy.models.utils import parse_datetime
from democracy.network.messages.base_message import BaseMessage


@dataclass
class FundingPledgeMessage(DataClassPayload[6], BaseMessage[FundingPledge]):
    """
    Message to propagate a Bitcoin funding pledge.

    The signed pledge transaction is not broadcast immediately. It is stored
    and later combined with other pledges once the campaign reaches its target.
    """

    id: str
    campaign_id: str
    pledger_id: str
    txid: str
    vout: int
    value_sats: int
    signed_pledge_psbt: str
    created_at: str

    @property
    def entity_id(self) -> UUID:
        return UUID(self.id)

    def brief(self) -> str:
        return (
            "FundingPledge("
            f"id={self.id}, "
            f"campaign_id={self.campaign_id}, "
            f"value_sats={self.value_sats}"
            ")"
        )

    def to_model(self) -> FundingPledge:
        return FundingPledge(
            id=UUID(self.id),
            campaign_id=UUID(self.campaign_id),
            pledger_id=UUID(self.pledger_id),
            txid=self.txid,
            vout=self.vout,
            value_sats=self.value_sats,
            signed_pledge_psbt=self.signed_pledge_psbt,
            created_at=parse_datetime(self.created_at),
        )

    @classmethod
    def from_model(cls, pledge: FundingPledge) -> "FundingPledgeMessage":
        return cls(
            id=str(pledge.id),
            campaign_id=str(pledge.campaign_id),
            pledger_id=str(pledge.pledger_id),
            txid=pledge.txid,
            vout=pledge.vout,
            value_sats=pledge.value_sats,
            signed_pledge_psbt=pledge.signed_pledge_psbt,
            created_at=pledge.created_at.isoformat(),
        )


# Force schema generation once on import.
_ = FundingPledgeMessage(
    id="00000000-0000-0000-0000-000000000000",
    campaign_id="00000000-0000-0000-0000-000000000000",
    pledger_id="00000000-0000-0000-0000-000000000000",
    txid="0" * 64,
    vout=0,
    value_sats=1,
    signed_pledge_psbt="cHNidP8BAAoCAAAAAQ==",
    created_at="1970-01-01T00:00:00+00:00",
)
