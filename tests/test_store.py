"""Tests for the SQLite store internals: index consistency, migration, import.

These reach into private state on purpose -- the whole design rests on the
in-memory index staying in lockstep with the database, and that invariant is not
observable through the public API alone.
"""

import json
import random
import sqlite3

import pytest
from conftest import CHANNEL_1, CHANNEL_2, GUILD_A, GUILD_B, YT_A, YT_B

from otomopy import db
from otomopy.config import GuildConfig
from otomopy.migrate_json import CorruptConfigError, import_legacy_json


def _snapshot(store):
    """The complete index state, normalised for comparison."""
    return (
        {yt: sorted(targets) for yt, targets in store._relay_by_youtube.items()},
        {g: {yt: sorted(c) for yt, c in rel.items()} for g, rel in store._relay_by_guild.items()},
        {g: sorted(names) for g, names in store._blacklist.items()},
        dict(store._emotes),
    )


class TestIndexConsistency:
    def test_index_matches_db_after_scripted_ops(self, config, reopen):
        """The single most valuable test: drift in any mutator shows up here."""
        rng = random.Random(20260829)
        guilds = [GUILD_A, GUILD_B, 111222333444555666]
        youtube = [f"UC{i:022d}" for i in range(5)]
        discord = [900000000000000000 + i for i in range(4)]

        for _ in range(200):
            guild = rng.choice(guilds)
            match rng.randrange(4):
                case 0:
                    config.add_relay_channel(guild, rng.choice(discord), rng.choice(youtube))
                case 1:
                    config.remove_relay_channel(guild, rng.choice(discord), rng.choice(youtube))
                case 2:
                    config.add_blacklisted_user(guild, f"user{rng.randrange(5)}")
                case 3:
                    config.remove_blacklisted_user(guild, f"user{rng.randrange(5)}")

        assert _snapshot(config) == _snapshot(reopen())

    def test_empty_youtube_key_is_pruned_not_left_empty(self, config):
        """A lingering empty key leaks a Holodex subscription that is never closed."""
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        config.remove_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        assert YT_A not in config._relay_by_youtube
        assert GUILD_A not in config._relay_by_guild

    def test_removing_one_guild_leaves_the_other(self, config):
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        config.add_relay_channel(GUILD_B, CHANNEL_2, YT_A)
        config.remove_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        assert config.get_relay_targets(YT_A) == [(GUILD_B, CHANNEL_2)]


class TestRelayTargets:
    def test_single_channel(self, config):
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        config.add_relay_channel(GUILD_B, CHANNEL_2, YT_A)
        assert set(config.get_relay_targets(YT_A)) == {(GUILD_A, CHANNEL_1), (GUILD_B, CHANNEL_2)}

    def test_union_dedupes_shared_target(self, config):
        """on_vtuber_message unions two YouTube IDs that may share a Discord channel."""
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_B)
        assert config.get_relay_targets(YT_A, YT_B) == [(GUILD_A, CHANNEL_1)]

    def test_union_collects_both(self, config):
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        config.add_relay_channel(GUILD_A, CHANNEL_2, YT_B)
        assert set(config.get_relay_targets(YT_A, YT_B)) == {
            (GUILD_A, CHANNEL_1),
            (GUILD_A, CHANNEL_2),
        }

    def test_unknown_channel_is_empty(self, config):
        assert config.get_relay_targets("UCnope") == []

    def test_returns_a_copy(self, config):
        """bot.py awaits inside this loop; a concurrent /relay remove must not
        mutate the list being iterated."""
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        targets = config.get_relay_targets(YT_A)
        targets.append((GUILD_B, CHANNEL_2))
        assert config.get_relay_targets(YT_A) == [(GUILD_A, CHANNEL_1)]


class TestReadsDoNotWrite:
    def test_is_user_blacklisted_does_not_create_guild(self, config):
        """Regression: the old get_guild_config() rewrote the whole config file
        as a side effect of a blacklist lookup."""
        assert config.is_user_blacklisted(GUILD_A, "someone") is False
        assert config._conn.execute("SELECT count(*) FROM guild").fetchone()[0] == 0

    def test_read_helpers_do_not_create_guild(self, config):
        config.get_relay_channels(GUILD_A)
        config.get_blacklisted_users(GUILD_A)
        config.get_relay_targets(YT_A)
        assert config._conn.execute("SELECT count(*) FROM guild").fetchone()[0] == 0


