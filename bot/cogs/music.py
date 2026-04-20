"""
Music cog — all voice/playback slash commands.
"""
from __future__ import annotations
import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.queue import QueueManager, Track
from bot.sources import resolve, FFMPEG_OPTIONS


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.queue_manager = QueueManager()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_voice_client(self, guild: discord.Guild) -> Optional[discord.VoiceClient]:
        return guild.voice_client  # type: ignore[return-value]

    def _play_next(self, guild: discord.Guild) -> None:
        """Callback: pull the next track from the queue and start playing."""
        q = self.queue_manager.get(guild.id)
        track = q.next()
        vc: Optional[discord.VoiceClient] = self._get_voice_client(guild)

        if not track or not vc or not vc.is_connected():
            return

        source = discord.FFmpegPCMAudio(
            track.url,
            before_options=FFMPEG_OPTIONS["before_options"],
            options=FFMPEG_OPTIONS["options"],
        )
        source = discord.PCMVolumeTransformer(source, volume=1.0)

        def after(error: Optional[Exception]) -> None:
            if error:
                print(f"[playback error] {error}")
            self._play_next(guild)

        vc.play(source, after=after)

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

        # Auto-join if not connected
        vc = self._get_voice_client(interaction.guild)
        if not vc:
            vc = await member.voice.channel.connect()
        elif vc.channel != member.voice.channel:
            await vc.move_to(member.voice.channel)

        # Resolve the track
        try:
            track = await resolve(query, requester=interaction.user.display_name)
        except ValueError as e:
            await interaction.followup.send(f"❌ Could not resolve track: {e}")
            return

        q = self.queue_manager.get(interaction.guild.id)
        q.add(track)

        if not vc.is_playing() and not vc.is_paused():
            self._play_next(interaction.guild)
            await interaction.followup.send(f"▶️ Now playing: **{track.title}**")
        else:
            position = len(q.list_tracks())
            await interaction.followup.send(f"📋 Added to queue (position {position}): **{track.title}**")

    # ------------------------------------------------------------------
    # /skip
    # ------------------------------------------------------------------

    @app_commands.command(name="skip", description="Skip the current track.")
    async def skip(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return

        vc = self._get_voice_client(interaction.guild)
        if not vc or not vc.is_playing():
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
            return

        q = self.queue_manager.get(interaction.guild.id)
        skipped = q.current

        vc.stop()  # Triggers the `after` callback → _play_next

        msg = f"⏭️ Skipped **{skipped.title}**." if skipped else "⏭️ Skipped."
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

        q = self.queue_manager.get(interaction.guild.id)
        q.clear()

        await vc.disconnect()
        self.queue_manager.remove(interaction.guild.id)

        await interaction.response.send_message("⏹️ Stopped playback and disconnected.")

    # ------------------------------------------------------------------
    # /queue
    # ------------------------------------------------------------------

    @app_commands.command(name="queue", description="Show the current track queue.")
    async def queue(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return

        q = self.queue_manager.get(interaction.guild.id)

        embed = discord.Embed(title="🎵 Current Queue", color=discord.Color.blurple())

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
                dur = _fmt_duration(t.duration)
                lines.append(f"`{i}.` **{t.title}** {dur}")
            if len(tracks) > 10:
                lines.append(f"… and {len(tracks) - 10} more")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Up Next", value="Queue is empty.", inline=False)

        await interaction.response.send_message(embed=embed)


def _fmt_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return ""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"`{h}:{m:02}:{s:02}`"
    return f"`{m}:{s:02}`"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
