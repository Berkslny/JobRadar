"""Search settings for the app: what to look for, where, and on which sources; plus an AI-made first setup."""

from __future__ import annotations

import importlib.util
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from jobradar import settings
from jobradar.config import ATS_TYPES, EMPLOYMENT_TYPES, AppConfig, TrackConfig
from jobradar.geo import COUNTRIES, country_code, country_name, is_germany
from jobradar.i18n import language_name
from jobradar.profile import Profile
from jobradar.scoring.llm import BaseLLM, complete_json
from jobradar.textutil import fold_umlauts, truncate

JOBSPY_SITES = ["linkedin", "indeed", "glassdoor", "google", "zip_recruiter", "bayt", "naukri"]


def jobspy_installed() -> bool:
    return importlib.util.find_spec("jobspy") is not None


def view(cfg: AppConfig) -> dict[str, Any]:
    s, src = cfg.search, cfg.sources
    return {
        "country": country_code(s.country), "country_name": s.country,
        "locations": [loc.model_dump() for loc in s.locations],
        "include_remote": s.include_remote, "max_age_days": s.max_age_days,
        "employment_types": list(s.employment_types),
        "tracks": [t.model_dump() for t in cfg.tracks],
        "sources": {
            "jobspy": {"enabled": src.jobspy.enabled, "sites": list(src.jobspy.sites),
                       "installed": jobspy_installed()},
            "arbeitsagentur": {"enabled": src.arbeitsagentur.enabled and is_germany(s.country),
                               "available": is_germany(s.country)},
            "freehire": {"enabled": src.freehire.enabled},
            "companies": [c.model_dump() for c in src.companies],
        },
        "filters": {"title_exclude": list(cfg.filters.title_exclude),
                    "company_blacklist": list(cfg.filters.company_blacklist),
                    "exclude_senior": cfg.filters.exclude_senior, "exclude_agencies": cfg.filters.exclude_agencies,
                    "require_track_match": cfg.filters.require_track_match},
        "scoring": {"llm_max_per_run": cfg.scoring.llm_max_per_run, "prescore_min": cfg.scoring.prescore_min,
                    "apply_threshold": cfg.scoring.apply_threshold},
        "options": {"countries": [{"code": c, "name": n} for c, n in COUNTRIES],
                    "employment_types": EMPLOYMENT_TYPES, "ats_types": ATS_TYPES, "jobspy_sites": JOBSPY_SITES},
    }


def track_id(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", fold_umlauts(name or "").lower()).strip("-")[:24] or "track"
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _strings(values: Any, limit: int = 80) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values or []:
        s = str(v).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:limit]


