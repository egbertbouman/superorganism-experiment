import re
from dataclasses import dataclass

from ui.constants import (
    SOLUTION_TITLE_MIN_LENGTH,
    SOLUTION_TITLE_MAX_LENGTH,
    SOLUTION_DESCRIPTION_MIN_LENGTH,
    SOLUTION_DESCRIPTION_MAX_LENGTH,
)

_BECH32_ADDRESS_RE = re.compile(r"^(bc1|tb1|bcrt1)[ac-hj-np-z02-9]{8,87}$")
_BASE58_ADDRESS_RE = re.compile(r"^[123mn2][1-9A-HJ-NP-Za-km-z]{25,62}$")


def _is_probable_bitcoin_address(value: str) -> bool:
    if not value:
        return False

    if value.startswith(("bc1", "tb1", "bcrt1")):
        return bool(_BECH32_ADDRESS_RE.fullmatch(value.lower()))

    return bool(_BASE58_ADDRESS_RE.fullmatch(value))


@dataclass(frozen=True)
class SolutionDraft:
    title: str
    description: str
    bitcoin_payout_address: str = ""
    asking_price_satoshis: str = ""
    deadline_height_offset: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(
            self,
            "bitcoin_payout_address",
            self.bitcoin_payout_address.strip(),
        )
        object.__setattr__(
            self,
            "asking_price_satoshis",
            self.asking_price_satoshis.strip(),
        )
        object.__setattr__(
            self,
            "deadline_height_offset",
            self.deadline_height_offset.strip(),
        )

    def validate_title(self) -> str:
        if not self.title:
            return "Title is required."
        if len(self.title) < SOLUTION_TITLE_MIN_LENGTH:
            return f"Title must be at least {SOLUTION_TITLE_MIN_LENGTH} characters."
        if len(self.title) > SOLUTION_TITLE_MAX_LENGTH:
            return f"Title must be at most {SOLUTION_TITLE_MAX_LENGTH} characters."
        return ""

    def validate_description(self) -> str:
        if not self.description:
            return "Description is required."
        if len(self.description) < SOLUTION_DESCRIPTION_MIN_LENGTH:
            return f"Description must be at least {SOLUTION_DESCRIPTION_MIN_LENGTH} characters."
        if len(self.description) > SOLUTION_DESCRIPTION_MAX_LENGTH:
            return f"Description must be at most {SOLUTION_DESCRIPTION_MAX_LENGTH} characters."
        return ""

    def validate_funding_fields(self) -> dict[str, str]:
        errors: dict[str, str] = {}

        if not (
            self.bitcoin_payout_address
            or self.asking_price_satoshis
            or self.deadline_height_offset
        ):
            return errors

        payout_address = self.bitcoin_payout_address
        asking_price = self.asking_price_satoshis
        deadline_offset = self.deadline_height_offset

        if asking_price == "0" and not payout_address and not deadline_offset:
            return errors

        if not payout_address:
            errors["bitcoin_payout_address"] = (
                "Bitcoin payout address is required when creating a funding campaign."
            )
        elif not _is_probable_bitcoin_address(payout_address):
            errors["bitcoin_payout_address"] = "Enter a valid Bitcoin payout address."

        if not asking_price:
            errors["asking_price_satoshis"] = (
                "Asking price is required when creating a funding campaign."
            )
        else:
            try:
                asking_price_sats = int(asking_price)
            except ValueError:
                errors["asking_price_satoshis"] = (
                    "Asking price must be a whole number of satoshis."
                )
            else:
                if asking_price_sats <= 0:
                    errors["asking_price_satoshis"] = (
                        "Asking price must be greater than 0."
                    )

        if not deadline_offset:
            errors["deadline_height_offset"] = (
                "Deadline height offset is required when creating a funding campaign."
            )
        else:
            try:
                deadline_height_offset = int(deadline_offset)
            except ValueError:
                errors["deadline_height_offset"] = (
                    "Deadline height offset must be a whole number of blocks."
                )
            else:
                if deadline_height_offset <= 0:
                    errors["deadline_height_offset"] = (
                        "Deadline height offset must be greater than 0."
                    )

        return errors

    def validate(self) -> dict[str, str]:
        errors: dict[str, str] = {}

        title_error = self.validate_title()
        if title_error:
            errors["title"] = title_error

        description_error = self.validate_description()
        if description_error:
            errors["description"] = description_error

        errors.update(self.validate_funding_fields())
        return errors

    @property
    def is_valid(self) -> bool:
        return not self.validate()
