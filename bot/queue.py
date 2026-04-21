from __future__ import annotations
import random
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LoopMode(Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


@dataclass
class Track:
    title: str
    url: str
    source: str
    duration: Optional[int] = None
    requester: Optional[str] = None
    webpage_url: Optional[str] = None
    thumbnail_url: Optional[str] = None


@dataclass
class GuildQueue:
    tracks: deque[Track] = field(default_factory=deque)
    current: Optional[Track] = None
    loop_mode: LoopMode = field(default_factory=lambda: LoopMode.OFF)

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

    def clear_upcoming(self) -> None:
        self.tracks.clear()

    def is_empty(self) -> bool:
        return len(self.tracks) == 0

    def list_tracks(self) -> list[Track]:
        return list(self.tracks)

    def remove(self, index: int) -> Optional[Track]:
        if index < 1 or index > len(self.tracks):
            return None
        lst = list(self.tracks)
        track = lst.pop(index - 1)
        self.tracks = deque(lst)
        return track

    def move(self, from_idx: int, to_idx: int) -> bool:
        n = len(self.tracks)
        if not (1 <= from_idx <= n and 1 <= to_idx <= n) or from_idx == to_idx:
            return False
        lst = list(self.tracks)
        track = lst.pop(from_idx - 1)
        lst.insert(to_idx - 1, track)
        self.tracks = deque(lst)
        return True

    def shuffle(self) -> None:
        lst = list(self.tracks)
        random.shuffle(lst)
        self.tracks = deque(lst)


class QueueManager:
    def __init__(self) -> None:
        self._queues: dict[int, GuildQueue] = {}

    def get(self, guild_id: int) -> GuildQueue:
        if guild_id not in self._queues:
            self._queues[guild_id] = GuildQueue()
        return self._queues[guild_id]

    def remove(self, guild_id: int) -> None:
        self._queues.pop(guild_id, None)
