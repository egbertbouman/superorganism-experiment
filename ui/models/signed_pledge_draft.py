from dataclasses import dataclass

from bitcoin.utils import validate_psbt_base64


@dataclass(frozen=True)
class SignedPledgeDraft:
    signed_pledge_psbt: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "signed_pledge_psbt",
            self.signed_pledge_psbt.strip(),
        )

    def validate_signed_pledge_psbt(self) -> str:
        try:
            validate_psbt_base64(self.signed_pledge_psbt)
        except ValueError as exc:
            return str(exc)
        return ""

    def validate(self) -> dict[str, str]:
        errors: dict[str, str] = {}

        signed_psbt_error = self.validate_signed_pledge_psbt()
        if signed_psbt_error:
            errors["signed_pledge_psbt"] = signed_psbt_error

        return errors

    @property
    def normalized_signed_pledge_psbt(self) -> str:
        return validate_psbt_base64(self.signed_pledge_psbt)
