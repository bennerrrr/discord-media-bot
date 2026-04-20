"""
Source resolvers turn user input into a playable Track.
Each resolver returns a Track or raises ValueError on failure.
"""
from __future__ import annotations
import os
import asyncio
from functools import partial
from typing import Optional

import aiohttp
import yt_dlp

from bot.queue import Track

# ---------------------------------------------------------------------------
# FFmpeg options shared by all sources
# ---------------------------------------------------------------------------
FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5"
    ),
    "options": "-vn",  # audio only
}

# ---------------------------------------------------------------------------
# yt-dlp config  (no download, best audio stream)
# ---------------------------------------------------------------------------
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "noplaylist": True,
}


async def resolve_youtube(query: str, requester: Optional[str] = None) -> Track:
    """
    Accepts a YouTube URL or a plain search query.
    Returns a Track with a direct stream URL (no file download).
    """
    loop = asyncio.get_event_loop()

    def _extract(q: str):
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            # If it looks like a URL use it directly; otherwise prefix with ytsearch:
            search = q if q.startswith("http") else f"ytsearch1:{q}"
            info = ydl.extract_info(search, download=False)
            # ytsearch wraps results in an entries list
            if "entries" in info:
                info = info["entries"][0]
            return info

    info = await loop.run_in_executor(None, partial(_extract, query))

    stream_url = info.get("url")
    if not stream_url:
        raise ValueError(f"yt-dlp could not extract a stream URL for: {query}")

    return Track(
        title=info.get("title", query),
        url=stream_url,
        source="youtube",
        duration=info.get("duration"),
        requester=requester,
    )


# ---------------------------------------------------------------------------
# Jellyfin resolver
# ---------------------------------------------------------------------------
JELLYFIN_BASE_URL = os.environ.get("JELLYFIN_BASE_URL", "")
JELLYFIN_API_KEY = os.environ.get("JELLYFIN_API_KEY", "")
JELLYFIN_USER_ID = os.environ.get("JELLYFIN_USER_ID", "")


async def resolve_jellyfin(query: str, requester: Optional[str] = None) -> Track:
    """
    Searches Jellyfin for audio/music items matching *query*.
    Returns a Track whose URL is a direct Jellyfin stream URL.
    """
    if not JELLYFIN_BASE_URL or not JELLYFIN_API_KEY:
        raise ValueError("Jellyfin environment variables are not configured.")

    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    search_url = f"{JELLYFIN_BASE_URL}/Items"
    params = {
        "searchTerm": query,
        "IncludeItemTypes": "Audio,MusicAlbum",
        "Recursive": "true",
        "Limit": "1",
        "UserId": JELLYFIN_USER_ID,
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(search_url, headers=headers, params=params) as resp:
            if resp.status != 200:
                raise ValueError(f"Jellyfin search failed with HTTP {resp.status}")
            data = await resp.json()

    items = data.get("Items", [])
    if not items:
        raise ValueError(f"No Jellyfin results for: {query}")

    item = items[0]
    item_id = item["Id"]
    title = item.get("Name", query)
    duration_ticks = item.get("RunTimeTicks")
    duration = int(duration_ticks / 10_000_000) if duration_ticks else None

    # Direct stream URL — Jellyfin will transcode if needed, or serve original
    stream_url = (
        f"{JELLYFIN_BASE_URL}/Audio/{item_id}/stream"
        f"?api_key={JELLYFIN_API_KEY}&static=true"
    )

    return Track(
        title=title,
        url=stream_url,
        source="jellyfin",
        duration=duration,
        requester=requester,
    )


async def resolve(query: str, requester: Optional[str] = None) -> Track:
    """
    Auto-detects the source:
      - "jellyfin:<query>"  → Jellyfin
      - everything else     → YouTube
    """
    if query.lower().startswith("jellyfin:"):
        return await resolve_jellyfin(query[9:].strip(), requester=requester)
    return await resolve_youtube(query, requester=requester)
