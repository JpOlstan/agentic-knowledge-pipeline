from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from pathlib import Path, PurePosixPath
from typing import Protocol

from knowledge_agents.config import Settings
from knowledge_agents.ports.run_store import RunStore


class DoctorProfile(StrEnum):
    LOCAL = "local"
    NOTEBOOKLM = "notebooklm"
    WEB = "web"
    TRIGGER = "trigger"
    FULL = "full"


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class ExitCode(IntEnum):
    SUCCESS = 0
    PRECONDITION = 2
    DEPENDENCY_UNAVAILABLE = 3
    EXECUTION_FAILURE = 4


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    exit_code: ExitCode
    message: str
    metadata: dict[str, str | int | bool]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "exit_code": int(self.exit_code),
            "message": self.message,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class DoctorReport:
    profile: DoctorProfile
    checks: tuple[CheckResult, ...]
    exit_code: ExitCode

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile.value,
            "status": "pass" if self.exit_code is ExitCode.SUCCESS else "fail",
            "exit_code": int(self.exit_code),
            "checks": [check.to_dict() for check in self.checks],
        }


class DoctorCheck(Protocol):
    name: str

    async def run(self) -> CheckResult: ...


class PythonVersionCheck:
    name = "python"

    def __init__(self, version: tuple[int, int] | None = None) -> None:
        self.version = version or (sys.version_info.major, sys.version_info.minor)

    async def run(self) -> CheckResult:
        valid = self.version == (3, 12)
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASS if valid else CheckStatus.FAIL,
            exit_code=ExitCode.SUCCESS if valid else ExitCode.DEPENDENCY_UNAVAILABLE,
            message="python_version_supported" if valid else "python_version_unsupported",
            metadata={"major": self.version[0], "minor": self.version[1]},
        )


class ConfigurationCheck:
    name = "configuration"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run(self) -> CheckResult:
        allowed_paths_valid = all(
            _safe_relative_path(path) for path in self.settings.vault_allowed_paths
        )
        roots_distinct = self.settings.runtime_path.resolve() != self.settings.vault_path.resolve()
        valid = bool(self.settings.vault_allowed_paths) and allowed_paths_valid and roots_distinct
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASS if valid else CheckStatus.FAIL,
            exit_code=ExitCode.SUCCESS if valid else ExitCode.PRECONDITION,
            message="configuration_valid" if valid else "configuration_invalid",
            metadata={"allowlist_entries": len(self.settings.vault_allowed_paths)},
        )


class DirectoryCheck:
    def __init__(self, name: str, path: Path) -> None:
        self.name = name
        self.path = path

    async def run(self) -> CheckResult:
        available = self.path.is_dir() and os.access(self.path, os.R_OK | os.W_OK)
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASS if available else CheckStatus.FAIL,
            exit_code=ExitCode.SUCCESS if available else ExitCode.DEPENDENCY_UNAVAILABLE,
            message="directory_available" if available else "directory_unavailable",
            metadata={},
        )


class VaultAllowlistCheck:
    name = "vault_allowlist"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run(self) -> CheckResult:
        root = self.settings.vault_path
        paths_safe = all(_safe_relative_path(path) for path in self.settings.vault_allowed_paths)
        valid = paths_safe and root.is_dir()
        if valid:
            resolved_root = root.resolve()
            valid = all(
                _safe_relative_path(path)
                and resolved_root.joinpath(*PurePosixPath(path).parts)
                .resolve(strict=False)
                .is_relative_to(resolved_root)
                for path in self.settings.vault_allowed_paths
            )
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASS if valid else CheckStatus.FAIL,
            exit_code=(
                ExitCode.SUCCESS
                if valid
                else ExitCode.PRECONDITION
                if not paths_safe
                else ExitCode.DEPENDENCY_UNAVAILABLE
            ),
            message=(
                "vault_allowlist_valid"
                if valid
                else "vault_allowlist_invalid"
                if not paths_safe
                else "vault_unavailable"
            ),
            metadata={"allowlist_entries": len(self.settings.vault_allowed_paths)},
        )


class SqliteCheck:
    name = "sqlite"

    def __init__(self, store: RunStore) -> None:
        self.store = store

    async def run(self) -> CheckResult:
        versions = await self.store.migrate()
        valid = versions == (1, 2)
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASS if valid else CheckStatus.FAIL,
            exit_code=ExitCode.SUCCESS if valid else ExitCode.PRECONDITION,
            message="sqlite_ready" if valid else "sqlite_migrations_incomplete",
            metadata={"migration_count": len(versions)},
        )


class DoctorService:
    def __init__(self) -> None:
        self.registry: dict[DoctorProfile, tuple[DoctorCheck, ...]] = {}

    def register(self, profile: DoctorProfile, checks: tuple[DoctorCheck, ...]) -> None:
        self.registry[profile] = checks

    async def run(self, profile: DoctorProfile) -> DoctorReport:
        checks = self.registry.get(profile)
        if checks is None:
            return DoctorReport(
                profile=profile,
                checks=(
                    CheckResult(
                        name="profile",
                        status=CheckStatus.FAIL,
                        exit_code=ExitCode.PRECONDITION,
                        message="profile_not_configured",
                        metadata={},
                    ),
                ),
                exit_code=ExitCode.PRECONDITION,
            )

        results: list[CheckResult] = []
        for check in checks:
            try:
                results.append(await check.run())
            except Exception:
                results.append(
                    CheckResult(
                        name=check.name,
                        status=CheckStatus.FAIL,
                        exit_code=ExitCode.EXECUTION_FAILURE,
                        message="check_execution_failed",
                        metadata={},
                    )
                )
        exit_code = max((result.exit_code for result in results), default=ExitCode.SUCCESS)
        return DoctorReport(profile=profile, checks=tuple(results), exit_code=ExitCode(exit_code))


def local_doctor_service(settings: Settings, store: RunStore) -> DoctorService:
    service = DoctorService()
    service.register(
        DoctorProfile.LOCAL,
        (
            PythonVersionCheck(),
            ConfigurationCheck(settings),
            DirectoryCheck("runtime_path", settings.runtime_path),
            VaultAllowlistCheck(settings),
            SqliteCheck(store),
        ),
    )
    return service


def _safe_relative_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    return (
        bool(path.parts)
        and not path.is_absolute()
        and ".." not in path.parts
        and ":" not in path.parts[0]
    )
