"""Tests for .env resolution.

python-dotenv resolves relative to the calling source file by default, which
made the bot ignore a .env in the working directory in favour of one beside a
development checkout -- i.e. silently running with the wrong credentials.
"""

# The autouse fixture is registered by its decorator, never called by name.
# pyright: reportUnusedFunction=false

import os
import re
from pathlib import Path

import pytest

from otomopy.bot import DotEnvConfig

ENV = "DISCORD_TOKEN=t\nOWNER_ID=1\nCONFIG_FILE=./config.json\nHOLODEX_API_KEY=k\n"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTOMOPY_ENV_FILE", raising=False)


def test_prefers_the_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(ENV)
    monkeypatch.chdir(tmp_path)
    assert DotEnvConfig.find_env_file() == str(tmp_path / ".env")


def test_walks_up_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running from a subdirectory of a checkout must still find its .env."""
    (tmp_path / ".env").write_text(ENV)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert DotEnvConfig.find_env_file() == str(tmp_path / ".env")


def test_does_not_fall_back_to_the_source_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repository checkout holds a real .env; an unrelated cwd must not use it."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    found = DotEnvConfig.find_env_file()
    if found is not None:
        # tmp_path may sit under a directory that legitimately has its own .env,
        # but it must never be the one shipped with the source tree.
        source_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        assert not found.startswith(source_root)


def test_explicit_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(ENV)
    chosen = tmp_path / "other.env"
    chosen.write_text(ENV)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OTOMOPY_ENV_FILE", str(chosen))
    assert DotEnvConfig.find_env_file() == str(chosen)


def test_explicit_override_must_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OTOMOPY_ENV_FILE", str(tmp_path / "nope.env"))
    with pytest.raises(RuntimeError, match="does not exist"):
        DotEnvConfig.find_env_file()


def test_load_env_reads_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "DISCORD_TOKEN=scratch-token\nOWNER_ID=7\nCONFIG_FILE=./config.json\nHOLODEX_API_KEY=k\n"
    )
    monkeypatch.chdir(tmp_path)
    for key in ("DISCORD_TOKEN", "OWNER_ID", "CONFIG_FILE", "HOLODEX_API_KEY", "DB_FILE"):
        monkeypatch.delenv(key, raising=False)

    config = DotEnvConfig.load_env()
    assert config.token == "scratch-token"
    assert config.owner_id == 7
    assert config.db_file == str((tmp_path / "otomopy.db").resolve())


class TestPathResolution:
    """CONFIG_FILE and DB_FILE are both optional.

    DB_FILE defaults to otomopy.db in the working directory. CONFIG_FILE names
    the deprecated JSON config; when it exists and the database does not, it is
    imported and archived.
    """

    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Deliberately omits CONFIG_FILE and DB_FILE so the defaults are exercised.
        (tmp_path / ".env").write_text("DISCORD_TOKEN=t\nOWNER_ID=1\nHOLODEX_API_KEY=k\n")
        monkeypatch.chdir(tmp_path)
        for key in ("DISCORD_TOKEN", "OWNER_ID", "CONFIG_FILE", "DB_FILE", "HOLODEX_API_KEY"):
            monkeypatch.delenv(key, raising=False)

    def test_both_unset_defaults_to_cwd(self, tmp_path: Path) -> None:
        config = DotEnvConfig.load_env()
        assert config.config_file is None
        assert config.db_file == str((tmp_path / "otomopy.db").resolve())

    def test_db_file_is_resolved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB_FILE", "state/bot.db")
        assert DotEnvConfig.load_env().db_file == str((tmp_path / "state" / "bot.db").resolve())

    def test_config_file_is_resolved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONFIG_FILE", "config.json")
        assert DotEnvConfig.load_env().config_file == str((tmp_path / "config.json").resolve())

    def test_db_file_does_not_follow_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DB_FILE defaults to the working directory, not next to CONFIG_FILE."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.setenv("CONFIG_FILE", str(elsewhere / "config.json"))
        assert DotEnvConfig.load_env().db_file == str((tmp_path / "otomopy.db").resolve())

    def test_warns_about_an_unreferenced_config_json(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "config.json").write_text("{}")
        with caplog.at_level("WARNING"):
            assert DotEnvConfig.load_env().config_file is None
        assert "CONFIG_FILE is not set" in caplog.text

    def test_no_warning_once_the_database_exists(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "otomopy.db").write_bytes(b"")
        with caplog.at_level("WARNING"):
            DotEnvConfig.load_env()
        assert "CONFIG_FILE is not set" not in caplog.text


class TestMissingSettingDiagnostics:
    """A missing required setting must say whether a .env was found at all."""

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in ("DISCORD_TOKEN", "OWNER_ID", "CONFIG_FILE", "DB_FILE", "HOLODEX_API_KEY"):
            monkeypatch.delenv(key, raising=False)

    def test_no_env_file_found_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(DotEnvConfig, "find_env_file", staticmethod(lambda: None))
        with pytest.raises(
            RuntimeError, match=re.escape("no .env file was found searching upwards")
        ):
            DotEnvConfig.load_env()

    def test_env_file_found_but_incomplete_names_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = tmp_path / ".env"
        env.write_text("DISCORD_TOKEN=t\n")  # OWNER_ID missing
        monkeypatch.chdir(tmp_path)
        with pytest.raises(
            RuntimeError, match=re.escape(f"OWNER_ID is not set. Please add it to {env}")
        ):
            DotEnvConfig.load_env()

    def test_holodex_key_is_still_required(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".env").write_text("DISCORD_TOKEN=t\nOWNER_ID=1\n")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(RuntimeError, match=re.escape("HOLODEX_API_KEY is not set")):
            DotEnvConfig.load_env()

    def test_non_integer_owner_id_still_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".env").write_text("DISCORD_TOKEN=t\nOWNER_ID=abc\nHOLODEX_API_KEY=k\n")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="Invalid owner ID"):
            DotEnvConfig.load_env()
