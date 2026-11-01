"""Isolated training invoked by either Streamlit entry point."""
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def train_history(samples, params, source):
    root = Path(__file__).resolve().parents[2]
    if source not in ("synthetic", "observed"):
        raise ValueError("必须标注历史样本来源")
    payload = {"samples": samples, "params": params, "source": source,
               "trained_before": datetime.now(timezone.utc).isoformat()}
    result = subprocess.run([sys.executable, "-I", str(root / "driver_bridge/train_model.py")],
        input=json.dumps(payload, allow_nan=False).encode(), capture_output=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode or len(result.stdout) > 131072:
        raise ValueError("历史模型训练进程失败或输出过大")
    value = json.loads(result.stdout)
    if value.get("error"):
        raise ValueError(value["error"])
    return value["model"]
