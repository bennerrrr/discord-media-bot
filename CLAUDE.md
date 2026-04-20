# Discord Media Streaming Bot — Project Context

Python Discord bot (discord.py) that streams audio into voice channels. Hosted
via Docker Compose on a homelab (Debian 13 server, `mediaSrv`).

## Stack

- Python 3.12 (slim base image)
- `discord.py[voice] >= 2.4` — **do not pin to 2.3.x**; Discord's voice gateway
  V8 handshake broke that version, causing silent voice failures (bot joins
  channel but no audio plays).
- FFmpeg + libopus (for PCM/Opus encoding)
- `yt-dlp` for YouTube URL/search resolution
- Jellyfin REST API (optional, for local library playback)
- In-memory queue (`collections.deque`) per guild
- Docker Compose

## File structure

```
discord-bot/
├── bot/
│   ├── __init__.py
│   ├── main.py        # Entry point, loads cogs, syncs slash commands
│   ├── queue.py       # Track, GuildQueue, QueueManager dataclasses
│   ├── sources.py     # resolve(), resolve_youtube(), resolve_jellyfin()
│   └── cogs/
│       ├── __init__.py
│       └── music.py   # Slash commands + idle-timeout disconnect
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
├── CLAUDE.md          # this file
└── README.md
```

## Architecture decisions

- **Source routing:** queries prefixed with `jellyfin:` go to the Jellyfin
  resolver, everything else goes to YouTube via yt-dlp. See
  `bot/sources.py::resolve`.
- **Config via environment:** every secret and tunable lives in `.env` /
  Docker env vars. No hardcoded tokens or URLs. `docker-compose.yml`
  declares each env var with a default where appropriate.
- **Stream resilience:** FFmpeg is invoked with `-reconnect 1
  -reconnect_streamed 1 -reconnect_delay_max 5` so transient network blips
  don't kill playback mid-track.
- **Per-guild isolation:** `QueueManager` maintains one `GuildQueue` per
  Discord guild ID. Voice connections, queues, and idle-timeout tasks are
  all keyed on guild ID so guilds never interfere with each other.
- **Idle auto-disconnect:** after `IDLE_TIMEOUT_SECONDS` (default 300) of no
  playback and an empty queue, the bot disconnects on its own. The timer is
  cancelled whenever a new track starts. Implementation uses
  `bot.loop.call_soon_threadsafe` because the audio `after` callback fires
  from discord.py's audio thread, not the main event loop.
- **Slash commands only:** no prefix commands. `bot.tree.sync()` runs on
  `on_ready`.

## Slash commands

| Command | Behavior |
|---|---|
| `/join` | Join the caller's current voice channel |
| `/play <query>` | Play a YouTube URL, YouTube search, or `jellyfin:<title>` |
| `/skip` | Skip the current track |
| `/stop` | Clear queue, disconnect |
| `/queue` | Show now-playing + up to 10 upcoming tracks |

## Deployment environment and gotchas

**Host:** Debian 13 (trixie), Docker 28.3.2 (CE, from Docker's apt repo).

**Do not upgrade Docker to 29.x on this machine.** Docker 29 on Debian 13
enables the containerd image snapshotter + `overlayfs` storage driver by
default, which has a known bug that surfaces as:

```
failed to open writer: ref moby/1/... locked for Xs ... unavailable
```

during the final "exporting to image" step of any build, regardless of
builder (BuildKit, classic, buildx to tarball, OCI pipe — all fail). The
daemon is pinned to 28 via `apt-mark hold docker-ce docker-ce-cli` to
prevent accidental upgrades.

**`PYTHONUNBUFFERED=1`** is set in the Dockerfile. Without it, Python's
`print()` output is block-buffered under Docker's pipe stdout and logs
appear frozen even though the bot is running fine.

**Other containers on `mediaSrv`:** Jellyfin, Sonarr, Radarr, Prowlarr,
SABnzbd, Portainer, Beszel-agent (all LinuxServer.io or first-party images).
When modifying Docker daemon config, be careful — switching storage drivers
orphans existing containers' images, though named volumes are preserved.

## Dev / rebuild loop

On `mediaSrv`:

```bash
cd ~/discord-media-bot
git pull
sudo docker compose up -d --build
sudo docker compose logs -f discord-bot
```

For env-only tweaks (e.g. `IDLE_TIMEOUT_SECONDS`), skip `--build`:

```bash
sudo docker compose up -d
```

Tail logs:

```bash
sudo docker compose logs -f discord-bot
# Look for: `Logged in as ...`, `[play_next] playing ...`,
# `[playback finished] ...`, `[idle] disconnecting ...`
```

Source of truth is the GitHub repo. Edits made in other environments (e.g.
a Windows workspace via Cowork) should be committed and pushed, then
`git pull`'d on `mediaSrv` before rebuilding.

## Current status

Deployed and working end-to-end on `mediaSrv`. Audio playback verified on
YouTube sources. Idle-timeout disconnect implemented. Jellyfin path exists
in code but not yet exercised against a real Jellyfin instance.

## Roadmap

- Exercise Jellyfin resolver against a live instance; fix any issues
- Local file support (mount a directory, resolve file paths)
- Spotify via `spotdl`
- Volume control (`/volume <0-200>`)
- Shuffle / loop / remove-from-queue commands
- Auto-leave when the voice channel becomes empty of humans (complements
  idle timeout)
- Persistent queue across restarts (optional — SQLite?)
- Web dashboard (stretch)

## What NOT to build

- **Video streaming from the bot.** Discord's bot API does not expose
  screen share / Go Live. The only way to do it is selfbotting (automating
  a user account), which violates Discord ToS and risks account bans. If
  video is ever wanted, spin it up as a separate disposable-account project,
  not inside this bot.
