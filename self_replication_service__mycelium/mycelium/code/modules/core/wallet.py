import logging
import os
import resource
import threading
import time
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Optional, Tuple

from bitcoinlib.wallets import Wallet
import bitcoinlib.db as _bitcoinlib_db

from config import Config
from utils import setup_logger

_orig_create_engine = _bitcoinlib_db.create_engine

def _create_engine_thread_safe(url, *args, **kwargs):
    if isinstance(url, str) and url.startswith("sqlite:"):
        kwargs.setdefault("connect_args", {}).setdefault("check_same_thread", False)
    return _orig_create_engine(url, *args, **kwargs)

_bitcoinlib_db.create_engine = _create_engine_thread_safe


# Sim-only electrumx patches. Production uses HTTP providers and never hits these.
if Config.SIM_MODE:
    import asyncio as _asyncio
    import socket as _socket
    from bitcoinlib.services.baseclient import BaseClient as _BaseClient
    _BaseClient.__init__.__defaults__ = tuple(
        60 if d == 5 else d for d in _BaseClient.__init__.__defaults__
    )
    try:
        import aiorpcx as _aiorpcx
    except ImportError:
        _aiorpcx = None

    if _aiorpcx is not None:
        # ElectrumxClient.compose_request calls asyncio.get_event_loop(), which raises
        # inside asyncio.to_thread workers — wraps in a fresh event loop per call.
        from bitcoinlib.services.electrumx import ElectrumxClient as _ElectrumxClient
        from bitcoinlib.services.baseclient import ClientError as _ClientError

        def _electrumx_compose_request_thread_safe(self, method, parameters=None):
            try:
                host, port = self.base_url.split(':')
            except ValueError:
                raise _ClientError('Please specify ElectrumX uri in format host:port')
            parameters = parameters or []
            probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            probe.settimeout(2)
            try:
                if probe.connect_ex((host, int(port))) != 0:
                    raise _ClientError('ElectrumX server %s unavailable at port %s' % (host, port))
            finally:
                probe.close()

            async def _send():
                async with _aiorpcx.connect_rs(host, int(port),
                                               framer=_aiorpcx.NewlineFramer(5000000)) as session:
                    session.sent_request_timeout = self.timeout
                    return await session.send_request(method, parameters)

            loop = _asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_send())
            finally:
                loop.close()

        _ElectrumxClient.compose_request = _electrumx_compose_request_thread_safe

    # _parse_transaction accesses tx['confirmations'], which KeyErrors on mempool txs — default to 0.
    from bitcoinlib.services.electrumx import ElectrumxClient as _EC2  # noqa: E402
    _orig_parse_transaction = _EC2._parse_transaction
    def _parse_transaction_safe(self, tx, *args, **kwargs):
        tx.setdefault("confirmations", 0)
        return _orig_parse_transaction(self, tx, *args, **kwargs)
    _EC2._parse_transaction = _parse_transaction_safe


_wallet_lock = threading.RLock()

_SIM_SEND_SCAN_ATTEMPTS = 20
_SIM_SEND_SCAN_DELAY = 1.5
_SIM_SEND_FEE_HEADROOM_SAT = 5_000
_SIM_SEND_RSS_WARN_KB = 2_000_000  # 2 GB


