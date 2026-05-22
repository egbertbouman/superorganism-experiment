from dataclasses import dataclass

from bitcoin.utils import validate_txid


@dataclass(frozen=True)
class PledgeDraft:
    txid: str
    vout: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "txid", self.txid.strip())
        object.__setattr__(self, "vout", self.vout.strip())

    def validate_txid(self) -> str:
        try:
            validate_txid(self.txid)
        except ValueError as exc:
            return str(exc)
        return ""

    def validate_vout(self) -> str:
        if not self.vout:
            return "vout is required."
        try:
            vout = int(self.vout)
        except ValueError:
            return "vout must be a whole number."
        if vout < 0:
            return "vout must be non-negative."
        return ""

    def validate(self) -> dict[str, str]:
        errors: dict[str, str] = {}

        txid_error = self.validate_txid()
        if txid_error:
            errors["txid"] = txid_error

        vout_error = self.validate_vout()
        if vout_error:
            errors["vout"] = vout_error

        return errors

    @property
    def normalized_txid(self) -> str:
        return validate_txid(self.txid)

    @property
    def normalized_vout(self) -> int:
        vout = int(self.vout)
        if vout < 0:
            raise ValueError("vout must be non-negative.")
        return vout
