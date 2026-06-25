from __future__ import annotations

import pytest

from authentication.transaction_verification.rpc_verifier import RpcVerifier
from tests.integration.config import REGTEST_RPC_CONFIG
from tests.integration.regtest import RegtestBitcoinRpcClient, run_regtest_script


@pytest.fixture(scope="session")
def regtest_environment() -> None:
    """
    Create a clean regtest chain once for the integration test session.
    """
    run_regtest_script("reset")
    yield
    run_regtest_script("stop")


@pytest.fixture()
def rpc_client(regtest_environment: None) -> RegtestBitcoinRpcClient:
    client = RegtestBitcoinRpcClient.from_config(REGTEST_RPC_CONFIG)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture()
def verifier(regtest_environment: None) -> RpcVerifier:
    instance = RpcVerifier.from_config(REGTEST_RPC_CONFIG)
    try:
        yield instance
    finally:
        instance.close()
