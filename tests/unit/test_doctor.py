import asyncio
import json
from pathlib import Path

from knowledge_agents.adapters.sqlite_run_store import SqliteRunStore
from knowledge_agents.application.services.doctor_service import (
    CheckStatus,
    ConfigurationCheck,
    DoctorProfile,
    DoctorService,
    ExitCode,
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
