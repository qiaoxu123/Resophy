"""
Database connection pool for Resophy (MySQL 8.4+).

Provides:
- get_db()        -> connection from the Resophy pool
- get_flarum_db() -> connection from the Flarum pool (read-only, for auth)
- init_db(cfg)    -> initialize pools at startup
- close_db()      -> tear down pools on shutdown
"""

from __future__ import annotations

import contextlib
import os
import threading
from typing import Optional

import pymysql
from pymysql.cursors import DictCursor

from resophy.config import AppConfig, DatabaseConfig, FlarumConfig

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_pool_lock = threading.Lock()

_resophy_pool: Optional[_SimplePool] = None
_flarum_pool: Optional[_SimplePool] = None


class _SimplePool:
    """
    Lightweight connection pool wrapping PyMySQL.

    We keep it simple: a bounded list of idle connections protected by a lock.
    On acquire, pop from idle or create new (up to max_size).
    On release, push back to idle (or close if pool is full).
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        charset: str = "utf8mb4",
        max_size: int = 5,
    ):
        self._params = dict(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset=charset,
            cursorclass=DictCursor,
            autocommit=True,
        )
        self._max_size = max_size
        self._lock = threading.Lock()
        self._idle: list[pymysql.Connection] = []
        self._count = 0  # total connections created (idle + in-use)

    def _create_conn(self) -> pymysql.Connection:
        return pymysql.connect(**self._params)

    def acquire(self) -> pymysql.Connection:
        with self._lock:
            # Try reusing an idle connection
            while self._idle:
                conn = self._idle.pop()
                try:
                    conn.ping(reconnect=True)
                    return conn
                except Exception:
                    self._count -= 1
                    try:
                        conn.close()
                    except Exception:
                        pass

            # Create a new connection (allow exceeding max temporarily)
            self._count += 1

        conn = self._create_conn()
        return conn

    def release(self, conn: pymysql.Connection) -> None:
        with self._lock:
            if len(self._idle) < self._max_size:
                self._idle.append(conn)
                return
            self._count -= 1

        # Pool full, close excess connection
        try:
            conn.close()
        except Exception:
            pass

    def close_all(self) -> None:
        with self._lock:
            for conn in self._idle:
                try:
                    conn.close()
                except Exception:
                    pass
            self._idle.clear()
            self._count = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db(cfg: AppConfig) -> None:
    """Initialize connection pools. Call once at app startup."""
    global _resophy_pool, _flarum_pool

    with _pool_lock:
        db = cfg.db
        _resophy_pool = _SimplePool(
            host=db.host,
            port=db.port,
            user=db.user,
            password=db.password,
            database=db.name,
            charset=db.charset,
            max_size=db.pool_size,
        )

        fl = cfg.flarum
        if fl.db_user and fl.db_password:
            _flarum_pool = _SimplePool(
                host=fl.db_host,
                port=fl.db_port,
                user=fl.db_user,
                password=fl.db_password,
                database=fl.db_name,
                max_size=2,  # auth queries are infrequent
            )


def close_db() -> None:
    """Tear down all pools. Call on app shutdown."""
    global _resophy_pool, _flarum_pool

    with _pool_lock:
        if _resophy_pool:
            _resophy_pool.close_all()
            _resophy_pool = None
        if _flarum_pool:
            _flarum_pool.close_all()
            _flarum_pool = None


@contextlib.contextmanager
def get_db():
    """
    Context manager yielding a Resophy MySQL connection (DictCursor).

    Usage::

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM papers WHERE id=%s", (pid,))
                row = cur.fetchone()
    """
    if _resophy_pool is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    conn = _resophy_pool.acquire()
    try:
        yield conn
    finally:
        _resophy_pool.release(conn)


@contextlib.contextmanager
def get_flarum_db():
    """
    Context manager yielding a read-only Flarum MySQL connection.

    Used exclusively for user authentication lookups.
    """
    if _flarum_pool is None:
        raise RuntimeError("Flarum database not configured.")

    conn = _flarum_pool.acquire()
    try:
        yield conn
    finally:
        _flarum_pool.release(conn)


def ensure_schema() -> None:
    """
    Run deploy/init.sql against the Resophy database if tables don't exist yet.

    Safe to call on every startup -- CREATE TABLE IF NOT EXISTS is idempotent.
    """
    sql_path = os.path.join(os.path.dirname(__file__), "..", "deploy", "init.sql")
    sql_path = os.path.normpath(sql_path)

    if not os.path.exists(sql_path):
        print(f"[DB] Schema file not found: {sql_path}, skipping auto-migration.")
        return

    with open(sql_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # Split by ';' and execute each statement
    # Skip empty statements and USE / CREATE DATABASE (handled externally)
    with get_db() as conn:
        with conn.cursor() as cur:
            for statement in sql_content.split(";"):
                stmt = statement.strip()
                if not stmt:
                    continue
                # Skip database-level commands (handled by DBA / init script)
                upper = stmt.upper().lstrip()
                if upper.startswith("CREATE DATABASE") or upper.startswith("USE "):
                    continue
                try:
                    cur.execute(stmt)
                except Exception as e:
                    # Log but don't crash -- table may already exist
                    print(f"[DB] Schema statement warning: {e}")
        conn.commit()
    print("[DB] Schema check completed.")
