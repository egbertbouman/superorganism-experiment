#!/usr/bin/env python3
"""Top-level entry point for the mycelium offline sim (TODO 8.10).

Brings up the BTC regtest stack, event collector, mock SporeStack, IPv8
bootstrap container, and a single genesis mycelium node — then tails the
genesis orchestrator log. Companion teardown: stop_simulation.sh.
"""
import argparse
import json
import math
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SIM_DIR = pathlib.Path(__file__).resolve().parent
BOOTSTRAP_DIR = SIM_DIR.parent
SIM_HOME = pathlib.Path.home() / ".mycelium-sim"
LOG_DIR = SIM_HOME / "logs"

EVENT_COLLECTOR_URL = "http://127.0.0.1:8765"
MOCK_SPORESTACK_URL = "http://127.0.0.1:8766"
MYCELIUM_BASE_IMAGE = "mycelium-base"
IPV8_BOOTSTRAP_IMAGE = "ipv8-bootstrap-base"
IPV8_BOOTSTRAP_NAME = "ipv8-bootstrap"
LXC_BRIDGE = "lxdbr0"
EVENT_API_KEY = "123456789"
GENESIS_NAME = "genesis"
BCLI_DATADIR = SIM_HOME / "regtest"
BCLI = [
    "bitcoin-cli", "-regtest", f"-datadir={BCLI_DATADIR}",
    "-rpcuser=mycelium", "-rpcpassword=regtest",
    "-rpcconnect=127.0.0.1", "-rpcport=18443",
    "-rpcwallet=mycelium-regtest",
]

os.environ.setdefault("MYCELIUM_SIM_MODE", "1")
sys.path.insert(0, str(BOOTSTRAP_DIR))
from lib.wallet import BitcoinWallet  # noqa: E402
from lib.deployer import generate_ssh_keypair  # noqa: E402


def _log(msg: str) -> None:
    print(f"[run_sim] {msg}", flush=True)


def _http_get_json(url: str, timeout: float = 15) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _http_get_text(url: str, timeout: float = 15) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode().strip()


def _http_post_json(url: str, payload: dict, timeout: float = 30) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode()
    return json.loads(text) if text else {}


def _wait_for_healthz(url: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    last_err = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception as e:
            last_err = str(e)
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}: {last_err}")


def preflight() -> None:
    for binary in ("lxc", "bitcoind", "electrs", "bitcoin-cli"):
        if not shutil.which(binary):
            sys.exit(f"[run_sim] missing required binary: {binary}")
    try:
        cidr = subprocess.check_output(
            ["lxc", "network", "get", LXC_BRIDGE, "ipv4.address"],
            text=True, timeout=5,
        ).strip()
    except Exception as e:
        sys.exit(
            f"[run_sim] cannot read lxd bridge '{LXC_BRIDGE}': {e}\n"
            "         Run `lxd init` and ensure the default bridge exists."
        )
    if not cidr:
        sys.exit(
            f"[run_sim] lxd bridge '{LXC_BRIDGE}' has no ipv4.address — run `lxd init`"
        )


def start_btc_stack() -> None:
    _log("starting BTC regtest stack...")
    subprocess.run([str(SIM_DIR / "btc" / "start.sh")], check=True)


def _spawn_background(name: str, script_path: pathlib.Path,
                      extra_env: dict | None = None) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SIM_HOME.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pkill", "-f", str(script_path)], check=False)
    time.sleep(0.5)
    log_path = LOG_DIR / f"{name}.log"
    pid_path = SIM_HOME / f"{name}.pid"
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    log_fp = open(log_path, "ab")
    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=log_fp, stderr=subprocess.STDOUT, env=env,
        start_new_session=True,
    )
    pid_path.write_text(str(proc.pid))


def start_event_collector() -> None:
    _log("starting event collector...")
    _spawn_background("event_collector", SIM_DIR / "event_collector.py")
    _wait_for_healthz(f"{EVENT_COLLECTOR_URL}/healthz")
    _log("event collector healthy")


def start_mock_sporestack(time_scale: float) -> None:
    _log(f"starting mock SporeStack (TIME_SCALE={time_scale})...")
    _spawn_background(
        "mock_sporestack", SIM_DIR / "mock_sporestack.py",
        extra_env={"MYCELIUM_SIM_TIME_SCALE": str(time_scale)},
    )
    _wait_for_healthz(f"{MOCK_SPORESTACK_URL}/healthz", timeout=60)
    _log("mock SporeStack healthy")


