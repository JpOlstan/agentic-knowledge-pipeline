import asyncio
import json
import sys
from pathlib import Path

from knowledge_agents.adapters.sqlite_run_store import SqliteRunStore
from knowledge_agents.application.services.doctor_service import (
    CheckStatus,
    ConfigurationCheck,
    DoctorProfile,
    DoctorService,
    ExitCode,
    NotebookLMRegistryCheck,
    NotebookLMRuntimeCheck,
    PythonVersionCheck,
    SqliteCheck,
    local_doctor_service,
)
from knowledge_agents.config import Settings


def settings_for(tmp_path: Path, **overrides: object) -> Settings:
    runtime = tmp_path / "runtime"
    vault = tmp_path / "vault"
    runtime.mkdir(exist_ok=True)
    vault.mkdir(exist_ok=True)
    values: dict[str, object] = {
        "runtime_path": runtime,
        "vault_path": vault,
        "vault_allowed_paths": ("01-inbox/agent-runs",),
        "openai_api_key": "sensitive-test-value",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_local_doctor_reports_a_valid_offline_environment(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = settings_for(tmp_path)
        store = SqliteRunStore(settings.runtime_path / "state" / "runs.db")

        report = await local_doctor_service(settings, store).run(DoctorProfile.LOCAL)

        assert report.exit_code is ExitCode.SUCCESS
        assert {check.name for check in report.checks} == {
            "python",
            "configuration",
            "runtime_path",
            "vault_allowlist",
            "sqlite",
        }
        assert all(check.status is CheckStatus.PASS for check in report.checks)
        rendered = json.dumps(report.to_dict())
        assert str(settings.runtime_path) not in rendered
        assert str(settings.vault_path) not in rendered
        assert "sensitive-test-value" not in rendered

    asyncio.run(scenario())


def test_invalid_allowlist_is_a_precondition_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = settings_for(tmp_path, vault_allowed_paths=("../outside",))
        store = SqliteRunStore(settings.runtime_path / "state" / "runs.db")

        report = await local_doctor_service(settings, store).run(DoctorProfile.LOCAL)

        assert report.exit_code is ExitCode.PRECONDITION
        failures = {
            check.name: check for check in report.checks if check.status is CheckStatus.FAIL
        }
        assert failures["configuration"].exit_code is ExitCode.PRECONDITION
        assert failures["vault_allowlist"].message == "vault_allowlist_invalid"

    asyncio.run(scenario())


def test_missing_runtime_or_vault_is_dependency_unavailable(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = settings_for(tmp_path)
        settings.runtime_path.rmdir()
        settings.vault_path.rmdir()
        store = SqliteRunStore(settings.runtime_path / "state" / "runs.db")

        report = await local_doctor_service(settings, store).run(DoctorProfile.LOCAL)

        assert report.exit_code is ExitCode.DEPENDENCY_UNAVAILABLE
        failed = {check.name for check in report.checks if check.status is CheckStatus.FAIL}
        assert failed == {"runtime_path", "vault_allowlist"}

    asyncio.run(scenario())


def test_check_exception_becomes_sanitized_execution_failure(tmp_path: Path) -> None:
    class FailingStore:
        async def migrate(self) -> tuple[int, ...]:
            raise RuntimeError(f"private path: {tmp_path}")

    async def scenario() -> None:
        service = DoctorService()
        service.register(DoctorProfile.LOCAL, (SqliteCheck(FailingStore()),))

        report = await service.run(DoctorProfile.LOCAL)

        assert report.exit_code is ExitCode.EXECUTION_FAILURE
        assert report.checks[0].message == "check_execution_failed"
        assert str(tmp_path) not in json.dumps(report.to_dict())

    asyncio.run(scenario())


def test_registry_supports_future_profiles_without_network_checks(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = settings_for(tmp_path)
        service = DoctorService()
        service.register(
            DoctorProfile.WEB,
            (PythonVersionCheck((3, 12)), ConfigurationCheck(settings)),
        )

        report = await service.run(DoctorProfile.WEB)
        unconfigured = await service.run(DoctorProfile.TRIGGER)

        assert report.exit_code is ExitCode.SUCCESS
        assert unconfigured.exit_code is ExitCode.PRECONDITION
        assert unconfigured.checks[0].message == "profile_not_configured"

    asyncio.run(scenario())


def test_notebooklm_profile_validates_runtime_and_supervised_registry(
    tmp_path: Path,
) -> None:
    proxy = tmp_path / "notebooklm-safe-proxy.mjs"
    package_json = tmp_path / "package.json"
    data_dir = tmp_path / "data"
    proxy.write_text("// fixture", encoding="utf-8")
    package_json.write_text(
        '{"name":"@roomi-fields/notebooklm-mcp","version":"2.1.0"}',
        encoding="utf-8",
    )
    data_dir.mkdir()

    async def scenario() -> None:
        settings = settings_for(
            tmp_path,
            notebooklm_node_executable=sys.executable,
            notebooklm_proxy_path=proxy,
            notebooklm_runtime_package_json=package_json,
            notebooklm_data_dir=data_dir,
            notebooklm_registry_status="evaluating",
            notebooklm_supervised=True,
        )
        store = SqliteRunStore(settings.runtime_path / "state" / "runs.db")

        report = await local_doctor_service(settings, store).run(DoctorProfile.NOTEBOOKLM)

        assert report.exit_code is ExitCode.SUCCESS
        assert {check.name for check in report.checks} == {
            "python",
            "configuration",
            "notebooklm_runtime",
            "notebooklm_registry",
        }
        assert str(proxy) not in json.dumps(report.to_dict())
        assert str(data_dir) not in json.dumps(report.to_dict())

    asyncio.run(scenario())


def test_notebooklm_registry_blocks_unsupervised_evaluating_runtime(tmp_path: Path) -> None:
    package_json = tmp_path / "package.json"
    package_json.write_text(
        '{"name":"@roomi-fields/notebooklm-mcp","version":"2.1.0"}',
        encoding="utf-8",
    )
    settings = settings_for(
        tmp_path,
        notebooklm_runtime_package_json=package_json,
        notebooklm_registry_status="evaluating",
        notebooklm_supervised=False,
    )

    async def scenario() -> None:
        result = await NotebookLMRegistryCheck(settings).run()
        runtime = await NotebookLMRuntimeCheck(settings).run()

        assert result.status is CheckStatus.FAIL
        assert result.exit_code is ExitCode.PRECONDITION
        assert result.message == "notebooklm_registry_blocked"
        assert runtime.status is CheckStatus.FAIL

    asyncio.run(scenario())
