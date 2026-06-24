import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Iterator
from urllib.parse import quote_plus

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

DB_CONNECT_MAX_ATTEMPTS = 3
DB_CONNECT_RETRY_DELAY_SECONDS = 0.25
_pool_lock = Lock()
_connection_pool: ConnectionPool | None = None
_connection_pool_key: tuple[str, int, int, float] | None = None

@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    schema: str
    embedding_dimension: int

def build_database_url(settings: Settings | None = None) -> str:
    current_settings = settings or get_settings()

    if current_settings.database_url:
        return current_settings.database_url

    password = quote_plus(current_settings.database_password)

    return (
        f"postgresql://{current_settings.database_user}:{password}"
        f"@{current_settings.database_host}:{current_settings.database_port}"
        f"/{current_settings.database_name}"
        f"?sslmode={current_settings.database_ssl_mode}"
    )

def get_database_config(settings: Settings | None = None) -> DatabaseConfig:
    current_settings = settings or get_settings()

    return DatabaseConfig(
        url=build_database_url(current_settings),
        schema=current_settings.database_schema,
        embedding_dimension=current_settings.embedding_dimension,
    )

def database_is_configured(settings: Settings | None = None) -> bool:
    current_settings = settings or get_settings()

    return bool(
        current_settings.database_url
        or (
            current_settings.database_host
            and current_settings.database_name
            and current_settings.database_user
        )
    )

def _configure_connection(connection: psycopg.Connection) -> None:
    register_vector(connection)

def get_connection_pool(settings: Settings | None = None) -> ConnectionPool:
    current_settings = settings or get_settings()
    database_url = build_database_url(current_settings)
    min_size = max(current_settings.database_pool_min_size, 0)
    max_size = max(current_settings.database_pool_max_size, max(min_size, 1))
    timeout = max(current_settings.database_pool_timeout_seconds, 1.0)
    pool_key = (database_url, min_size, max_size, timeout)

    global _connection_pool, _connection_pool_key
    with _pool_lock:
        if _connection_pool is not None and _connection_pool_key == pool_key:
            return _connection_pool

        if _connection_pool is not None:
            _connection_pool.close()

        _connection_pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            configure=_configure_connection,
            open=True,
        )
        _connection_pool_key = pool_key

    return _connection_pool

def close_database_pool() -> None:
    global _connection_pool, _connection_pool_key
    with _pool_lock:
        if _connection_pool is not None:
            _connection_pool.close()
        _connection_pool = None
        _connection_pool_key = None

def warm_database_pool(settings: Settings | None = None) -> None:
    current_settings = settings or get_settings()
    if not current_settings.database_pool_enabled:
        return

    with database_connection(current_settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

def get_db_connection(settings: Settings | None = None) -> psycopg.Connection:
    current_settings = settings or get_settings()
    database_url = build_database_url(current_settings)
    last_error: psycopg.OperationalError | None = None

    for attempt in range(1, DB_CONNECT_MAX_ATTEMPTS + 1):
        try:
            connection = psycopg.connect(
                database_url,
                row_factory=dict_row,
                prepare_threshold=None,
            )
            register_vector(connection)
            return connection
        except psycopg.OperationalError as exc:
            last_error = exc
            if attempt == DB_CONNECT_MAX_ATTEMPTS:
                break

            logger.warning(
                "Database connection attempt %s/%s failed; retrying.",
                attempt,
                DB_CONNECT_MAX_ATTEMPTS,
            )
            time.sleep(DB_CONNECT_RETRY_DELAY_SECONDS * attempt)

    raise last_error or psycopg.OperationalError("Database connection failed.")

@contextmanager
def database_connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    current_settings = settings or get_settings()
    if current_settings.database_pool_enabled:
        pool = get_connection_pool(current_settings)
        with pool.connection() as connection:
            yield connection
        return

    connection = get_db_connection(settings)

    try:
        yield connection
    finally:
        connection.close()

def get_database_connection_placeholder() -> psycopg.Connection:
                                                                                      

    logger.debug("Using direct psycopg database connection helper.")
    return get_db_connection()
