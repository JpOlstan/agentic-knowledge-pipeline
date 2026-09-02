import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from knowledge_agents.adapters.sqlite_run_store import SqliteRunStore
from knowledge_agents.cli import app
from knowledge_agents.domain.contracts import RepairTask
from knowledge_agents.domain.enums import RepairTarget

runner = CliRunner()


def configure_local_profile(monkeypatch: object, tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime"
    vault = tmp_path / "vault"
    runtime.mkdir()
    vault.mkdir()
    monkeypatch.setenv("KA_RUNTIME_PATH", str(runtime))
    monkeypatch.setenv("KA_VAULT_PATH", str(vault))
    monkeypatch.setenv("KA_VAULT_ALLOWED_PATHS", '["01-inbox/agent-runs"]')
    return runtime, vault


def test_help_exposes_the_designed_command_tree() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("trigger", "worker", "doctor", "runs", "repairs", "index"):
        assert command in result.stdout


def test_doctor_local_json_succeeds_without_network(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    configure_local_profile(monkeypatch, tmp_path)

    result = runner.invoke(app, ["doctor", "--profile", "local", "--json"])

    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["status"] == "pass"
    assert report["exit_code"] == 0
    assert {check["name"] for check in report["checks"]} == {
        "python",
        "configuration",
        "runtime_path",
        "vault_allowlist",
        "sqlite",
    }


def test_doctor_local_returns_dependency_exit_code_and_redacts_paths(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    runtime, vault = configure_local_profile(monkeypatch, tmp_path)
    vault.rmdir()

    result = runner.invoke(app, ["doctor", "--profile", "local", "--json"])

    assert result.exit_code == 3
    report = json.loads(result.stdout)
    assert report["exit_code"] == 3
    assert str(runtime) not in result.stdout
    assert str(vault) not in result.stdout


def test_future_side_effect_commands_fail_as_explicit_preconditions() -> None:
    result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 2
    assert "precondition_failed operation=runs.list" in result.output


def test_index_sync_fails_closed_without_embedding_credentials(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    configure_local_profile(monkeypatch, tmp_path)

    result = runner.invoke(app, ["index", "sync", "--json"])

    assert result.exit_code == 2
    report = json.loads(result.stdout)
    assert report["message"] == "embedding_credentials_required"


def test_index_rebuild_requires_explicit_confirmation() -> None:
    result = runner.invoke(app, ["index", "rebuild", "--json"])

    assert result.exit_code == 2
    report = json.loads(result.stdout)
    assert report["message"] == "confirmation_required"


def test_repairs_list_and_empty_run_are_offline_safe(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    configure_local_profile(monkeypatch, tmp_path)

    listed = runner.invoke(app, ["repairs", "list", "--json"])
    executed = runner.invoke(app, ["repairs", "run", "run-without-repairs", "--json"])

    assert listed.exit_code == 0
    assert json.loads(listed.stdout) == {"status": "ok", "count": 0, "repairs": []}
    assert executed.exit_code == 0
    report = json.loads(executed.stdout)
    assert report["run_id"] == "run-without-repairs"
    assert report["attempted"] == []


def test_repairs_run_fails_closed_without_target_credentials(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    runtime, _ = configure_local_profile(monkeypatch, tmp_path)
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    async def seed() -> None:
        store = SqliteRunStore(runtime / "state" / "runs.db")
        await store.migrate()
        await store.create_or_get_run(
            run_id="run-langfuse-repair-0001",
            idempotency_key="cli-repair-idempotency",
            request_hash="a" * 64,
        )
        await store.enqueue_repair(
            RepairTask(
                repair_id="repair-langfuse-cli",
                run_id="run-langfuse-repair-0001",
                target=RepairTarget.LANGFUSE,
                attempts=0,
                next_attempt_at=now,
                last_error="telemetry_repair_required",
            )
        )

    asyncio.run(seed())
    result = runner.invoke(app, ["repairs", "run", "run-langfuse-repair-0001", "--json"])

    assert result.exit_code == 2
    report = json.loads(result.stdout)
    assert report["message"] == "langfuse_credentials_required"
