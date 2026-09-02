from __future__ import annotations
"""真实数据接口：车位状态快照 CSV 解析。"""

import csv
import io

from ._realtime_helpers import (_SPOT_COLUMN_ALIASES, _TRUE_VALUES, _FALSE_VALUES,
                                _first_match, _require)


def parse_spot_status_csv(text: str) -> dict[str, bool]:
    """解析车位状态快照 CSV → {spot_id: occupied}。

    必需列：车位编号、占用状态（1/0、true/false、占用/空闲 等均可）。
    """
    _require(isinstance(text, str) and text.strip(), "车位状态 CSV 内容为空")
    reader = csv.DictReader(io.StringIO(text))
    _require(reader.fieldnames, "车位状态 CSV 缺少表头")
    header = dict(zip(reader.fieldnames, reader.fieldnames))
    spot_col = _first_match(header, _SPOT_COLUMN_ALIASES, "spot_id")
    occ_col = _first_match(header, _SPOT_COLUMN_ALIASES, "occupied")
    _require(spot_col, "车位状态 CSV 缺少车位编号列（spot_id / 车位号）")
    _require(occ_col, "车位状态 CSV 缺少占用状态列（occupied / 状态）")

    result: dict[str, bool] = {}
    for i, row in enumerate(reader, start=2):
        label = f"第 {i} 行"
        sid = (row.get(spot_col) or "").strip()
        _require(bool(sid), f"{label} 车位编号为空")
        _require(sid not in result, f"{label} 车位编号 {sid!r} 重复")
        raw = (row.get(occ_col) or "").strip().lower()
        if raw in _TRUE_VALUES:
            result[sid] = True
        elif raw in _FALSE_VALUES:
            result[sid] = False
        else:
            raise ValueError(f"{label} 占用状态无法识别：{row.get(occ_col)!r}（支持 1/0、占用/空闲 等）")
    _require(bool(result), "车位状态 CSV 没有有效数据行")
    return result
