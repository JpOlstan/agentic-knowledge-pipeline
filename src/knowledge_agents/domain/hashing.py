from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Set
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _json_ready(value: Any, *, exclude: frozenset[str] = frozenset()) -> Any:
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude=exclude)
        schema_version = getattr(type(value), "schema_version", None)
        if schema_version is not None:
            payload = {"schema_version": schema_version, **payload}
        return _json_ready(payload)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value), exclude=exclude)
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item) for key, item in value.items() if str(key) not in exclude
        }
    if isinstance(value, tuple | list):
        return [_json_ready(item) for item in value]
    if isinstance(value, Set) and not isinstance(value, str | bytes):
        normalized = [_json_ready(item) for item in value]
        return sorted(normalized, key=lambda item: canonical_json(item))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def canonical_json(value: Any, *, exclude: set[str] | frozenset[str] = frozenset()) -> str:
    return json.dumps(
        _json_ready(value, exclude=frozenset(exclude)),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_sha256(value: Any, *, exclude: set[str] | frozenset[str] = frozenset()) -> str:
    payload = canonical_json(value, exclude=exclude).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hash_contract(contract: BaseModel) -> str:
    return canonical_sha256(contract)


def hash_draft(draft: BaseModel | Mapping[str, Any]) -> str:
    return canonical_sha256(draft, exclude={"content_hash"})
