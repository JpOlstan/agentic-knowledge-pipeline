from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Annotated

import typer
from openai import AsyncOpenAI
from pydantic import ValidationError
from qdrant_client import AsyncQdrantClient

from knowledge_agents.adapters.chunker import MarkdownChunker
from knowledge_agents.adapters.embeddings import EmbeddingConfig, OpenAIEmbeddings
from knowledge_agents.adapters.langfuse_telemetry import create_langfuse_telemetry
from knowledge_agents.adapters.qdrant_index import QdrantVectorIndex
from knowledge_agents.adapters.sqlite_run_store import SqliteRunStore
from knowledge_agents.adapters.vault_scanner import VaultScanner
from knowledge_agents.application.services.doctor_service import (
    DoctorProfile,
    ExitCode,
    local_doctor_service,
)
from knowledge_agents.application.services.index_service import IndexScan, IndexService, IndexSource
from knowledge_agents.application.services.repair_service import RepairRunResult, RepairService
from knowledge_agents.config import Settings
from knowledge_agents.domain.contracts import RepairTask
from knowledge_agents.domain.enums import RepairTarget
from knowledge_agents.ports.telemetry import TelemetryEvent
from knowledge_agents.ports.vector_index import DRAFT_COLLECTION, NOTE_COLLECTION

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
worker_app = typer.Typer(no_args_is_help=True)
runs_app = typer.Typer(no_args_is_help=True)
repairs_app = typer.Typer(no_args_is_help=True)
index_app = typer.Typer(no_args_is_help=True)

app.add_typer(worker_app, name="worker")
app.add_typer(runs_app, name="runs")
app.add_typer(repairs_app, name="repairs")
app.add_typer(index_app, name="index")


@app.command()
def trigger(url: Annotated[str, typer.Argument(help="Source URL")]) -> None:
    _unavailable("trigger", url=url)


@worker_app.command("start")
def worker_start() -> None:
    _unavailable("worker.start")


