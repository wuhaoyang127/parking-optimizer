"""Canonical JSON and content-hash behavior."""

from __future__ import annotations

import pytest
from conftest import minimal_snapshot

from parking_opt.contracts.canonical import (
    canonical_json_bytes,
    canonical_sha256,
    snapshot_content_sha256,
)


def test_canonical_hash_is_key_order_independent_and_preserves_unicode() -> None:
    left = {"中文": "车位", "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "中文": "车位"}

    assert canonical_sha256(left) == canonical_sha256(right)
    assert b"\xe8\xbd\xa6\xe4\xbd\x8d" in canonical_json_bytes(left)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json_bytes({"value": value})


def test_snapshot_hash_excludes_only_the_self_hash_field() -> None:
    snapshot = minimal_snapshot()
    original = snapshot["snapshot_content_sha256"]
    snapshot["snapshot_content_sha256"] = "f" * 64

    assert snapshot_content_sha256(snapshot) == original

    snapshot["decision_time_s"] = 1
    assert snapshot_content_sha256(snapshot) != original
