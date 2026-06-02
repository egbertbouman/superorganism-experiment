"""
Spawn eligibility thresholds and caution trait inheritance.

A node is eligible to spawn iff its POST-spawn total runway (after paying the
child's VPS invoice, inheritance, and spawn fee) still clears a caution-scaled
threshold, and the spawn outlay is physically affordable from its BTC wallet.
Caution scales the threshold via base * (1 + caution).

"""
import random
from dataclasses import dataclass

from config import Config
from utils import setup_logger
from ..monitoring.node_monitor import NodeState

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


@dataclass
class SpawnEligibility:
    eligible: bool
    reason: str
    effective_threshold: int    # days
    post_spawn_runway_days: int # total runway remaining after the spawn outlay
    post_spawn_btc_sat: int     # BTC left in wallet after the spawn outlay (for logging)
    child_share_sat: int        # BTC that would go to child


def _vps_cost_sat() -> int:
    """Sat-equivalent of the SporeStack invoice spawn_identity will mint."""
    cents = max(
        Config.SPORESTACK_MIN_INVOICE_DOLLARS * 100,
        int(Config.VPS_MONTHLY_COST_CENTS * Config.TOPUP_TARGET_DAYS / 30),
    )
    return int((cents / 100) / Config.BTC_USD_RATE * 100_000_000)


def _cost_per_day_sat() -> int:
    cents_per_day = Config.VPS_MONTHLY_COST_CENTS / 30
    return int((cents_per_day / 100) / Config.BTC_USD_RATE * 100_000_000)


def compute_child_share(btc_balance_sat: int) -> int:
    """Inheritance: ratio of the parent's BTC AFTER it has paid the child's VPS invoice."""
    transferable = max(0, btc_balance_sat - _vps_cost_sat())
    return int(transferable * Config.INHERITANCE_RATIO)


def check_spawn_eligibility(node_state: NodeState, caution_trait: float) -> SpawnEligibility:
    c = max(0.0, min(1.0, caution_trait))
    effective_threshold = int(Config.SPAWN_THRESHOLD_DAYS * (1 + c))

    if node_state.days_remaining is None:
        return SpawnEligibility(
            eligible=False,
            reason="days_remaining unknown",
            effective_threshold=effective_threshold,
            post_spawn_runway_days=0,
            post_spawn_btc_sat=0,
            child_share_sat=0,
        )

    # Spawn guard uses total_runway_days (bought + convertible funds) so spawn fires
    # whenever the node has the FUNDS to support a child, not only when it has
    # pre-paid VPS days. Falls back to bought-runway if total isn't computed yet.
    runway_basis = node_state.total_runway_days if node_state.total_runway_days is not None else node_state.days_remaining

    vps_cost     = _vps_cost_sat()
    fee          = Config.SPAWN_FEE_BUFFER_SAT
    inheritance  = compute_child_share(node_state.btc_balance_sat)
    cost_per_day = _cost_per_day_sat()
    spawn_cost_sat  = vps_cost + inheritance + fee
    spawn_cost_days = spawn_cost_sat / cost_per_day if cost_per_day > 0 else 0
    post_spawn_runway_days = int(runway_basis - spawn_cost_days)
    post_spawn_btc = node_state.btc_balance_sat - vps_cost - inheritance - fee

    affordable = post_spawn_btc >= 0
    runway_ok  = post_spawn_runway_days >= effective_threshold
    eligible   = runway_ok and affordable

    child_share = inheritance if eligible else 0

    if eligible:
        reason = f"eligible (child share: {child_share} sat)"
    elif not affordable:
        reason = (
            f"can't afford spawn outlay: btc {node_state.btc_balance_sat} sat "
            f"< vps {vps_cost} + inheritance {inheritance} + fee {fee}"
        )
    else:
        reason = f"post-spawn runway {post_spawn_runway_days}d < {effective_threshold}d required"

    logger.debug("Spawn eligibility [caution=%.2f]: %s", caution_trait, reason)
    return SpawnEligibility(
        eligible=eligible,
        reason=reason,
        effective_threshold=effective_threshold,
        post_spawn_runway_days=post_spawn_runway_days,
        post_spawn_btc_sat=post_spawn_btc,
        child_share_sat=child_share,
    )


def mutate_caution_trait(parent_trait: float) -> float:
    """
    Produce a slightly mutated child caution trait via Gaussian drift.
    Called by parent at spawn time; result injected as MYCELIUM_CAUTION_TRAIT for child.
    """
    drift = Config.CAUTION_MEAN_REVERSION * (Config.CAUTION_TRAIT_TARGET - parent_trait)
    child = parent_trait + drift + random.gauss(0, Config.CAUTION_MUTATION_SIGMA)
    result = max(Config.CAUTION_TRAIT_MIN, min(Config.CAUTION_TRAIT_MAX, child))
    logger.debug("Caution mutation: %.3f -> %.3f (drift=%.3f, sigma=%.3f)",
                 parent_trait, result, drift, Config.CAUTION_MUTATION_SIGMA)
    return result