def _lxc_image_exists(alias: str) -> bool:
    try:
        out = subprocess.check_output(
            ["lxc", "image", "list", alias, "--format", "json"],
            text=True, timeout=15,
        )
    except subprocess.CalledProcessError:
        return False
    for img in json.loads(out or "[]"):
        for a in img.get("aliases") or []:
            if a.get("name") == alias:
                return True
    return False


def ensure_images(rebuild: bool = False) -> None:
    for alias, build_script in [
        (MYCELIUM_BASE_IMAGE, SIM_DIR / "image" / "build.sh"),
        (IPV8_BOOTSTRAP_IMAGE, SIM_DIR / "ipv8_bootstrap" / "build.sh"),
    ]:
        if rebuild and _lxc_image_exists(alias):
            _log(f"--rebuild-images: deleting stale {alias}...")
            subprocess.run(["lxc", "image", "delete", alias], check=True)
        if not _lxc_image_exists(alias):
            _log(f"building {alias} image (this can take a few minutes)...")
            subprocess.run([str(build_script)], check=True)
        else:
            _log(f"{alias} image already present")


def _lxc_instance(name: str) -> dict | None:
    try:
        out = subprocess.check_output(
            ["lxc", "list", name, "--format", "json"], text=True, timeout=10,
        )
    except subprocess.CalledProcessError:
        return None
    for inst in json.loads(out or "[]"):
        if inst.get("name") == name:
            return inst
    return None


def _lxc_ipv4(name: str) -> str:
    inst = _lxc_instance(name)
    if not inst:
        return ""
    eth0 = ((inst.get("state") or {}).get("network") or {}).get("eth0") or {}
    for addr in eth0.get("addresses", []):
        if addr.get("family") == "inet":
            return addr.get("address", "")
    return ""


def launch_ipv8_bootstrap() -> str:
    _log("launching IPv8 bootstrap container...")
    inst = _lxc_instance(IPV8_BOOTSTRAP_NAME)
    if inst is None:
        subprocess.run(
            ["lxc", "launch", IPV8_BOOTSTRAP_IMAGE, IPV8_BOOTSTRAP_NAME],
            check=True, timeout=120,
        )
    elif inst.get("status") != "Running":
        subprocess.run(
            ["lxc", "start", IPV8_BOOTSTRAP_NAME], check=True, timeout=30,
        )
    deadline = time.time() + 30
    ip = ""
    while time.time() < deadline:
        ip = _lxc_ipv4(IPV8_BOOTSTRAP_NAME)
        if ip:
            break
        time.sleep(0.5)
    if not ip:
        raise RuntimeError("ipv8-bootstrap container never got an IPv4 within 30s")

    # The image entrypoint isn't PID 1 (no openrc service), so `lxc start`
    # alone leaves the tracker un-started. Mirror mock_sporestack's mycelium
    # boot pattern: detach the entrypoint via `lxc exec ... nohup &`.
    #
    # The first kick can race with a freshly-booted container's userspace
    # (orphaned-child reparenting before openrc finishes its init sequence has
    # been observed to drop the python process before it binds), so the loop
    # below re-kicks every iter until netstat confirms UDP/7759 is listening.
    # Once one tracker is bound, subsequent kicks fail at bind() and exit —
    # harmless. busybox-alpine ships `netstat`; iproute2's `ss` is not in the
    # bootstrap image.
    kick_cmd = [
        "lxc", "exec", IPV8_BOOTSTRAP_NAME, "--",
        "sh", "-c",
        "mkdir -p /root/logs && "
        "nohup /usr/local/bin/ipv8-bootstrap-entrypoint "
        ">>/root/logs/tracker.log 2>&1 </dev/null &",
    ]
    probe_cmd = [
        "lxc", "exec", IPV8_BOOTSTRAP_NAME, "--",
        "sh", "-c", "netstat -uln 2>/dev/null | grep -q ':7759 '",
    ]
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if subprocess.run(probe_cmd, timeout=5).returncode == 0:
                _log(f"ipv8-bootstrap up at {ip}, tracker listening on UDP 7759")
                return ip
            subprocess.run(kick_cmd, check=False, timeout=10)
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(
        f"ipv8-bootstrap tracker never started listening on {ip}:7759 — "
        f"check `lxc exec {IPV8_BOOTSTRAP_NAME} -- cat /root/logs/tracker.log`"
    )


