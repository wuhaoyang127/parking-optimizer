"""Bounded execution of a fixed, locally reviewed research entry point."""
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class ResearchRuntime:
    def __init__(self, root: Path, python: str | None = None):
        self.root = root.resolve()
        self.runner = self.root / "driver_bridge" / "runner.py"
        candidate = self.root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.python = python or (str(candidate) if candidate.is_file() else sys.executable)

    def _run(self, args, payload=None):
        result = subprocess.run(
            [self.python, "-I", str(self.runner), *args],
            input=None if payload is None else json.dumps(payload, allow_nan=False).encode(),
            capture_output=True, timeout=15.0, cwd=self.root,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise ValueError("RESEARCH_EXECUTION_FAILED")
        if len(result.stdout) > 262144:
            raise ValueError("RESEARCH_OUTPUT_TOO_LARGE")
        value = json.loads(result.stdout)
        if value.get("error"):
            raise ValueError(value["error"])
        return value

    def describe(self):
        return self._run(["--describe"])

    def check_release(self, release):
        return self._run(["--check-release"], release)

    def rank(self, payload, source_hash):
        if self.describe()["source_hash"] != source_hash:
            raise ValueError("RESEARCH_SOURCE_CHANGED")
        result = self._run([], payload)
        ids = result.get("space_ids")
        allowed = {c["space_id"] for c in payload["candidates"]}
        if (result.get("input_hash") != payload["input_hash"]
                or result.get("source_hash") != source_hash
                or not isinstance(ids, list) or any(not isinstance(i, str) for i in ids)
                or len(ids) != len(set(ids)) or set(ids) != allowed):
            raise ValueError("RESEARCH_INVALID_CANDIDATES")
        ranked = RankedCandidates(ids)
        ranked.evidence = result.get("evidence", {})
        return ranked


class RankedCandidates(list):
    """Ordered candidates with non-authoritative solver diagnostic evidence."""
