#!/usr/bin/env bash
# Tear down the offline mycelium sim (TODO 8.10). Companion to run_simulation.py.
# No `set -e`: continue past failures so partial state still gets cleaned.
set -uo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TS="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${SIM_DIR}/data/runs/${TS}"
mkdir -p "${RUN_DIR}"

# Archive events first — before kill, so an in-flight POST isn't lost.
if [ -f "${SIM_DIR}/data/events.jsonl" ]; then
    mv "${SIM_DIR}/data/events.jsonl" "${RUN_DIR}/events.jsonl"
    echo "[stop_simulation] archived events to ${RUN_DIR}/events.jsonl"
fi

# Kill background processes (reverse startup order).
pkill -f mock_sporestack.py     || true
pkill -f event_collector.py     || true
pkill -f 'sim/btc/miner.py'     || true
pkill -f 'electrs --network regtest' || true
pkill -f 'bitcoind.*-regtest'   || true

# Delete provisioned LXC containers — mycelium nodes match m-<12hex>; plus the bootstrap.
# Images (mycelium-base, ipv8-bootstrap-base) are kept so re-runs stay fast.
for c in $(lxc list --format csv -c n 2>/dev/null | grep -E '^(m-[a-f0-9]+|ipv8-bootstrap)$' || true); do
    echo "[stop_simulation] deleting container ${c}"
    lxc delete --force "${c}" || true
done

echo "[stop_simulation] torn down."
