"""本地计算结果大字段压缩：gzip + base64，减小 Supabase 回传体积。

compare_all 任务（尤其 1000 车 + 真实布局）的 events_by_strategy /
vehicles_by_strategy / main_events 可达 8MB+ JSON，worker 回传
complete_compute_task 时可能触发 Supabase 语句超时（57014，
statement_timeout=2min）。worker 回传前用 gzip+base64 打包这三个大字段，
网页载入本地计算结果时再解压；旧格式（无 _packed 标记）原样返回。
"""
import base64
import gzip
import json

_PACKED_MARK = "gzip_b64_v1"
_PACK_FIELDS = ("events_by_strategy", "vehicles_by_strategy", "main_events")


def _pack_one(value):
    if value is None:
        return None
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, 6)).decode("ascii")


def _unpack_one(value):
    if value is None:
        return None
    if isinstance(value, str):
        raw = gzip.decompress(base64.b64decode(value.encode("ascii")))
        return json.loads(raw.decode("utf-8"))
    return value


def compress_result(result: dict) -> dict:
    """把 result 的三个大字段替换为 gzip+base64 字符串（无副作用，返回新 dict）。"""
    if not isinstance(result, dict) or result.get("_packed"):
        return result
    out = dict(result)
    for key in _PACK_FIELDS:
        if key in out:
            out[key] = _pack_one(out[key])
    if any(key in out for key in _PACK_FIELDS):
        out["_packed"] = _PACKED_MARK
    return out


def decompress_result(result: dict) -> dict:
    """还原 compress_result 打包的字段；旧格式（无标记）原样返回。"""
    if not isinstance(result, dict) or result.get("_packed") != _PACKED_MARK:
        return result
    out = dict(result)
    for key in _PACK_FIELDS:
        if key in out:
            out[key] = _unpack_one(out[key])
    out.pop("_packed", None)
    return out
