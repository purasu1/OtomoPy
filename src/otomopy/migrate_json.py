"""One-shot import of the legacy ``config.json`` into the SQLite database.

Runs at most once, guarded by the database being empty. On success the JSON file
is renamed aside (never deleted) so the original remains recoverable.

Can also be run standalone to rehearse the import against a scratch database::

    python -m otomopy.migrate_json ./config.json ./scratch.db
"""

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Set to bypass the hard failure on unparseable JSON and start with an empty
# database instead. Deliberately awkward: booting empty looks healthy while
# silently dropping every configured relay.
IGNORE_BAD_CONFIG_ENV = "OTOMOPY_IGNORE_BAD_CONFIG"


@dataclass
class ImportReport:
    """Counts from a legacy import, for logging and tests."""

    guilds: int = 0
    relays: int = 0
    blacklist: int = 0
    emotes: int = 0
    skipped: list[str] = field(default_factory=list)
    admin_roles_discarded: int = 0

    def summary(self) -> str:
        return (
            f"{self.guilds} guilds, {self.relays} relays, "
            f"{self.blacklist} blacklist entries, {self.emotes} emotes; "
            f"{len(self.skipped)} malformed entries skipped, "
            f"{self.admin_roles_discarded} unused admin_roles discarded"
        )


class CorruptConfigError(RuntimeError):
    """The legacy config file exists but could not be parsed."""


def _load_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise CorruptConfigError(
            f"{path} is not valid JSON ({e}). Repair it, or move it aside to "
            f"start with an empty database. Set {IGNORE_BAD_CONFIG_ENV}=1 to "
            f"start empty without moving it."
        ) from e
    if not isinstance(data, dict):
        raise CorruptConfigError(f"{path} does not contain a JSON object.")
    return data


def import_legacy_json(conn: sqlite3.Connection, path: str | Path) -> ImportReport:
    """Import ``path`` into ``conn`` in a single transaction.

    Malformed individual entries are skipped and counted rather than aborting the
    whole import; only an unparseable file is fatal.
    """
    path = Path(path)
    report = ImportReport()
    data = _load_json(path)

    guilds = data.get("guilds") or {}
    if not isinstance(guilds, dict):
        report.skipped.append("'guilds' is not an object; no guilds imported")
        guilds = {}

    with conn:
        for raw_guild_id, guild_config in guilds.items():
            try:
                guild_id = int(raw_guild_id)
            except (TypeError, ValueError):
                report.skipped.append(f"guild key {raw_guild_id!r} is not an integer")
                continue
            if not isinstance(guild_config, dict):
                report.skipped.append(f"guild {guild_id} value is not an object")
                continue

            conn.execute("INSERT OR IGNORE INTO guild(guild_id) VALUES (?)", (guild_id,))
            report.guilds += 1

            # admin_roles is written by the old code but read nowhere; permissions
            # are enforced by discord's default_permissions. Dropped on purpose.
            admin_roles = guild_config.get("admin_roles") or []
            if isinstance(admin_roles, list) and admin_roles:
                report.admin_roles_discarded += len(admin_roles)
                logger.warning(
                    f"Guild {guild_id}: discarding {len(admin_roles)} admin_roles "
                    f"entries; permissions are enforced by Discord command permissions."
                )

            report.relays += _import_relays(conn, guild_id, guild_config, report)
            report.blacklist += _import_blacklist(conn, guild_id, guild_config, report)

        report.emotes = _import_emotes(conn, data, report)

    logger.info(f"Imported {path}: {report.summary()}")
    return report


def _import_relays(conn, guild_id: int, guild_config: dict, report: ImportReport) -> int:
    relay_channels = guild_config.get("relay_channels") or {}
    if not isinstance(relay_channels, dict):
        report.skipped.append(f"guild {guild_id}: relay_channels is not an object")
        return 0

    count = 0
    for youtube_id, discord_ids in relay_channels.items():
        if not isinstance(youtube_id, str) or not youtube_id:
            report.skipped.append(f"guild {guild_id}: bad YouTube channel id {youtube_id!r}")
            continue
        if not isinstance(discord_ids, list):
            report.skipped.append(f"guild {guild_id}: targets for {youtube_id} are not a list")
            continue
        for raw in discord_ids:
            try:
                discord_id = int(raw)
            except (TypeError, ValueError):
                report.skipped.append(
                    f"guild {guild_id}: bad Discord channel id {raw!r} for {youtube_id}"
                )
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO relay(guild_id, youtube_channel_id, discord_channel_id)"
                " VALUES (?, ?, ?)",
                (guild_id, youtube_id, discord_id),
            )
            count += cur.rowcount
    return count


def _import_blacklist(conn, guild_id: int, guild_config: dict, report: ImportReport) -> int:
    blacklist = guild_config.get("tl_blacklist") or []
    if not isinstance(blacklist, list):
        report.skipped.append(f"guild {guild_id}: tl_blacklist is not a list")
        return 0

    count = 0
    for user_name in blacklist:
        if not isinstance(user_name, str) or not user_name:
            report.skipped.append(f"guild {guild_id}: bad blacklist entry {user_name!r}")
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO tl_blacklist(guild_id, user_name) VALUES (?, ?)",
            (guild_id, user_name),
        )
        count += cur.rowcount
    return count


def _import_emotes(conn, data: dict, report: ImportReport) -> int:
    emotes = data.get("emotes") or {}
    if not isinstance(emotes, dict):
        report.skipped.append("'emotes' is not an object")
        return 0

    seen: dict[str, str] = {}
    for name, emote in emotes.items():
        if not isinstance(name, str) or not isinstance(emote, str):
            report.skipped.append(f"bad emote entry {name!r}")
            continue
        key = name.lower()
        if key in seen and seen[key] != emote:
            # get_emote/set_emote already lowercase, so this should not happen in
            # practice -- but a silent drop would surface much later as bot.py
            # quietly falling back to plain text.
            logger.warning(f"Emote name collision on {key!r}: {seen[key]!r} replaced by {emote!r}")
        seen[key] = emote
        conn.execute("INSERT OR REPLACE INTO emote(name, emote) VALUES (?, ?)", (key, emote))
    return len(seen)


def import_and_archive(conn: sqlite3.Connection, path: str | Path) -> ImportReport | None:
    """Import ``path`` if it exists, then rename it aside.

    Returns None if there was nothing to import. Raises :class:`CorruptConfigError`
    unless the escape-hatch environment variable is set.
    """
    path = Path(path)
    if not path.exists():
        return None

    try:
        report = import_legacy_json(conn, path)
    except CorruptConfigError:
        if os.environ.get(IGNORE_BAD_CONFIG_ENV):
            logger.error(
                f"{path} is unparseable; {IGNORE_BAD_CONFIG_ENV} is set, so "
                f"starting with an empty database. The file is left in place."
            )
            return None
        raise

    conn.execute("PRAGMA wal_checkpoint(FULL)")
    archived = path.with_name(f"{path.name}.migrated-{time.strftime('%Y%m%d%H%M%S')}")
    os.replace(path, archived)
    logger.info(f"Legacy config archived as {archived}")
    return report


def main() -> int:
    import sys

    from otomopy import db

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <config.json> <target.db>", file=sys.stderr)
        return 2

    conn = db.connect(sys.argv[2])
    report = import_legacy_json(conn, sys.argv[1])
    print(report.summary())
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
