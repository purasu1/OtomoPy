# OtomoPy

A Discord bot that integrates with the Holodex API to relay VTuber stream notifications and chat messages to Discord channels.

## Features

- **Live Stream Monitoring**: Automatically detects when VTubers go live using the Holodex API
- **Stream Notifications**: Posts notifications in configured Discord channels when streams start
- **Chat Relay**: Relays live chat messages from YouTube streams to Discord channels
- **Channel Management**: Add/remove YouTube channels to monitor per Discord server
- **Translation Blacklist**: Filter out specific translators or chat messages
- **Multi-Server Support**: Configure different settings for each Discord server
- **Chat Translation**: Automatic translation of VTuber messages via DeepL or Azure AI Translator

## Requirements

- Python 3.11 or higher
- Discord Bot Token
- Holodex API Key
- Discord server with appropriate permissions
- Optionally, a DeepL API key or an Azure Translator key/region

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
# Required:
DISCORD_TOKEN=your_discord_bot_token_here
OWNER_ID=your_discord_user_id_here
CONFIG_FILE=config.json
HOLODEX_API_KEY=your_holodex_api_key_here
# Optional (choose a translation backend; "deepl" is the default):
TRANSLATION_BACKEND=deepl
DEEPL_API_KEY=your_deepl_api_key_here
# Or, to use Azure AI Translator instead:
# TRANSLATION_BACKEND=azure
# AZURE_TRANSLATOR_KEY=your_azure_translator_key_here
# AZURE_TRANSLATOR_REGION=your_azure_resource_region_here
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

### Translation (Optional)

The bot can translate live chat messages that aren't already in English. Set
`TRANSLATION_BACKEND` to `deepl` (the default) or `azure`, and provide the
corresponding API key(s) below. If no key is configured, translation is
disabled.

#### DeepL

1. Sign up at [DeepL](https://www.deepl.com/pro-api) and create an API key
   from your account page
2. Set `DEEPL_API_KEY` in your `.env` file

#### Azure AI Translator

1. Sign in to the [Azure Portal](https://portal.azure.com/)
2. Click "Create a resource" and search for **Translator** (under "AI +
   Machine Learning" / "Azure AI services")
3. Create the resource:
   - Pick a **Subscription** and **Resource group** (create a new resource
     group if you don't have one)
   - Pick a **Region** — this becomes `AZURE_TRANSLATOR_REGION`. If you
     select "Global", no region header is required and you can leave
     `AZURE_TRANSLATOR_REGION` unset
   - Choose a **Name** and the **Free F0** pricing tier if you just want to
     try it out (paid **S1** tier otherwise); free tier limits are generous
     for a chat relay bot
4. Once deployed, go to the resource's **"Keys and Endpoint"** page (under
   "Resource Management")
5. Copy **KEY 1** (or KEY 2) into `AZURE_TRANSLATOR_KEY` and the **Location/Region**
   value into `AZURE_TRANSLATOR_REGION`
6. Leave `AZURE_TRANSLATOR_ENDPOINT` unset unless you're using a custom or
   sovereign-cloud endpoint — the bot defaults to the standard global
   endpoint (`https://api.cognitive.microsofttranslator.com`)
7. Set `TRANSLATION_BACKEND=azure` in your `.env` file

Unlike DeepL, Azure's translate endpoint auto-detects the source language on
every request, so no separate language-detection call or API is needed.

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

By default, all slash commands require manage messages permissions. This can be adjusted on a per-guild basis in the server integration settings.

#### `/relay add <channel_id>`
Add a YouTube channel to monitor for the current Discord channel.
- Auto-completes channel names

#### `/relay remove <channel_id>`
Remove a YouTube channel from monitoring for the current Discord channel.
- Auto-completes channel names

#### `/relay list`
List all configured channel relays for the current Discord channel.

#### `/relay list-category`
List all configured channel relays for channels in the current category.

#### `/relay list-guild`
List all configured channel relays for channels in the current guild.

#### `/blacklist translator <username>`
Add a translator to the blacklist for the current guild.

#### `/blacklist vtuber <username>`
Add a vtuber to the blacklist for the current guild.
- Auto-completes channel names

#### `/blacklist remove <username>`
Remove a translator or vtuber from the blacklist for the current guild.
- Autocompletes usernames

#### `/blacklist list`
Show all blacklisted translators or vtubers for the current guild.

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
│   ├── channel_cache.py    # YouTube channel caching
│   └── commands/           # Slash command implementations
│       ├── relay.py        # Channel relay commands
│       ├── blacklist.py    # Translator blacklist commands
│       └── system.py       # System/utility commands
├── config.json             # Server configuration
├── pyproject.toml          # Project dependencies and metadata
└── .env                    # Environment variables (create this)
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
