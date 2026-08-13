from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from knowledge_agents.adapters.mcp_stdio_client import (
    MCPServerInfo,
    MCPStdioClient,
    MCPStdioConfig,
    MCPTool,
)
from knowledge_agents.adapters.notebooklm_provider import (
    DESIGN_PROVIDER_TOOLS,
    EXPECTED_PACKAGE_NAME,
    EXPECTED_PACKAGE_VERSION,
    REGISTRY_READ_ONLY_TOOLS,
    NotebookLMProvider,
    NotebookLMRuntime,
)
from knowledge_agents.domain.budgets import ContextBudget
from knowledge_agents.domain.contracts import AcquisitionRequest
from knowledge_agents.domain.enums import AcquisitionMethod, SourceType
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.ports.providers import KnowledgeSourceProvider

NOTEBOOK_URL = "https://notebooklm.google.com/notebook/00000000-0000-0000-0000-000000000000"


class FakeMCPClient:
    def __init__(
        self,
        *,
        tool_names: set[str] | None = None,
        authenticated: bool = True,
        sources: list[dict[str, Any]] | None = None,
        answer: str = "A grounded answer.",
        citations: list[dict[str, Any]] | None = None,
    ) -> None:
        self.tool_names = tool_names or set(REGISTRY_READ_ONLY_TOOLS)
        self.authenticated = authenticated
        self.sources = (
            sources
            if sources is not None
            else [
                {
                    "id": "source-0",
                    "name": "Public source",
                    "type": "document",
                    "status": "ready",
                }
            ]
        )
        self.answer = answer
        self.citations = citations or [{"excerpt": "A source-backed excerpt."}]
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True
        self.started = False

    async def initialize(self) -> MCPServerInfo:
        self.calls.append(("initialize", {}))
        return MCPServerInfo("2025-06-18", "notebooklm-safe-proxy", "0.1.0")

    async def list_tools(self) -> tuple[MCPTool, ...]:
        self.calls.append(("tools/list", {}))
        return tuple(MCPTool(name, {}) for name in sorted(self.tool_names))

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((name, dict(arguments)))
        payloads: dict[str, dict[str, Any]] = {
            "server_health": {
                "authenticated": self.authenticated,
                "headless": True,
                "auto_login_enabled": False,
            },
            "content_list": {"sources": self.sources, "sourceCount": len(self.sources)},
            "notebook_ask": {
                "answer": self.answer,
                "sources": self.citations,
                "session_id": "session-sensitive",
                "notebook_url": NOTEBOOK_URL,
            },
        }
        return {"structuredContent": {"success": True, "data": payloads[name]}}


def runtime(*, status: str = "evaluating", supervised: bool = True) -> NotebookLMRuntime:
    return NotebookLMRuntime(
        package_name=EXPECTED_PACKAGE_NAME,
        package_version=EXPECTED_PACKAGE_VERSION,
        registry_status=status,
        supervised=supervised,
    )


def test_preflight_accepts_only_registered_read_only_tools() -> None:
    async def scenario() -> None:
        client = FakeMCPClient()
        provider = NotebookLMProvider(client, runtime())

        result = await provider.preflight()

        assert result.authenticated is True
        assert set(result.tools) == REGISTRY_READ_ONLY_TOOLS
        assert [name for name, _ in client.calls] == [
            "initialize",
            "tools/list",
            "server_health",
        ]
        await provider.close()
        assert client.closed is True

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "tool_name",
    ["source_add", "notebook_delete", "content_generate", "vault_batch", "server_cleanup"],
)
def test_preflight_fails_closed_when_mutable_tool_is_advertised(tool_name: str) -> None:
    async def scenario() -> None:
        client = FakeMCPClient(tool_names=set(REGISTRY_READ_ONLY_TOOLS) | {tool_name})
        provider = NotebookLMProvider(client, runtime())

        with pytest.raises(DomainError) as captured:
            await provider.preflight()

        assert captured.value.code is ErrorCode.ACCESS_DENIED
        assert captured.value.operation == "notebooklm.tools.allowlist"
        assert client.closed is True
        assert "server_health" not in [name for name, _ in client.calls]

    asyncio.run(scenario())


def test_preflight_rejects_missing_design_tool() -> None:
    async def scenario() -> None:
        client = FakeMCPClient(tool_names=set(DESIGN_PROVIDER_TOOLS) - {"notebook_ask"})
        provider = NotebookLMProvider(client, runtime())

        with pytest.raises(DomainError) as captured:
            await provider.preflight()

        assert captured.value.code is ErrorCode.PROVIDER_UNAVAILABLE
        assert captured.value.operation == "notebooklm.tools.required"
        assert client.closed is True

    asyncio.run(scenario())


def test_preflight_stops_on_expired_session_without_provider_retry() -> None:
    async def scenario() -> None:
        client = FakeMCPClient(authenticated=False)
        provider = NotebookLMProvider(client, runtime())

        with pytest.raises(DomainError) as captured:
            await provider.preflight()

        assert captured.value.code is ErrorCode.ACCESS_DENIED
        assert captured.value.operation == "notebooklm.health"
        assert [name for name, _ in client.calls].count("server_health") == 1
        assert client.closed is True

    asyncio.run(scenario())


