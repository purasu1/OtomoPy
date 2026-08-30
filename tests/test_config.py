"""Behavioural tests for the guild configuration store.

These are written against GuildConfig's *public API only* — never its internal
storage — so that they remain valid when the JSON backend is replaced by SQLite.
Discord channel IDs are normalised through `_ids()` because the store is free to
return them as either str or int.
"""

from conftest import CHANNEL_1, CHANNEL_2, GUILD_A, GUILD_B, YT_A, YT_B


def _ids(relay_channels):
    """Normalise {yt_id: [discord_id, ...]} to {yt_id: {int, ...}} for comparison."""
    return {yt: {int(c) for c in channels} for yt, channels in relay_channels.items()}


class TestRelayChannels:
    def test_add_returns_true_then_false(self, config):
        assert config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A) is True
        assert config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A) is False

    def test_add_persists_across_reopen(self, config, reopen):
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        assert _ids(reopen().get_relay_channels(GUILD_A)) == {YT_A: {CHANNEL_1}}

    def test_one_youtube_channel_to_many_discord_channels(self, config):
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        config.add_relay_channel(GUILD_A, CHANNEL_2, YT_A)
        assert _ids(config.get_relay_channels(GUILD_A)) == {YT_A: {CHANNEL_1, CHANNEL_2}}

    def test_filter_by_discord_channel(self, config):
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        config.add_relay_channel(GUILD_A, CHANNEL_2, YT_B)
        assert _ids(config.get_relay_channels(GUILD_A, CHANNEL_1)) == {YT_A: {CHANNEL_1}}
        assert _ids(config.get_relay_channels(GUILD_A, CHANNEL_2)) == {YT_B: {CHANNEL_2}}

    def test_remove_returns_false_when_absent(self, config):
        assert config.remove_relay_channel(GUILD_A, CHANNEL_1, YT_A) is False
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        assert config.remove_relay_channel(GUILD_A, CHANNEL_2, YT_A) is False

    def test_remove_prunes_youtube_key_when_last_target_goes(self, config):
        """The YouTube ID must disappear entirely, or Holodex keeps a dead subscription."""
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        assert config.remove_relay_channel(GUILD_A, CHANNEL_1, YT_A) is True
        assert config.get_relay_channels(GUILD_A) == {}
        assert config.get_all_youtube_channels() == set()

    def test_remove_keeps_youtube_key_while_targets_remain(self, config):
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        config.add_relay_channel(GUILD_A, CHANNEL_2, YT_A)
        config.remove_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        assert _ids(config.get_relay_channels(GUILD_A)) == {YT_A: {CHANNEL_2}}
        assert config.get_all_youtube_channels() == {YT_A}

    def test_guilds_are_isolated(self, config):
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        config.add_relay_channel(GUILD_B, CHANNEL_2, YT_B)
        assert _ids(config.get_relay_channels(GUILD_A)) == {YT_A: {CHANNEL_1}}
        assert _ids(config.get_relay_channels(GUILD_B)) == {YT_B: {CHANNEL_2}}

    def test_get_all_youtube_channels_unions_across_guilds(self, config):
        config.add_relay_channel(GUILD_A, CHANNEL_1, YT_A)
        config.add_relay_channel(GUILD_B, CHANNEL_2, YT_A)
        config.add_relay_channel(GUILD_B, CHANNEL_2, YT_B)
        assert config.get_all_youtube_channels() == {YT_A, YT_B}


class TestBlacklist:
    def test_add_returns_true_then_false(self, config):
        assert config.add_blacklisted_user(GUILD_A, "Translator") is True
        assert config.add_blacklisted_user(GUILD_A, "Translator") is False

    def test_roundtrip_across_reopen(self, config, reopen):
        config.add_blacklisted_user(GUILD_A, "カンザリンch")
        assert reopen().is_user_blacklisted(GUILD_A, "カンザリンch") is True

    def test_remove_returns_false_when_absent(self, config):
        """Regression: `return True` inside a `finally` made this always return True."""
        assert config.remove_blacklisted_user(GUILD_A, "never-added") is False

    def test_remove_returns_false_for_other_guilds_entry(self, config):
        config.add_blacklisted_user(GUILD_A, "Translator")
        assert config.remove_blacklisted_user(GUILD_B, "Translator") is False
        assert config.is_user_blacklisted(GUILD_A, "Translator") is True

    def test_remove_roundtrip(self, config, reopen):
        config.add_blacklisted_user(GUILD_A, "Translator")
        assert config.remove_blacklisted_user(GUILD_A, "Translator") is True
        assert reopen().is_user_blacklisted(GUILD_A, "Translator") is False

    def test_blacklist_is_per_guild(self, config):
        config.add_blacklisted_user(GUILD_A, "Translator")
        assert config.is_user_blacklisted(GUILD_B, "Translator") is False

    def test_get_blacklisted_users(self, config):
        config.add_blacklisted_user(GUILD_A, "Alice")
        config.add_blacklisted_user(GUILD_A, "Bob")
        assert set(config.get_blacklisted_users(GUILD_A)) == {"Alice", "Bob"}


class TestEmotes:
    def test_set_get_roundtrip(self, config, reopen):
        config.set_emote("Hololive", "<:holo:123>")
        assert reopen().get_emote("hololive") == "<:holo:123>"

    def test_lookup_is_case_insensitive(self, config):
        config.set_emote("DeepL", "<:deepl:1>")
        assert config.get_emote("deepl") == "<:deepl:1>"
        assert config.get_emote("DEEPL") == "<:deepl:1>"

    def test_get_missing_returns_default(self, config):
        assert config.get_emote("nope") is None
        assert config.get_emote("nope", "fallback") == "fallback"

    def test_unset_missing_returns_false(self, config):
        assert config.unset_emote("nope") is False

    def test_unset_roundtrip(self, config, reopen):
        config.set_emote("hololive", "<:holo:123>")
        assert config.unset_emote("hololive") is True
        assert reopen().get_emote("hololive") is None
