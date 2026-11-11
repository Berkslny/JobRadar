"""Bundesagentur für Arbeit - Jobsuche API (official, free).

List endpoint v6 (``ergebnisliste``) with the public client key; details via
``/pc/v4/jobdetails/{base64(refnr)}``. Endpoints follow bundesAPI/jobsuche-api
and career-ops' provider.
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from jobradar.http import get_json
from jobradar.models import RawJob
from jobradar.sources.base import Source, SourceContext, SourceError, search_terms
from jobradar.textutil import clean_text, html_to_text, parse_date

LIST_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
DETAIL_URLS = [
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{code}",
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v3/jobdetails/{code}",
]
DETAIL_PAGE = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}"
HEADERS = {"X-API-Key": "jobboerse-jobsuche", "Accept": "application/json"}
# v6 lists carry datumErsteVeroeffentlichung; older versions used other names.
_DATE_KEYS = (
    "datumErsteVeroeffentlichung", "aktuelleVeroeffentlichungsdatum", "veroeffentlichungsdatum",
    "ersteVeroeffentlichungsdatum", "veroeffentlichtAm", "modifikationsTimestamp",
)


def detail_page_url(refnr: str) -> str:
    # The public page wants a slash in the refnr encoded twice.
    return DETAIL_PAGE.format(ref=quote(refnr, safe="").replace("%2F", "%252F"))


def _location(item: dict[str, Any]) -> str:
    places: list[str] = []
    for entry in item.get("stellenlokationen") or []:
        adr = (entry or {}).get("adresse") or {}
        ort = str(adr.get("ort") or "").strip()
        land = str(adr.get("land") or "").strip()
        if land and land.upper() not in ("DEUTSCHLAND", "GERMANY", "DE"):
            place = f"{ort}, {land.title()}" if ort else land.title()
        else:
            place = ort
        if place and place not in places:
            places.append(place)
    if not places:
        ao = item.get("arbeitsort") or {}
        if isinstance(ao, dict):
            ort = str(ao.get("ort") or "").strip()
            if ort:
                places.append(ort)
    return " · ".join(places)


def parse_list(data: Any, angebotsart: int | None = None) -> list[RawJob]:
    if not isinstance(data, dict):
        return []
    items = data.get("ergebnisliste")
    if items is None:
        items = data.get("stellenangebote") or []
    out: list[RawJob] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        refnr = str(item.get("referenznummer") or item.get("refnr") or "").strip()
        title = clean_text(item.get("stellenangebotsTitel") or item.get("titel") or item.get("beruf") or "")
        if not refnr or not title:
            continue
        posted = None
        for key in _DATE_KEYS:
            posted = parse_date(item.get(key))
            if posted:
                break
        remote = None
        try:
            if float(item.get("homeofficeprozent") or 0) >= 100:
                remote = True
        except (TypeError, ValueError):
            pass
        employment = ""
        if item.get("arbeitszeitVollzeit") is True:
            employment = "fulltime"
        elif item.get("arbeitszeitTeilzeitFlexibel") or item.get("arbeitszeitTeilzeitVormittag"):
            employment = "parttime"
        out.append(RawJob(
            source="arbeitsagentur",
            title=title,
            company=clean_text(item.get("firma") or item.get("arbeitgeber") or ""),
            location=_location(item),
            url=detail_page_url(refnr),
            apply_url=str(item.get("externeUrl") or ""),
            external_id=refnr,
            posted_at=posted,
            employment_type=employment,
            remote=remote,
            detail_ref=f"aa:{refnr}",
            extra={"angebotsart": angebotsart, "beruf": item.get("hauptberuf") or item.get("beruf") or "",
                   "distance_km": item.get("entfernung")},
        ))
    return out


def fetch_detail(client: httpx.Client, refnr: str) -> dict[str, Any]:
    code = base64.b64encode(refnr.encode("utf-8")).decode("ascii")
    last: Exception | None = None
    for tmpl in DETAIL_URLS:
        try:
            data = get_json(client, tmpl.format(code=code), headers=HEADERS, retries=2)
        except Exception as exc:  # noqa: BLE001
            last = exc
            continue
        if not isinstance(data, dict):
            continue
        desc = data.get("stellenangebotsBeschreibung") or data.get("stellenbeschreibung") or ""
        out: dict[str, Any] = {"description": html_to_text(desc)}
        company = data.get("firma") or data.get("arbeitgeber")
        if company:
            out["company"] = clean_text(company)
        ext = data.get("externeUrl") or data.get("allianzpartnerUrl")
        if ext:
            out["apply_url"] = str(ext)
        verg = data.get("verguetung")
        if isinstance(verg, str) and verg and verg != "KEINE_ANGABEN":
            out["salary_text"] = clean_text(verg)
        if data.get("istArbeitnehmerUeberlassung") or data.get("istPrivateArbeitsvermittlung"):
            out["agency"] = True
        return out
    raise SourceError(f"Arbeitsagentur detayı alınamadı ({refnr}): {last}")


class ArbeitsagenturSource(Source):
    name = "arbeitsagentur"

    def queries(self, ctx: SourceContext) -> list[tuple[str, str | None, int | None]]:
        out: list[tuple[str, str | None, int | None]] = []
        for term, track in search_terms(ctx):
            if track.nationwide or not ctx.config.search.locations:
                out.append((term, None, None))
            else:
                for loc in ctx.config.search.locations:
                    out.append((term, loc.city, loc.radius_km))
        return out

    def fetch(self, ctx: SourceContext) -> list[RawJob]:
        cfg = ctx.config.sources.arbeitsagentur
        by_ref: dict[str, RawJob] = {}
        errors: list[str] = []
        ok = 0
        queries = self.queries(ctx)
        for qi, (was, wo, umkreis) in enumerate(queries):
            ctx.report(qi, len(queries), f"{was}, {wo}" if wo else was)
            for art in cfg.angebotsart or [1]:
                for page in range(1, max(1, cfg.max_pages) + 1):
                    params: dict[str, Any] = {
                        "was": was, "size": cfg.size, "page": page, "angebotsart": art,
                        "veroeffentlichtseit": cfg.days,
                        "zeitarbeit": "true" if cfg.include_zeitarbeit else "false",
                        "pav": "true" if cfg.include_private_agencies else "false",
                    }
                    if wo:
                        params["wo"] = wo
                        params["umkreis"] = umkreis or 50
                    try:
                        data = get_json(ctx.client, LIST_URL, params=params, headers=HEADERS)
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"'{was}'/{wo or 'DE'}/{art}/s{page}: {exc}")
                        break
                    ok += 1
                    batch = parse_list(data, art)
                    for raw in batch:
                        raw.extra["query"] = was
                        by_ref.setdefault(raw.external_id, raw)
                    items = (data or {}).get("ergebnisliste") if isinstance(data, dict) else None
                    if len(items or []) < cfg.size:
                        break
        ctx.report(len(queries), len(queries))
        ctx.warnings.extend(errors)
        if ok == 0 and errors:
            raise SourceError(errors[0])
        return list(by_ref.values())