@app.command()
def doctor(
    profile: Annotated[DoctorProfile, typer.Option("--profile")] = DoctorProfile.LOCAL,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        settings = Settings()
    except ValidationError:
        _emit_error("configuration_invalid", ExitCode.PRECONDITION, json_output=json_output)
        return

    store = SqliteRunStore(settings.runtime_path / "state" / "runs.db")
    report = asyncio.run(local_doctor_service(settings, store).run(profile))
    if json_output:
        typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        for check in report.checks:
            typer.echo(f"{check.status.value.upper()} {check.name}: {check.message}")
        typer.echo(f"exit_code={int(report.exit_code)}")
    if report.exit_code is not ExitCode.SUCCESS:
        raise typer.Exit(int(report.exit_code))


@runs_app.command("list")
def runs_list() -> None:
    _unavailable("runs.list")


@runs_app.command("show")
def runs_show(run_id: str) -> None:
    _unavailable("runs.show", run_id=run_id)


@runs_app.command("resume")
def runs_resume(run_id: str) -> None:
    _unavailable("runs.resume", run_id=run_id)


@runs_app.command("replay")
def runs_replay(run_id: str) -> None:
    _unavailable("runs.replay", run_id=run_id)


@repairs_app.command("list")
def repairs_list(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        settings = Settings()
        payload = asyncio.run(_list_repairs(settings))
    except ValidationError:
        _emit_error("configuration_invalid", ExitCode.PRECONDITION, json_output=json_output)
        return
    except Exception:
        _emit_error("repairs_store_unavailable", ExitCode.DEPENDENCY, json_output=json_output)
        return
    _emit_payload(payload, json_output=json_output)


@repairs_app.command("run")
def repairs_run(
    run_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        settings = Settings()
        payload = asyncio.run(_run_repairs(run_id, settings))
    except ValidationError:
        _emit_error("configuration_invalid", ExitCode.PRECONDITION, json_output=json_output)
        return
    except RepairPreconditionError as error:
        _emit_error(str(error), ExitCode.PRECONDITION, json_output=json_output)
        return
    except Exception:
        _emit_error("repair_dependency_unavailable", ExitCode.DEPENDENCY, json_output=json_output)
        return
    _emit_payload(payload, json_output=json_output)


@index_app.command("status")
def index_status(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _execute_index("status", json_output=json_output)


@index_app.command("sync")
def index_sync(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _execute_index("sync", json_output=json_output)


@index_app.command("rebuild")
def index_rebuild(
    confirm: Annotated[bool, typer.Option("--yes", help="Confirm derived-index reset")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if not confirm:
        _emit_error("confirmation_required", ExitCode.PRECONDITION, json_output=json_output)
    _execute_index("rebuild", json_output=json_output)


def _execute_index(operation: str, *, json_output: bool) -> None:
    try:
        settings = Settings()
    except ValidationError:
        _emit_error("configuration_invalid", ExitCode.PRECONDITION, json_output=json_output)
        return
    if operation in {"sync", "rebuild"} and settings.openai_api_key is None:
        _emit_error(
            "embedding_credentials_required", ExitCode.PRECONDITION, json_output=json_output
        )
        return
    try:
        payload = asyncio.run(_run_index_operation(operation, settings))
    except Exception:
        _emit_error("index_dependency_unavailable", ExitCode.DEPENDENCY, json_output=json_output)
        return
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        typer.echo(" ".join(f"{key}={value}" for key, value in sorted(payload.items())))


async def _run_index_operation(
    operation: str,
    settings: Settings,
    *,
    run_id: str | None = None,
) -> dict[str, object]:
    qdrant = AsyncQdrantClient(url=str(settings.qdrant_url))
    openai_client: AsyncOpenAI | None = None
    try:
        if settings.openai_api_key is not None:
            openai_client = AsyncOpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                timeout=120,
                max_retries=2,
            )
        embeddings = OpenAIEmbeddings(
            openai_client,
            EmbeddingConfig(
                model=settings.openai_embedding_model,
                dimensions=settings.openai_embedding_dimensions,
            ),
        )
        vector_index = QdrantVectorIndex(qdrant, embeddings)
        store = SqliteRunStore(settings.runtime_path / "state" / "runs.db")
        await store.migrate()
        service = IndexService(
            vector_index=vector_index,
            run_store=store,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            chunker=MarkdownChunker(),
        )
        if operation == "status":
            return asdict(await service.status())
        scan = await _vault_index_scan(settings)
        result = (
            await service.rebuild(scan, run_id=run_id)
            if operation == "rebuild"
            else await service.sync(scan, run_id=run_id)
        )
        return asdict(result)
    finally:
        if openai_client is not None:
            await openai_client.close()
        await qdrant.close()


async def _vault_index_scan(settings: Settings) -> IndexScan:
    scanner = VaultScanner(settings.vault_path, allowed_paths=settings.vault_allowed_paths)
    inventory = await scanner.scan()
    sources: list[IndexSource] = []
    for entry in inventory.entries:
        if entry.note_id is None:
            continue
        content = await scanner.read_markdown(entry.relative_path)
        parts = entry.relative_path.split("/")
        is_draft = "agent-runs" in parts and "drafts" in parts
        run_id = ""
        if "agent-runs" in parts:
            position = parts.index("agent-runs")
            if position + 1 < len(parts):
                run_id = parts[position + 1]
        sources.append(
            IndexSource(
                path=entry.relative_path,
                document_id=entry.note_id,
                note_id=entry.note_id,
                collection=DRAFT_COLLECTION if is_draft else NOTE_COLLECTION,
                content=content,
                content_hash=entry.file_hash,
                run_id=run_id,
                source_type="vault_draft" if is_draft else "vault_note",
                status=entry.status or "unknown",
                metadata={
                    "file_identity": hashlib.sha256(entry.relative_path.encode("utf-8")).hexdigest()
                },
            )
        )
    return IndexScan(sources=tuple(sources), complete=True)


def _unavailable(operation: str, **_: str) -> None:
    typer.echo(f"precondition_failed operation={operation}", err=True)
    raise typer.Exit(int(ExitCode.PRECONDITION))


class RepairPreconditionError(RuntimeError):
    pass


async def _list_repairs(settings: Settings) -> dict[str, object]:
    store = SqliteRunStore(settings.runtime_path / "state" / "runs.db")
    await store.migrate()
    repairs = await RepairService(run_store=store, handlers={}).list()
    return {
        "status": "ok",
        "count": len(repairs),
        "repairs": [_repair_payload(task) for task in repairs],
    }


async def _run_repairs(run_id: str, settings: Settings) -> dict[str, object]:
    store = SqliteRunStore(settings.runtime_path / "state" / "runs.db")
    await store.migrate()
    service = RepairService(run_store=store, handlers={})
    repairs = await service.list(run_id=run_id)
    if not repairs:
        return _repair_result_payload(await service.run(run_id))

    targets = {task.target for task in repairs}
    if RepairTarget.QDRANT in targets and settings.openai_api_key is None:
        raise RepairPreconditionError("embedding_credentials_required")
    if RepairTarget.LANGFUSE in targets and (
        settings.langfuse_public_key is None or settings.langfuse_secret_key is None
    ):
        raise RepairPreconditionError("langfuse_credentials_required")

    async def repair_qdrant(task: RepairTask) -> None:
        result = await _run_index_operation("sync", settings, run_id=task.run_id)
        if result.get("repair_required") or result.get("failed_paths"):
            raise RuntimeError("qdrant repair incomplete")

    async def repair_langfuse(task: RepairTask) -> None:
        assert settings.langfuse_public_key is not None
        assert settings.langfuse_secret_key is not None
        telemetry = create_langfuse_telemetry(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=str(settings.langfuse_host),
            environment=settings.env,
        )
        await telemetry.record(
            TelemetryEvent(
                run_id=task.run_id,
                name="repairs.langfuse",
                occurred_at=task.next_attempt_at,
                attributes={
                    "target": task.target.value,
                    "status": "repair",
                    "error_code": task.last_error or "telemetry_repair_required",
                },
            )
        )
        await telemetry.flush()

    service = RepairService(
        run_store=store,
        handlers={
            RepairTarget.QDRANT: repair_qdrant,
            RepairTarget.LANGFUSE: repair_langfuse,
        },
    )
    return _repair_result_payload(await service.run(run_id))


def _repair_payload(task: RepairTask) -> dict[str, object]:
    return {
        "repair_id": task.repair_id,
        "run_id": task.run_id,
        "target": task.target.value,
        "attempts": task.attempts,
        "next_attempt_at": task.next_attempt_at.isoformat(),
        "last_error": task.last_error,
    }


def _repair_result_payload(result: RepairRunResult) -> dict[str, object]:
    return {"status": "ok", **asdict(result)}


def _emit_payload(payload: dict[str, object], *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        typer.echo(" ".join(f"{key}={value}" for key, value in sorted(payload.items())))


def _emit_error(message: str, exit_code: ExitCode, *, json_output: bool) -> None:
    if json_output:
        typer.echo(
            json.dumps(
                {"status": "fail", "exit_code": int(exit_code), "message": message},
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"FAIL configuration: {message}", err=True)
    raise typer.Exit(int(exit_code))
