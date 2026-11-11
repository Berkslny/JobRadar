"""LinkedIn, Indeed and Glassdoor through JobSpy (used as a library)."""

from __future__ import annotations

import inspect
import logging
import math
import time
from typing import Any

from jobradar.models import RawJob
from jobradar.sources.base import Source, SourceContext, SourceError, SourceUnavailable, search_terms
from jobradar.textutil import clean_text, is_blank, parse_date

KM_PER_MILE = 1.609


def _val(row: dict[str, Any], key: str) -> Any:
    v = row.get(key)
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if is_blank(v) and not isinstance(v, bool):
        return None
    return v


def row_to_raw(row: dict[str, Any]) -> RawJob | None:
    title = clean_text(_val(row, "title") or "")
    url = str(_val(row, "job_url") or "")
    if not title or not url:
        return None
    site = str(_val(row, "site") or "jobspy").lower()
    remote = _val(row, "is_remote")
    min_amt, max_amt = _val(row, "min_amount"), _val(row, "max_amount")
    interval = str(_val(row, "interval") or "")
    period = {"yearly": "year", "monthly": "month", "hourly": "hour", "weekly": "week", "daily": "day"}.get(interval, "")
    level = str(_val(row, "job_level") or "")
    return RawJob(
        source=site,
        title=title,
        company=clean_text(_val(row, "company") or ""),
        location=clean_text(_val(row, "location") or ""),
        url=url,
        apply_url=str(_val(row, "job_url_direct") or ""),
        external_id=str(_val(row, "id") or ""),
        description=str(_val(row, "description") or ""),
        description_html=False,
        posted_at=parse_date(_val(row, "date_posted")),
        employment_type=str(_val(row, "job_type") or ""),
        remote=bool(remote) if remote is not None else None,
        salary_min=float(min_amt) if min_amt is not None else None,
        salary_max=float(max_amt) if max_amt is not None else None,
        salary_currency=str(_val(row, "currency") or ""),
        salary_period=period,
        needs_location_check=False,
        extra={"job_level": level, "company_url": str(_val(row, "company_url") or "")},
    )


class JobSpySource(Source):
    name = "jobspy"

    def __init__(self, scrape_fn=None, sleep=time.sleep):
        self._scrape = scrape_fn
        self._sleep = sleep

    def _scrape_fn(self):
        if self._scrape is not None:
            return self._scrape
        try:
            from jobspy import scrape_jobs  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on install
            raise SourceUnavailable(
                "python-jobspy kurulu değil. Kurulum: pip install 'jobradar[jobspy]'"
            ) from exc
        return scrape_jobs

    def queries(self, ctx: SourceContext) -> list[tuple[str, str, str, int | None]]:
        """(term, city_only_location, full_location, distance_miles)"""
        cfg = ctx.config
        out: list[tuple[str, str, str, int | None]] = []
        seen: set[tuple[str, str]] = set()
        for term, track in search_terms(ctx):
            places: list[tuple[str, str, int | None]]
            if track.nationwide or not cfg.search.locations:
                places = [(cfg.search.country, cfg.search.country, None)]
            else:
                places = [(l.city, f"{l.city}, {cfg.search.country}", max(5, round(l.radius_km / KM_PER_MILE)))
                          for l in cfg.search.locations]
            for city, full, miles in places:
                if (term.lower(), full) not in seen:
                    seen.add((term.lower(), full))
                    out.append((term, city, full, miles))
        return out[: cfg.sources.jobspy.max_queries]

    def _call(self, scrape, params: set[str], kwargs: dict[str, Any]):
        if params:
            kwargs = {k: v for k, v in kwargs.items() if k in params}
        try:
            return scrape(**kwargs)
        except TypeError:
            if kwargs.get("verbose", 0) is None:  # older JobSpy: verbose must be an int
                kwargs["verbose"] = 0
                return scrape(**kwargs)
            raise

    def fetch(self, ctx: SourceContext) -> list[RawJob]:
        cfg = ctx.config.sources.jobspy
        scrape = self._scrape_fn()
        try:
            params = set(inspect.signature(scrape).parameters)
        except (TypeError, ValueError):  # pragma: no cover
            params = set()
        # JobSpy logs every failure itself; JobRadar reports them once, briefly.
        logging.getLogger("jobspy").setLevel(logging.CRITICAL)
        sites = [s for s in cfg.sites if s]
        jobs: list[RawJob] = []
        errors: list[str] = []
        reported: set[str] = set()
        linkedin_blocks = 0
        queries = self.queries(ctx)
        for i, (term, city, full, miles) in enumerate(queries):
            if not sites:
                break
            ctx.report(i, len(queries), f"{term}, {city}")
            if i and cfg.pause_seconds:
                self._sleep(cfg.pause_seconds)
            # Glassdoor only resolves bare place names ("Aachen"), the others want "Aachen, Germany".
            groups = [[s for s in sites if s != "glassdoor"], [s for s in sites if s == "glassdoor"]]
            for group in groups:
                if not group:
                    continue
                kwargs: dict[str, Any] = {
                    "site_name": group,
                    "search_term": term,
                    "location": city if group == ["glassdoor"] else full,
                    "results_wanted": cfg.results_wanted,
                    "hours_old": cfg.hours_old,
                    "country_indeed": ctx.config.search.country,
                    "description_format": "markdown",
                    "verbose": None,
                }
                if miles:
                    kwargs["distance"] = miles
                if cfg.proxies:
                    kwargs["proxies"] = cfg.proxies
                if "fetch_description" in params:
                    kwargs["fetch_description"] = cfg.fetch_description
                elif "linkedin_fetch_description" in params:
                    kwargs["linkedin_fetch_description"] = cfg.fetch_description
                try:
                    df = self._call(scrape, params, kwargs)
                except Exception as exc:  # noqa: BLE001 - JobSpy raises many kinds
                    errors.append(f"'{term}' @ {full}: {exc}")
                    continue
                attrs = getattr(df, "attrs", {}) or {}
                site_errors = attrs.get("errors") or {}
                for site, msg in site_errors.items():
                    errors.append(f"{site}: {msg}")
                    key = f"{site}:{str(msg)[:40]}"
                    if key not in reported:
                        reported.add(key)
                        ctx.log(f"  ! {site}: {str(msg)[:120]}")
                records = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
                for row in records:
                    raw = row_to_raw(row)
                    if raw:
                        raw.extra["query"] = term
                        jobs.append(raw)
                if "linkedin" in site_errors and "429" in str(site_errors["linkedin"]):
                    linkedin_blocks += 1
                    if linkedin_blocks >= cfg.linkedin_max_blocks:
                        sites = [s for s in sites if s != "linkedin"]
                        ctx.log("  ! LinkedIn tekrar tekrar engelledi; bu çalıştırmada LinkedIn atlanıyor")
                        errors.append("linkedin: bu çalıştırmada devre dışı bırakıldı (429)")
                    elif cfg.linkedin_cooldown_seconds:
                        ctx.log(f"  … LinkedIn hız sınırı: {cfg.linkedin_cooldown_seconds} sn bekleniyor")
                        self._sleep(cfg.linkedin_cooldown_seconds)
        ctx.report(len(queries), len(queries))
        ctx.warnings.extend(errors)
        if not jobs and errors:
            raise SourceError("; ".join(errors[:3]))
        return jobs
