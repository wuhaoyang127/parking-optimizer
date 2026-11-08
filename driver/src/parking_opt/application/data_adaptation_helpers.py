"""Validation and mapping helpers for anonymous data adaptation."""
from __future__ import annotations
import hashlib
import json
from collections import deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from parking_opt.application.data_adaptation_types import (
    _EMAIL,
    _PHONE,
    _PII_KEYS,
    _PLATE,
    DataQualityCheck,
)
def _check(stage, status, code, message, artifact=None, *, json_pointer=None, fix_hint=None) -> DataQualityCheck:
    return DataQualityCheck(stage=stage, status=status, code=code, artifact=artifact, message=message, json_pointer=json_pointer, fix_hint=fix_hint)
def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeError as exc:
        raise ValueError("source artifact is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON at line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return cast(dict[str, Any], value)
def _read_jsonl(path: Path, max_records: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                if len(records) >= max_records:
                    raise OverflowError("record limit exceeded")
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at line {line_number}, column {exc.colno}") from exc
                if not isinstance(value, dict):
                    raise ValueError(f"JSONL line {line_number} must be an object")
                records.append(cast(dict[str, Any], value))
    except UnicodeError as exc:
        raise ValueError("source artifact is not valid UTF-8") from exc
    return records
def _pii_key(key: object) -> bool:
    text = str(key).casefold()
    return text != "anonymous_vehicle_id" and text in _PII_KEYS
def _contains_pii(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_pii_key(key) or _contains_pii(child) for key, child in value.items())
    if isinstance(value, list | tuple):
        return any(_contains_pii(child) for child in value)
    if isinstance(value, str):
        return bool(_EMAIL.search(value) or _PHONE.search(value) or _PLATE.search(value))
    return False
def _mapping_references_pii(mapping: Mapping[str, Any]) -> bool:
    for section_name in ("layout", "events"):
        section = mapping.get(section_name)
        if not isinstance(section, Mapping): continue
        fields = section.get("fields")
        if not isinstance(fields, list): continue
        for item in fields:
            if not isinstance(item, Mapping): continue
            source = item.get("source")
            if isinstance(source, str) and any(_pii_key(part.replace("~1", "/").replace("~0", "~")) for part in source.split("/")[1:]): return True
    return False
def _pointer_parts(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/") or pointer == "/": raise ValueError("JSON Pointer must identify a non-root object field")
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/"))
def _pointer_get(source: Mapping[str, Any], pointer: str) -> Any:
    value: Any = source
    for part in _pointer_parts(pointer):
        if not isinstance(value, Mapping) or part not in value: raise KeyError(pointer)
        value = value[part]
    return deepcopy(value)
def _pointer_set(target: dict[str, Any], pointer: str, value: Any) -> None:
    parts = _pointer_parts(pointer)
    current = target
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict): raise ValueError("mapping targets overlap")
        current = child
    if parts[-1] in current: raise ValueError("mapping target is duplicated")
    current[parts[-1]] = deepcopy(value)
def _mapping_section(source: Mapping[str, Any], section: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    if set(section) != {"constants", "fields"}: raise ValueError("mapping section must contain only constants and fields")
    constants = section["constants"]
    fields = section["fields"]
    if not isinstance(constants, Mapping) or not isinstance(fields, list): raise ValueError("mapping constants/fields have invalid types")
    target: dict[str, Any] = {}
    for pointer, value in constants.items():
        if not isinstance(pointer, str): raise ValueError("constant target must be a JSON Pointer")
        _pointer_set(target, pointer, value)
    count = len(constants)
    for item in fields:
        if not isinstance(item, Mapping) or set(item) != {"source", "target"}: raise ValueError("each field mapping requires source and target")
        source_pointer = item["source"]
        target_pointer = item["target"]
        if not isinstance(source_pointer, str) or not isinstance(target_pointer, str): raise ValueError("field mappings must use JSON Pointer strings")
        _pointer_set(target, target_pointer, _pointer_get(source, source_pointer))
        count += 1
    return target, count
def _top_level_sources(section: Mapping[str, Any]) -> set[str]:
    fields = cast(Sequence[Mapping[str, Any]], section["fields"])
    return {
        _pointer_parts(cast(str, item["source"]))[0]
        for item in fields
        if isinstance(item.get("source"), str)
    }
def _reachable(starts: set[str], adjacency: Mapping[str, set[str]]) -> set[str]:
    seen = set(starts)
    queue = deque(starts)
    while queue:
        node = queue.popleft()
        for neighbor in adjacency.get(node, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen
def _validate_reachability(layout: Mapping[str, Any]) -> None:
    nodes = cast(Sequence[Mapping[str, Any]], layout["road_nodes"])
    entrances = {cast(str, item["road_node_id"]) for item in nodes if item["node_kind"] == "entrance"}
    exits = {cast(str, item["road_node_id"]) for item in nodes if item["node_kind"] == "exit"}
    if not entrances or not exits: raise ValueError("layout must provide at least one entrance and one exit")
    adjacency: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
    for edge in cast(Sequence[Mapping[str, Any]], layout["road_edges"]):
        origin = cast(str, edge["from_node_id"])
        destination = cast(str, edge["to_node_id"])
        adjacency.setdefault(origin, set()).add(destination)
        reverse.setdefault(destination, set()).add(origin)
        if edge["directed"] is False:
            adjacency.setdefault(destination, set()).add(origin)
            reverse.setdefault(origin, set()).add(destination)
    from_entrance = _reachable(entrances, adjacency)
    to_exit = _reachable(exits, reverse)
    access_nodes = {
        cast(str, item["access_node_id"])
        for collection in ("slots", "buffer_slots")
        for item in cast(Sequence[Mapping[str, Any]], layout[collection])
    }
    if access_nodes - from_entrance or access_nodes - to_exit: raise ValueError("one or more parking positions are not entrance-to-exit reachable")
def _aware_iso8601(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None
def _validate_events(events: Sequence[Mapping[str, Any]], layout: Mapping[str, Any]) -> None:
    event_ids = [item["event_id"] for item in events]
    sequences = [item["sequence_no"] for item in events]
    if len(event_ids) != len(set(event_ids)) or len(sequences) != len(set(sequences)): raise ValueError("event IDs and sequence numbers must be unique")
    if sequences != list(range(1, len(events) + 1)): raise ValueError("event sequence numbers must be contiguous from one")
    sim_times = [item["sim_time_s"] for item in events]
    if sim_times != sorted(sim_times): raise ValueError("event simulation times must be nondecreasing")
    if any(not _aware_iso8601(item["recorded_at"]) for item in events): raise ValueError("event recorded_at values must be timezone-aware ISO 8601")
    positions = {item["position_id"] for collection in ("slots", "buffer_slots") for item in cast(Sequence[Mapping[str, Any]], layout[collection])}
    nodes = {item["road_node_id"]: item["node_kind"] for item in cast(Sequence[Mapping[str, Any]], layout["road_nodes"])}
    zones = {
        item["channel_zone_id"]
        for item in cast(Sequence[Mapping[str, Any]], layout["channel_zones"])
    }
    for event in events:
        actions: list[Mapping[str, Any]] = []
        action = event.get("action")
        if isinstance(action, Mapping):
            actions.append(action)
        payload = cast(Mapping[str, Any], event.get("payload") or {})
        extra_actions = payload.get("transaction_actions")
        if isinstance(extra_actions, list): actions.extend(item for item in extra_actions if isinstance(item, Mapping))
        for item in actions:
            for key in ("origin_position_id", "destination_position_id"):
                if item.get(key) is not None and item[key] not in positions: raise ValueError("event action references an unknown parking position")
            if item.get("destination_exit_id") is not None and nodes.get(item["destination_exit_id"]) != "exit": raise ValueError("event action references an unknown exit")
            if set(cast(Sequence[str], item["channel_zone_ids"])) - zones: raise ValueError("event action references an unknown channel zone")
        pending = payload.get("pending_request")
        if isinstance(pending, Mapping) and pending.get("entrance_node_id") is not None and nodes.get(pending["entrance_node_id"]) != "entrance": raise ValueError("arrival request references an unknown entrance")
        confirmed = payload.get("confirmed_location_state")
        if isinstance(confirmed, Mapping) and confirmed.get("position_id") is not None and confirmed["position_id"] not in positions: raise ValueError("position reconciliation references an unknown position")
