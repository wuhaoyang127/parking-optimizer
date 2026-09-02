from __future__ import annotations
"""真实数据接口预留：道闸流水 / 车位状态 解析与转换。

设计目标（企业合作预留）：
  1. 定义版本化的真实数据字段规范（见 docs/data/03_真实数据接口规范_v1.md）；
  2. 把停车场常见导出格式（CSV：车牌识别 + 道闸进出时间）转换为
     内部需求序列（Vehicle 列表），直接复用现有仿真与评估流程；
  3. 支持车牌脱敏（企业数据合规）。

本模块只做「只读解析」，不控制任何真实设备；数据源可以是 CSV 文件，
也可以是后续接入的 HTTP/WebSocket 接口（同一字段规范）。
"""

from ._gate_io import (parse_gate_csv, gate_records_to_vehicles,  # noqa: F401
                       gate_csv_to_demand_json)
from ._spot_io import parse_spot_status_csv  # noqa: F401
from ._realtime_helpers import (_GATE_COLUMN_ALIASES, _SPOT_COLUMN_ALIASES,  # noqa: F401
                                _TRUE_VALUES, _FALSE_VALUES, _first_match,
                                _require, _parse_time, _anonymize_plate,
                                _is_finite_nonneg)