def _synchronized(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _wallet_lock:
            return fn(*args, **kwargs)
    return wrapper

logger = setup_logger(
    __name__,
    log_file=Config.LOG_DIR / "orchestrator.log",
    level=Config.LOG_LEVEL
)


class WalletError(Exception):
    """Base exception for wallet operations."""
    pass


def parse_bitcoin_uri(uri: str) -> Optional[Tuple[str, int]]:
    """Parse BIP-21 bitcoin:ADDRESS?amount=BTC → (address, amount_sat) or None."""
    if not uri.startswith("bitcoin:"):
        return None
    parts = uri[8:].split("?")
    address = parts[0]
    amount_btc_str = None
    if len(parts) > 1:
        for param in parts[1].split("&"):
            if param.startswith("amount="):
                amount_btc_str = param[7:]
                break
    if not address or amount_btc_str is None:
        return None
    # Decimal avoids float imprecision: int(float("0.0006") * 1e8) truncates to 59999.
    return address, int(Decimal(amount_btc_str) * 100_000_000)


def _remove_from_etc_environment(key: str) -> None:
    """Remove a KEY=... line from /etc/environment, ignoring errors."""
    env_file = Path("/etc/environment")
    if not env_file.exists():
        return
    try:
        lines = env_file.read_text().splitlines()
        filtered = [line for line in lines if not line.startswith(f"{key}=")]
        tmp = env_file.with_suffix(".tmp")
        tmp.write_text("\n".join(filtered) + "\n")
        tmp.chmod(0o644)
        tmp.replace(env_file)
        logger.info("Removed %s from /etc/environment", key)
    except Exception as e:
        logger.warning("Could not remove %s from /etc/environment: %s", key, e)


class SpendingWallet:
    def __init__(self, wallet: Wallet):
        self._wallet = wallet

    @_synchronized
    def get_receiving_address(self) -> str:
        if Config.SIM_MODE:
            key = self._wallet.key_for_path([0, 0])  # deterministic m/84'/.../0/0, never rotates
        else:
            key = self._wallet.get_key()
        return key.address

    @_synchronized
    def get_balance_satoshis(self) -> int:
        return self._wallet.balance()

    @_synchronized
    def get_balance_btc(self) -> float:
        return self.get_balance_satoshis() / 100_000_000

    @_synchronized
    def scan(self) -> None:
        self._resync_spendable_utxos()
        logger.info("Refresh complete. Balance: %s BTC", self.get_balance_btc())

    def _resync_spendable_utxos(self) -> None:
        """Refresh UTXOs and unconfirmed-tx confirmations; called by scan() and pre-send."""
        self._wallet.utxos_update(rescan_all=Config.SIM_MODE)

        DbTransaction = _bitcoinlib_db.DbTransaction
        unconfirmed_rows = (
            self._wallet.session.query(DbTransaction.txid)
            .filter(
                DbTransaction.wallet_id == self._wallet.wallet_id,
                DbTransaction.network_name == self._wallet.network.name,
                (DbTransaction.block_height.is_(None))
                | (DbTransaction.confirmations == 0),
            )
            .all()
        )
        txids = [row[0] for row in unconfirmed_rows if row[0]]
        if txids:
            self._wallet.transactions_update_by_txids(txids)
        self._wallet.transactions_update_confirmations()

        peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if peak_kb >= _SIM_SEND_RSS_WARN_KB:
            logger.warning(
                "pre-send UTXO refresh peak RSS %.2f GB — refresh is bloating again, "
                "OOM-kill risk (refreshed %d unconfirmed txid(s))",
                peak_kb / 1_048_576, len(txids),
            )
        else:
            logger.debug(
                "pre-send UTXO refresh peak RSS %.1f MB (%d unconfirmed txid(s) refreshed)",
                peak_kb / 1024, len(txids),
            )

    @_synchronized
    def send(self, address: str, amount_satoshis: int, fee=None) -> str:
        if Config.SIM_MODE:
            needed = amount_satoshis + _SIM_SEND_FEE_HEADROOM_SAT
            last_err: Optional[Exception] = None
            for attempt in range(_SIM_SEND_SCAN_ATTEMPTS):
                try:
                    self._resync_spendable_utxos()
                    utxos = self._wallet.utxos() or []
                    spendable = sum(
                        int(u.get("value", 0))
                        for u in utxos
                        if int(u.get("confirmations", 0)) >= 1
                    )
                    if spendable >= needed:
                        if attempt > 0:
                            logger.info(
                                "wallet ready after %d refresh(es): %d confirmed utxo(s), %d sat spendable",
                                attempt + 1,
                                sum(1 for u in utxos if int(u.get("confirmations", 0)) >= 1),
                                spendable,
                            )
                        break
                    logger.info(
                        "wallet has %d utxo(s), %d sat spendable (< %d needed); refresh %d/%d, retrying in %.1fs...",
                        len(utxos), spendable, needed,
                        attempt + 1, _SIM_SEND_SCAN_ATTEMPTS, _SIM_SEND_SCAN_DELAY,
                    )
                except Exception as e:
                    last_err = e
                    logger.warning(
                        "wallet refresh before send failed on attempt %d/%d: %s",
                        attempt + 1, _SIM_SEND_SCAN_ATTEMPTS, e,
                    )
                if attempt < _SIM_SEND_SCAN_ATTEMPTS - 1:
                    time.sleep(_SIM_SEND_SCAN_DELAY)
            else:
                # Loop exhausted without break — surface a clear error instead
                # of letting send_to raise bitcoinlib's misleading
                # "no key available for UTXO's" message.
                detail = f" (last error: {last_err})" if last_err else ""
                raise WalletError(
                    f"No spendable UTXOs covering {needed} sat after "
                    f"{_SIM_SEND_SCAN_ATTEMPTS} refresh attempts — electrs may be "
                    f"stalled or mempool tx unmined{detail}"
                )

        balance = self.get_balance_satoshis()
        if balance < amount_satoshis:
            raise WalletError(
                f"Insufficient funds. Balance: {balance} sat, "
                f"Required: {amount_satoshis} sat"
            )

        logger.info("Sending %d sat to %s", amount_satoshis, address)
        if Config.SIM_MODE:
            # broadcast=True so bitcoinlib marks spent UTXOs in the local DB.
            tx = self._wallet.send_to(address, amount_satoshis, fee=fee, broadcast=True)
            if not tx.verified:
                raise WalletError(f"Transaction verification failed: {tx.error}")
            if not tx.txid:
                raise WalletError(f"Broadcast failed: {getattr(tx, 'error', 'unknown error')}")
            logger.info("Transaction sent: %s", tx.txid)
            return tx.txid

        from bitcoinlib.services.services import Service
        tx = self._wallet.send_to(address, amount_satoshis, fee=fee, broadcast=False)
        if not tx.verified:
            raise WalletError(f"Transaction verification failed: {tx.error}")
        srv = Service(network=Config.BITCOIN_NETWORK)
        result = srv.sendrawtransaction(tx.raw_hex())
        if result and result.get("txid"):
            logger.info("Transaction sent: %s", tx.txid)
            return tx.txid
        raise WalletError(f"Broadcast failed: {result}")

    @_synchronized
    def sweep_all(self, address: str, fee_per_kb: int = None) -> str:
        tx = self._wallet.sweep(address, broadcast=True, fee_per_kb=fee_per_kb)
        if not tx or not tx.txid:
            raise WalletError(f"Sweep failed: {getattr(tx, 'error', 'unknown error')}")
        logger.info("Sweep complete: %s", tx.txid)
        return tx.txid


# How long to keep re-querying the indexer before we accept "no prior tx exists"
_RECONCILE_POLL_TIMEOUT_SECONDS = 90
_RECONCILE_POLL_INTERVAL_SECONDS = 10


def scan_for_prior_send(
    wallet: "SpendingWallet",
    address: str,
    amount_sat: int,
) -> Optional[str]:
    try:
        wallet._wallet.transactions_update()
    except Exception as e:
        logger.warning("transactions_update failed during reconcile: %s", e)

    try:
        txs = wallet._wallet.transactions_full()
    except Exception as e:
        logger.warning("transactions_full failed during reconcile: %s", e)
        return None

    for tx in txs or []:
        if not getattr(tx, "is_send", True):
            continue
        outputs = getattr(tx, "outputs", None) or []
        for out in outputs:
            out_addr = getattr(out, "address", None)
            out_value = getattr(out, "value", None)
            if out_addr == address and int(out_value or 0) == amount_sat:
                txid = getattr(tx, "txid", None) or getattr(tx, "hash", None)
                if txid:
                    return txid
    return None


def find_prior_send(
    wallet: "SpendingWallet",
    address: str,
    amount_sat: int,
) -> Optional[str]:
    start = time.time()
    while True:
        txid = scan_for_prior_send(wallet, address, amount_sat)
        if txid:
            return txid
        if time.time() - start >= _RECONCILE_POLL_TIMEOUT_SECONDS:
            return None
        time.sleep(_RECONCILE_POLL_INTERVAL_SECONDS)


_wallet_instance: Optional[SpendingWallet] = None


def initialize_wallet() -> None:
    global _wallet_instance

    name = Config.BITCOIN_WALLET_NAME
    network = Config.BITCOIN_NETWORK
    wallet_db = Config.DATA_DIR / f"{name}.db"
    mnemonic_file = Config.DATA_DIR / "mnemonic.txt"
    db_uri = f"sqlite:///{wallet_db}"

    mnemonic_seed_file = Config.DATA_DIR / "btc_mnemonic_seed"

    try:
        if wallet_db.exists():
            logger.info("Loading wallet from existing DB...")
            if mnemonic_seed_file.exists():
                mnemonic_seed_file.unlink()
                logger.info("Cleaned up stale btc_mnemonic_seed")
            raw = Wallet(name, db_uri=db_uri)
        else:
            if mnemonic_seed_file.exists():
                mnemonic = mnemonic_seed_file.read_text().strip()
            else:
                mnemonic = os.environ.get("MYCELIUM_BTC_MNEMONIC") or Config.BTC_MNEMONIC
            if not mnemonic:
                logger.warning(
                    "No wallet DB and no MYCELIUM_BTC_MNEMONIC — wallet not configured"
                )
                return

            from bitcoinlib.mnemonic import Mnemonic as _Mnemonic
            try:
                _Mnemonic().to_entropy(mnemonic)
            except Exception:
                raise WalletError("Invalid BIP39 mnemonic — check seed file or MYCELIUM_BTC_MNEMONIC")

            logger.info("First boot: creating wallet from mnemonic...")
            raw = Wallet.create(
                name,
                keys=mnemonic,
                network=network,
                db_uri=db_uri,
                witness_type="segwit"
            )
            # One-time HD walk on first boot: discovers any prior activity on
            # either chain (change=0 and change=1) under this mnemonic.
            raw.scan(scan_gap_limit=5)

            if wallet_db.exists():
                wallet_db.chmod(0o600)

            if mnemonic_seed_file.exists():
                mnemonic_seed_file.unlink()

            fd = os.open(str(mnemonic_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, mnemonic.encode())
            finally:
                os.close(fd)
            logger.info("Mnemonic persisted to %s (mode 600)", mnemonic_file)

            _remove_from_etc_environment("MYCELIUM_BTC_MNEMONIC")
            os.environ.pop("MYCELIUM_BTC_MNEMONIC", None)

        _wallet_instance = SpendingWallet(raw)
        logger.info("Wallet ready. Address: %s", _wallet_instance.get_receiving_address())

    except Exception as e:
        logger.error("Failed to initialize wallet: %s", e)
        _wallet_instance = None


def get_wallet() -> Optional[SpendingWallet]:
    """Return the wallet singleton, or None if not configured."""
    return _wallet_instance
