"""Cross-source deduplication.

Identity is tried in three steps (JobNavigator idea, extended):
1. canonical URL key (LinkedIn job id, Indeed jk, StepStone id, refnr ...)
2. company + title key with gender markers removed ("(m/w/d)" variants)
3. fuzzy title match inside the same company (>= 0.92 similarity)
"""

from __future__ import annotations

import hashlib
import sqlite3
from difflib import SequenceMatcher
from typing import Any, Optional

from jobradar import db
from jobradar.processing.normalize import is_aggregator

FUZZY_THRESHOLD = 0.92


def dedup_key(company_norm: str, title_norm: str) -> str:
    if not company_norm or not title_norm:
        return ""
    return hashlib.sha1(f"{company_norm}|{title_norm}".encode("utf-8")).hexdigest()[:16]


def job_id_from(key: str, url_key: str, fallback: str) -> str:
    basis = key or url_key or fallback
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def find_existing(conn: sqlite3.Connection, job: dict[str, Any], url_keys: list[str]) -> Optional[dict[str, Any]]:
    for uk in url_keys:
        if not uk:
            continue
        jid = db.job_id_for_url(conn, uk)
        if jid:
            existing = db.get_job(conn, jid)
            if existing:
                return existing
    key = job.get("dedup_key")
    if key:
        hits = db.jobs_by_dedup_key(conn, key)
        if hits:
            return hits[0]
    cn, tn = job.get("company_norm"), job.get("title_norm")
    if cn and tn:
        best: tuple[float, Optional[dict[str, Any]]] = (0.0, None)
        for other in db.jobs_by_company(conn, cn):
            ratio = SequenceMatcher(None, tn, other.get("title_norm", "")).ratio()
            if ratio > best[0]:
                best = (ratio, other)
        if best[0] >= FUZZY_THRESHOLD:
            return best[1]
    return None


def merge(existing: dict[str, Any], new: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Merge a freshly processed job into the stored one.

    Returns (merged_job, content_changed). Status, notes and LLM results of the
    stored job are never touched.
    """
    merged = dict(existing)
    changed = False
    sources = list(existing.get("sources") or [])
    known = {(s.get("source"), s.get("url")) for s in sources}
    for s in new.get("sources") or []:
        if (s.get("source"), s.get("url")) not in known:
            sources.append(s)
            known.add((s.get("source"), s.get("url")))
    merged["sources"] = sources

    if len(new.get("description") or "") > len(existing.get("description") or "") + 50:
        merged["description"] = new["description"]
        merged["lang"] = new.get("lang") or existing.get("lang", "")
        changed = True
    for field in ("company", "company_norm", "location", "employment_type"):
        if not existing.get(field) and new.get(field):
            merged[field] = new[field]
            changed = True
    if not existing.get("salary") and new.get("salary"):
        merged["salary"] = new["salary"]
        changed = True
    # Prefer the employer's own posting over an aggregator copy.
    for field in ("url", "apply_url"):
        old, cand = existing.get(field) or "", new.get(field) or ""
        if cand and (not old or (is_aggregator(old) and not is_aggregator(cand))):
            merged[field] = cand
    if new.get("posted_at") and (not existing.get("posted_at") or new["posted_at"] < existing["posted_at"]):
        merged["posted_at"] = new["posted_at"]
    if not existing.get("detail_ref") and new.get("detail_ref"):
        merged["detail_ref"] = new["detail_ref"]
    # A posting found by a search source is not a "global board" posting anymore.
    if existing.get("needs_location_check") and not new.get("needs_location_check"):
        merged["needs_location_check"] = False
        changed = True
    merged["last_seen"] = new.get("last_seen") or existing.get("last_seen")
    if existing.get("status") == "closed" and existing.get("live_status") == "closed":
        pass  # a closed posting that reappears stays closed until re-checked
    return merged, changed
