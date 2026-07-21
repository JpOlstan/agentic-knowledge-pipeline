from __future__ import annotations

import asyncio
import json
from typing import Annotated

import typer
from pydantic import ValidationError

from knowledge_agents.adapters.sqlite_run_store import SqliteRunStore
from knowledge_agents.application.services.doctor_service import (
    DoctorProfile,
    ExitCode,
    local_doctor_service,
)
from knowledge_agents.config import Settings

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
def repairs_list() -> None:
    _unavailable("repairs.list")


@repairs_app.command("run")
def repairs_run(run_id: str) -> None:
    _unavailable("repairs.run", run_id=run_id)


@index_app.command("status")
def index_status() -> None:
    _unavailable("index.status")


@index_app.command("sync")
def index_sync() -> None:
    _unavailable("index.sync")


@index_app.command("rebuild")
def index_rebuild() -> None:
    _unavailable("index.rebuild")


def _unavailable(operation: str, **_: str) -> None:
    typer.echo(f"precondition_failed operation={operation}", err=True)
    raise typer.Exit(int(ExitCode.PRECONDITION))


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
