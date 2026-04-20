# Discord Media Bot

A self-hosted Discord bot that streams audio from YouTube and Jellyfin into voice channels.

## Quick Start

```bash
# 1. Clone and enter the repo
git clone <your-repo> && cd discord-bot

# 2. Create your .env file
cp .env.example .env
# Edit .env with your Discord token and (optionally) Jellyfin credentials

# 3. Build and start
docker compose up -d --build

# 4. Invite the bot to your server with the bot + applications.commands scopes
```

## Slash Commands

| Command | Description |
|---------|-------------|
| `/join` | Join your current voice channel |
| `/play <query>` | Play a YouTube URL, search query, or Jellyfin item |
| `/skip` | Skip the current track |
| `/stop` | Stop playback and disconnect |
| `/queue` | Show the current queue |

### Jellyfin playback

Prefix your query with `jellyfin:` to search your Jellyfin library:

```
/play jellyfin:Dark Side of the Moon
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ | Your Discord bot token |
| `JELLYFIN_BASE_URL` | Optional | e.g. `http://192.168.1.10:8096` |
| `JELLYFIN_API_KEY` | Optional | Jellyfin API key |
| `JELLYFIN_USER_ID` | Optional | Jellyfin user ID for search |

## Keeping yt-dlp Updated

YouTube changes formats frequently. Update yt-dlp by rebuilding the image:

```bash
docker compose build --no-cache && docker compose up -d
```

Or to update only yt-dlp in a running container (temporary):

```bash
docker compose exec discord-bot pip install -U yt-dlp
```

## Project Structure

```
discord-bot/
├── bot/
│   ├── main.py          # Bot entry point
│   ├── queue.py         # Per-guild in-memory queue
│   ├── sources.py       # YouTube (yt-dlp) + Jellyfin resolvers
│   └── cogs/
│       └── music.py     # All slash commands
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Planned Features (v2+)

- Spotify support (via spotdl)
- Local file playback
- Volume control (`/volume`)
- Web dashboard
