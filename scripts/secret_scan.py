from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    rule: str


RULES = (
    Rule("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    Rule("aws_access_key", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    Rule(
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{40,255})\b"),
    ),
    Rule(
        "provider_secret",
        re.compile(r"\bsk-(?:(?:proj|lf)-)?[A-Za-z0-9_-]{20,255}\b", re.IGNORECASE),
    ),
    Rule("credential_in_url", re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)),
    Rule(
        "assigned_secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|authorization|password|secret|token)\b\s*[:=]\s*"
            r"[\"'](?!<|example\b|dummy\b|fake\b|placeholder\b|test\b)[^\s\"'#]{16,}[\"']"
        ),
    ),
    Rule(
        "environment_secret",
        re.compile(
            r"(?i)^\s*[A-Z0-9_]*(?:API_KEY|AUTHORIZATION|PASSWORD|SECRET|TOKEN)\s*=\s*"
            r"(?!<|example\b|dummy\b|fake\b|placeholder\b|test\b)[A-Za-z0-9_./+=-]{16,}\s*$"
        ),
    ),
)


def repository_files(root: Path) -> tuple[Path, ...]:
    result = subprocess.run(
        ("git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"),
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tuple(root / raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw)


def scan_paths(paths: Iterable[Path], *, root: Path | None = None) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for path in sorted(paths, key=lambda item: item.as_posix()):
        display_path = _display_path(path, root)
        if path.is_symlink():
            findings.append(Finding(display_path, 0, "tracked_symlink"))
            continue
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            findings.append(Finding(display_path, 0, "oversized_tracked_file"))
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for rule in RULES:
                match = rule.pattern.search(line)
                if match is not None and not _approved_synthetic_match(rule, match):
                    findings.append(Finding(display_path, line_number, rule.name))
    return tuple(findings)


def format_findings(findings: Sequence[Finding]) -> str:
    return "\n".join(
        f"{finding.path}:{finding.line}: potential credential ({finding.rule})"
        for finding in findings
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan candidate repository files for credentials.")
    parser.add_argument("paths", nargs="*", type=Path)
    arguments = parser.parse_args(argv)
    root = Path.cwd().resolve()
    paths = tuple(path.resolve() for path in arguments.paths) or repository_files(root)
    findings = scan_paths(paths, root=root)
    if findings:
        print(format_findings(findings))
        return 1
    print(f"secret scan passed: {len(paths)} files checked")
    return 0


def _display_path(path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def _approved_synthetic_match(rule: Rule, match: re.Match[str]) -> bool:
    value = match.group(0).lower()
    if rule.name == "credential_in_url" and value.startswith(
        ("http://user:password@", "https://user:password@")
    ):
        return True
    return rule.name in {"assigned_secret", "environment_secret", "provider_secret"} and any(
        marker in value
        for marker in ("sk-private-value", "must-not-reach-child", "synthetic-secret")
    )


if __name__ == "__main__":
    raise SystemExit(main())
