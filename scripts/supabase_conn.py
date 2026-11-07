"""Supabase 连接与表结构探测（供 backup_supabase.py 复用）。"""
from __future__ import annotations

import os
import re

from psycopg2 import sql

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NUMERIC_TYPES = {
    "bigint", "integer", "smallint", "numeric", "real", "double precision",
}


def load_database_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DATABASE_URL")
    if url:
        return url.strip()
    secrets_path = os.path.join(ROOT, ".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        with open(secrets_path, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r'^DATABASE_URL\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            return m.group(1)
    raise SystemExit(
        "找不到 DATABASE_URL：请设置环境变量 DATABASE_URL，"
        "或确认 .streamlit/secrets.toml 中存在 [supabase] DATABASE_URL。"
    )


def connect(url: str):
    import psycopg2

    sep = "&" if "?" in url else "?"
    if "sslmode=" not in url:
        url = url + sep + "sslmode=require"
    conn = psycopg2.connect(url, connect_timeout=25)
    conn.autocommit = True
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180000'")
    return conn


def list_tables(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        )
        return [row[0] for row in cur.fetchall()]


def pk_info(conn, table: str):
    """返回 (主键列名列表, 对应 data_type 列表)。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.column_name, c.data_type
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.columns c
              ON c.table_schema = kcu.table_schema
             AND c.table_name = kcu.table_name
             AND c.column_name = kcu.column_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = %s
            ORDER BY kcu.ordinal_position
            """,
            (table,),
        )
        rows = cur.fetchall()
        cols = [r[0] for r in rows]
        types = [r[1] for r in rows]
        return cols, types
