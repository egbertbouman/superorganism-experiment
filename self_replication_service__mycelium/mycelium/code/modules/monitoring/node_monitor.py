"""
Aggregates BTC balance and SporeStack runway details into a NodeState.
Decision loop and SeedboxInfoPayload broadcast consume info.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import Config
from utils import setup_logger
from . import sporestack_client
from ..core.wallet import get_wallet

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


@dataclass
class NodeState:
    btc_balance_sat: int = 0
    sporestack_balance_cents: int = 0
    burn_rate_cents_per_day: int = 0
    cost_per_day_usd: float = 0.0
    days_remaining: Optional[int] = None        # bought_runway: server lease days
    total_runway_days: Optional[int] = None     # bought_runway + (wallet+credits)/cost_per_day
    server_expiry_ts: int = 0        # Unix ts of running server lease end
    last_updated: float = 0.0
    vps_provider: str = ""
    vps_region: str = ""


class NodeMonitor:
    REFRESH_INTERVAL = 30 if Config.SIM_MODE else 300  # sim: 30s, prod: 5 min

    def __init__(self, token_file: Path):
        self._token_file = token_file
        self._state = NodeState()

    def _load_token(self) -> Optional[str]:
        try:
            if self._token_file.exists():
                token = self._token_file.read_text().strip()
                return token or None
        except Exception:
            pass
        return None

    def refresh(self) -> None:
        """Refresh node state from blockchain and SporeStack API. Swallows all exceptions."""
        try:
            w = get_wallet()
            if w:
                try:
                    w.scan()
                except Exception as e:
                    logger.warning("Wallet scan failed: %s", e)
                btc_balance_sat = w.get_balance_satoshis()
            else:
                btc_balance_sat = 0

            sporestack_balance_cents = 0
            burn_rate_cents_per_day = 0
            cost_per_day_usd = 0.0
            days_remaining = None

            vps_provider = ""
            vps_region = ""

            server_expiry_ts = 0
            server = None

            token = self._load_token()
            if token:
                data = sporestack_client.get_info(token)
                if data:
                    sporestack_balance_cents = int(data.get("balance_cents", 0))
                    burn_rate_cents_per_day = int(data.get("burn_rate_cents", 0))
                    cost_per_day_usd = round(burn_rate_cents_per_day / 100, 4)
                    # Do NOT use data.get("days_remaining") — SporeStack computes it as
                    # balance/burn_rate, which is always 0 for per-cycle-billed servers.
                    # Real days must be inferred from the server expiration timestamp instead.

                try:
                    servers = sporestack_client.get_servers(token)
                except sporestack_client.SporeStackError as e:
                    logger.warning("get_servers failed (monitor refresh): %s", e)
                    servers = []
                if servers:
                    server = servers[-1]
                if server:
                    vps_provider = server.get("provider", "")
                    vps_region = server.get("region", "")
                    server_expiry_ts = int(server.get("expiration", 0))

                    # TODO: once SporeStack's /server/quote endpoint supports the VPS provider
                    # used here, use it to get the cost per 30-day cycle and compute additional
                    # runway from (sporestack_balance_cents + btc_as_cents) / cost_per_cycle * 30.
                    if server_expiry_ts:
                        days_remaining = max(0, int((server_expiry_ts - time.time()) / 86400))

            # total_runway_days = bought server-days + spendable funds converted to days.
            # Lets spawn fire when funds are sufficient, not only when VPS time is pre-paid.
            total_runway_days: Optional[int] = days_remaining
            if days_remaining is not None and Config.VPS_MONTHLY_COST_CENTS > 0:
                cost_per_day_cents = Config.VPS_MONTHLY_COST_CENTS / 30
                btc_balance_cents = (btc_balance_sat / 100_000_000) * Config.BTC_USD_RATE * 100
                total_funds_cents = sporestack_balance_cents + btc_balance_cents
                total_runway_days = days_remaining + int(total_funds_cents / cost_per_day_cents)

            self._state = NodeState(
                btc_balance_sat=btc_balance_sat,
                sporestack_balance_cents=sporestack_balance_cents,
                burn_rate_cents_per_day=burn_rate_cents_per_day,
                cost_per_day_usd=cost_per_day_usd,
                days_remaining=days_remaining,
                total_runway_days=total_runway_days,
                server_expiry_ts=server_expiry_ts,
                last_updated=time.time(),
                vps_provider=vps_provider,
                vps_region=vps_region,
            )
            logger.info(
                "Monitor refresh: btc=%d sat, runway=%s days (total %s), burn=%d cents/day",
                btc_balance_sat, days_remaining, total_runway_days, burn_rate_cents_per_day,
            )
        except Exception as e:
            logger.error("NodeMonitor.refresh failed: %s", e)

    def get_state(self) -> NodeState:
        return self._state


_monitor: Optional[NodeMonitor] = None


def init(token_file: Path) -> None:
    global _monitor
    _monitor = NodeMonitor(token_file)


def get_monitor() -> Optional[NodeMonitor]:
    return _monitor
