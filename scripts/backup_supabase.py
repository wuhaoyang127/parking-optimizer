"""导出 Supabase public schema 全部业务表为 CSV 备份。

用法：py scripts/backup_supabase.py [--out DIR] [--batch N]
每张表一个 CSV（含表头）到 backups/<时间戳>/，并生成 manifest.json。
连接串：环境变量 DATABASE_URL 或 .streamlit/secrets.toml 的 [supabase] DATABASE_URL。
导出策略：优先 COPY；失败自动降级为按主键分页导出。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import datetime

from psycopg2 import sql

from supabase_conn import (NUMERIC_TYPES, ROOT, connect, list_tables,
                           load_database_url, pk_info)


def _copy_table(conn, table: str, path: str) -> dict:
    info = {"status": "ok", "rows": 0, "bytes": 0, "error": None}
    buf = io.StringIO()
    with conn.cursor() as cur:
        cur.copy_expert(
            f'COPY public."{table}" TO STDOUT WITH (FORMAT CSV, HEADER TRUE)',
            buf,
        )
    data = buf.getvalue()
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(data)
    info["rows"] = max(0, data.count("\n") - (1 if data else 0))
    info["bytes"] = len(data.encode("utf-8"))
    return info


def _paged_table(conn, table: str, path: str, batch: int) -> dict:
    """按主键分页导出，适配 Supabase 连接池对大表 COPY 不稳定的情况。"""
    info = {"status": "ok", "rows": 0, "bytes": 0, "error": None}
    pk_cols, pk_types = pk_info(conn, table)
    if not pk_cols:
        raise RuntimeError("表无主键，无法分页导出")

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = None
        count = 0
        with conn.cursor() as cur:
            select_sql = sql.SQL("SELECT * FROM public.{}").format(
                sql.Identifier(table)
            )

            if len(pk_cols) == 1:
                col = pk_cols[0]
                numeric = pk_types[0] in NUMERIC_TYPES
                order_sql = sql.SQL(" ORDER BY {}").format(sql.Identifier(col))
                limit_sql = sql.SQL(" LIMIT %s")
                if numeric:
                    cond_sql = sql.SQL(" WHERE {} > %s").format(sql.Identifier(col))
                else:
                    cond_sql = sql.SQL(" WHERE {}::text > %s").format(
                        sql.Identifier(col)
                    )

                last = None
                while True:
                    if last is None:
                        cur.execute(select_sql + order_sql + limit_sql, (batch,))
                    else:
                        cur.execute(
                            select_sql + cond_sql + order_sql + limit_sql,
                            (last, batch),
                        )
                    rows = cur.fetchall()
                    if writer is None:
                        writer = csv.writer(f)
                        writer.writerow([d[0] for d in cur.description])
                    if not rows:
                        break
                    col_idx = [d[0] for d in cur.description].index(col)
                    writer.writerows(rows)
                    count += len(rows)
                    last = rows[-1][col_idx]
                    if len(rows) < batch:
                        break
            else:
                # 复合主键：按全部主键列排序，用 OFFSET 分页（此类表通常很小）
                order_sql = sql.SQL(" ORDER BY {}").format(
                    sql.SQL(", ").join(sql.Identifier(c) for c in pk_cols)
                )
                offset = 0
                while True:
                    cur.execute(
                        select_sql + order_sql + sql.SQL(" OFFSET %s LIMIT %s"),
                        (offset, batch),
                    )
                    rows = cur.fetchall()
                    if writer is None:
                        writer = csv.writer(f)
                        writer.writerow([d[0] for d in cur.description])
                    if not rows:
                        break
                    writer.writerows(rows)
                    count += len(rows)
                    offset += len(rows)
                    if len(rows) < batch:
                        break

    info["rows"] = count
    info["bytes"] = os.path.getsize(path)
    return info


def _backup_table(url: str, table: str, out_dir: str, batch: int) -> dict:
    result = {"table": table, "status": "ok", "rows": 0, "bytes": 0,
              "method": "copy", "error": None}
    safe_name = re.sub(r"[^A-Za-z0-9_\-]", "_", table)
    path = os.path.join(out_dir, f"{safe_name}.csv")

    conn = connect(url)
    try:
        try:
            info = _copy_table(conn, table, path)
            result.update(info)
            return result
        except Exception:
            # COPY 失败会破坏当前连接状态，重建连接后降级为分页导出
            conn.close()
            if os.path.exists(path):
                os.remove(path)
            conn = connect(url)
            info = _paged_table(conn, table, path, batch)
            result.update(info)
            result["method"] = "paged"
            return result
    except Exception as exc:  # noqa: BLE001
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        if os.path.exists(path):
            os.remove(path)
        return result
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="备份 Supabase 数据库到本地 CSV")
    parser.add_argument("--out", help="输出目录（默认 backups/<时间戳>）")
    parser.add_argument("--batch", type=int, default=2000,
                        help="分页导出时每批行数（默认 2000）")
    args = parser.parse_args()

    url = load_database_url()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out or os.path.join(ROOT, "backups", f"backup_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    conn = connect(url)
    try:
        tables = list_tables(conn)
    finally:
        conn.close()

    print(f"共发现 {len(tables)} 张表，开始导出到 {out_dir} ...")

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "supabase public schema",
        "tables": [],
    }
    ok_count = 0
    for table in tables:
        info = _backup_table(url, table, out_dir, args.batch)
        manifest["tables"].append(info)
        mark = "OK " if info["status"] == "ok" else "FAIL"
        print(
            f"  [{mark}] {table:<40} {info['rows']:>8} 行 "
            f"{info['bytes']:>10} 字节  ({info['method']})"
        )
        if info["status"] == "ok":
            ok_count += 1
        else:
            print(f"         错误: {info['error']}")

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n完成：{ok_count}/{len(tables)} 张表导出成功 -> {out_dir}")
    return 0 if ok_count == len(tables) else 2


if __name__ == "__main__":
    sys.exit(main())
