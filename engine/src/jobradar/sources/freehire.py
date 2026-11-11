"""freehire.me open API: postings crawled from company ATSs, XING, EURES and
Arbeitsagentur (free for personal, non-commercial use)."""

from __future__ import annotations

import os
from typing import Any

from jobradar.http import get_json
from jobradar.models import RawJob
from jobradar.sources.base import Source, SourceContext, SourceError, search_terms
from jobradar.textutil import clean_text, parse_date

_EMPLOYMENT = {"full_time": "fulltime", "part_time": "parttime", "internship": "internship",
               "contract": "contract", "fellowship": "internship"}


def parse_item(item: dict[str, Any]) -> RawJob | None:
    title = clean_text(item.get("title") or "")
    url = str(item.get("url") or "")
    slug = str(item.get("public_slug") or "")
    if not title or not (url or slug):
        return None
    if item.get("closed_at"):
        return None
    enr = item.get("enrichment") or {}
    remote = None
    if item.get("work_mode") == "remote":
        remote = True
    origin = str(item.get("source") or "")
    return RawJob(
        source="freehire",
        title=title,
        company=clean_text(item.get("company") or ""),
        location=clean_text(item.get("location") or ", ".join(item.get("cities") or [])),
        url=url or f"https://freehire.me/jobs/{slug}",
        apply_url=url,
        external_id=slug,
        description=str(item.get("description") or ""),
        description_html="<" in str(item.get("description") or "")[:500],
        posted_at=parse_date(item.get("posted_at") or item.get("created_at")),
        employment_type=_EMPLOYMENT.get(str(enr.get("employment_type") or ""), ""),
        remote=remote,
        salary_min=enr.get("salary_min"),
        salary_max=enr.get("salary_max"),
        salary_currency=str(enr.get("salary_currency") or ""),
        salary_period=str(enr.get("salary_period") or ""),
        needs_location_check=True,
        detail_ref=f"url:{url}" if url else "",
        extra={"origin": origin, "freehire_slug": slug, "seniority": enr.get("seniority") or "",
               "countries": item.get("countries") or [],
               "agency": str(enr.get("company_type") or "") in ("outstaff", "agency"),
               "stale": (item.get("reality") or {}).get("class") == "stale"
               or bool((item.get("reality") or {}).get("fake_freshness"))},
    )


class FreehireSource(Source):
    name = "freehire"

    def fetch(self, ctx: SourceContext) -> list[RawJob]:
        cfg = ctx.config.sources.freehire
        base = cfg.base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        key = os.environ.get(cfg.api_key_env, "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        out: dict[str, RawJob] = {}
        errors: list[str] = []
        ok = 0
        limit = max(1, min(100, cfg.limit))
        terms = search_terms(ctx, cfg.max_queries)
        for qi, (term, _track) in enumerate(terms):
            ctx.report(qi, len(terms), term)
            for page in range(max(1, cfg.max_pages)):
                params = {
                    "q": term,
                    "countries": ",".join(cfg.countries),
                    "limit": limit,
                    "offset": page * limit,
                    "posted_within_days": cfg.posted_within_days,
                    "sort": "posted_at",
                    "order": "desc",
                }
                try:
                    data = get_json(ctx.client, f"{base}/jobs/search", params=params, headers=headers)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"'{term}': {exc}")
                    break
                ok += 1
                items = (data or {}).get("data") or []
                for item in items:
                    raw = parse_item(item) if isinstance(item, dict) else None
                    if raw:
                        raw.extra["query"] = term
                        out.setdefault(raw.external_id or raw.url, raw)
                total = ((data or {}).get("meta") or {}).get("total")
                if len(items) < limit or (isinstance(total, int) and (page + 1) * limit >= total):
                    break
        ctx.report(len(terms), len(terms))
        ctx.warnings.extend(errors)
        if ok == 0 and errors:
            raise SourceError(errors[0])
        return list(out.values())
