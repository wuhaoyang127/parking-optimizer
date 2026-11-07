# Web v2 契约

本目录是 `/api/v2` 的机器可读 JSON Schema。版本固定为 `2.0.0`；源模型位于
`src/parking_opt/api/models.py`，通过 `python scripts/export_web_v2_contracts.py` 可重复生成。

所有停车场内资源均使用 `parking_lot_id` 隔离；时间戳使用带时区 RFC 3339，耗时使用
`*_s`，距离使用 `*_m`。真实数据字段缺失时必须失败关闭，不得隐式换用模拟数据。

`openapi.json` 是固定 API 快照，通过 `python scripts/export_web_v2_openapi.py` 生成。
