import json
from pathlib import Path

from typer.testing import CliRunner

from knowledge_agents.cli import app

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