class TestWriteFailure:
    def test_failed_write_leaves_index_unchanged(self, config, monkeypatch):
        """The DB commits before the index is touched, so a failed write cannot
        leave memory ahead of durable state."""
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        before = _snapshot(config)

        class FailingConn:
            """sqlite3.Connection.execute is read-only, so proxy the whole object."""

            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, *args, **kwargs):
                if "INSERT OR IGNORE INTO relay" in sql:
                    raise sqlite3.OperationalError("disk I/O error")
                return self._conn.execute(sql, *args, **kwargs)

            def __enter__(self):
                return self._conn.__enter__()

            def __exit__(self, *exc):
                return self._conn.__exit__(*exc)

        real_conn = config._conn
        monkeypatch.setattr(config, "_conn", FailingConn(real_conn))
        with pytest.raises(sqlite3.OperationalError):
            config.add_relay_channel(GUILD_B, CHANNEL_2, YT_B)

        monkeypatch.undo()
        assert _snapshot(config) == before
        # ...and the guild row inserted alongside it rolled back too.
        assert (
            real_conn.execute(
                "SELECT count(*) FROM guild WHERE guild_id = ?", (GUILD_B,)
            ).fetchone()[0]
            == 0
        )


class TestMigrations:
    def test_migrate_is_idempotent(self, db_path):
        conn = db.connect(db_path)
        assert db.migrate(conn) == db.LATEST_VERSION
        assert db.migrate(conn) == db.LATEST_VERSION
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.LATEST_VERSION
        conn.close()

    def test_snowflakes_survive_a_roundtrip(self, config, reopen):
        """Discord snowflakes exceed 2**53; they must not lose precision."""
        big_guild = 1234567890123456789
        big_channel = 9876543210987654321 % (2**63)
        config.add_relay_channel(big_guild, big_channel, YT_A)
        assert reopen().get_relay_targets(YT_A) == [(big_guild, big_channel)]


LEGACY = {
    "guilds": {
        str(GUILD_A): {
            "admin_roles": ["111", "222"],
            "relay_channels": {YT_A: [str(CHANNEL_1)], YT_B: [str(CHANNEL_1), str(CHANNEL_2)]},
            "tl_blacklist": ["カンザリンch /[kanzarin]"],
        },
        str(GUILD_B): {
            "admin_roles": [],
            # Deliberately overlaps GUILD_A on YT_A.
            "relay_channels": {YT_A: [str(CHANNEL_2)]},
            "tl_blacklist": [],
        },
    },
    "emotes": {"hololive": "<:holo:1>", "nijisanji": "<:niji:2>", "deepl": "<:deepl:3>"},
}


