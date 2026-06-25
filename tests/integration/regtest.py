from __future__ import annotations

import subprocess

from decimal import Decimal
from pathlib import Path

from bitcoin.rpc_client import BitcoinRpcClient
from bitcoin.utils import (
    SATOSHIS_PER_BTC,
    sats_to_btc_string,
    validate_psbt_base64,
    validate_txid,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGTEST_SCRIPT = PROJECT_ROOT / "scripts" / "regtest.sh"


class RegtestBitcoinRpcClient(BitcoinRpcClient):
    def get_new_address(self, label: str, address_type: str = "bech32") -> str:
        if not isinstance(label, str):
            raise ValueError("label must be a string.")

        normalized_label = label.strip()
        if not normalized_label:
            raise ValueError("label must not be empty.")

        result = self.call("getnewaddress", normalized_label, address_type)
        if not isinstance(result, str):
            raise ValueError("getnewaddress returned a non-string result.")

        normalized_address = result.strip()
        if not normalized_address:
            raise ValueError("getnewaddress returned an empty address.")

        return normalized_address

    def mine_blocks(self, count: int = 1) -> list[str]:
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError("count must be an integer.")
        if count <= 0:
            raise ValueError("count must be positive.")

        address = self.get_new_address("mining", "bech32")
        result = self.call("generatetoaddress", count, address)

        if not isinstance(result, list) or not all(
            isinstance(item, str) for item in result
        ):
            raise ValueError("generatetoaddress returned an unexpected result.")

        return result

    def send_to_address(self, address: str, amount_sats: int) -> str:
        if not isinstance(address, str):
            raise ValueError("address must be a string.")
        if isinstance(amount_sats, bool) or not isinstance(amount_sats, int):
            raise ValueError("amount_sats must be an integer.")
        if amount_sats <= 0:
            raise ValueError("amount_sats must be positive.")

        result = self.call(
            "sendtoaddress", address.strip(), sats_to_btc_string(amount_sats)
        )
        if not isinstance(result, str):
            raise ValueError("sendtoaddress returned a non-string result.")

        return validate_txid(result)

    def sign_psbt_anyonecanpay(self, psbt_base64: str) -> str:
        psbt_base64 = validate_psbt_base64(psbt_base64)
        result = self.call(
            "walletprocesspsbt",
            psbt_base64,
            True,
            "ALL|ANYONECANPAY",
            False,
            False,
        )

        if not isinstance(result, dict):
            raise ValueError("walletprocesspsbt returned a non-dict result.")

        signed_psbt = result.get("psbt")
        if not isinstance(signed_psbt, str):
            raise ValueError("walletprocesspsbt returned a non-string psbt result.")

        return validate_psbt_base64(signed_psbt)

    def lock_unspent(self, unlock: bool, outputs: list[dict[str, Any]]) -> bool:
        if not isinstance(unlock, bool):
            raise ValueError("unlock must be a bool.")
        if not isinstance(outputs, list):
            raise ValueError("outputs must be a list.")

        result = self.call("lockunspent", unlock, outputs)
        if not isinstance(result, bool):
            raise ValueError("lockunspent returned a non-bool result.")

        return result


def run_regtest_script(*args: str) -> subprocess.CompletedProcess[str]:
    if not REGTEST_SCRIPT.exists():
        raise FileNotFoundError(f"Regtest script not found: {REGTEST_SCRIPT}")

    return subprocess.run(
        [str(REGTEST_SCRIPT), *args],
        cwd=str(PROJECT_ROOT),
        check=True,
        text=True,
        capture_output=True,
    )


def create_regtest_payment_with_op_return(
    treasury_address: str,
    amount_sats: int,
    commitment_hex: str,
) -> str:
    amount_btc = format(Decimal(amount_sats) / SATOSHIS_PER_BTC, "f")
    result = run_regtest_script("send", treasury_address, amount_btc, commitment_hex)

    for line in result.stdout.splitlines():
        if line.startswith("Sent transaction: "):
            return validate_txid(line.removeprefix("Sent transaction: ").strip())

    raise RuntimeError(f"Could not parse txid from regtest.sh output: {result.stdout}")
