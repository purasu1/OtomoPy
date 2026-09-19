"""Tests for when a stream is announced to Discord and when it is subscribed to.

The two decisions are deliberately independent. Chat subscription happens as soon as
Holodex lists a stream, however far out it is, so that no translation is missed.
Announcing waits until the stream is nearly starting -- schedules go up days ahead,
and a notification that far in advance is noise by the time the stream begins.
"""

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from otomopy.holodex import HolodexManager, StreamEvent

YT_CHANNEL = "UCp6993wxpyDPHUpavwDFqgg"


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Await `coro` from a sync test; the suite carries no async plugin."""
    return asyncio.run(coro)


def stream_item(
    video_id: str,
    status: str,
    starts_in: timedelta | None = None,
    *,
    members_only: bool = False,
) -> dict[str, Any]:
    """Build one entry of a Holodex /users/live response."""
    item: dict[str, Any] = {
        "id": video_id,
        "channel": {"id": YT_CHANNEL, "name": "Test Channel"},
        "title": f"Stream {video_id}",
        "status": status,
    }
    if starts_in is not None:
        start = datetime.now(UTC) + starts_in
        item["start_scheduled"] = start.isoformat().replace("+00:00", "Z")
    if members_only:
        item["topic_id"] = "membersonly"
    return item


class Harness:
    """A HolodexManager wired to a fake API and a fake WebSocket.

    `poll` drives one pass of the update loop and returns the streams announced
    during it, so each assertion reads as "this poll announced exactly this".
    """

    def __init__(self, cache_dir: Path):
        self.manager: HolodexManager = HolodexManager("test-key", cache_dir=str(cache_dir))
        self.manager.tracked_channels = {YT_CHANNEL}
        self.manager.stream_callback = self._record
        self.manager.ws_connected = True
        self.manager.ws = cast(Any, self)
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self._announced: list[StreamEvent] = []
        self.closed: bool = False

    async def _record(self, event: StreamEvent) -> None:
        self._announced.append(event)

    async def send_str(self, message: str) -> None:
        """Stand in for the Socket.IO connection, recording subscribe traffic."""
        video_id = message.split('"video_id":"')[1].split('"')[0]
        if message.startswith('42["subscribe"'):
            self.subscribed.append(video_id)
        elif message.startswith('42["unsubscribe"'):
            self.unsubscribed.append(video_id)

    def poll(self, *items: dict[str, Any]) -> list[str]:
        """Run one update pass over `items`; return the video IDs announced by it."""

        async def fake_get_live_streams(channel_ids: set[str]) -> list[dict[str, Any]] | None:
            return list(items) or None

        cast(Any, self.manager.api).get_live_streams = fake_get_live_streams
        update = self.manager._update_streams  # pyright: ignore[reportPrivateUsage]
        run(update(self.manager.tracked_channels))
        announced = [event.video_id for event in self._announced]
        self._announced.clear()
        return announced


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_first_poll_announces_nothing(harness: Harness):
    """Startup adopts whatever Holodex already lists rather than replaying it."""
    assert harness.poll(stream_item("aaa", "live"), stream_item("bbb", "upcoming")) == []


def test_stream_inside_window_at_startup_is_not_announced_later(harness: Harness):
    """The baseline poll records imminent streams so the next poll stays quiet."""
    imminent = stream_item("aaa", "upcoming", timedelta(minutes=10))
    harness.poll(imminent)

    assert harness.poll(imminent) == []


def test_distant_upcoming_stream_subscribes_but_does_not_announce(harness: Harness):
    """A stream days away is worth listening to, not worth notifying about."""
    harness.poll(stream_item("aaa", "live"))

    distant = stream_item("bbb", "upcoming", timedelta(days=3))
    assert harness.poll(distant) == []
    assert "bbb" in harness.subscribed


def test_upcoming_stream_announced_once_it_enters_the_window(harness: Harness):
    """The announcement fires on a later poll, with the stream itself unchanged.

    Widening the lead time stands in for the clock advancing toward a fixed start
    time: what matters is that an unchanged stream is announced on a later pass.
    """
    harness.poll(stream_item("aaa", "live"))

    distant = stream_item("bbb", "upcoming", timedelta(hours=3))
    assert harness.poll(distant) == []

    harness.manager.announce_lead_time = timedelta(hours=4)
    assert harness.poll(distant) == ["bbb"]


def test_upcoming_stream_announced_only_once(harness: Harness):
    """An upcoming stream stays upcoming for many polls; it is announced on one."""
    harness.poll(stream_item("aaa", "live"))

    imminent = stream_item("bbb", "upcoming", timedelta(minutes=30))
    assert harness.poll(imminent) == ["bbb"]
    assert harness.poll(imminent) == []
    assert harness.poll(imminent) == []


def test_going_live_is_announced_even_if_upcoming_never_was(harness: Harness):
    """A stream that appears days out and then starts still gets one notification."""
    harness.poll(stream_item("aaa", "live"))

    assert harness.poll(stream_item("bbb", "upcoming", timedelta(days=3))) == []
    assert harness.poll(stream_item("bbb", "live")) == ["bbb"]


def test_upcoming_without_start_time_is_announced_immediately(harness: Harness):
    """With no start time, nothing will later tell us the stream has drawn near."""
    harness.poll(stream_item("aaa", "live"))

    assert harness.poll(stream_item("bbb", "upcoming")) == ["bbb"]


def test_members_only_stream_is_not_subscribed_to(harness: Harness):
    harness.poll(stream_item("aaa", "live"))

    harness.poll(stream_item("bbb", "upcoming", timedelta(minutes=30), members_only=True))
    assert "bbb" not in harness.subscribed


def test_announced_streams_are_forgotten_once_delisted(harness: Harness):
    """The announced set tracks live data, so it cannot grow without bound."""
    harness.poll(stream_item("aaa", "live"))
    harness.poll(stream_item("bbb", "upcoming", timedelta(minutes=30)))
    assert harness.manager.announced_upcoming == {"bbb"}

    harness.poll(stream_item("aaa", "live"))
    assert harness.manager.announced_upcoming == set()


def test_restart_does_not_resend_the_upcoming_notification(tmp_path: Path):
    """A bot restart inside the announce window must not re-announce the stream.

    `announced_upcoming` lives only in memory, so the restarted process has no
    record of the notification it already sent. The baseline poll is what protects
    against a duplicate: it marks the stream announced without announcing it.
    """
    imminent = stream_item("bbb", "upcoming", timedelta(minutes=30))

    before = Harness(tmp_path)
    before.poll(stream_item("aaa", "live"))
    assert before.poll(imminent) == ["bbb"]

    # Restart: a brand new manager, carrying nothing over.
    after = Harness(tmp_path)
    assert after.manager.announced_upcoming == set()
    assert after.poll(imminent) == []
    assert after.manager.announced_upcoming == {"bbb"}
    assert after.poll(imminent) == []

    # The stream going live is still announced by the restarted bot.
    assert after.poll(stream_item("bbb", "live")) == ["bbb"]
