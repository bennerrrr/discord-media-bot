from __future__ import annotations
import asyncio
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.queue import GuildQueue, LoopMode, QueueManager, Track
from bot.sources import resolve, youtube_suggestions, FFMPEG_OPTIONS

IDLE_TIMEOUT_SECONDS = int(os.environ.get("IDLE_TIMEOUT_SECONDS", "300"))

_LOOP_NEXT = {LoopMode.OFF: LoopMode.TRACK, LoopMode.TRACK: LoopMode.QUEUE, LoopMode.QUEUE: LoopMode.OFF}
_LOOP_LABEL = {LoopMode.OFF: None, LoopMode.TRACK: "Track", LoopMode.QUEUE: "Queue"}
_LOOP_STYLE = {
    LoopMode.OFF: discord.ButtonStyle.secondary,
    LoopMode.TRACK: discord.ButtonStyle.success,
    LoopMode.QUEUE: discord.ButtonStyle.success,
}


# ---------------------------------------------------------------------------
# Interactive now-playing control panel
# ---------------------------------------------------------------------------

class NowPlayingView(discord.ui.View):
    def __init__(self, cog: Music, guild: discord.Guild) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.guild = guild

    async def _refresh(self, interaction: discord.Interaction) -> None:
        vc = self.cog._get_voice_client(self.guild)
        q = self.cog.queue_manager.get(self.guild.id)
        self.pause_resume_btn.emoji = "▶️" if (vc and vc.is_paused()) else "⏸"
        self.loop_btn.label = _LOOP_LABEL[q.loop_mode]
        self.loop_btn.style = _LOOP_STYLE[q.loop_mode]
        embed = self.cog._make_now_playing_embed(q.current, q) if q.current else None
        if embed:
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji="⏸", style=discord.ButtonStyle.secondary, row=0)
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        vc = self.cog._get_voice_client(self.guild)
        if not vc:
            await interaction.response.defer()
            return
        if vc.is_playing():
            vc.pause()
        elif vc.is_paused():
            vc.resume()
        await self._refresh(interaction)

    @discord.ui.button(emoji="⏭", style=discord.ButtonStyle.primary, row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        vc = self.cog._get_voice_client(self.guild)
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        await interaction.response.defer()

    @discord.ui.button(emoji="⏹", style=discord.ButtonStyle.danger, row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.cog._stopping.add(self.guild.id)
        self.cog._cancel_idle(self.guild.id)
        q = self.cog.queue_manager.get(self.guild.id)
        q.clear()
        vc = self.cog._get_voice_client(self.guild)
        if vc:
            await vc.disconnect()
        self.cog._active_views.pop(self.guild.id, None)
        self.cog._now_playing_msgs.pop(self.guild.id, None)
        self.cog.queue_manager.remove(self.guild.id)
        self.stop()
        embed = discord.Embed(description="⏹ Stopped and disconnected.", color=discord.Color.dark_grey())
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=0)
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        q = self.cog.queue_manager.get(self.guild.id)
        q.loop_mode = _LOOP_NEXT[q.loop_mode]
        await self._refresh(interaction)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        q = self.cog.queue_manager.get(self.guild.id)
        q.shuffle()
        await self._refresh(interaction)


# ---------------------------------------------------------------------------
# Music cog
# ---------------------------------------------------------------------------

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.queue_manager = QueueManager()
        self._idle_tasks: dict[int, asyncio.Task] = {}
        self._active_views: dict[int, NowPlayingView] = {}
        self._now_playing_msgs: dict[int, discord.Message] = {}
        self._last_channel: dict[int, discord.abc.Messageable] = {}
        self._volumes: dict[int, float] = {}
        self._replay_current: set[int] = set()
        self._seek_seconds: dict[int, int] = {}
        self._stopping: set[int] = set()

    # ------------------------------------------------------------------
    # Idle timeout helpers
    # ------------------------------------------------------------------

    def _cancel_idle_inner(self, guild_id: int) -> None:
        task = self._idle_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _cancel_idle(self, guild_id: int) -> None:
        self.bot.loop.call_soon_threadsafe(self._cancel_idle_inner, guild_id)

    def _schedule_idle(self, guild: discord.Guild) -> None:
        def _do() -> None:
            self._cancel_idle_inner(guild.id)
            self._idle_tasks[guild.id] = self.bot.loop.create_task(
                self._idle_disconnect(guild)
            )
        self.bot.loop.call_soon_threadsafe(_do)

    async def _idle_disconnect(self, guild: discord.Guild) -> None:
        try:
            await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            return
        vc = self._get_voice_client(guild)
        if not vc or not vc.is_connected():
            return
        if vc.is_playing() or vc.is_paused():
            return
        q = self.queue_manager.get(guild.id)
        if not q.is_empty() or q.current:
            return
        print(f"[idle] disconnecting guild {guild.id} after {IDLE_TIMEOUT_SECONDS}s", flush=True)
        await vc.disconnect()
        await self._cleanup_guild(guild, "Disconnected (idle timeout).")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_voice_client(self, guild: discord.Guild) -> Optional[discord.VoiceClient]:
        return guild.voice_client  # type: ignore[return-value]

    async def _cleanup_guild(self, guild: discord.Guild, reason: str = "Stopped.") -> None:
        self._cancel_idle(guild.id)
        view = self._active_views.pop(guild.id, None)
        if view:
            view.stop()
        msg = self._now_playing_msgs.pop(guild.id, None)
        if msg:
            try:
                embed = discord.Embed(description=f"⏹ {reason}", color=discord.Color.dark_grey())
                await msg.edit(embed=embed, view=None)
            except discord.NotFound:
                pass
        self.queue_manager.remove(guild.id)

    def _make_now_playing_embed(self, track: Track, q: GuildQueue) -> discord.Embed:
        embed = discord.Embed(
            title=track.title,
            url=track.webpage_url,
            color=discord.Color.blurple(),
        )
        if track.thumbnail_url:
            embed.set_thumbnail(url=track.thumbnail_url)
        if track.duration:
            embed.add_field(name="Duration", value=_fmt_duration(track.duration), inline=True)
        if track.requester:
            embed.add_field(name="Requested by", value=track.requester, inline=True)
        loop_display = {"off": "Off", "track": "🔂 Track", "queue": "🔁 Queue"}[q.loop_mode.value]
        embed.add_field(name="Loop", value=loop_display, inline=True)
        upcoming = q.list_tracks()
        if upcoming:
            lines = [f"`{i}.` {t.title}" for i, t in enumerate(upcoming[:3], 1)]
            if len(upcoming) > 3:
                lines.append(f"… and {len(upcoming) - 3} more")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        return embed

    async def _play_next(self, guild: discord.Guild) -> None:
        if guild.id in self._stopping:
            self._stopping.discard(guild.id)
            return

        q = self.queue_manager.get(guild.id)
        vc = self._get_voice_client(guild)

        if not vc or not vc.is_connected():
            return

        seek_to = self._seek_seconds.pop(guild.id, 0)
        replay = guild.id in self._replay_current
        if replay:
            self._replay_current.discard(guild.id)

        if replay or seek_to:
            track = q.current
        elif q.loop_mode == LoopMode.TRACK and q.current:
            track = q.current
        else:
            prev = q.current
            if q.loop_mode == LoopMode.QUEUE and prev:
                q.add(prev)
            track = q.next()

        if not track:
            print(f"[play_next] queue empty for guild {guild.id}", flush=True)
            if vc.is_connected():
                self._schedule_idle(guild)
            # Clear the now-playing panel
            old_view = self._active_views.pop(guild.id, None)
            if old_view:
                old_view.stop()
            msg = self._now_playing_msgs.pop(guild.id, None)
            if msg:
                try:
                    embed = discord.Embed(description="Queue finished.", color=discord.Color.dark_grey())
                    await msg.edit(embed=embed, view=None)
                except discord.NotFound:
                    pass
            return

        self._cancel_idle(guild.id)
        print(f"[play_next] playing {track.title!r}", flush=True)

        before_opts = FFMPEG_OPTIONS["before_options"]
        if seek_to:
            before_opts = f"-ss {seek_to} " + before_opts

        source = discord.FFmpegPCMAudio(
            track.url,
            before_options=before_opts,
            options=FFMPEG_OPTIONS["options"],
        )
        volume = self._volumes.get(guild.id, 1.0)
        source = discord.PCMVolumeTransformer(source, volume=volume)

        def after(error: Optional[Exception]) -> None:
            if error:
                print(f"[playback error] {error!r}", flush=True)
            else:
                print(f"[playback finished] {track.title!r}", flush=True)
            asyncio.run_coroutine_threadsafe(self._play_next(guild), self.bot.loop)

        vc.play(source, after=after)

        # Update or send the now-playing embed with controls
        channel = self._last_channel.get(guild.id)
        if channel:
            embed = self._make_now_playing_embed(track, q)
            old_view = self._active_views.pop(guild.id, None)
            if old_view:
                old_view.stop()
            view = NowPlayingView(self, guild)
            self._active_views[guild.id] = view

            existing = self._now_playing_msgs.get(guild.id)
            msg: Optional[discord.Message] = None
            if existing:
                try:
                    await existing.edit(embed=embed, view=view)
                    msg = existing
                except discord.NotFound:
                    pass
            if not msg:
                msg = await channel.send(embed=embed, view=view)
                self._now_playing_msgs[guild.id] = msg

    # ------------------------------------------------------------------
    # /join
    # ------------------------------------------------------------------

    @app_commands.command(name="join", description="Join your current voice channel.")
    async def join(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.voice or not member.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel first.", ephemeral=True)
            return
        channel = member.voice.channel
        vc = self._get_voice_client(interaction.guild)
        if vc:
            await vc.move_to(channel)
        else:
            await channel.connect()
        self._last_channel[interaction.guild.id] = interaction.channel  # type: ignore[assignment]
        self._schedule_idle(interaction.guild)
        await interaction.response.send_message(f"Joined **{channel.name}**.")

    # ------------------------------------------------------------------
    # /play
    # ------------------------------------------------------------------

    @app_commands.command(name="play", description="Play a YouTube URL/search or Jellyfin item (prefix with 'jellyfin:').")
    @app_commands.describe(query="YouTube URL, search query, or 'jellyfin:<title>'")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.voice or not member.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel first.", ephemeral=True)
            return

        await interaction.response.defer()
        self._last_channel[interaction.guild.id] = interaction.channel  # type: ignore[assignment]

        vc = self._get_voice_client(interaction.guild)
        if not vc:
            vc = await member.voice.channel.connect()
        elif vc.channel != member.voice.channel:
            await vc.move_to(member.voice.channel)

        try:
            track = await resolve(query, requester=interaction.user.display_name)
        except ValueError as e:
            await interaction.followup.send(f"Could not resolve track: {e}")
            return

        q = self.queue_manager.get(interaction.guild.id)
        q.add(track)
        self._cancel_idle(interaction.guild.id)

        if not vc.is_playing() and not vc.is_paused():
            await self._play_next(interaction.guild)
            await interaction.followup.send(f"Now playing: **{track.title}**")
        else:
            position = len(q.list_tracks())
            await interaction.followup.send(f"Added to queue (position {position}): **{track.title}**")

    @play.autocomplete("query")
    async def play_query_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if current.lower().startswith("jellyfin:"):
            return []
        suggestions = await youtube_suggestions(current)
        return [app_commands.Choice(name=title[:100], value=url) for title, url in suggestions]

    # ------------------------------------------------------------------
    # /pause  /resume  /restart  /seek
    # ------------------------------------------------------------------

    @app_commands.command(name="pause", description="Pause playback.")
    async def pause(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        vc = self._get_voice_client(interaction.guild)
        if not vc or not vc.is_playing():
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        vc.pause()
        await interaction.response.send_message("⏸ Paused.")

    @app_commands.command(name="resume", description="Resume paused playback.")
    async def resume(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        vc = self._get_voice_client(interaction.guild)
        if not vc or not vc.is_paused():
            await interaction.response.send_message("Playback is not paused.", ephemeral=True)
            return
        vc.resume()
        await interaction.response.send_message("▶️ Resumed.")

    @app_commands.command(name="restart", description="Restart the current track from the beginning.")
    async def restart(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        vc = self._get_voice_client(interaction.guild)
        q = self.queue_manager.get(interaction.guild.id)
        if not vc or not q.current or (not vc.is_playing() and not vc.is_paused()):
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        self._replay_current.add(interaction.guild.id)
        vc.stop()
        await interaction.response.send_message(f"↩️ Restarting **{q.current.title}**.")

    @app_commands.command(name="seek", description="Seek to a position in the current track.")
    @app_commands.describe(position="Position to seek to, e.g. 1:30 or 90")
    async def seek(self, interaction: discord.Interaction, position: str) -> None:
        if not interaction.guild:
            return
        vc = self._get_voice_client(interaction.guild)
        q = self.queue_manager.get(interaction.guild.id)
        if not vc or not q.current or (not vc.is_playing() and not vc.is_paused()):
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        seconds = _parse_timestamp(position)
        if seconds is None:
            await interaction.response.send_message("Invalid position. Use `1:30` or `90`.", ephemeral=True)
            return
        self._seek_seconds[interaction.guild.id] = seconds
        self._replay_current.add(interaction.guild.id)
        vc.stop()
        await interaction.response.send_message(f"⏩ Seeking to {_fmt_duration(seconds)}.")

    # ------------------------------------------------------------------
    # /volume
    # ------------------------------------------------------------------

    @app_commands.command(name="volume", description="Set playback volume (0–200).")
    @app_commands.describe(level="Volume level from 0 to 200 (100 = normal)")
    async def volume(self, interaction: discord.Interaction, level: int) -> None:
        if not interaction.guild:
            return
        if not 0 <= level <= 200:
            await interaction.response.send_message("Volume must be between 0 and 200.", ephemeral=True)
            return
        vol = level / 100.0
        self._volumes[interaction.guild.id] = vol
        vc = self._get_voice_client(interaction.guild)
        if vc and vc.source:
            vc.source.volume = vol  # type: ignore[attr-defined]
        await interaction.response.send_message(f"🔊 Volume set to **{level}%**.")

    # ------------------------------------------------------------------
    # /skip
    # ------------------------------------------------------------------

    @app_commands.command(name="skip", description="Skip the current track.")
    async def skip(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        vc = self._get_voice_client(interaction.guild)
        if not vc or not (vc.is_playing() or vc.is_paused()):
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
            return
        q = self.queue_manager.get(interaction.guild.id)
        skipped = q.current
        vc.stop()
        msg = f"⏭ Skipped **{skipped.title}**." if skipped else "⏭ Skipped."
        await interaction.response.send_message(msg)

    # ------------------------------------------------------------------
    # /stop
    # ------------------------------------------------------------------

    @app_commands.command(name="stop", description="Stop playback and disconnect from voice.")
    async def stop(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        vc = self._get_voice_client(interaction.guild)
        if not vc:
            await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)
            return
        self._stopping.add(interaction.guild.id)
        q = self.queue_manager.get(interaction.guild.id)
        q.clear()
        await vc.disconnect()
        await self._cleanup_guild(interaction.guild, "Stopped by user.")
        await interaction.response.send_message("⏹ Stopped and disconnected.")

    # ------------------------------------------------------------------
    # /queue  /clear  /remove  /move  /shuffle  /loop
    # ------------------------------------------------------------------

    @app_commands.command(name="queue", description="Show the current track queue.")
    async def queue(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        q = self.queue_manager.get(interaction.guild.id)
        embed = discord.Embed(title="Current Queue", color=discord.Color.blurple())
        if q.current:
            dur = _fmt_duration(q.current.duration)
            embed.add_field(
                name="Now Playing",
                value=f"**{q.current.title}** {dur} — *{q.current.requester or 'unknown'}*",
                inline=False,
            )
        tracks = q.list_tracks()
        if tracks:
            lines = []
            for i, t in enumerate(tracks[:10], start=1):
                lines.append(f"`{i}.` **{t.title}** {_fmt_duration(t.duration)}")
            if len(tracks) > 10:
                lines.append(f"… and {len(tracks) - 10} more")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Up Next", value="Queue is empty.", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clear", description="Clear the upcoming queue without stopping playback.")
    async def clear(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        q = self.queue_manager.get(interaction.guild.id)
        q.clear_upcoming()
        await interaction.response.send_message("🗑️ Queue cleared.")

    @app_commands.command(name="remove", description="Remove a track from the queue by position.")
    @app_commands.describe(position="Queue position to remove (1 = next up)")
    async def remove(self, interaction: discord.Interaction, position: int) -> None:
        if not interaction.guild:
            return
        q = self.queue_manager.get(interaction.guild.id)
        track = q.remove(position)
        if not track:
            await interaction.response.send_message(f"No track at position {position}.", ephemeral=True)
            return
        await interaction.response.send_message(f"🗑️ Removed **{track.title}** from the queue.")

    @app_commands.command(name="move", description="Move a track to a different position in the queue.")
    @app_commands.describe(from_position="Current position", to_position="New position")
    async def move(self, interaction: discord.Interaction, from_position: int, to_position: int) -> None:
        if not interaction.guild:
            return
        q = self.queue_manager.get(interaction.guild.id)
        if not q.move(from_position, to_position):
            await interaction.response.send_message("Invalid positions.", ephemeral=True)
            return
        await interaction.response.send_message(f"↕️ Moved track from position {from_position} to {to_position}.")

    @app_commands.command(name="shuffle", description="Shuffle the upcoming queue.")
    async def shuffle(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        q = self.queue_manager.get(interaction.guild.id)
        if q.is_empty():
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
            return
        q.shuffle()
        await interaction.response.send_message("🔀 Queue shuffled.")

    @app_commands.command(name="loop", description="Cycle loop mode: off → track → queue → off.")
    async def loop(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        q = self.queue_manager.get(interaction.guild.id)
        q.loop_mode = _LOOP_NEXT[q.loop_mode]
        labels = {LoopMode.OFF: "Off", LoopMode.TRACK: "🔂 Track", LoopMode.QUEUE: "🔁 Queue"}
        await interaction.response.send_message(f"Loop mode: **{labels[q.loop_mode]}**")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return ""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"`{h}:{m:02}:{s:02}`"
    return f"`{m}:{s:02}`"


def _parse_timestamp(ts: str) -> Optional[int]:
    parts = ts.strip().split(":")
    try:
        if len(parts) == 1:
            return max(0, int(parts[0]))
        elif len(parts) == 2:
            return max(0, int(parts[0]) * 60 + int(parts[1]))
        elif len(parts) == 3:
            return max(0, int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
    except ValueError:
        pass
    return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
