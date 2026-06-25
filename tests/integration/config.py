from bitcoin.rpc_client import BitcoinRpcConfig

REGTEST_RPC_CONFIG = BitcoinRpcConfig(
    rpc_url="http://127.0.0.1:18443",
    rpc_user="demo",
    rpc_password="superorganism",
    wallet_name="demo",
    timeout_seconds=10.0,
)
