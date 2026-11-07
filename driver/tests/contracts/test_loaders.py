"""UTF-8 JSON and JSONL reader diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest

from parking_opt.contracts.loaders import iter_jsonl, load_json


def test_json_loader_reads_utf8(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    path.write_text('{"note":"纵深车位"}', encoding="utf-8")

    assert load_json(path) == {"note": "纵深车位"}


def test_json_loader_reports_line_and_column(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{\n  "value":\n}', encoding="utf-8")

    with pytest.raises(ValueError, match=r"line 3, column 1"):
        load_json(path)


def test_jsonl_loader_reports_physical_line_number(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text('{"ok":1}\n\n{"broken":}\n', encoding="utf-8")

    iterator = iter_jsonl(path)
    assert next(iterator) == {"ok": 1}
    with pytest.raises(ValueError, match=r"line 3"):
        next(iterator)