def get_or_create_genesis_wallet() -> tuple[BitcoinWallet, str]:
    SIM_HOME.mkdir(parents=True, exist_ok=True)
    db_path = SIM_HOME / "genesis_wallet.db"
    mnemonic_path = SIM_HOME / "genesis_mnemonic.txt"
    db_uri = f"sqlite:///{db_path}"
    wallet = BitcoinWallet("mycelium-sim-genesis", network="regtest", db_uri=db_uri)
    if wallet.exists():
        wallet.load()
        mnemonic = mnemonic_path.read_text().strip()
        _log(f"loaded existing genesis wallet ({wallet.get_balance_btc()} BTC)")
    else:
        mnemonic = wallet.create_new()
        mnemonic_path.write_text(mnemonic + "\n")
        os.chmod(mnemonic_path, 0o600)
        _log("created fresh genesis wallet")
    return wallet, mnemonic


def faucet_fund(address: str, btc: int) -> None:
    _log(f"faucet → {address} ({btc} BTC)...")
    subprocess.run(
        [str(SIM_DIR / "btc" / "faucet.py"), "send", address, str(btc)],
        check=True,
    )


def parse_bip21_amount_sat(payment_uri: str) -> int:
    if "?" not in payment_uri:
        raise ValueError(f"invoice payment_uri lacks query: {payment_uri}")
    query = payment_uri.split("?", 1)[1]
    for kv in query.split("&"):
        if kv.startswith("amount="):
            return int(round(float(kv[len("amount="):]) * 100_000_000))
    raise ValueError(f"invoice payment_uri lacks amount=: {payment_uri}")


def parse_bip21_address(payment_uri: str) -> str:
    return payment_uri[len("bitcoin:"):].split("?", 1)[0]


def fresh_regtest_sink_address() -> str:
    return subprocess.check_output(
        BCLI + ["getnewaddress"], text=True, timeout=10,
    ).strip()


def _scan_with_retry(wallet: BitcoinWallet, max_attempts: int = 6, delay: float = 3.0) -> None:
    """Retry wallet.scan() — electrs is briefly unavailable while indexing a new block."""
    for attempt in range(max_attempts):
        try:
            wallet.scan()
            return
        except Exception as e:
            if attempt < max_attempts - 1:
                _log(f"wallet.scan() attempt {attempt + 1}/{max_attempts} failed: {e}; retrying in {delay:.0f}s...")
                time.sleep(delay)
            else:
                raise


def buy_genesis_server(wallet: BitcoinWallet, days: int) -> tuple[str, str]:
    """Quote → invoice → pay → poll credit → launch server. Returns (token, machine_id)."""
    token = _http_get_text(f"{MOCK_SPORESTACK_URL}/token")
    _log(f"got token={token[:8]}..")

    quote = _http_get_json(f"{MOCK_SPORESTACK_URL}/server/quote?days={days}")
    cents = int(quote["cents"])
    dollars = math.ceil(cents / 100)
    _log(f"quote: {cents}c for {days} days → ${dollars} invoice")

    add = _http_post_json(
        f"{MOCK_SPORESTACK_URL}/token/{token}/add", {"dollars": dollars},
    )
    invoice = add["invoice"]
    pay_addr = parse_bip21_address(invoice["payment_uri"])
    amount_sat = parse_bip21_amount_sat(invoice["payment_uri"])
    _log(f"invoice: pay {amount_sat} sat to {pay_addr}")

    _scan_with_retry(wallet)
    txid = wallet.send(pay_addr, amount_sat)
    _log(f"sent {txid}")

    deadline = time.time() + 60
    while time.time() < deadline:
        info = _http_get_json(f"{MOCK_SPORESTACK_URL}/token/{token}/info")
        if info.get("balance_cents", 0) >= cents - 100:
            _log(f"token credited: balance_cents={info['balance_cents']}")
            break
        time.sleep(2)
    else:
        raise RuntimeError("token never credited within 60s")

    _, pub_key = generate_ssh_keypair(
        str(SIM_HOME / "genesis_ssh"), comment="mycelium-sim-genesis",
    )

    create = _http_post_json(
        f"{MOCK_SPORESTACK_URL}/token/{token}/servers",
        {
            "days": days,
            "flavor": "vps-1vcpu-1gb",
            "operating_system": "debian-12",
            "provider": "digitalocean",
            "region": "ams3",
            "billing_cycle": "monthly",
            "hostname": GENESIS_NAME,
            "ssh_key": pub_key,
        },
        timeout=120,
    )
    machine_id = create["machine_id"]
    _log(f"server provisioned: machine_id={machine_id}")
    return token, machine_id


