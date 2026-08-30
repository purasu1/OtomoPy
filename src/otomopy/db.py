"""SQLite connection, schema, and migration runner for OtomoPy.

The database is the durability layer only. Reads are served from the in-memory
index maintained by :class:`otomopy.config.GuildConfig`; nothing on the message
hot path touches SQL.

Single connection, owned by ``GuildConfig``, used exclusively from the event loop
thread. ``check_same_thread`` is deliberately left at its default so that any
future attempt to call in from a worker thread fails loudly rather than
corrupting state.
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# STRICT tables require SQLite 3.37. They matter here because the previous JSON
# store stringified every ID: STRICT turns an int/str snowflake mixup into an
# immediate IntegrityError rather than a row that silently never matches.
MIN_SQLITE_VERSION = (3, 37, 0)

SCHEMA_V1: tuple[str, ...] = (
    """
    CREATE TABLE guild (
        guild_id   INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    ) STRICT
    """,
    """
    CREATE TABLE relay (
        guild_id           INTEGER NOT NULL REFERENCES guild(guild_id) ON DELETE CASCADE,
        youtube_channel_id TEXT    NOT NULL,
        discord_channel_id INTEGER NOT NULL,
        created_at         TEXT    NOT NULL
                           DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        PRIMARY KEY (guild_id, youtube_channel_id, discord_channel_id)
    ) STRICT, WITHOUT ROWID
    """,
    "CREATE INDEX relay_by_youtube ON relay(youtube_channel_id)",
    """
    CREATE TABLE tl_blacklist (
        guild_id   INTEGER NOT NULL REFERENCES guild(guild_id) ON DELETE CASCADE,
        user_name  TEXT    NOT NULL,
        created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        PRIMARY KEY (guild_id, user_name)
    ) STRICT, WITHOUT ROWID
    """,
    """
    CREATE TABLE emote (
        name       TEXT PRIMARY KEY,
        emote      TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    ) STRICT, WITHOUT ROWID
    """,
)

# (version, statements). Each migration is a tuple of individual statements
# rather than one script: sqlite3.Connection.executescript() issues an implicit
# COMMIT, which would silently break the enclosing transaction and could leave
# DDL applied with user_version unbumped.
MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (1, SCHEMA_V1),
]

LATEST_VERSION = MIGRATIONS[-1][0]


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the database, apply pragmas, and run any pending migrations."""
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise RuntimeError(
            f"OtomoPy needs SQLite >= {'.'.join(map(str, MIN_SQLITE_VERSION))} "
            f"for STRICT tables, but this Python is linked against "
            f"{sqlite3.sqlite_version}. Upgrade SQLite or your Python build."
        )

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)

    # journal_mode returns the mode actually adopted; WAL is unavailable on some
    # network and container filesystems, so fall back to durable rollback mode.
    mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if mode.lower() != "wal":
        logger.warning(
            f"Could not enable WAL on {path} (journal_mode={mode}); "
            f"using synchronous=FULL instead. This is expected on NFS "
            f"and some container mounts."
        )
        conn.execute("PRAGMA synchronous = FULL")
    else:
        conn.execute("PRAGMA synchronous = NORMAL")

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")

    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the resulting schema version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, statements in MIGRATIONS:
        if version <= current:
            continue
        logger.info(f"Applying database migration {version}")
        with conn:  # BEGIN ... COMMIT, or ROLLBACK on any exception
            for statement in statements:
                conn.execute(statement)
            # PRAGMA cannot be parameterised; version is an int literal from
            # MIGRATIONS, never user input.
            conn.execute(f"PRAGMA user_version = {version:d}")
        current = version
    return current


def has_data(conn: sqlite3.Connection) -> bool:
    """True if the database holds any guild or emote rows.

    Tests for *empty* rather than *missing* so that a first run which created the
    schema and then crashed before importing still gets its import.
    """
    row = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM guild) OR EXISTS(SELECT 1 FROM emote)"
    ).fetchone()
    return bool(row[0])