def normalize_tracks(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable unique ids, priority by order, clean keyword lists."""
    taken: set[str] = set()
    out = []
    for i, raw in enumerate(tracks or []):
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        tid = str(raw.get("id") or "").strip()
        if not tid or tid in taken or not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", tid):
            tid = track_id(name, taken)
        taken.add(tid)
        terms = _strings(raw.get("search_terms"), 12)
        titles = _strings(raw.get("title_keywords"))
        out.append(TrackConfig(
            id=tid, name=name, priority=i + 1, enabled=bool(raw.get("enabled", True)),
            title_keywords=titles or terms, domain_keywords=_strings(raw.get("domain_keywords")),
            search_terms=terms or titles[:5], north_star=str(raw.get("north_star") or "").strip(),
            nationwide=bool(raw.get("nationwide", False))).model_dump())
    return out


def save(cfg: AppConfig, body: dict[str, Any]) -> None:
    """Store the parts of the search settings that ``body`` contains."""
    patch: dict[str, Any] = {}
    search: dict[str, Any] = {}
    sources: dict[str, Any] = {k: dict(v) for k, v in (body.get("sources") or {}).items()
                               if k in ("jobspy", "arbeitsagentur", "freehire") and isinstance(v, dict)}
    for key in ("jobspy", "arbeitsagentur", "freehire"):
        if key in sources:
            sources[key] = {k: v for k, v in sources[key].items() if k in ("enabled", "sites")}
    if "country" in body:
        code = country_code(str(body["country"]))
        search["country"] = country_name(code) if code else str(body["country"]).strip()
        was_germany = is_germany(cfg.search.country)
        sources.setdefault("freehire", {})["countries"] = [code] if code else []
        if code == "DE" and not was_germany:
            sources.setdefault("arbeitsagentur", {}).setdefault("enabled", True)
        if code != "DE":
            sources.setdefault("arbeitsagentur", {})["enabled"] = False
    if "locations" in body:
        locs = []
        for loc in body["locations"] or []:
            city = str(loc.get("city") or "").strip()
            if city:
                locs.append({"city": city, "radius_km": max(5, min(500, int(loc.get("radius_km") or 50)))})
        search["locations"] = locs
        search["preferred_cities"] = [x["city"] for x in locs]
        patch.setdefault("tailor", {})["sender_city"] = locs[0]["city"] if locs else cfg.tailor.sender_city
    for key in ("include_remote", "max_age_days"):
        if key in body:
            search[key] = body[key]
    if "employment_types" in body:
        search["employment_types"] = [e for e in body["employment_types"] or [] if e in EMPLOYMENT_TYPES] or ["fulltime"]
    if "tracks" in body:
        patch["tracks"] = normalize_tracks(body["tracks"])
    if "companies" in (body.get("sources") or {}):
        sources["companies"] = [c for c in body["sources"]["companies"] or [] if str(c.get("name") or "").strip()]
    if "filters" in body:
        allowed = ("title_exclude", "company_blacklist", "exclude_senior", "exclude_agencies", "require_track_match")
        patch["filters"] = {k: (_strings(v, 200) if isinstance(v, list) else v)
                            for k, v in (body["filters"] or {}).items() if k in allowed}
    if "scoring" in body:
        allowed = ("llm_max_per_run", "prescore_min", "apply_threshold")
        patch["scoring"] = {k: v for k, v in (body["scoring"] or {}).items() if k in allowed}
    if search:
        patch["search"] = search
    if sources:
        patch["sources"] = sources
    if patch:
        settings.update(cfg, patch)


# ---------------------------------------------------------------------------
# First setup made by the model
# ---------------------------------------------------------------------------


class _TrackDraft(BaseModel):
    id: str = ""
    name: str = ""
    north_star: str = ""
    title_keywords: list[str] = Field(default_factory=list)
    domain_keywords: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)


class SearchDraft(BaseModel):
    tracks: list[_TrackDraft] = Field(default_factory=list)
    title_exclude: list[str] = Field(default_factory=list)
    exclude_senior: bool = True


SUGGEST_SYSTEM = """You set up an automated job search for ONE candidate. From the candidate's own description of what they want, and their profile, define 1 to 3 search tracks. Use more than one track only for clearly different directions.

Rules:
1. Follow what the candidate asks for. Use the profile only to choose a realistic level and fitting keywords. Do not invent other career directions.
2. title_keywords: 15-30 words or word stems that appear in the TITLES of matching postings on job boards in COUNTRY, in the local language(s) of COUNTRY and in English. Stems are welcome (e.g. "Entwickl" matches Entwickler and Entwicklung). No generic words on their own (Engineer, Manager, m/w/d).
3. domain_keywords: 10-20 tools, technologies and domain terms that appear in matching DESCRIPTIONS.
4. search_terms: 4-6 queries for a job board's search box, the most productive first, in the local language and in English, 1-3 words each.
5. north_star: 1-2 sentences in English describing the ideal role (field, level, kind of employer, place).
6. name: a short display name in UI_LANGUAGE.
7. title_exclude: up to 15 title words that mark clearly unrelated postings for this candidate (other professions that share a keyword). Never exclude a word that is among the title_keywords.
8. exclude_senior: true unless the candidate has 8+ years of experience or asks for senior or lead roles.
9. Output exactly one JSON object. No markdown, no commentary."""

SUGGEST_SCHEMA = """{
  "tracks": [{"id": "lowercase-slug", "name": "", "north_star": "", "title_keywords": [], "domain_keywords": [], "search_terms": []}],
  "title_exclude": [],
  "exclude_senior": true
}"""


def fallback(roles: str) -> dict[str, Any]:
    """Without a model: one track per line or comma-separated role, the words themselves as keywords."""
    names = [r.strip() for r in re.split(r"[\n,;]+", roles or "") if r.strip()][:3]
    tracks = [{"name": n, "title_keywords": [n] + [w for w in n.split() if len(w) > 3], "search_terms": [n],
               "domain_keywords": [], "north_star": n} for n in names]
    return {"tracks": normalize_tracks(tracks), "title_exclude": [], "exclude_senior": True}


def suggest(llm: Optional[BaseLLM], profile: Optional[Profile], *, roles: str, country: str, where: str,
            ui_lang: str, tier: str = "smart") -> dict[str, Any]:
    """Tracks and filters for a new user. Nothing is saved; the client shows them for review."""
    if llm is None:
        return fallback(roles)
    facts = truncate(profile.fact_bank_text(), 6000) if profile and profile.name else "(no profile yet)"
    user = f"""TASK: SET UP SEARCH
COUNTRY: {country or 'not given'}
UI_LANGUAGE: {language_name(ui_lang)}

## What the candidate is looking for (their own words)
<<<WISH
{truncate(roles, 1500)}
WISH>>>

## Where
{where or 'not given'}

## Candidate profile
{facts}

## Output JSON schema
{SUGGEST_SCHEMA}"""
    draft, _ = complete_json(llm, SUGGEST_SYSTEM, user, SearchDraft, tier=tier, max_tokens=3000)
    tracks = normalize_tracks([t.model_dump() for t in draft.tracks][:3])
    if not tracks:
        return fallback(roles)
    keywords = {k.lower() for t in tracks for k in t["title_keywords"]}
    return {"tracks": tracks, "title_exclude": [w for w in _strings(draft.title_exclude, 15) if w.lower() not in keywords],
            "exclude_senior": draft.exclude_senior}
