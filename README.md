# OtomoPy

A Discord bot that integrates with the Holodex API to relay VTuber stream notifications and chat messages to Discord channels.

## Features

- **Live Stream Monitoring**: Automatically detects when VTubers go live using the Holodex API
- **Stream Notifications**: Posts notifications in configured Discord channels when streams start
- **Chat Relay**: Relays live chat messages from YouTube streams to Discord channels
- **Channel Management**: Add/remove YouTube channels to monitor per Discord server
- **Translation Blacklist**: Filter out specific translators or chat messages
- **Permission System**: Role-based access control for bot commands
- **Multi-Server Support**: Configure different settings for each Discord server

## Requirements

- Python 3.11 or higher
- Discord Bot Token
- Holodex API Key
- Discord server with appropriate permissions

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd OtomoPy
```

2. Install dependencies:
```bash
pip install -e .
```

3. Create a `.env` file in the project root with the following variables:
```env
DISCORD_TOKEN=your_discord_bot_token_here
OWNER_ID=your_discord_user_id_here
CONFIG_FILE=config.json
HOLODEX_API_KEY=your_holodex_api_key_here
```

## Configuration

### Discord Bot Setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application and bot
3. Copy the bot token to your `.env` file

### Holodex API Key

1. Visit [Holodex](https://holodex.net/)
2. Sign up for an account
3. Click your profile icon in the top right corner and select "Account Settings"
4. Scroll down and click on "GET NEW API KEY"
5. Add the API key to your `.env` file

### Server Configuration

The bot uses a `config.json` file to store per-server settings:

```json
{
  "guild_id": {
    "admin_roles": ["role_id_1", "role_id_2"],
    "relay_channels": {
      "youtube_channel_id": ["discord_channel_id"]
    },
    "tl_blacklist": ["translator_name"]
  }
}
```

This config file is automatically managed by the bot. You do not need to edit it manually.

## Usage

### Running the Bot

```bash
python -m otomopy
```

Or using the installed script:

```bash
otomopy
```

### Slash Commands

#### `/relay <channel_id>`
Add a YouTube channel to monitor for the current Discord channel.
- Auto-completes channel names
- Requires guild admin privileges

#### `/unrelay <channel_id>`
Remove a YouTube channel from monitoring for the current Discord channel.
- Auto-completes channel names
- Requires admin privileges

#### `/relays`
List all configured channel relays for the current Discord channel.

#### `/blacklist_translator <username>`
Add a translator to the blacklist for the current guild.
- Requires admin privileges

#### `/unblacklist_translator <username>`
Remove a translator from the blacklist for the current guild.
- Requires admin privileges

#### `/list_blacklisted`
Show all blacklisted translators for the current guild.

#### `/add_admin_role <role_id>`
Add an admin role to the current guild.
- Requires admin privileges

#### `/remove_admin_role <role_id>`
Remove an admin role from the current guild.
- Requires admin privileges

#### `/shutdown`
Shut down the bot.
- Requires owner privileges

## How It Works

1. **Channel Monitoring**: The bot continuously polls the Holodex API for live streams from configured YouTube channels
2. **Stream Detection**: When a stream starts, the bot posts a notification in the configured Discord channels
3. **Chat Relay**: For live streams, the bot fetches chat messages and relays them to Discord, filtering out blacklisted translators
4. **Permission Control**: Commands are restricted based on configured admin roles per server

## Project Structure

```
OtomoPy/
├── src/otomopy/
│   ├── bot.py              # Main bot client and event handlers
│   ├── holodex.py          # Holodex API integration
│   ├── config.py           # Configuration management
│   ├── permissions.py      # Role-based permission system
│   ├── channel_cache.py    # YouTube channel caching
│   └── commands/           # Slash command implementations
│       ├── relay.py        # Channel relay commands
│       ├── blacklist.py    # Translator blacklist commands
│       ├── admin.py        # Administrative commands
│       └── system.py       # System/utility commands
├── config.json             # Server configuration
├── pyproject.toml          # Project dependencies and metadata
└── .env                    # Environment variables (create this)
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
