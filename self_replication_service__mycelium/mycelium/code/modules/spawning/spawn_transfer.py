"""Sends inheritance BTC to the child and marks spawn complete in persistent state.

Bracket the broadcast with a write-ahead `spawn_transfer_intent` record and a
`spawn_transfer_txid` result. On resume, if intent exists but no txid, inspect
bitcoinlib's local transaction history for a matching outbound tx before
re-broadcasting — bitcoinlib has no in-flight dedup, so a re-broadcast can pay
the inheritance twice from different UTXOs.
"""

import asyncio

from config import Config
from utils import setup_logger
from ..core import state as state_module
from ..core import wallet as wallet_module
from ..core.wallet import find_prior_send, _RECONCILE_POLL_TIMEOUT_SECONDS
from ..monitoring.node_monitor import NodeState
from ..orchestration.spawn_thresholds import compute_child_share
from .errors import SpawnError
from .spawn_identity import ChildIdentity

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)

_DUST_THRESHOLD_SAT = 546   # below this, a P2WPKH output is non-standard


async def transfer_inheritance(
    identity: ChildIdentity,
    node_state: NodeState,
) -> str:
    """Send inheritance BTC to child. Returns txid. Leaves spawn_in_progress=True on failure for retry."""
    ps = state_module.get()
    wallet = wallet_module.get_wallet()
    if ps is None:
        raise SpawnError("transfer", "NodePersistentState not initialised")
    if wallet is None:
        raise SpawnError("transfer", "SpendingWallet not initialised")

    # Fast path: broadcast already succeeded in a prior attempt.
    txid = ps.get("spawn_transfer_txid")
    if txid:
        logger.info(
            "Resume: spawn_transfer_txid already persisted (%s) — skipping broadcast",
            txid,
        )
        ps.mark_spawn_completed(success=True, child_btc_address=identity.btc_address)
        return txid

    intent = ps.get("spawn_transfer_intent")
    if intent and intent.get("spawn_id") == identity.spawn_id:
        child_btc_address = intent["child_btc_address"]
        child_share_sat = int(intent["amount_sat"])
        logger.info(
            "Resume: spawn_transfer_intent found — reconciling against wallet history "
            "(amount=%d sat to=%s, polling up to %ds)",
            child_share_sat, child_btc_address, _RECONCILE_POLL_TIMEOUT_SECONDS,
        )
        prior_txid = await asyncio.to_thread(
            find_prior_send, wallet, child_btc_address, child_share_sat,
        )
        if prior_txid:
            logger.info(
                "Resume: found matching outbound tx %s — treating as already-sent",
                prior_txid,
            )
            ps.set("spawn_transfer_txid", prior_txid)
            ps.mark_spawn_completed(success=True, child_btc_address=identity.btc_address)
            return prior_txid
        # We have a transfer intent but couldn't find a matching tx in the
        # parent's wallet history within the poll window. Re-broadcasting blindly
        # could double-pay if a prior broadcast is sitting unobserved in mempool.
        # Stop here, leave spawn_in_progress=True, and let the operator reconcile.
        logger.critical(
            "Resume: spawn_transfer_intent exists for spawn_id=%s but no matching outbound tx "
            "found after %ds of polling. Refusing to re-broadcast — a prior tx may be unconfirmed "
            "in mempool. Leaving spawn_in_progress=True for human reconciliation. "
            "Intent: amount=%d sat to=%s",
            identity.spawn_id, _RECONCILE_POLL_TIMEOUT_SECONDS, child_share_sat, child_btc_address,
        )
        raise SpawnError(
            "transfer",
            f"Inheritance reconcile inconclusive after {_RECONCILE_POLL_TIMEOUT_SECONDS}s; "
            "manual review required",
        )
    else:
        # Size the inheritance from the eligibility-time snapshot, which is the
        # pre-funding parent balance. compute_child_share subtracts the VPS cost
        # exactly once; recomputing on the post-funding wallet balance would
        # double-subtract that cost (and risk a stale-low read), yielding 0 sat.
        child_share_sat = compute_child_share(node_state.btc_balance_sat)
        child_btc_address = identity.btc_address

        # Resync UTXOs + confirmations before reading a live balance, then cap the
        # share so the send can't exceed actual spendable funds.
        await asyncio.to_thread(wallet.scan)
        available_sat = await asyncio.to_thread(wallet.get_balance_satoshis)
        spendable_sat = max(0, available_sat - Config.SPAWN_FEE_BUFFER_SAT)
        child_share_sat = min(child_share_sat, spendable_sat)
        logger.info(
            "Transferring inheritance: spawn_id=%s available=%d sat amount=%d sat to=%s",
            identity.spawn_id, available_sat, child_share_sat, child_btc_address,
        )

        if child_share_sat <= _DUST_THRESHOLD_SAT:
            logger.warning(
                "Inheritance for spawn_id=%s is %d sat (<= dust) — child already funded via VPS; "
                "skipping BTC transfer and marking spawn complete.",
                identity.spawn_id, child_share_sat,
            )
            ps.mark_spawn_completed(success=True, child_btc_address=identity.btc_address)
            return ""   # sentinel: no on-chain inheritance tx

        ps.set("spawn_transfer_intent", {
            "spawn_id": identity.spawn_id,
            "child_btc_address": child_btc_address,
            "amount_sat": child_share_sat,
        })

    try:
        txid = await asyncio.to_thread(
            wallet.send, child_btc_address, child_share_sat
        )
    except Exception as e:
        raise SpawnError(
            "transfer",
            f"Inheritance transfer failed for {identity.spawn_id}: {e}",
        ) from e

    ps.set("spawn_transfer_txid", txid)
    ps.mark_spawn_completed(success=True, child_btc_address=identity.btc_address)
    logger.info(
        "Spawn complete: spawn_id=%s txid=%s amount=%d sat",
        identity.spawn_id, txid, child_share_sat,
    )
    return txid
