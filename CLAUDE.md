# Discord Media Streaming Bot — Project Context

Python Discord bot (discord.py) that streams audio into voice channels. Hosted via Docker on a homelab.

## Stack
Python, discord.py, FFmpeg/Opus, yt-dlp (YouTube), Jellyfin REST API, in-memory queue (deque per guild), Docker Compose.

## File structure

```
discord-bot/
├── bot/
│   ├── main.py        # Entry point, loads cogs
│   ├── queue.py       # Track, GuildQueue, QueueManager dataclasses
│   ├── sources.py     # resolve(), resolve_youtube(), resolve_jellyfin()
│   └── cogs/
│       └── music.py   # Slash commands: /join /play /skip /stop /queue
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Key decisions

- Jellyfin queries prefixed with `jellyfin:`, everything else goes to YouTube
- Config via `.env` / Docker env vars — no hardcoded secrets
- FFmpeg `-reconnect` flags enabled for stream resilience
- Per-guild independent voice connections and queues

## Current status

Scaffolded, not yet tested.

## Next steps

- Local file support
- Spotify (spotdl)
- Volume control
- Possible web dashboard