class TestLegacyImport:
    def _write(self, tmp_path, payload):
        path = tmp_path / "config.json"
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
        )
        return path

    def test_import_fidelity(self, tmp_path, db_path):
        json_path = self._write(tmp_path, LEGACY)
        store = GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path))

        assert store.get_relay_channels(GUILD_A) == {
            YT_A: [CHANNEL_1],
            YT_B: sorted([CHANNEL_1, CHANNEL_2]),
        }
        assert store.get_relay_channels(GUILD_B) == {YT_A: [CHANNEL_2]}
        assert store.get_all_youtube_channels() == {YT_A, YT_B}
        assert set(store.get_relay_targets(YT_A)) == {(GUILD_A, CHANNEL_1), (GUILD_B, CHANNEL_2)}
        assert store.is_user_blacklisted(GUILD_A, "カンザリンch /[kanzarin]") is True
        assert store.get_emote("Hololive") == "<:holo:1>"
        store.close()

    def test_admin_roles_are_not_stored(self, tmp_path, db_path):
        json_path = self._write(tmp_path, LEGACY)
        store = GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path))
        schema = " ".join(
            row[0] or "" for row in store._conn.execute("SELECT sql FROM sqlite_master")
        )
        assert "admin_role" not in schema
        store.close()

    def test_source_file_is_archived_not_deleted(self, tmp_path, db_path):
        json_path = self._write(tmp_path, LEGACY)
        store = GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path))
        store.close()

        assert not json_path.exists()
        archived = list(tmp_path.glob("config.json.migrated-*"))
        assert len(archived) == 1
        assert json.loads(archived[0].read_text(encoding="utf-8")) == LEGACY

    def test_import_runs_only_once(self, tmp_path, db_path):
        json_path = self._write(tmp_path, LEGACY)
        GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path)).close()
        # The archived file is gone from the original path, so a second start is
        # a no-op even before the row-count guard is consulted.
        store = GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path))
        assert store.get_all_youtube_channels() == {YT_A, YT_B}
        store.close()

    def test_malformed_entries_are_skipped_not_fatal(self, tmp_path, db_path):
        payload = {
            "guilds": {
                "notanint": {"relay_channels": {YT_A: [str(CHANNEL_1)]}},
                str(GUILD_A): {
                    "relay_channels": {
                        YT_A: "not-a-list",
                        YT_B: [str(CHANNEL_1), "abc"],
                    },
                    "tl_blacklist": ["ok", 42],
                },
            },
            "emotes": {"hololive": "<:holo:1>"},
        }
        json_path = self._write(tmp_path, payload)
        store = GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path))

        assert store.get_relay_channels(GUILD_A) == {YT_B: [CHANNEL_1]}
        assert store.get_blacklisted_users(GUILD_A) == ["ok"]
        assert store.get_emote("hololive") == "<:holo:1>"
        store.close()

    def test_corrupt_json_raises_and_preserves_the_file(self, tmp_path, db_path):
        """Modelled on the real truncated config.json.bak. Booting empty would
        look healthy while silently dropping every configured relay."""
        truncated = json.dumps(LEGACY)[: len(json.dumps(LEGACY)) // 2]
        json_path = self._write(tmp_path, truncated)

        with pytest.raises(CorruptConfigError):
            GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path))

        assert json_path.exists()
        assert list(tmp_path.glob("config.json.migrated-*")) == []

    def test_ignore_bad_config_escape_hatch(self, tmp_path, db_path, monkeypatch):
        json_path = self._write(tmp_path, "{ broken")
        monkeypatch.setenv("OTOMOPY_IGNORE_BAD_CONFIG", "1")

        store = GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path))
        assert store.get_all_youtube_channels() == set()
        assert json_path.exists()  # left in place as evidence
        store.close()

    def test_emote_case_collision_warns_and_keeps_one(self, tmp_path, db_path, caplog):
        json_path = self._write(
            tmp_path, {"guilds": {}, "emotes": {"DeepL": "<:a:1>", "deepl": "<:b:2>"}}
        )
        store = GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path))
        assert store.get_emote("deepl") in {"<:a:1>", "<:b:2>"}
        store.close()

    def test_report_counts(self, tmp_path, db_path):
        json_path = self._write(tmp_path, LEGACY)
        conn = db.connect(db_path)
        report = import_legacy_json(conn, json_path)
        assert (report.guilds, report.relays, report.blacklist, report.emotes) == (2, 4, 1, 3)
        assert report.admin_roles_discarded == 2
        assert report.skipped == []
        conn.close()


class TestStartupMatrix:
    """The four combinations of legacy JSON and database presence."""

    def test_neither_exists_creates_an_empty_database(self, tmp_path):
        db_path = tmp_path / "otomopy.db"
        store = GuildConfig(db_file=str(db_path), legacy_json_path=None)
        assert store.get_all_youtube_channels() == set()
        store.close()
        assert db_path.exists()

    def test_missing_legacy_path_is_not_an_error(self, tmp_path):
        store = GuildConfig(
            db_file=str(tmp_path / "otomopy.db"),
            legacy_json_path=str(tmp_path / "nonexistent.json"),
        )
        assert store.get_all_youtube_channels() == set()
        store.close()

    def test_legacy_only_is_imported(self, tmp_path):
        (tmp_path / "config.json").write_text(json.dumps(LEGACY), encoding="utf-8")
        store = GuildConfig(
            db_file=str(tmp_path / "otomopy.db"), legacy_json_path=str(tmp_path / "config.json")
        )
        assert store.get_all_youtube_channels() == {YT_A, YT_B}
        store.close()

    def test_populated_database_wins_and_legacy_is_left_alone(self, tmp_path):
        db_path = tmp_path / "otomopy.db"
        first = GuildConfig(db_file=str(db_path))
        first.add_relay_channel(GUILD_A, CHANNEL_1, "UConlyinthedb0000000000")
        first.close()

        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps(LEGACY), encoding="utf-8")

        second = GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path))
        assert second.get_all_youtube_channels() == {"UConlyinthedb0000000000"}
        second.close()
        assert json_path.exists()  # not imported, not archived

    def test_empty_database_still_imports(self, tmp_path):
        """A previous run that created the schema then crashed must not lose the JSON."""
        db_path = tmp_path / "otomopy.db"
        GuildConfig(db_file=str(db_path)).close()
        assert db_path.exists()

        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps(LEGACY), encoding="utf-8")
        store = GuildConfig(db_file=str(db_path), legacy_json_path=str(json_path))
        assert store.get_all_youtube_channels() == {YT_A, YT_B}
        store.close()
