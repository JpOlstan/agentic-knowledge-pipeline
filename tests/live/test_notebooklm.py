from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from knowledge_agents.adapters.mcp_stdio_client import MCPStdioClient, MCPStdioConfig
from knowledge_agents.adapters.notebooklm_provider import (
    NotebookLMProvider,
    load_notebooklm_runtime,
)
from knowledge_agents.domain.budgets import ContextBudget
from knowledge_agents.domain.contracts import AcquisitionRequest


@pytest.mark.live
def test_notebooklm_read_only_smoke_is_explicit_and_sanitized() -> None:
    if os.getenv("KA_RUN_LIVE_NOTEBOOKLM") != "1":
        pytest.skip("set KA_RUN_LIVE_NOTEBOOKLM=1 for the explicitly authorized smoke test")
    notebook_url = os.getenv("KA_NOTEBOOKLM_TEST_URL")
    proxy_value = os.getenv("KA_NOTEBOOKLM_PROXY_PATH")
    package_value = os.getenv("KA_NOTEBOOKLM_RUNTIME_PACKAGE_JSON")
    data_value = os.getenv("KA_NOTEBOOKLM_DATA_DIR")
    if not all((notebook_url, proxy_value, package_value, data_value)):
        pytest.skip("NotebookLM live smoke configuration is incomplete")

    async def scenario() -> None:
        proxy = Path(proxy_value).resolve()
        package_json = Path(package_value).resolve()
        data_dir = Path(data_value).resolve()
        runtime = load_notebooklm_runtime(
            package_json,
            registry_status=os.getenv("KA_NOTEBOOKLM_REGISTRY_STATUS", "evaluating"),
            supervised=True,
        )
        client = MCPStdioClient(
            MCPStdioConfig(
                command=(os.getenv("KA_NOTEBOOKLM_NODE_EXECUTABLE", "node"), str(proxy)),
                cwd=proxy.parent,
                data_dir=data_dir,
            )
        )
        provider = NotebookLMProvider(client, runtime)
        try:
            source = await provider.inspect(AcquisitionRequest(url=notebook_url))
            evidence = await provider.acquire(source, ContextBudget())
            assert evidence.source == source
            assert evidence.evidence_items
            assert notebook_url not in source.model_dump_json()
            assert notebook_url not in evidence.model_dump_json()
        finally:
            await provider.close()

    asyncio.run(scenario())
