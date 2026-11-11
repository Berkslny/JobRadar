"""Source plumbing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

from jobradar.config import AppConfig, TrackConfig
from jobradar.models import RawJob
from jobradar.profile import Profile


class SourceError(Exception):
    """The source failed completely (recorded in source health)."""


class SourceUnavailable(SourceError):
    """The source cannot run in this installation (missing package/key)."""


@dataclass
class SourceContext:
    config: AppConfig
    profile: Profile
    client: httpx.Client
    log: Callable[[str], None] = print
    warnings: list[str] = field(default_factory=list)
    step: Optional[Callable[[int, int, str], None]] = None

    @property
    def tracks(self) -> list[TrackConfig]:
        return self.config.enabled_tracks()

    def report(self, done: int, total: int, label: str = "") -> None:
        """Progress inside a source (query or company `done` of `total`) for the progress bar."""
        if self.step is None:
            return
        try:
            self.step(done, total, label)
        except Exception:  # noqa: BLE001 - a progress bar must never break a scan
            pass


class Source:
    name: str = "source"

    def fetch(self, ctx: SourceContext) -> list[RawJob]:  # pragma: no cover - interface
        raise NotImplementedError


def search_terms(ctx: SourceContext, limit: int | None = None) -> list[tuple[str, TrackConfig]]:
    """Interleave the tracks' search terms so every track gets coverage."""
    per_track = [[(term, t) for term in t.search_terms if term.strip()] for t in ctx.tracks]
    out: list[tuple[str, TrackConfig]] = []
    seen: set[str] = set()
    i = 0
    while any(i < len(lst) for lst in per_track):
        for lst in per_track:
            if i < len(lst):
                term, t = lst[i]
                if term.lower() not in seen:
                    seen.add(term.lower())
                    out.append((term, t))
        i += 1
    return out[:limit] if limit else out
