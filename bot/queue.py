from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Track:
    title: str
    url: str          # Resolved stream URL (passed to FFmpeg)
    source: str       # "youtube" | "jellyfin"
    duration: Optional[int] = None   # seconds, if known
    requester: Optional[str] = None  # Discord display name


@dataclass
class GuildQueue:
    tracks: deque[Track] = field(default_factory=deque)
    current: Optional[Track] = None

    def add(self, track: Track) -> None:
        self.tracks.append(track)

    def next(self) -> Optional[Track]:
        if self.tracks:
            self.current = self.tracks.popleft()
            return self.current
        self.current = None
        return None

    def clear(self) -> None:
        self.tracks.clear()
        self.current = None

    def is_empty(self) -> bool:
        return len(self.tracks) == 0

    def list_tracks(self) -> list[Track]:
        return list(self.tracks)


class QueueManager:
    """Manages one GuildQueue per Discord guild."""

    def __init__(self) -> None:
        self._queues: dict[int, GuildQueue] = {}

    def get(self, guild_id: int) -> GuildQueue:
        if guild_id not in self._queues:
            self._queues[guild_id] = GuildQueue()
        return self._queues[guild_id]

    def remove(self, guild_id: int) -> None:
        self._queues.pop(guild_id, None)
