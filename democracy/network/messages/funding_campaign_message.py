from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ipv8.messaging.payload_dataclass import DataClassPayload

from democracy.funding.models import FundingCampaign
from democracy.models.utils import parse_datetime
from democracy.network.messages.base_message import BaseMessage


@dataclass
class FundingCampaignMessage(DataClassPayload[5], BaseMessage[FundingCampaign]):
    """
    Message to propagate funding campaign metadata.

    A campaign binds a solution to a Bitcoin payout address, asking price,
    deadline, and solution hash. Inactive campaigns are encoded on the wire with
    an empty payout address and deadline height 0.
    """

    id: str
    solution_id: str
    solution_hash: str
    developer_payout_address: str
    asking_price_sats: int
    deadline_height: int
    created_at: str

    @property
    def entity_id(self) -> UUID:
        return UUID(self.id)

    def brief(self) -> str:
        return (
            "FundingCampaign("
            f"id={self.id}, "
            f"solution_id={self.solution_id}, "
            f"asking_price_sats={self.asking_price_sats}"
            ")"
        )

    def to_model(self) -> FundingCampaign:
        payout_address = self.developer_payout_address or None
        deadline_height = self.deadline_height or None

        return FundingCampaign(
            id=UUID(self.id),
            solution_id=UUID(self.solution_id),
            solution_hash=self.solution_hash,
            developer_payout_address=payout_address,
            asking_price_sats=self.asking_price_sats,
            deadline_height=deadline_height,
            created_at=parse_datetime(self.created_at),
        )

    @classmethod
    def from_model(cls, campaign: FundingCampaign) -> "FundingCampaignMessage":
        return cls(
            id=str(campaign.id),
            solution_id=str(campaign.solution_id),
            solution_hash=campaign.solution_hash,
            developer_payout_address=campaign.developer_payout_address or "",
            asking_price_sats=campaign.asking_price_sats,
            deadline_height=campaign.deadline_height or 0,
            created_at=campaign.created_at.isoformat(),
        )


# Force schema generation once on import.
_ = FundingCampaignMessage(
    id="00000000-0000-0000-0000-000000000000",
    solution_id="00000000-0000-0000-0000-000000000000",
    solution_hash="0" * 64,
    developer_payout_address="bcrt1qexampleaddress",
    asking_price_sats=1,
    deadline_height=1,
    created_at="1970-01-01T00:00:00+00:00",
)
