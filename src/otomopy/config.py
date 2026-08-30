"""
Configuration management for OtomoPy.

SQLite is the durability layer; an in-memory index is the read layer. Every read
is served from dicts and never touches SQL, because the message relay paths in
:mod:`otomopy.bot` run per inbound Holodex event and must not scale with the
number of guilds the bot is installed in.

Mutations write to SQLite first and update the index only after the commit
succeeds, so a failed write can never leave memory ahead of durable state. The
``bool`` returned by each mutator comes from ``cursor.rowcount`` -- the database,
not the index, decides whether anything actually changed.

Writes are synchronous by design: a single-row insert plus commit measures around
0.013 ms even with 150k relay rows, which is far below anything that would matter
on the event loop.
"""

import logging
from pathlib import Path

from otomopy import db
from otomopy.migrate_json import import_and_archive

logger = logging.getLogger(__name__)


class GuildConfig:
    """Manages guild configuration data."""

    def __init__(self, db_file: str | Path, legacy_json_path: str | Path | None = None):
        """Open the database, import any legacy JSON config, and build the index.

        Args:
            db_file: Path to the SQLite database.
            legacy_json_path: Optional path to a pre-SQLite ``config.json`` to
                import if the database is empty.
        """
        self.db_file = str(db_file)
        self._conn = db.connect(db_file)

        if legacy_json_path and not db.has_data(self._conn):
            import_and_archive(self._conn, legacy_json_path)

        # yt_channel_id -> [(guild_id, discord_channel_id)]
        self._relay_by_youtube: dict[str, list[tuple[int, int]]] = {}
        # guild_id -> yt_channel_id -> {discord_channel_id}
        self._relay_by_guild: dict[int, dict[str, set[int]]] = {}
        self._blacklist: dict[int, set[str]] = {}
        self._emotes: dict[str, str] = {}
        self._load_index()

    # ------------------------------------------------------------------
    # Index construction and maintenance
    # ------------------------------------------------------------------

    def _load_index(self):
        """Populate the in-memory index from the database."""
        for guild_id, youtube_id, discord_id in self._conn.execute(
            "SELECT guild_id, youtube_channel_id, discord_channel_id FROM relay"
            " ORDER BY guild_id, youtube_channel_id"
        ):
            self._index_add_relay(guild_id, youtube_id, discord_id)

        for guild_id, user_name in self._conn.execute(
            "SELECT guild_id, user_name FROM tl_blacklist"
        ):
            self._blacklist.setdefault(guild_id, set()).add(user_name)

        self._emotes = dict(self._conn.execute("SELECT name, emote FROM emote"))

        logger.info(
            f"Loaded configuration for {len(self._relay_by_guild)} guilds, "
            f"{len(self._relay_by_youtube)} tracked YouTube channels"
        )

    def _index_add_relay(self, guild_id: int, youtube_id: str, discord_id: int):
        self._relay_by_youtube.setdefault(youtube_id, []).append((guild_id, discord_id))
        self._relay_by_guild.setdefault(guild_id, {}).setdefault(youtube_id, set()).add(discord_id)

    def _index_remove_relay(self, guild_id: int, youtube_id: str, discord_id: int):
        targets = self._relay_by_youtube.get(youtube_id)
        if targets is not None:
            # Rebuild rather than mutate: callers hold copies, but keeping this
            # symmetric with the pruning below keeps the invariant obvious.
            remaining = [t for t in targets if t != (guild_id, discord_id)]
            if remaining:
                self._relay_by_youtube[youtube_id] = remaining
            else:
                # The key must disappear entirely, not linger as an empty list --
                # get_all_youtube_channels() feeds Holodex subscriptions, and a
                # stale key means a subscription that is never cleaned up.
                del self._relay_by_youtube[youtube_id]

        guild_relays = self._relay_by_guild.get(guild_id)
        if guild_relays is not None:
            channels = guild_relays.get(youtube_id)
            if channels is not None:
                channels.discard(discord_id)
                if not channels:
                    del guild_relays[youtube_id]
            if not guild_relays:
                del self._relay_by_guild[guild_id]

    def _ensure_guild(self, guild_id: int):
        """Create the guild row. Only ever called from mutating paths.

        Read methods must never create rows -- the previous implementation wrote
        the entire config file as a side effect of a blacklist lookup.
        """
        self._conn.execute("INSERT OR IGNORE INTO guild(guild_id) VALUES (?)", (guild_id,))

    def close(self):
        """Checkpoint the write-ahead log and close the database."""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            self._conn.close()

    # ------------------------------------------------------------------
    # Relay channels
    # ------------------------------------------------------------------

    def get_relay_targets(self, *youtube_channel_ids: str) -> list[tuple[int, int]]:
        """Get every relay target for the given YouTube channels.

        Args:
            *youtube_channel_ids: One or more YouTube channel IDs.

        Returns:
            list: Deduplicated (guild_id, discord_channel_id) pairs. Always a
            fresh list -- callers await between iterations, and a concurrent
            /relay remove must not mutate what they are iterating over.
        """
        if len(youtube_channel_ids) == 1:
            return list(self._relay_by_youtube.get(youtube_channel_ids[0], ()))

        seen: dict[tuple[int, int], None] = {}
        for youtube_id in youtube_channel_ids:
            for target in self._relay_by_youtube.get(youtube_id, ()):
                seen[target] = None
        return list(seen)

    def add_relay_channel(
        self, guild_id: int, discord_channel_id: int, youtube_channel_id: str
    ) -> bool:
        """Add a YouTube channel to relay to a Discord channel.

        Args:
            guild_id: The Discord guild ID
            discord_channel_id: The Discord channel ID to relay to
            youtube_channel_id: The YouTube channel ID to relay from

        Returns:
            bool: True if the channel was added, False if it was already configured

        Raises:
            sqlite3.Error: If the change could not be persisted.
        """
        with self._conn:
            self._ensure_guild(guild_id)
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO relay(guild_id, youtube_channel_id, discord_channel_id)"
                " VALUES (?, ?, ?)",
                (guild_id, youtube_channel_id, discord_channel_id),
            )
            added = cursor.rowcount == 1

        if added:
            self._index_add_relay(guild_id, youtube_channel_id, discord_channel_id)
        return added

    def remove_relay_channel(
        self, guild_id: int, discord_channel_id: int, youtube_channel_id: str
    ) -> bool:
        """Remove a YouTube channel relay from a Discord channel.

        Args:
            guild_id: The Discord guild ID
            discord_channel_id: The Discord channel ID to stop relaying to
            youtube_channel_id: The YouTube channel ID to stop relaying from

        Returns:
            bool: True if the channel was removed, False if it wasn't configured

        Raises:
            sqlite3.Error: If the change could not be persisted.
        """
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM relay WHERE guild_id = ? AND youtube_channel_id = ?"
                " AND discord_channel_id = ?",
                (guild_id, youtube_channel_id, discord_channel_id),
            )
            removed = cursor.rowcount == 1

        if removed:
            self._index_remove_relay(guild_id, youtube_channel_id, discord_channel_id)
        return removed

    def get_relay_channels(
        self, guild_id: int, discord_channel_id: int | None = None
    ) -> dict[str, list[int]]:
        """Get all relay channel configurations for a guild or a specific Discord channel.

        Args:
            guild_id: The Discord guild ID
            discord_channel_id: Optional Discord channel ID to filter by

        Returns:
            dict: Dictionary mapping YouTube channel IDs to lists of Discord channel IDs
        """
        guild_relays = self._relay_by_guild.get(guild_id, {})

        if discord_channel_id is None:
            return {youtube_id: sorted(channels) for youtube_id, channels in guild_relays.items()}

        return {
            youtube_id: sorted(channels)
            for youtube_id, channels in guild_relays.items()
            if discord_channel_id in channels
        }

    def get_all_youtube_channels(self) -> set:
        """Get all YouTube channel IDs that are being relayed across all guilds.

        Returns:
            set: Set of all YouTube channel IDs
        """
        return set(self._relay_by_youtube)

    # ------------------------------------------------------------------
    # Translation blacklist
    # ------------------------------------------------------------------

    def add_blacklisted_user(self, guild_id: int, user_name: str) -> bool:
        """Add a user to the translation blacklist for a guild.

        Args:
            guild_id: The Discord guild ID
            user_name: The user to blacklist

        Returns:
            bool: True if the user was added, False if they were already blacklisted

        Raises:
            sqlite3.Error: If the change could not be persisted.
        """
        with self._conn:
            self._ensure_guild(guild_id)
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO tl_blacklist(guild_id, user_name) VALUES (?, ?)",
                (guild_id, user_name),
            )
            added = cursor.rowcount == 1

        if added:
            self._blacklist.setdefault(guild_id, set()).add(user_name)
        return added

    def remove_blacklisted_user(self, guild_id: int, user_name: str) -> bool:
        """Remove a user from the translation blacklist for a guild.

        Args:
            guild_id: The Discord guild ID
            user_name: The user to remove from blacklist

        Returns:
            bool: True if the user was removed, False if they weren't blacklisted

        Raises:
            sqlite3.Error: If the change could not be persisted.
        """
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM tl_blacklist WHERE guild_id = ? AND user_name = ?",
                (guild_id, user_name),
            )
            removed = cursor.rowcount == 1

        if removed:
            blacklist = self._blacklist.get(guild_id)
            if blacklist is not None:
                blacklist.discard(user_name)
                if not blacklist:
                    del self._blacklist[guild_id]
        return removed

    def is_user_blacklisted(self, guild_id: int, user_name: str) -> bool:
        """Check if a user is blacklisted for translations in a guild.

        Args:
            guild_id: The Discord guild ID
            user_name: The user to check

        Returns:
            bool: True if the user is blacklisted, False otherwise
        """
        return user_name in self._blacklist.get(guild_id, ())

    def get_blacklisted_users(self, guild_id: int) -> list:
        """Get all blacklisted users for a guild.

        Args:
            guild_id: The Discord guild ID

        Returns:
            list: Sorted list of blacklisted user names
        """
        return sorted(self._blacklist.get(guild_id, ()))

    # ------------------------------------------------------------------
    # Emotes (global, not per-guild)
    # ------------------------------------------------------------------

    def get_emote(self, name: str, default: str | None = None) -> str | None:
        """Get emote by name.

        Args:
            name: The name (e.g. VTuber org) to fetch an emote for
            default: Value to return when no emote is configured

        Returns:
            str: The emote markdown, if configured
        """
        return self._emotes.get(name.lower(), default)

    def set_emote(self, name: str, emote: str) -> bool:
        """Set emote by name.

        Args:
            name: The name (e.g. VTuber org) to set an emote for
            emote: The emote markdown to set

        Returns:
            bool: True if the emote was set

        Raises:
            sqlite3.Error: If the change could not be persisted.
        """
        key = name.lower()
        with self._conn:
            self._conn.execute(
                "INSERT INTO emote(name, emote) VALUES (?, ?)"
                " ON CONFLICT(name) DO UPDATE SET"
                " emote = excluded.emote,"
                " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (key, emote),
            )

        self._emotes[key] = emote
        return True

    def unset_emote(self, name: str) -> bool:
        """Unset emote by name.

        Args:
            name: The name (e.g. VTuber org) to remove the emote for

        Returns:
            bool: True if the emote was unset, False if it was not set

        Raises:
            sqlite3.Error: If the change could not be persisted.
        """
        key = name.lower()
        with self._conn:
            cursor = self._conn.execute("DELETE FROM emote WHERE name = ?", (key,))
            removed = cursor.rowcount == 1

        if removed:
            self._emotes.pop(key, None)
        return removed
