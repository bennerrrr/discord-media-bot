# Future Plans

## High Priority

### Interactive Control Panel
Persistent embed with discord.py `View` buttons that appears when a track
starts playing. Buttons: pause/resume, skip, stop, loop toggle, shuffle.
The embed updates (via `message.edit`) when the track changes or playback
state changes. Removes itself on disconnect.

### Additional Playback Commands
| Command | Behavior |
|---|---|
| `/pause` | Pause current track |
| `/resume` | Resume paused track |
| `/restart` | Restart the current track from the beginning |
| `/seek <timestamp>` | Jump to a position (e.g. `1:32`) in the current track |
| `/volume <0-200>` | Set per-guild playback volume |

### Queue Management Commands
| Command | Behavior |
|---|---|
| `/remove <position>` | Remove a specific track from the queue |
| `/move <from> <to>` | Reorder tracks in the queue |
| `/shuffle` | Randomise the remaining queue |
| `/loop` | Cycle loop mode: off → loop track → loop queue |
| `/clear` | Clear the queue without disconnecting |

---

## Medium Priority

### Vote-Skip
Require a majority (configurable %) of non-bot VC members to vote before
a skip goes through. Single user bypasses vote if they queued the track or
have the DJ role.

### DJ Role
Restrict destructive commands (`/stop`, `/skip`, `/clear`, queue reorder)
to members with a configurable DJ role. Set via `/djrole <role>`.

### Now-Playing Embed with Progress Bar
Edit the now-playing message every ~15s to show a Unicode progress bar and
elapsed/total time. Stop editing when paused or track ends.

### Lyrics
`/lyrics` fetches lyrics for the current track via the Genius API and posts
them as a paginated embed (button-based pagination for long songs).

### History
`/history` shows the last N (default 10) tracks played in the guild.
Stored in-memory per session; optionally persisted to SQLite.

---

## Lower Priority / Stretch

### Playlist Save & Load
- `/playlist save <name>` — snapshot the current queue as a named playlist
- `/playlist load <name>` — enqueue a saved playlist
- `/playlist list` — show saved playlists
- Backed by SQLite so playlists survive restarts.

### Persistent Queue
Save the active queue to SQLite on shutdown and restore it on startup.
Useful for bot restarts without losing a long queue.

### Spotify Integration
Resolve Spotify track/album/playlist URLs via `spotdl`, then stream via
YouTube. Handle playlist imports by queuing all tracks.

### Local File Support
Mount a host directory into the container. `/play file:<name>` searches
that directory and streams the file directly via FFmpeg.

### Auto-Leave on Empty VC
Detect when all humans leave the voice channel (using `on_voice_state_update`)
and disconnect immediately, regardless of the idle timeout.

### Web Dashboard
Read-only (and optionally write) dashboard showing now-playing, queue, and
recent history across all guilds. Built with FastAPI + a simple frontend.
Stretch goal — evaluate after core features are stable.

---

## Known Gotchas to Keep in Mind

- Discord's autocomplete timeout is 3 seconds — any suggestion lookup must
  resolve within ~2.5s.
- `discord.py >= 2.4` required; 2.3.x has a broken voice gateway handshake.
- Do not upgrade Docker to 29.x on mediaSrv (overlayfs image-export bug).
- Video streaming / screen share from a bot is impossible via Discord's
  official API — do not pursue this direction.
