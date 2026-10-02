from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ValidationError

from knowledge_agents.application.evaluation import (
    EvaluationAuthorization,
    EvaluationPlan,
    ExternalReadiness,
    RouteEvaluation,
    build_comparison_report,
    evaluate_preflight,
    render_public_report,
    require_evaluation_ready,
)
from knowledge_agents.domain.errors import DomainError

MAX_PRIVATE_MANIFEST_BYTES = 1024 * 1024


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a sanitized public comparison from private typed eval manifests."
    )
    parser.add_argument("--private-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    private_dir = arguments.private_dir.resolve()
    output = arguments.output.resolve()
    try:
        plan = _read_model(private_dir / "plan.json", EvaluationPlan)
        authorization = _read_model(private_dir / "authorization.json", EvaluationAuthorization)
        readiness = _read_model(private_dir / "external-readiness.json", ExternalReadiness)
        routes = (
            _read_model(private_dir / "notebooklm-route.json", RouteEvaluation),
            _read_model(private_dir / "web-article-route.json", RouteEvaluation),
        )
        preflight = evaluate_preflight(
            plan,
            authorization=authorization,
            readiness=readiness,
        )
        require_evaluation_ready(preflight)
        report = build_comparison_report(plan, routes)
        rendered = render_public_report(report)
        _write_atomic(output, rendered)
    except (DomainError, OSError, ValidationError, ValueError):
        print("evaluation report preflight failed", file=sys.stderr)
        return 2
    print("sanitized evaluation report written")
    return 0


def _read_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    if path.is_symlink() or not path.is_file():
        raise ValueError("private manifest must be a regular file")
    if path.stat().st_size > MAX_PRIVATE_MANIFEST_BYTES:
        raise ValueError("private manifest exceeds the size limit")
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
