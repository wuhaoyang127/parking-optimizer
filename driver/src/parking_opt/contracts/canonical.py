"""Canonical UTF-8 JSON encoding and SHA-256 hashing for v1 contracts."""

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any


def _reject_non_finite(value: Any, pointer: str = "") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite number is forbidden at {pointer or '/'}")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _reject_non_finite(child, f"{pointer}/{key}")
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            _reject_non_finite(child, f"{pointer}/{index}")


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a JSON value using the approved v1 canonical form."""

    _reject_non_finite(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    """Return the lowercase SHA-256 of canonical UTF-8 JSON."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def snapshot_content_sha256(snapshot: Mapping[str, Any]) -> str:
    """Hash a snapshot after removing its self-referential hash field."""

    content = dict(snapshot)
    content.pop("snapshot_content_sha256", None)
    return canonical_sha256(content)