def test_evaluating_registry_status_requires_supervision() -> None:
    async def scenario() -> None:
        client = FakeMCPClient()
        provider = NotebookLMProvider(client, runtime(supervised=False))

        with pytest.raises(DomainError) as captured:
            await provider.preflight()

        assert captured.value.code is ErrorCode.ACCESS_DENIED
        assert captured.value.operation == "notebooklm.registry"
        assert client.calls == []

    asyncio.run(scenario())


def test_inspect_and_acquire_return_versioned_opaque_contracts() -> None:
    async def scenario() -> None:
        now = datetime(2026, 8, 13, 12, tzinfo=UTC)
        client = FakeMCPClient(
            answer=f"A grounded answer from {NOTEBOOK_URL}",
            citations=[{"excerpt": f"An excerpt linked to {NOTEBOOK_URL}"}],
        )
        provider = NotebookLMProvider(client, runtime(), clock=lambda: now)
        assert isinstance(provider, KnowledgeSourceProvider)

        source = await provider.inspect(AcquisitionRequest(url=NOTEBOOK_URL))
        evidence = await provider.acquire(source, ContextBudget())

        assert source.source_type is SourceType.NOTEBOOKLM
        assert source.acquisition_method is AcquisitionMethod.NOTEBOOKLM_MCP
        assert source.canonical_ref.startswith("notebooklm:notebooklm-")
        assert NOTEBOOK_URL not in source.model_dump_json()
        assert evidence.source == source
        assert [item.locator for item in evidence.evidence_items] == [
            "notebooklm:answer",
            "notebooklm:citation:0001",
        ]
        assert evidence.coverage.completeness == 1.0
        assert NOTEBOOK_URL not in evidence.model_dump_json()
        invoked = [name for name, _ in client.calls]
        assert invoked == [
            "initialize",
            "tools/list",
            "server_health",
            "content_list",
            "notebook_ask",
        ]
        assert set(invoked[2:]).issubset(DESIGN_PROVIDER_TOOLS)
        await provider.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("source_count", [0, 2])
def test_inspect_requires_exactly_one_source(source_count: int) -> None:
    async def scenario() -> None:
        sources = [
            {"id": f"source-{index}", "name": f"Source {index}", "type": "document"}
            for index in range(source_count)
        ]
        client = FakeMCPClient(sources=sources)
        provider = NotebookLMProvider(client, runtime())

        with pytest.raises(DomainError) as captured:
            await provider.inspect(AcquisitionRequest(url=NOTEBOOK_URL))

        assert captured.value.code is ErrorCode.INVALID_REQUEST
        assert captured.value.operation == "notebooklm.source_count"
        await provider.close()

    asyncio.run(scenario())


def test_acquire_enforces_source_budget() -> None:
    async def scenario() -> None:
        client = FakeMCPClient(answer="x" * 100)
        provider = NotebookLMProvider(client, runtime())
        source = await provider.inspect(AcquisitionRequest(url=NOTEBOOK_URL))

        with pytest.raises(DomainError) as captured:
            await provider.acquire(source, ContextBudget(max_source_bytes=10))

        assert captured.value.code is ErrorCode.BUDGET_EXCEEDED
        assert NOTEBOOK_URL not in str(captured.value)
        await provider.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "http://notebooklm.google.com/notebook/example",
        "https://example.com/notebook/example",
        "https://user:password@notebooklm.google.com/notebook/example",
        "https://notebooklm.google.com/notebook/example#private",
    ],
)
def test_inspect_rejects_invalid_notebook_urls_without_starting_mcp(url: str) -> None:
    async def scenario() -> None:
        client = FakeMCPClient()
        provider = NotebookLMProvider(client, runtime())

        with pytest.raises(DomainError) as captured:
            await provider.inspect(AcquisitionRequest(url=url))

        assert captured.value.code is ErrorCode.INVALID_REQUEST
        assert client.calls == []
        assert url not in str(captured.value)

    asyncio.run(scenario())


def test_stdio_client_controls_process_and_does_not_inherit_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = tmp_path / "fake_mcp.py"
    server.write_text(
        """
import json
import os
import sys

for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message["method"]
    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "notebooklm-safe-proxy", "version": "0.1.0"},
            "capabilities": {"tools": {}},
        }
    elif method == "tools/list":
        result = {"tools": [{"name": "server_health", "annotations": {}}]}
    elif method == "tools/call":
        payload = {
            "success": True,
            "data": {"credential_inherited": "KA_OPENAI_API_KEY" in os.environ},
        }
        result = {"structuredContent": payload}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
""".lstrip(),
        encoding="utf-8",
    )
    data_dir = tmp_path / "mcp-data"
    data_dir.mkdir()
    monkeypatch.setenv("KA_OPENAI_API_KEY", "must-not-reach-child")

    async def scenario() -> None:
        client = MCPStdioClient(
            MCPStdioConfig(
                command=(sys.executable, str(server)),
                data_dir=data_dir.resolve(),
                cwd=tmp_path.resolve(),
            )
        )
        await client.start()
        info = await client.initialize()
        tools = await client.list_tools()
        result = await client.call_tool("server_health", {})

        assert info.name == "notebooklm-safe-proxy"
        assert [tool.name for tool in tools] == ["server_health"]
        assert result["structuredContent"]["data"]["credential_inherited"] is False
        assert client.running is True
        await client.close()
        assert client.running is False

    asyncio.run(scenario())
