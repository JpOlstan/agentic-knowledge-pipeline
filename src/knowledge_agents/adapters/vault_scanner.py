from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from knowledge_agents.domain.errors import DomainError, ErrorCode

FRONTMATTER_FIELD = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$")
NOTE_ID_FIELDS = ("note_id", "note-id", "id")


@dataclass(frozen=True, slots=True)
class VaultEntry:
    relative_path: str
    note_id: str | None
    title: str | None
    status: str | None
    declared_content_hash: str | None
    file_hash: str


@dataclass(frozen=True, slots=True)
class VaultInventory:
    entries: tuple[VaultEntry, ...]

    def entries_for_note(self, note_id: str) -> tuple[VaultEntry, ...]:
        return tuple(entry for entry in self.entries if entry.note_id == note_id)


class VaultScanner:
    def __init__(self, vault_root: Path, *, allowed_paths: tuple[str, ...]) -> None:
        if not allowed_paths:
            raise DomainError(ErrorCode.ACCESS_DENIED, "vault_scanner.allowlist")
        self.vault_root = vault_root
        self.allowed_paths = tuple(_validated_relative_path(path) for path in allowed_paths)

    async def scan(self) -> VaultInventory:
        return await asyncio.to_thread(self._scan)

    async def read_markdown(self, relative_path: str) -> str:
        return await asyncio.to_thread(self._read_markdown, relative_path)

    def _scan(self) -> VaultInventory:
        root = self.vault_root.resolve()
        entries: list[VaultEntry] = []
        seen_paths: set[str] = set()
        for allowed in self.allowed_paths:
            scan_root = self._safe_target(allowed)
            if not scan_root.exists():
                continue
            if scan_root.is_symlink() or not scan_root.is_dir():
                raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "vault_scanner.scan")
            for directory, directory_names, file_names in os.walk(
                scan_root,
                topdown=True,
                followlinks=False,
            ):
                current = Path(directory)
                for name in directory_names:
                    if (current / name).is_symlink():
                        raise DomainError(
                            ErrorCode.PATH_TRAVERSAL_BLOCKED,
                            "vault_scanner.scan",
                        )
                for name in file_names:
                    path = current / name
                    if path.suffix.lower() != ".md":
                        continue
                    if path.is_symlink():
                        raise DomainError(
                            ErrorCode.PATH_TRAVERSAL_BLOCKED,
                            "vault_scanner.scan",
                        )
                    resolved = path.resolve(strict=True)
                    if not resolved.is_relative_to(root):
                        raise DomainError(
                            ErrorCode.PATH_TRAVERSAL_BLOCKED,
                            "vault_scanner.scan",
                        )
                    relative_path = resolved.relative_to(root).as_posix()
                    if relative_path in seen_paths:
                        continue
                    seen_paths.add(relative_path)
                    entries.append(_read_entry(resolved, relative_path))
        return VaultInventory(entries=tuple(sorted(entries, key=lambda item: item.relative_path)))

    def _safe_target(self, relative_path: str) -> Path:
        relative = PurePosixPath(relative_path)
        root = self.vault_root.resolve()
        current = root
        for part in relative.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise DomainError(
                    ErrorCode.PATH_TRAVERSAL_BLOCKED,
                    "vault_scanner.path",
                )
        resolved = current.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "vault_scanner.path")
        return current

    def _read_markdown(self, relative_path: str) -> str:
        normalized = _validated_relative_path(relative_path)
        relative = PurePosixPath(normalized)
        if not any(
            relative == PurePosixPath(allowed) or relative.is_relative_to(PurePosixPath(allowed))
            for allowed in self.allowed_paths
        ):
            raise DomainError(ErrorCode.ACCESS_DENIED, "vault_scanner.read")
        path = self._safe_target(normalized)
        if path.suffix.lower() != ".md" or path.is_symlink() or not path.is_file():
            raise DomainError(ErrorCode.ACCESS_DENIED, "vault_scanner.read")
        return path.read_text(encoding="utf-8")


def _validated_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or ":" in relative.parts[0]
    ):
        raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "vault_scanner.allowlist")
    return relative.as_posix()


def _read_entry(path: Path, relative_path: str) -> VaultEntry:
    content = path.read_text(encoding="utf-8")
    fields = _frontmatter_fields(content)
    note_id = next((fields[field] for field in NOTE_ID_FIELDS if fields.get(field)), None)
    title = next(
        (line.removeprefix("# ").strip() for line in content.splitlines() if line.startswith("# ")),
        None,
    )
    return VaultEntry(
        relative_path=relative_path,
        note_id=note_id,
        title=title,
        status=fields.get("status"),
        declared_content_hash=fields.get("content_hash"),
        file_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _frontmatter_fields(content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = FRONTMATTER_FIELD.fullmatch(line)
        if match is None:
            continue
        key, value = match.groups()
        fields[key] = _unquote_scalar(value)
    return fields


def _unquote_scalar(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped
