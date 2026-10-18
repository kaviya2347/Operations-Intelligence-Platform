"""Database access (SQLAlchemy over SQLite).

The warehouse is a single SQLite file so the platform runs anywhere with no
server. Swapping DATABASE_URL for PostgreSQL works for every module except the
SQL lab's EXPLAIN QUERY PLAN helper.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from oip import config

_ENGINE: Engine | None = None


def engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        url = os.environ.get("DATABASE_URL", f"sqlite:///{config.DB_PATH}")
        _ENGINE = create_engine(url, future=True)
        if url.startswith("sqlite"):
            @event.listens_for(_ENGINE, "connect")
            def _pragmas(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.execute("PRAGMA temp_store=MEMORY")
                cur.close()
    return _ENGINE


def reset_engine():
    global _ENGINE
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None


def read_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine().connect() as con:
        return pd.read_sql(text(sql), con, params=params or {})


def execute(sql: str, params: dict | None = None) -> None:
    with engine().begin() as con:
        con.execute(text(sql), params or {})


def executescript(sql: str) -> None:
    """Run a multi-statement script (DDL, views)."""
    raw = engine().raw_connection()
    try:
        raw.driver_connection.executescript(sql)
        raw.commit()
    finally:
        raw.close()


def write(df: pd.DataFrame, table: str, if_exists: str = "replace", index: bool = False) -> int:
    with engine().begin() as con:
        df.to_sql(table, con, if_exists=if_exists, index=index, chunksize=50_000, method=None)
    return len(df)


@contextmanager
def readonly_connection():
    """Read-only SQLite connection for the SQL lab (cannot write even if a statement slips through)."""
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    try:
        yield con
    finally:
        con.close()
