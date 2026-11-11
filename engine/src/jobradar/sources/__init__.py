"""Source registry."""

from __future__ import annotations

from jobradar.config import AppConfig
from jobradar.sources.base import Source


def build_sources(cfg: AppConfig, only: list[str] | None = None) -> list[Source]:
    from jobradar.sources.arbeitsagentur import ArbeitsagenturSource
    from jobradar.sources.ats import CompanyBoardsSource
    from jobradar.sources.freehire import FreehireSource
    from jobradar.sources.jobspy_src import JobSpySource

    sources: list[Source] = []
    if cfg.sources.arbeitsagentur.enabled:
        sources.append(ArbeitsagenturSource())
    if cfg.sources.freehire.enabled:
        sources.append(FreehireSource())
    if any(c.enabled for c in cfg.sources.companies):
        sources.append(CompanyBoardsSource())
    if cfg.sources.jobspy.enabled:
        sources.append(JobSpySource())
    if only:
        wanted = {o.lower() for o in only}
        sources = [s for s in sources if s.name in wanted]
    return sources


SOURCE_NAMES = ["arbeitsagentur", "freehire", "companies", "jobspy"]
