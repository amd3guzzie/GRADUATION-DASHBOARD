import os
from typing import Any

import pymysql
import pymysql.cursors
from pymysql.constants import CLIENT
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
import streamlit as st

DB_ENV_VARS = {
    "host": "DASHBOARD_DB_HOST",
    "port": "DASHBOARD_DB_PORT",
    "user": "DASHBOARD_DB_USER",
    "password": "DASHBOARD_DB_PASSWORD",
    "database": "DASHBOARD_DB_NAME",
}

def db_settings(section: str = "mysql") -> dict[str, Any]:
    settings: dict[str, Any] = {}
    try:
        settings.update(dict(st.secrets[section]))
    except Exception:
        pass
    for key, env_name in DB_ENV_VARS.items():
        if os.environ.get(env_name):
            settings[key] = os.environ[env_name]
    missing = [key for key in ("host", "user", "password", "database") if not settings.get(key)]
    if missing:
        raise RuntimeError(
            "Database settings are missing: " + ", ".join(missing)
            + ". Set the DASHBOARD_DB_* environment variables or a [mysql] section in .streamlit/secrets.toml."
        )
    return settings

class PooledConnection:
    """Preserve the DictCursor interface while returning connections to a pool."""
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *args, **kwargs):
        if args or kwargs:
            return self._conn.cursor(*args, **kwargs)
        return self._conn.cursor(pymysql.cursors.DictCursor)

    def close(self):
        self._conn.close()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

@st.cache_resource(ttl=3600)
def get_db_engine():
    """Share a small connection pool so app reruns reuse established sessions."""
    db_cfg = db_settings("mysql")
    url = URL.create(
        "mysql+pymysql",
        username=db_cfg["user"],
        password=db_cfg["password"],
        host=db_cfg["host"],
        port=int(db_cfg.get("port") or 3306),
        database=db_cfg["database"],
    )
    return create_engine(
        url,
        pool_size=10,
        max_overflow=10,
        pool_timeout=10,
        pool_recycle=1800,
        pool_pre_ping=False,
        pool_reset_on_return=None,
        connect_args={
            "autocommit": True,
            "client_flag": CLIENT.MULTI_STATEMENTS,
        },
    )

def get_db_connection():
    """Check out a pooled MySQL connection using dictionary rows."""
    return PooledConnection(get_db_engine().raw_connection())

@st.cache_data(ttl=30, show_spinner=False)
def connection_check() -> tuple[bool, str]:
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT student_id FROM students LIMIT 1")
                cursor.fetchone()
        finally:
            conn.close()
        return True, "Connected (MySQL native tables)"
    except Exception as exc:
        return False, f"MySQL connection failed: {exc}"