def start_genesis_orchestrator(machine_id: str, token: str, mnemonic: str,
                               sink_address: str) -> None:
    env = {
        "MYCELIUM_FRIENDLY_NAME": GENESIS_NAME,
        "MYCELIUM_PARENT_NAME": GENESIS_NAME,
        "MYCELIUM_LOG_SECRET": EVENT_API_KEY,
        "MYCELIUM_SPORESTACK_TOKEN": token,
        "MYCELIUM_CAUTION_TRAIT": "0.5",
        "MYCELIUM_CAUTION_MUTATION_SIGMA": "0.05",
        "MYCELIUM_SPAWN_THRESHOLD_DAYS": "60",
        "MYCELIUM_SPAWN_RESERVE_DAYS": "30",
        "MYCELIUM_INHERITANCE_RATIO": "0.4",
        "MYCELIUM_DEFAULT_BTC_ADDRESS": sink_address,
    }
    secrets = {
        "/root/data/btc_mnemonic_seed": mnemonic,
        "/root/data/sporestack_token": token,
    }
    _log("posting /sim/start to mock SporeStack...")
    _http_post_json(
        f"{MOCK_SPORESTACK_URL}/sim/start/{machine_id}",
        {"env": env, "secrets": secrets},
        timeout=60,
    )
    _log("genesis orchestrator started")


def tail_genesis_logs(machine_id: str) -> None:
    _log(f"tailing /root/logs/orchestrator.log on {machine_id} (Ctrl+C to detach)...")

    def _on_sigint(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _on_sigint)
    try:
        subprocess.run([
            "lxc", "exec", machine_id, "--", "sh", "-c",
            "until [ -f /root/logs/orchestrator.log ]; do sleep 1; done; "
            "tail -f /root/logs/orchestrator.log",
        ])
    except KeyboardInterrupt:
        pass
    print()
    _log("detached from genesis log; sim still running. Use stop_simulation.sh to tear down.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the mycelium offline sim end-to-end.")
    parser.add_argument("--genesis-days", type=int, default=90,
                        help="Initial SporeStack runway purchased for genesis (default 90)")
    parser.add_argument("--genesis-btc", type=int, default=10,
                        help="Regtest BTC to faucet into the genesis wallet (default 10)")
    parser.add_argument("--time-scale", type=float, default=1000,
                        help="Mock SporeStack time-scale multiplier (default 1000)")
    parser.add_argument("--no-tail", action="store_true",
                        help="Skip the trailing `lxc exec ... tail -f` step")
    parser.add_argument("--rebuild-images", action="store_true",
                        help="Delete and rebuild LXC images before starting")
    args = parser.parse_args()

    preflight()
    start_btc_stack()
    start_event_collector()
    start_mock_sporestack(args.time_scale)
    ensure_images(rebuild=args.rebuild_images)
    launch_ipv8_bootstrap()

    wallet, mnemonic = get_or_create_genesis_wallet()
    genesis_addr = wallet.get_receiving_address()
    faucet_fund(genesis_addr, args.genesis_btc)

    sink_addr = fresh_regtest_sink_address()
    _log(f"failsafe sink address: {sink_addr}")

    token, machine_id = buy_genesis_server(wallet, args.genesis_days)
    start_genesis_orchestrator(machine_id, token, mnemonic, sink_addr)

    print()
    _log(f"sim up. genesis machine_id={machine_id}")
    _log(f"  events:  {SIM_DIR / 'data' / 'events.jsonl'}")
    _log(f"  mock:    {MOCK_SPORESTACK_URL}/healthz")
    _log(f"  collect: {EVENT_COLLECTOR_URL}/healthz")
    print()

    if args.no_tail:
        return
    tail_genesis_logs(machine_id)


if __name__ == "__main__":
    main()
