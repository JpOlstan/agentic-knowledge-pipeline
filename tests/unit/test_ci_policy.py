from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SCANNER = ROOT / "scripts" / "secret_scan.py"


def load_scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("secret_scan_under_test", SCANNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_pytest_policy_excludes_live_and_eval() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = configuration["tool"]["pytest"]["ini_options"]["addopts"]

    assert '-m "not live and not eval"' in addopts


def test_ci_is_read_only_offline_and_pins_external_actions() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: read" in workflow
    assert "id-token: write" not in workflow
    assert "secrets." not in workflow
    assert "uv sync --locked --all-groups" in workflow
    assert 'pytest -m "not live and not eval" -q' in workflow
    assert "terraform init -backend=false -lockfile=readonly -input=false" in workflow
    assert "terraform validate -no-color" in workflow
    assert "scripts/secret_scan.py" in workflow
    action_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
    assert action_lines
    assert all("@" in line and len(line.split("@", 1)[1].split()[0]) == 40 for line in action_lines)


def test_repository_secret_scan_is_green() -> None:
    scanner = load_scanner()
    findings = scanner.scan_paths(scanner.repository_files(ROOT), root=ROOT)

    assert findings == ()


def test_known_secret_fails_without_echoing_its_value(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scanner = load_scanner()
    synthetic_secret = "AKIA" + "A" * 16
    candidate = tmp_path / "credential.txt"
    candidate.write_text(f"credential={synthetic_secret}\n", encoding="utf-8")

    findings = scanner.scan_paths((candidate,), root=tmp_path)
    rendered = scanner.format_findings(findings)

    assert [finding.rule for finding in findings] == ["aws_access_key"]
    assert synthetic_secret not in rendered
    assert rendered == "credential.txt:1: potential credential (aws_access_key)"
    assert scanner.main((str(candidate),)) == 1
    captured = capsys.readouterr()
    assert synthetic_secret not in captured.out


def test_documented_placeholders_do_not_fail_the_scanner(tmp_path: Path) -> None:
    scanner = load_scanner()
    example = tmp_path / ".env.example"
    example.write_text(
        "KA_OPENAI_API_KEY=<SET_LOCALLY>\nKA_LANGFUSE_SECRET_KEY=<SET_LOCALLY>\n",
        encoding="utf-8",
    )

    assert scanner.scan_paths((example,), root=tmp_path) == ()
