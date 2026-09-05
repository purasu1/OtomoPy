"""Tests for webhook lookup.

Webhooks are keyed on the channel's immutable ID, so that renaming a channel --
which happens whenever the emoji for the active members change -- does not make
the bot create a second webhook alongside the one it already owns.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any, cast

import discord
import pytest

from otomopy.webhook_manager import WebhookManager, webhook_name

GUILD_ID = 974075087680569405
CHANNEL_ID = 1011850325671546900


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Await `coro` from a sync test; the suite carries no async plugin."""
    return asyncio.run(coro)


class FakeWebhook:
    """A webhook that records the names it has been given."""

    def __init__(self, name: str):
        self.name: str = name

    async def edit(self, *, name: str, **_: object) -> "FakeWebhook":
        self.name = name
        return self

    async def fetch(self) -> "FakeWebhook":
        return self


class FakeChannel:
    """A text channel holding a fixed list of webhooks."""

    def __init__(self, name: str, webhooks: list[FakeWebhook] | None = None):
        self.id: int = CHANNEL_ID
        self.name: str = name
        self.guild: Any = type("FakeGuild", (), {"id": GUILD_ID, "name": "Guild"})()
        self._webhooks: list[FakeWebhook] = webhooks or []
        self.created: list[str] = []

    async def webhooks(self) -> list[FakeWebhook]:
        return list(self._webhooks)

    async def create_webhook(self, *, name: str, **_: object) -> FakeWebhook:
        self.created.append(name)
        webhook = FakeWebhook(name)
        self._webhooks.append(webhook)
        return webhook


def as_channel(channel: FakeChannel) -> discord.TextChannel:
    """Present a `FakeChannel` as the channel type the manager is annotated for."""
    return cast(discord.TextChannel, cast(object, channel))


@pytest.fixture
def manager() -> WebhookManager:
    return WebhookManager()


def test_name_is_keyed_on_channel_id(manager: WebhookManager) -> None:
    """A fresh channel gets a webhook named after its ID, not its name."""
    channel = FakeChannel("general")

    webhook = run(manager.get_or_create_webhook(as_channel(channel)))

    assert webhook is not None
    assert webhook.name == f"OtomoPy - {CHANNEL_ID}"
    assert channel.created == [f"OtomoPy - {CHANNEL_ID}"]


def test_renaming_the_channel_reuses_the_webhook(manager: WebhookManager) -> None:
    """The webhook survives a channel rename instead of being duplicated."""
    channel = FakeChannel("general")
    first = run(manager.get_or_create_webhook(as_channel(channel)))

    # A new manager stands in for a restart, so the lookup goes back to Discord.
    channel.name = "general-\U0001f430"
    second = run(WebhookManager().get_or_create_webhook(as_channel(channel)))

    assert second is first
    assert channel.created == [f"OtomoPy - {CHANNEL_ID}"]


def test_legacy_webhook_is_adopted_and_renamed(manager: WebhookManager) -> None:
    """A webhook from the old guild/channel-name scheme is reused, not duplicated."""
    legacy = FakeWebhook("OtomoPy - Guild - general")
    channel = FakeChannel("general-\U0001f430", [legacy])

    webhook = run(manager.get_or_create_webhook(as_channel(channel)))

    assert cast(object, webhook) is legacy
    assert legacy.name == f"OtomoPy - {CHANNEL_ID}"
    assert channel.created == []


def test_foreign_webhooks_are_left_alone(manager: WebhookManager) -> None:
    """Webhooks belonging to other integrations are neither adopted nor renamed."""
    other = FakeWebhook("Some Other Bot")
    channel = FakeChannel("general", [other])

    webhook = run(manager.get_or_create_webhook(as_channel(channel)))

    assert other.name == "Some Other Bot"
    assert webhook is not None
    assert webhook.name == webhook_name(as_channel(channel))
