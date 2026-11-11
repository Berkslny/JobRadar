"""Is a posting still open? Conservative by design (career-ops lesson): a
false 'closed' hides a real job, so only definitive signals count."""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

import httpx

from jobradar import db
from jobradar.http import request
from jobradar.processing.normalize import canonical_url
from jobradar.i18n import t
from jobradar.sources.importers import LINKEDIN_GUEST, parse_linkedin_guest
from jobradar.textutil import now_iso

CLOSED_PHRASES = re.compile(
    r"no longer accepting applications|this job is no longer available|this position has been filled"
    r"|job (?:posting )?has expired|the job you are looking for is no longer|position is no longer available"
    r"|stellenanzeige ist (?:leider )?nicht mehr (?:verfügbar|aktiv|online)|diese stelle ist (?:leider )?(?:nicht mehr|bereits)"
    r"|stelle (?:wurde|ist) bereits besetzt|stellenangebot ist (?:abgelaufen|nicht mehr verfügbar)"
    r"|anzeige ist (?:abgelaufen|nicht mehr aktiv)|job ist nicht mehr verfügbar",
    re.IGNORECASE,
)


def check_url(client: httpx.Client, url: str) -> tuple[str, str]:
    """Return (verdict, reason) with verdict in live|closed|uncertain."""
    if not url:
        return "uncertain", t("adres yok")
    _, key = canonical_url(url)
    try:
        if key.startswith("linkedin:"):
            resp = request(client, "GET", LINKEDIN_GUEST.format(id=key.split(":", 1)[1]), retries=2)
            if resp.status_code == 200:
                data = parse_linkedin_guest(resp.text)
                if data.get("closed"):
                    return "closed", t("LinkedIn: başvuru kabul edilmiyor")
                return ("live", "LinkedIn") if data.get("title") else ("uncertain", t("LinkedIn sayfası okunamadı"))
            return "uncertain", f"LinkedIn HTTP {resp.status_code}"
        resp = request(client, "GET", url, retries=2)
    except httpx.HTTPError as exc:
        return "uncertain", t("bağlantı hatası: {error}", error=type(exc).__name__)
    if resp.status_code in (404, 410):
        return "closed", f"HTTP {resp.status_code}"
    if resp.status_code >= 400:
        return "uncertain", f"HTTP {resp.status_code}"
    if CLOSED_PHRASES.search(resp.text[:200000]):
        return "closed", t("sayfada 'ilan kapandı' ifadesi var")
    return "live", f"HTTP {resp.status_code}"


def recheck(conn: sqlite3.Connection, client: httpx.Client, *, statuses: tuple[str, ...] = (
        "shortlisted", "tailored", "approved"), pause: float = 0.8, log=print) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT * FROM jobs WHERE status IN ({','.join('?' * len(statuses))})", statuses).fetchall()
    stats = {"live": 0, "closed": 0, "uncertain": 0}
    for i, r in enumerate(rows):
        if i and pause:
            time.sleep(pause)
        job: dict[str, Any] = db.row_to_job(r)
        verdict, reason = check_url(client, job.get("apply_url") or job.get("url"))
        stats[verdict] += 1
        db.update_fields(conn, job["id"], live_status=verdict, live_checked_at=now_iso())
        if verdict == "closed":
            db.add_event(conn, job["id"], "closed", reason)
            db.set_status(conn, job["id"], "closed", reason)
        log(f"  {verdict:9s} {job['title'][:60]} ({reason})")
    conn.commit()
    return stats
