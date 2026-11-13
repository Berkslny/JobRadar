"""The pipeline: scan -> process -> dedup -> filter -> pre-score -> enrich ->
LLM evaluation -> notify."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

import httpx

from jobradar import db
from jobradar.config import AppConfig
from jobradar.http import make_client
from jobradar.models import RawJob
from jobradar.processing.dedup import dedup_key, find_existing, job_id_from, merge
from jobradar.processing.filters import FilterEngine
from jobradar.processing.flags import detect_all, detect_salary
from jobradar.processing.normalize import canonical_url, normalize_company, normalize_title
from jobradar.profile import Profile
from jobradar.scoring import usage
from jobradar.scoring.evaluate import evaluate_job
from jobradar.scoring.llm import BaseLLM, LLMError, is_fatal, llm_hint
from jobradar.scoring.prescore import PreScorer
from jobradar.sources import build_sources
from jobradar.sources.base import Source, SourceContext, SourceUnavailable
from jobradar.sources.importers import fetch_job_details
from jobradar.processing import guard
from jobradar.i18n import t
from jobradar.textutil import clean_text, detect_language, html_to_text, now_iso

Log = Callable[[str], None]


@dataclass
class IngestCounts:
    found: int = 0
    new: int = 0
    merged: int = 0
    filtered: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class SourceReport:
    name: str
    found: int = 0
    new: int = 0
    merged: int = 0
    filtered: int = 0
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0


class Processor:
    """Turns RawJobs into stored job dicts (normalise, flag, filter, pre-score)."""

    def __init__(self, cfg: AppConfig, profile: Profile):
        self.cfg = cfg
        self.profile = profile
        self.filters = FilterEngine(cfg, profile)
        self.prescorer = PreScorer(cfg, profile)

    def process(self, raw: RawJob) -> tuple[dict[str, Any], list[str]]:
        desc = html_to_text(raw.description) if raw.description_html else clean_text(raw.description)
        title = clean_text(raw.title)
        company = clean_text(raw.company)
        url, url_key = canonical_url(raw.url)
        apply_url = canonical_url(raw.apply_url)[0] if raw.apply_url else ""
        hints = {
            "raw_employment": raw.employment_type or "",
            "raw_level": str(raw.extra.get("job_level") or raw.extra.get("seniority") or ""),
            "raw_remote": raw.remote,
            "agency": bool(raw.extra.get("agency")),
            "stale": bool(raw.extra.get("stale")),
        }
        salary = None
        if raw.salary_min:
            salary = {"min": float(raw.salary_min), "max": float(raw.salary_max) if raw.salary_max else None,
                      "currency": raw.salary_currency or "EUR", "period": raw.salary_period or "year",
                      "source": "source"}
        elif raw.extra.get("salary_text"):
            salary = detect_salary(str(raw.extra["salary_text"]) + " €")
        cn, tn = normalize_company(company), normalize_title(title)
        key = dedup_key(cn, tn)
        now = now_iso()
        source_entry = {"source": raw.source, "url": url or raw.url, "external_id": raw.external_id, "seen": now[:10]}
        if raw.extra.get("origin"):
            source_entry["origin"] = raw.extra["origin"]
        job: dict[str, Any] = {
            "id": job_id_from(key, url_key, f"{raw.source}|{raw.external_id}|{title}|{company}"),
            "dedup_key": key, "title": title, "title_norm": tn, "company": company, "company_norm": cn,
            "location": clean_text(raw.location), "url": url or raw.url, "apply_url": apply_url,
            "description": desc, "lang": detect_language(desc or title), "posted_at": raw.posted_at,
            "first_seen": now, "last_seen": now, "salary": salary, "sources": [source_entry],
            "detail_ref": raw.detail_ref, "needs_location_check": raw.needs_location_check, "status": "new",
            "flags": {"hints": hints},
        }
        if raw.extra.get("closed"):
            job["live_status"] = "closed"
        self.refresh(job)
        return job, [url_key] if url_key else []

    def refresh(self, job: dict[str, Any]) -> None:
        """(Re)compute flags, filter verdict and pre-score from current fields."""
        hints = (job.get("flags") or {}).get("hints") or {}
        semantic = (job.get("flags") or {}).get("semantic")
        flags = detect_all(
            title=job.get("title", ""), company=job.get("company", ""), location=job.get("location", ""),
            text=job.get("description", ""), raw_employment=hints.get("raw_employment", ""),
            raw_remote=hints.get("raw_remote"), raw_level=hints.get("raw_level", ""), profile=self.profile,
        )
        flags["hints"] = hints
        if semantic and self.cfg.matching.enabled and self.cfg.matching.promote:
            flags["semantic"] = semantic  # a promotion by semantic matching survives a re-filter
        injection = guard.scan(job.get("description", ""))
        if injection:
            flags["injection"] = injection
        if hints.get("agency"):
            flags["agency"] = True
        if hints.get("stale"):
            flags["stale"] = True
        job["flags"] = flags
        job["employment_type"] = flags.get("employment_type") or ""
        job["seniority"] = flags.get("seniority") or ""
        job["remote"] = flags.get("remote") or ""
        if not job.get("salary"):
            job["salary"] = detect_salary(job.get("description", ""))
        job["lang"] = detect_language(job.get("description") or job.get("title", "")) or job.get("lang", "")
        reasons = self.filters.reasons(job)
        score, track, detail = self.prescorer.score(job)
        job["prescore"], job["prescore_detail"] = score, detail
        marker = flags.get("semantic") or {}
        if marker.get("promoted") and self.cfg.track(marker.get("track")):
            track = marker["track"]  # no keyword tied it to a track: the track it is closest to in meaning
        if not job.get("llm_score"):
            job["track"] = track
        if reasons:
            job["filtered_reason"] = "; ".join(reasons)
            if job.get("status") in (None, "new", "filtered"):
                job["status"] = "filtered"
        else:
            job["filtered_reason"] = None
            if job.get("status") == "filtered":
                job["status"] = "new"


def ingest(conn: sqlite3.Connection, proc: Processor, raws: Iterable[RawJob]) -> IngestCounts:
    counts = IngestCounts()
    for raw in raws:
        counts.found += 1
        try:
            job, keys = proc.process(raw)
        except Exception as exc:  # noqa: BLE001 - one bad posting must not stop a scan
            counts.errors.append(f"{raw.source}: {raw.title[:50]}: {exc}")
            continue
        if not job["title"]:
            continue
        existing = find_existing(conn, job, keys)
        if existing is None and db.get_job(conn, job["id"]):
            existing = db.get_job(conn, job["id"])
        if existing:
            merged, changed = merge(existing, job)
            if changed and merged.get("status") in ("new", "filtered"):
                proc.refresh(merged)
            db.update_job(conn, merged)
            target = merged["id"]
            counts.merged += 1
        else:
            db.insert_job(conn, job)
            target = job["id"]
            counts.new += 1
            if job["status"] == "filtered":
                counts.filtered += 1
        for k in keys:
            db.add_url(conn, k, target)
    conn.commit()
    return counts


def run_source(conn: sqlite3.Connection, cfg: AppConfig, profile: Profile, src: Source, client: httpx.Client,
               proc: Processor, log: Log, step: Optional[Callable[[int, int, str], None]] = None) -> SourceReport:
    rep = SourceReport(name=src.name)
    run_id = db.start_source_run(conn, src.name)
    ctx = SourceContext(config=cfg, profile=profile, client=client, log=log, step=step)
    t0 = time.monotonic()
    try:
        raws = src.fetch(ctx)
        counts = ingest(conn, proc, raws)
        rep.found, rep.new, rep.merged, rep.filtered = counts.found, counts.new, counts.merged, counts.filtered
        rep.warnings = ctx.warnings + counts.errors
    except SourceUnavailable as exc:
        rep.error = str(exc)
    except Exception as exc:  # noqa: BLE001
        rep.error = f"{type(exc).__name__}: {exc}"
        rep.warnings = ctx.warnings
    rep.seconds = time.monotonic() - t0
    db.finish_source_run(conn, run_id, found=rep.found, new=rep.new, merged=rep.merged, filtered=rep.filtered,
                         error=rep.error, warnings=rep.warnings)
    return rep


def run_scan(conn: sqlite3.Connection, cfg: AppConfig, profile: Profile, *, only: list[str] | None = None,
             log: Log = print, client: httpx.Client | None = None,
             sources: list[Source] | None = None,
             progress: Optional[Callable[[int, int, str], None]] = None,
             step: Optional[Callable[[int, int, str], None]] = None) -> list[SourceReport]:
    """Fetch and ingest every source. `progress(i, n, name)` is called before each source and at the end,
    `step(done, total, label)` inside a source (queries, companies) for a smoother progress bar."""
    client = client or make_client()
    proc = Processor(cfg, profile)
    reports = []
    todo = list(sources if sources is not None else build_sources(cfg, only))
    for i, src in enumerate(todo):
        if progress:
            progress(i, len(todo), src.name)
        log(f"→ {src.name} taranıyor...")
        rep = run_source(conn, cfg, profile, src, client, proc, log, step=step)
        if rep.error:
            log(f"  ✗ {src.name}: {rep.error}")
        else:
            log(f"  ✓ {src.name}: {rep.found} bulundu, {rep.new} yeni, {rep.merged} birleşti, {rep.filtered} elendi")
        reports.append(rep)
    if progress:
        progress(len(todo), len(todo), "")
    return reports


def import_raws(conn: sqlite3.Connection, cfg: AppConfig, profile: Profile, raws: list[RawJob],
                source_name: str = "import") -> IngestCounts:
    proc = Processor(cfg, profile)
    run_id = db.start_source_run(conn, source_name)
    counts = ingest(conn, proc, raws)
    db.finish_source_run(conn, run_id, found=counts.found, new=counts.new, merged=counts.merged,
                         filtered=counts.filtered, error=None, warnings=counts.errors)
    return counts


# ---------------------------------------------------------------------------
# Enrichment (descriptions for postings that arrived without one)
# ---------------------------------------------------------------------------


def _merge_duplicate_after_enrich(conn: sqlite3.Connection, job: dict[str, Any]) -> Optional[str]:
    """After enrichment a job may reveal it duplicates another (alert imports)."""
    if not job.get("dedup_key"):
        return None
    for other in db.jobs_by_dedup_key(conn, job["dedup_key"]):
        if other["id"] == job["id"]:
            continue
        has_work = conn.execute("SELECT 1 FROM evaluations WHERE job_id = ? UNION SELECT 1 FROM documents WHERE job_id = ?",
                                (job["id"], job["id"])).fetchone()
        if has_work or job.get("status") not in ("new", "filtered"):
            return None
        merged, _ = merge(other, job)
        db.update_job(conn, merged)
        db.reassign_urls(conn, job["id"], other["id"])
        db.move_label(conn, job["id"], other["id"])
        db.delete_job(conn, job["id"])
        return other["id"]
    return None


def enrich_one(conn: sqlite3.Connection, proc: Processor, client: httpx.Client, job: dict[str, Any]) -> tuple[bool, str]:
    try:
        data = fetch_job_details(client, job)
    except Exception as exc:  # noqa: BLE001
        db.update_fields(conn, job["id"], enriched_at=now_iso())
        db.add_event(conn, job["id"], "enrich_failed", str(exc)[:200])
        conn.commit()
        return False, str(exc)
    desc = clean_text(data.get("description") or "")
    if len(desc) > len(job.get("description") or ""):
        job["description"] = desc
    for f in ("company", "location", "apply_url", "posted_at", "employment_type"):
        if data.get(f) and not job.get(f):
            job[f] = data[f]
    if data.get("company") and not job.get("company_norm"):
        job["company_norm"] = normalize_company(data["company"])
        job["dedup_key"] = dedup_key(job["company_norm"], job.get("title_norm") or normalize_title(job["title"]))
    if data.get("salary_text") and not job.get("salary"):
        job["salary"] = detect_salary(str(data["salary_text"]) + " €")
    if data.get("closed"):
        job["live_status"] = "closed"
    hints = (job.get("flags") or {}).get("hints") or {}
    if data.get("employment_type") and not hints.get("raw_employment"):
        hints["raw_employment"] = data["employment_type"]
    if data.get("seniority") and not hints.get("raw_level"):
        hints["raw_level"] = data["seniority"]
    if data.get("agency"):
        hints["agency"] = True
    job.setdefault("flags", {})["hints"] = hints
    job["enriched_at"] = now_iso()
    if job.get("status") in ("new", "filtered"):
        proc.refresh(job)
    db.update_job(conn, job)
    merged_into = _merge_duplicate_after_enrich(conn, job)
    conn.commit()
    return True, merged_into or job["id"]


def _job_label(title: Any, company: Any) -> str:
    """Short "title · company" for the progress bar."""
    title, company = str(title or "").strip(), str(company or "").strip()
    if len(title) > 60:
        title = title[:59].rstrip() + "…"
    return f"{title} · {company[:40]}" if company else title


def enrich_pending(conn: sqlite3.Connection, cfg: AppConfig, profile: Profile, *, client: httpx.Client | None = None,
                   limit: int | None = None, log: Log = print, pause: float = 0.6,
                   progress: Optional[Callable[..., None]] = None) -> int:
    client = client or make_client()
    proc = Processor(cfg, profile)
    limit = limit if limit is not None else cfg.sources.enrich_per_run
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = 'new' AND enriched_at IS NULL AND length(description) < 400 "
        f"AND {db.EVALUABLE} ORDER BY prescore DESC LIMIT ?",
        (max(0.0, cfg.scoring.prescore_min - 10), limit),
    ).fetchall()
    done = 0
    for i, r in enumerate(rows):
        if progress:
            progress(i, len(rows), _job_label(r["title"], r["company"]))
        if i and pause:
            time.sleep(pause)
        ok, info = enrich_one(conn, proc, client, db.row_to_job(r))
        done += 1 if ok else 0
    if progress:
        progress(len(rows), len(rows))
    if rows:
        log(f"→ açıklama tamamlama: {done}/{len(rows)} ilan")
    return done


# ---------------------------------------------------------------------------
# LLM evaluation
# ---------------------------------------------------------------------------


def evaluation_queue(conn: sqlite3.Connection, cfg: AppConfig, *, limit: int, force: bool = False) -> list[dict[str, Any]]:
    """The postings the next evaluations go to, best first.

    With semantic matching on, the keyword rank and the semantic rank are fused and promoted postings are
    included; otherwise (or while no semantic score exists yet) the quick score alone decides."""
    if cfg.matching.enabled:
        from jobradar.scoring import match  # late: match imports the Processor from here

        ids = match.llm_queue(conn, cfg, limit=limit, force=force)
        if ids is not None:
            return [j for j in (db.get_job(conn, i) for i in ids) if j]
    q = ("SELECT * FROM jobs WHERE status IN ('new','shortlisted') AND prescore >= ? "
         + ("" if force else "AND llm_score IS NULL ") + "ORDER BY prescore DESC LIMIT ?")
    return [db.row_to_job(r) for r in conn.execute(q, (cfg.scoring.prescore_min, limit))]


def evaluate_pending(conn: sqlite3.Connection, cfg: AppConfig, profile: Profile, llm: BaseLLM, *,
                     limit: int | None = None, job_ids: list[str] | None = None, force: bool = False,
                     log: Log = print, client: httpx.Client | None = None,
                     progress: Optional[Callable[..., None]] = None) -> list[tuple[str, float]]:
    limit = limit if limit is not None else cfg.scoring.llm_max_per_run
    if job_ids:
        jobs = [j for j in (db.get_job(conn, i) for i in job_ids) if j]
    else:
        jobs = evaluation_queue(conn, cfg, limit=limit, force=force)
    proc = Processor(cfg, profile)
    results: list[tuple[str, float]] = []
    same_errors, last_error = 0, ""
    for idx, job in enumerate(jobs):
        if progress:
            progress(idx, len(jobs), _job_label(job.get("title"), job.get("company")))
        if len(job.get("description") or "") < 200 and not job.get("enriched_at"):
            client = client or make_client()
            ok, info = enrich_one(conn, proc, client, job)
            if ok and info != job["id"]:
                continue  # merged into another posting
            job = db.get_job(conn, job["id"]) or job
        if len(job.get("description") or "") < 200:
            log(f"  – {job['title'][:60]}: açıklama yok, değerlendirme atlandı")
            db.add_event(conn, job["id"], "eval_skipped", t("açıklama yok"))
            conn.commit()
            continue
        try:
            with usage.tagged(job_id=job["id"]):
                ev, notes, provider, model = evaluate_job(cfg, profile, job, llm)
        except LLMError as exc:
            msg = str(exc)
            log(f"  ✗ {job['title'][:60]}: {msg[:200]}")
            db.add_event(conn, job["id"], "eval_failed", msg[:300])
            conn.commit()
            if is_fatal(msg):
                log(f"→ Değerlendirme durduruldu. {llm_hint(llm.provider, msg)}")
                break
            same_errors = same_errors + 1 if msg == last_error else 1
            last_error = msg
            if same_errors >= 3:
                log("→ Aynı hata 3 kez üst üste geldi; değerlendirme durduruldu.")
                break
            continue
        same_errors, last_error = 0, ""
        db.save_evaluation(conn, job["id"], provider=provider, model=model, profile_hash=profile.content_hash(),
                           score=ev.global_score, verdict=ev.verdict, result=ev.model_dump(), notes=notes)
        if ev.track:
            db.update_fields(conn, job["id"], track=ev.track)
        conn.commit()
        results.append((job["id"], ev.global_score))
        log(f"  {ev.global_score:.1f}  {job['title'][:60]} @ {job.get('company', '')[:30]}")
    if progress:
        progress(len(jobs), len(jobs))
    return results


def refilter_all(conn: sqlite3.Connection, cfg: AppConfig, profile: Profile) -> tuple[int, int]:
    """Re-apply filters and pre-scores after config/profile changes."""
    proc = Processor(cfg, profile)
    changed = kept = 0
    for r in conn.execute("SELECT * FROM jobs WHERE status IN ('new','filtered')").fetchall():
        job = db.row_to_job(r)
        before = (job["status"], job["prescore"])
        proc.refresh(job)
        db.update_job(conn, job)
        if (job["status"], job["prescore"]) != before:
            changed += 1
        if job["status"] == "new":
            kept += 1
    conn.commit()
    return changed, kept
