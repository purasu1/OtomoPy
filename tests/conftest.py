"""Shared fixtures for the OtomoPy test suite."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from otomopy.config import GuildConfig

GUILD_A = 974075087680569405
GUILD_B = 712730483183845397

CHANNEL_1 = 1011850325671546900
CHANNEL_2 = 1011850579573735504

YT_A = "UCp6993wxpyDPHUpavwDFqgg"
YT_B = "UCDqI2jOz0weumE8s7paEk6g"

# A callable that reconstructs the store over the same file; see the `reopen` fixture.
Reopen = Callable[[], GuildConfig]


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Path to a database file that does not exist yet."""
    return tmp_path / "otomopy.db"


@pytest.fixture
def config(db_path: Path) -> Iterator[GuildConfig]:
    """A GuildConfig backed by an empty temporary database."""
    store = GuildConfig(db_file=str(db_path))
    yield store
    store.close()


@pytest.fixture
def reopen(db_path: Path) -> Iterator[Reopen]:
    """Reconstruct a GuildConfig over the same file, to assert what was persisted.

    A real file rather than :memory: is deliberate: the highest-value assertion is
    that reopening rebuilds an identical index, which :memory: cannot express.
    """
    opened: list[GuildConfig] = []

    def _reopen() -> GuildConfig:
        store = GuildConfig(db_file=str(db_path))
        opened.append(store)
        return store

    yield _reopen
    for store in opened:
        store.close()
