from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

from .db import engine

VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_LIMIT = 200


def list_tables() -> list[str]:
    q = text(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(q).all()
    return [row[0] for row in rows]


def list_columns(table: str) -> list[dict[str, Any]]:
    _validate_table(table)
    q = text(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table
        ORDER BY ordinal_position
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(q, {"table": table}).mappings().all()
    return [dict(r) for r in rows]


def fetch_rows(table: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    _validate_table(table)
    lim = min(max(int(limit), 1), MAX_LIMIT)
    off = max(int(offset), 0)
    q = text(f"SELECT * FROM {table} LIMIT :lim OFFSET :off")
    with engine.connect() as conn:
        rows = conn.execute(q, {"lim": lim, "off": off}).mappings().all()
    return [dict(r) for r in rows]


def insert_row(table: str, data: dict[str, Any]) -> dict[str, Any]:
    _validate_table(table)
    _validate_columns(table, list(data.keys()))
    if not data:
        raise ValueError("data is required")
    cols = list(data.keys())
    placeholders = []
    params: dict[str, Any] = {}
    for col in cols:
        key = f"v_{col}"
        placeholders.append(f":{key}")
        params[key] = data[col]
    col_list = ", ".join(cols)
    placeholder_list = ", ".join(placeholders)
    q = text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholder_list}) RETURNING *")
    with engine.begin() as conn:
        row = conn.execute(q, params).mappings().first()
    return dict(row) if row else {}


def update_row(table: str, set_data: dict[str, Any], where: dict[str, Any]) -> list[dict[str, Any]]:
    _validate_table(table)
    if not set_data:
        raise ValueError("set is required")
    if not where:
        raise ValueError("where is required")
    _validate_columns(table, list(set_data.keys()) + list(where.keys()))

    set_clause = []
    params: dict[str, Any] = {}
    for col, value in set_data.items():
        key = f"s_{col}"
        set_clause.append(f"{col} = :{key}")
        params[key] = value

    where_clause, where_params = _build_where(where)
    params.update(where_params)

    q = text(f"UPDATE {table} SET {', '.join(set_clause)} WHERE {where_clause} RETURNING *")
    with engine.begin() as conn:
        rows = conn.execute(q, params).mappings().all()
    return [dict(r) for r in rows]


def delete_row(table: str, where: dict[str, Any]) -> list[dict[str, Any]]:
    _validate_table(table)
    if not where:
        raise ValueError("where is required")
    _validate_columns(table, list(where.keys()))

    where_clause, params = _build_where(where)
    q = text(f"DELETE FROM {table} WHERE {where_clause} RETURNING *")
    with engine.begin() as conn:
        rows = conn.execute(q, params).mappings().all()
    return [dict(r) for r in rows]


def _validate_table(table: str) -> None:
    if not VALID_NAME.match(table or ""):
        raise ValueError("invalid table name")
    q = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :table
        """
    )
    with engine.connect() as conn:
        row = conn.execute(q, {"table": table}).first()
    if not row:
        raise ValueError("table not found")


def _validate_columns(table: str, columns: list[str]) -> None:
    if not columns:
        return
    for col in columns:
        if not VALID_NAME.match(col or ""):
            raise ValueError("invalid column name")
    q = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(q, {"table": table}).all()
    allowed = {row[0] for row in rows}
    for col in columns:
        if col not in allowed:
            raise ValueError(f"unknown column: {col}")


def _build_where(where: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {}
    for col, value in where.items():
        key = f"w_{col}"
        clauses.append(f"{col} = :{key}")
        params[key] = value
    return " AND ".join(clauses), params
