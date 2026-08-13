from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_agents.domain.errors import DomainError, ErrorCode

SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18"})
SAFE_ENVIRONMENT_KEYS = ("PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP")


@dataclass(frozen=True, slots=True)
class MCPStdioConfig:
    command: tuple[str, ...]
    data_dir: Path
    cwd: Path | None = None
    timeout_seconds: float = 30.0
    shutdown_timeout_seconds: float = 2.0
    max_message_bytes: int = 1024 * 1024
    enable_remote_read: bool = True
    enable_ask: bool = True

    def __post_init__(self) -> None:
        if not self.command or not all(part and "\x00" not in part for part in self.command):
            raise ValueError("command must contain non-empty arguments")
        if self.timeout_seconds <= 0 or self.shutdown_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")
        if self.max_message_bytes <= 0:
            raise ValueError("max_message_bytes must be positive")
        if not self.data_dir.is_absolute():
            raise ValueError("data_dir must be absolute")
        if self.cwd is not None and not self.cwd.is_absolute():
            raise ValueError("cwd must be absolute")


@dataclass(frozen=True, slots=True)
class MCPServerInfo:
    protocol_version: str
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class MCPTool:
    name: str
    annotations: Mapping[str, Any]


class MCPStdioClient:
    def __init__(self, config: MCPStdioConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._request_lock = asyncio.Lock()
        self._next_id = 1

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def __aenter__(self) -> MCPStdioClient:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        if self.running:
            return
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.cwd,
                env=self._environment(),
                limit=self.config.max_message_bytes + 1,
            )
        except (OSError, ValueError) as error:
            self._process = None
            raise DomainError(ErrorCode.PROVIDER_UNAVAILABLE, "mcp.start", cause=error) from error
        if self._process.stderr is not None:
            self._stderr_task = asyncio.create_task(self._discard_stderr(self._process.stderr))

    async def close(self) -> None:
        process = self._process
        self._process = None
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await process.stdin.wait_closed()
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(
                        process.wait(), timeout=self.config.shutdown_timeout_seconds
                    )
                except TimeoutError:
                    process.kill()
                    await process.wait()
            else:
                await process.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task
            self._stderr_task = None

    async def initialize(self) -> MCPServerInfo:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "knowledge-agents", "version": "0.1.0"},
            },
        )
        protocol_version = result.get("protocolVersion")
        server_info = result.get("serverInfo")
        if (
            not isinstance(protocol_version, str)
            or protocol_version not in SUPPORTED_PROTOCOL_VERSIONS
            or not isinstance(server_info, dict)
            or not isinstance(server_info.get("name"), str)
            or not isinstance(server_info.get("version"), str)
        ):
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "mcp.initialize")
        await self.notify("notifications/initialized", {})
        return MCPServerInfo(
            protocol_version=protocol_version,
            name=server_info["name"],
            version=server_info["version"],
        )

    async def list_tools(self) -> tuple[MCPTool, ...]:
        result = await self.request("tools/list", {})
        raw_tools = result.get("tools")
        if not isinstance(raw_tools, list):
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "mcp.tools.list")
        tools: list[MCPTool] = []
        names: set[str] = set()
        for raw_tool in raw_tools:
            if not isinstance(raw_tool, dict) or not isinstance(raw_tool.get("name"), str):
                raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "mcp.tools.list")
            name = raw_tool["name"]
            if not name or name in names:
                raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "mcp.tools.list")
            annotations = raw_tool.get("annotations", {})
            if not isinstance(annotations, dict):
                raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "mcp.tools.list")
            names.add(name)
            tools.append(MCPTool(name=name, annotations=annotations))
        return tuple(tools)

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        result = await self.request(
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
        )
        return result

    async def request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        async with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            await self._write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": dict(params),
                }
            )
            while True:
                message = await self._read()
                if "method" in message and "id" not in message:
                    continue
                if message.get("id") != request_id:
                    raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "mcp.response.id")
                if "error" in message:
                    raise DomainError(
                        ErrorCode.PROVIDER_UNAVAILABLE,
                        f"mcp.rpc.{method.replace('/', '.')}",
                    )
                result = message.get("result")
                if not isinstance(result, dict):
                    raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "mcp.response.result")
                return result

    async def notify(self, method: str, params: Mapping[str, Any]) -> None:
        async with self._request_lock:
            await self._write({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    def _environment(self) -> dict[str, str]:
        environment = {key: os.environ[key] for key in SAFE_ENVIRONMENT_KEYS if key in os.environ}
        environment.update(
            {
                "AUTO_LOGIN_ENABLED": "false",
                "DATA_DIR": str(self.config.data_dir),
                "HEADLESS": "true",
                "NOTEBOOKLM_SAFE_ENABLE_ASK": str(self.config.enable_ask).lower(),
                "NOTEBOOKLM_SAFE_ENABLE_REMOTE_READ": str(self.config.enable_remote_read).lower(),
                "NOTEBOOKLM_SAFE_SOURCE_FORMAT": "json",
            }
        )
        return environment

    async def _write(self, message: Mapping[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise DomainError(ErrorCode.PROVIDER_UNAVAILABLE, "mcp.stdin")
        try:
            encoded = (
                json.dumps(
                    message,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
            if len(encoded) > self.config.max_message_bytes:
                raise DomainError(ErrorCode.INVALID_REQUEST, "mcp.message.limit")
            process.stdin.write(encoded)
            await asyncio.wait_for(process.stdin.drain(), timeout=self.config.timeout_seconds)
        except DomainError:
            raise
        except (BrokenPipeError, ConnectionResetError, TimeoutError) as error:
            raise DomainError(ErrorCode.PROVIDER_UNAVAILABLE, "mcp.write", cause=error) from error

    async def _read(self) -> dict[str, Any]:
        process = self._require_process()
        if process.stdout is None:
            raise DomainError(ErrorCode.PROVIDER_UNAVAILABLE, "mcp.stdout")
        try:
            encoded = await asyncio.wait_for(
                process.stdout.readline(), timeout=self.config.timeout_seconds
            )
        except (TimeoutError, ValueError) as error:
            raise DomainError(ErrorCode.PROVIDER_UNAVAILABLE, "mcp.read", cause=error) from error
        if (
            not encoded
            or len(encoded) > self.config.max_message_bytes
            or not encoded.endswith(b"\n")
        ):
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "mcp.message")
        try:
            message = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DomainError(
                ErrorCode.CONTRACT_VALIDATION_FAILED, "mcp.message", cause=error
            ) from error
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "mcp.message")
        return message

    def _require_process(self) -> asyncio.subprocess.Process:
        if not self.running or self._process is None:
            raise DomainError(ErrorCode.PROVIDER_UNAVAILABLE, "mcp.lifecycle")
        return self._process

    @staticmethod
    async def _discard_stderr(stream: asyncio.StreamReader) -> None:
        while await stream.read(4096):
            pass
