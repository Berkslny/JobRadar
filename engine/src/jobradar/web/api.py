"""JSON API for the Mac app (and anything else): /api/v1/...

Long operations (evaluation, CV generation, a full run) start a background
task and return its id; clients poll /api/v1/tasks/{id}. Cloudflare closes
proxied requests after about 100 seconds, so nothing slow runs inline."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from jobradar import __version__, db, i18n, profile_tools
from jobradar.config import AppConfig
from jobradar.locks import cycle_running
from jobradar.mailsync import signal_view
from jobradar.progress import STAGES as PROGRESS_STAGES, read as read_progress
from jobradar.models import STATUS_LABELS_TR, STATUSES
from jobradar.notify import follow_ups_due
from jobradar.processing.flags import flag_labels
from jobradar.processing.normalize import canonical_url, clean_title
from jobradar.i18n import t as tr
from jobradar.profile import Profile
from jobradar.scoring import bench, match
from jobradar.scoring.llm import BaseLLM, LLMError, cost_label
from jobradar.scoring.llm import llm_label as llm_text
from jobradar.textutil import now_iso, today_iso

MAX_PAGE = 20000  # most postings one /jobs answer carries
FEATURES = ("labels", "bench", "matching")  # what a client may use beyond the 1.0 API (in /summary)

VIEWS: dict[str, Optional[list[str]]] = {
    "inbox": ["new", "shortlisted"],
    "active": ["shortlisted", "tailored", "approved", "applied", "interview"],
    "done": ["offer", "rejected", "skipped", "closed"],
    "filtered": ["filtered"],
    "all": None,
}


class TaskRunner:
    """Tiny in-process background task registry (one uvicorn worker)."""

    def __init__(self, keep: int = 60):
        self.keep = keep
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, fn: Callable[[], Any], job_id: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            for t in self._tasks.values():
                if t["kind"] == kind and t["job_id"] == job_id and t["status"] == "running":
                    return dict(t)
            tid = uuid.uuid4().hex[:12]
            rec: dict[str, Any] = {"id": tid, "kind": kind, "job_id": job_id, "status": "running",
                                   "started_at": now_iso(), "finished_at": None, "message": "", "result": None}
            self._tasks[tid] = rec
            lang = i18n.get_lang()
            if len(self._tasks) > self.keep:
                for old in sorted(self._tasks.values(), key=lambda t: t["started_at"])[: len(self._tasks) - self.keep]:
                    if old["status"] != "running":
                        self._tasks.pop(old["id"], None)

        def run() -> None:
            i18n.set_lang(lang)
            try:
                res = fn()
                rec.update(status="done", result=res)
            except Exception as exc:  # noqa: BLE001
                rec.update(status="error", message=str(exc)[:500])
            finally:
                rec["finished_at"] = now_iso()

        threading.Thread(target=run, name=f"jobradar-{kind}", daemon=True).start()
        return dict(rec)

    def get(self, tid: str) -> Optional[dict[str, Any]]:
        with self._lock:
            t = self._tasks.get(tid)
            return dict(t) if t else None

    def recent(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted((dict(t) for t in self._tasks.values()), key=lambda t: t["started_at"], reverse=True)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

REMOTE_TR = {"remote": "Tam uzaktan", "hybrid": "Hibrit", "onsite": "Ofiste"}
EMPLOYMENT_TR = {"fulltime": "Tam zamanlı", "parttime": "Yarı zamanlı", "werkstudent": "Werkstudent",
                 "internship": "Praktikum", "thesis": "Abschlussarbeit", "trainee": "Trainee",
                 "apprenticeship": "Ausbildung", "freelance": "Freelance", "contract": "Sözleşmeli"}
PERIOD_TR = {"year": "yıl", "month": "ay", "hour": "saat", "week": "hafta", "day": "gün"}


def salary_text(sal: Any) -> str:
    if not isinstance(sal, dict) or not sal.get("min"):
        return ""

    def money(v: Any) -> str:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return str(v)
        if f < 1000 and f != int(f):
            return f"{f:.2f}".replace(".", ",")
        return f"{f:,.0f}".replace(",", ".")

    amount = money(sal["min"]) + (f"–{money(sal['max'])}" if sal.get("max") else "")
    currency = "€" if (sal.get("currency") or "EUR") == "EUR" else str(sal.get("currency"))
    period = tr(PERIOD_TR.get(str(sal.get("period") or ""), str(sal.get("period") or "")))
    return f"{amount} {currency}" + (f" / {period}" if period else "")


def job_summary(job: dict[str, Any], german_level: str) -> dict[str, Any]:
    sources = sorted({(s.get("source") or "?").split(":")[0] for s in (job.get("sources") or [])})
    return {
        "id": job["id"],
        "title": clean_title(job.get("title", "")),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "track": job.get("track"),
        "status": job.get("status", "new"),
        "status_label": tr(STATUS_LABELS_TR.get(job.get("status", ""), job.get("status", ""))),
        "prescore": round(float(job.get("prescore") or 0), 1),
        "llm_score": job.get("llm_score"),
        "verdict": job.get("verdict"),
        "posted_at": job.get("posted_at"),
        "first_seen": job.get("first_seen"),
        "remote": job.get("remote") or "",
        "employment_type": job.get("employment_type") or "",
        "seniority": job.get("seniority") or "",
        "salary_text": salary_text(job.get("salary")),
        "remote_label": tr(REMOTE_TR.get(job.get("remote") or "", "")),
        "employment_label": tr(EMPLOYMENT_TR.get(job.get("employment_type") or "", "")),
        "url": job.get("url") or "",
        "apply_url": job.get("apply_url") or "",
        "sources": sources,
        "badges": [{"label": label, "kind": kind} for label, kind in flag_labels(job.get("flags") or {}, german_level)],
        "live_status": job.get("live_status"),
        "needs_location_check": bool(job.get("needs_location_check")),
        "status_changed_at": job.get("status_changed_at"),
        "applied_at": job.get("applied_at"),
    }


def _evidence_ids(result: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for req in result.get("requirements") or []:
        ids.update(str(x) for x in (req.get("evidence") or []))
    for key in ("strengths",):
        for item in result.get(key) or []:
            if isinstance(item, dict):
                ids.update(str(x) for x in (item.get("evidence") or []))
    return ids


def job_detail(conn: sqlite3.Connection, cfg: AppConfig, prof: Profile, job: dict[str, Any]) -> dict[str, Any]:
    out = job_summary(job, prof.german_level)
    ev = db.latest_evaluation(conn, job["id"])
    facts = {fid: f.text for fid, (f, _) in prof.fact_index().items()}
    used = _evidence_ids(ev["result"]) if ev else set()
    track = cfg.track(job.get("track"))
    out.update({
        "description": job.get("description") or "",
        "notes": job.get("notes") or "",
        "flags": job.get("flags") or {},
        "prescore_detail": job.get("prescore_detail") or {},
        "filtered_reason": job.get("filtered_reason"),
        "track_name": track.name if track else None,
        "evaluation": ev,
        "facts": {fid: facts[fid] for fid in sorted(used) if fid in facts},
        "documents": db.documents_for(conn, job["id"]),
        "events": db.events_for(conn, job["id"])[:60],
        "contacts": db.contacts_for_company(conn, job.get("company_norm", "")),
        "mail_signals": [signal_view(conn, x) for x in db.mail_signals_for_job(conn, job["id"])],
        "label": bench.label_name(db.get_label(conn, job["id"])),
        "match": match.job_view(conn, cfg, job["id"]) if cfg.matching.enabled else None,
    })
    return out


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class StatusIn(BaseModel):
    status: str
    note: str = ""


class NotesIn(BaseModel):
    notes: str = ""


class TailorIn(BaseModel):
    language: str = ""


class UrlIn(BaseModel):
    url: str


class SignalApplyIn(BaseModel):
    job_id: str = ""


class LabelIn(BaseModel):
    label: str = ""   # good | maybe | bad | skip; "" takes the verdict back
    note: str = ""


def build_router(cfg: AppConfig, *, llm_factory: Callable[[AppConfig], Optional[BaseLLM]],
                 start_cycle: Callable[[], bool], tasks: TaskRunner,
                 is_running: Optional[Callable[[], bool]] = None) -> APIRouter:
    from jobradar.web.api_setup import use_language

    r = APIRouter(prefix="/api/v1", dependencies=[Depends(use_language)])
    running_now = is_running or (lambda: cycle_running(cfg.data_path))

    def progress_now(c: sqlite3.Connection) -> Optional[dict[str, Any]]:
        """Stored progress with the stage label in the language of this request."""
        p = read_progress(c)
        if p and p.get("stage") in PROGRESS_STAGES:
            p["label"] = tr(PROGRESS_STAGES[p["stage"]][0])
        return p

    def conn() -> sqlite3.Connection:
        return db.connect(cfg.db_path)

    def profile() -> Profile:
        """The profile; an empty one while the user has not created it yet."""
        try:
            return profile_tools.load_or_empty(cfg.profile_path)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, tr("Profil geçersiz: {error}", error=str(exc)[:300])) from exc

    def need_profile() -> Profile:
        prof = profile()
        if not prof.name.strip():
            raise HTTPException(409, tr("Profil henüz yok. Önce profilini oluştur."))
        return prof

    def need_job(c: sqlite3.Connection, job_id: str) -> dict[str, Any]:
        job = db.get_job(c, job_id)
        if not job:
            raise HTTPException(404, tr("İlan bulunamadı"))
        return job

    def need_llm() -> BaseLLM:
        try:
            llm = llm_factory(cfg)
        except LLMError as exc:
            raise HTTPException(503, str(exc)) from exc
        if llm is None:
            raise HTTPException(503, tr("AI modeli bağlı değil"))
        return llm

    @r.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @r.get("/summary")
    def summary() -> dict[str, Any]:
        c = conn()
        try:
            counts = db.status_counts(c)
            pending = db.pending_evaluation_count(c, cfg.scoring.prescore_min)
            strong = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('new','shortlisted') AND llm_score >= ?",
                (cfg.notify.email.min_score,)).fetchone()[0]
            last_cycle = db.get_meta(c, "last_cycle", "")
            last_error = db.get_meta(c, "last_cycle_error", "")
            due = len(follow_ups_due(c, cfg))
            replies = db.pending_mail_signal_count(c)
            last_quick = db.get_meta(c, "last_quick_cycle", "")
            last_mail = db.get_meta(c, "last_mail_sync", "")
            mail_error = db.get_meta(c, "last_mail_sync_error", "")
            progress = progress_now(c)
        finally:
            c.close()
        prof = profile()
        try:
            llm = llm_factory(cfg)
            llm_label = llm_text(llm) if llm else tr("yok")
            llm_ready = llm is not None
        except LLMError as exc:
            llm_label = tr("hata: {error}", error=exc)
            llm_ready = False
        views = {k: sum(counts.get(s, 0) for s in (v or counts.keys())) for k, v in VIEWS.items()}
        return {
            "version": __version__, "counts": counts, "views": views, "pending_evaluation": pending,
            "strong_open": strong, "strong_threshold": cfg.notify.email.min_score, "follow_ups_due": due,
            "last_cycle": last_cycle, "last_error": last_error, "running": running_now(),
            "last_quick_cycle": last_quick, "mail_signals_pending": replies, "last_mail_sync": last_mail,
            "mail_sync_error": mail_error, "progress": progress,
            "llm": llm_label, "llm_ready": llm_ready, "profile_name": prof.name,
            "profile_missing": profile_tools.missing_basics(prof), "todo_facts": len(prof.todo_facts()),
            "language": i18n.get_lang(),
            "features": list(FEATURES), "matching_enabled": cfg.matching.enabled,
            "tracks": [{"id": t.id, "name": t.name} for t in cfg.enabled_tracks()],
            "statuses": [{"id": s, "label": tr(STATUS_LABELS_TR.get(s, s))} for s in STATUSES],
        }

    @r.get("/progress")
    def progress_ep() -> dict[str, Any]:
        """Cheap to poll every few seconds while a scan runs (progress bar)."""
        c = conn()
        try:
            return {"running": running_now(), "progress": progress_now(c)}
        finally:
            c.close()

    @r.get("/jobs")
    def jobs(view: str = "inbox", track: str = "", q: str = "", order: str = "score", min_score: float | None = None,
             limit: int = 0, offset: int = 0) -> dict[str, Any]:
        """Postings of a view. No limit (0) returns all of them; `total` is the size of the whole view,
        so a client can page with `offset`."""
        filters: dict[str, Any] = {"statuses": VIEWS.get(view, VIEWS["inbox"]), "track": track or None,
                                   "query": q or None, "include_filtered": view in ("filtered", "all"),
                                   "min_score": min_score}
        page = min(limit, MAX_PAGE) if limit > 0 else MAX_PAGE
        c = conn()
        try:
            rows = db.list_jobs(c, order=order, limit=page, offset=max(0, offset), **filters)
            total = db.count_jobs(c, **filters)
        finally:
            c.close()
        german = profile().german_level
        return {"jobs": [job_summary(j, german) for j in rows], "view": view, "total": total,
                "offset": max(0, offset)}

    @r.get("/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        c = conn()
        try:
            return job_detail(c, cfg, profile(), need_job(c, job_id))
        finally:
            c.close()

    @r.post("/jobs/{job_id}/status")
    def set_status(job_id: str, body: StatusIn) -> dict[str, Any]:
        if body.status not in STATUSES:
            raise HTTPException(400, tr("geçersiz durum"))
        c = conn()
        try:
            need_job(c, job_id)
            db.set_status(c, job_id, body.status, body.note)
            c.commit()
            return job_summary(need_job(c, job_id), profile().german_level)
        finally:
            c.close()

    @r.post("/jobs/{job_id}/notes")
    def set_notes(job_id: str, body: NotesIn) -> dict[str, Any]:
        c = conn()
        try:
            need_job(c, job_id)
            db.update_fields(c, job_id, notes=body.notes)
            c.commit()
        finally:
            c.close()
        return {"ok": True}

    @r.put("/jobs/{job_id}/label")
    def set_label(job_id: str, body: LabelIn) -> dict[str, Any]:
        """Your own verdict on a posting: the reference for the measurements (GET /bench)."""
        c = conn()
        try:
            need_job(c, job_id)
            try:
                name = bench.set_label(c, job_id, body.label, body.note)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        finally:
            c.close()
        return {"job_id": job_id, "label": name}

    @r.get("/labels/queue")
    def label_queue(limit: int = 10) -> dict[str, Any]:
        """Postings to judge next: a random sample of what the AI model sees and of what it never sees."""
        german = profile().german_level
        c = conn()
        try:
            ids, remaining = bench.label_queue(c, cfg, max(1, min(limit, 50)))
            jobs = []
            for job_id in ids:
                job = db.get_job(c, job_id)
                if job:
                    item = job_summary(job, german)
                    item["description"] = (job.get("description") or "")[:6000]
                    jobs.append(item)
            judged = c.execute("SELECT COUNT(*) FROM labels WHERE label >= 0").fetchone()[0]
        finally:
            c.close()
        return {"jobs": jobs, "remaining": sum(remaining.values()), "judged": int(judged)}

    @r.get("/bench")
    def bench_ep(days: int = 30, explicit: bool = False) -> dict[str, Any]:
        """Measurements on your own verdicts: rankings, the gate in front of the AI model, the judge, the cost."""
        prof = profile()
        c = conn()
        try:
            return bench.report(c, cfg, prof, days=max(1, min(days, 365)), explicit_only=explicit)
        finally:
            c.close()

    @r.post("/jobs/{job_id}/evaluate", status_code=202)
    def evaluate(job_id: str) -> dict[str, Any]:
        from jobradar.pipeline import evaluate_pending

        c = conn()
        try:
            need_job(c, job_id)
        finally:
            c.close()
        llm = need_llm()
        prof = need_profile()

        def work() -> dict[str, Any]:
            logs: list[str] = []
            c2 = conn()
            try:
                res = evaluate_pending(c2, cfg, prof, llm, job_ids=[job_id], force=True, log=logs.append)
            finally:
                c2.close()
            if not res:
                raise RuntimeError(logs[-1].strip() if logs else tr("değerlendirilemedi"))
            return {"score": res[0][1], "job_id": res[0][0]}

        return tasks.start("evaluate", work, job_id)

    @r.post("/jobs/{job_id}/tailor", status_code=202)
    def tailor(job_id: str, body: TailorIn) -> dict[str, Any]:
        from jobradar.tailor.generate import tailor_job

        c = conn()
        try:
            need_job(c, job_id)
        finally:
            c.close()
        llm = need_llm()
        prof = need_profile()

        def work() -> dict[str, Any]:
            c2 = conn()
            try:
                doc = tailor_job(cfg, prof, c2, job_id, llm, language=body.language or None)
            finally:
                c2.close()
            v = doc.get("validation") or {}
            return {"doc_id": doc.get("id"), "version": doc.get("version"), "validation_ok": bool(v.get("ok"))}

        return tasks.start("tailor", work, job_id)

    @r.post("/jobs/{job_id}/enrich")
    def enrich(job_id: str) -> dict[str, Any]:
        from jobradar.http import make_client
        from jobradar.pipeline import Processor, enrich_one

        c = conn()
        try:
            job = need_job(c, job_id)
            ok, info = enrich_one(c, Processor(cfg, profile()), make_client(), job)
        finally:
            c.close()
        return {"ok": ok, "job_id": info if ok else job_id, "message": "" if ok else str(info)}

    @r.post("/docs/{doc_id}/approve")
    def approve(doc_id: int) -> dict[str, Any]:
        c = conn()
        try:
            doc = db.get_document(c, doc_id)
            if not doc:
                raise HTTPException(404)
            db.approve_document(c, doc_id)
            job = db.get_job(c, doc["job_id"])
            if job and job["status"] in ("new", "shortlisted", "tailored"):
                db.set_status(c, doc["job_id"], "approved", tr("belgeler v{v} onaylandı", v=doc["version"]))
            c.commit()
        finally:
            c.close()
        return {"ok": True}

    @r.get("/docs/{doc_id}/files/{name}")
    def doc_file(doc_id: int, name: str) -> FileResponse:
        c = conn()
        try:
            doc = db.get_document(c, doc_id)
        finally:
            c.close()
        if not doc or name not in doc["files"]:
            raise HTTPException(404)
        base = cfg.applications_path.resolve()
        path = (base / doc["folder"] / name).resolve()
        if base not in path.parents or not path.is_file():
            raise HTTPException(404)
        media = {"html": "text/html", "md": "text/markdown; charset=utf-8", "pdf": "application/pdf",
                 "json": "application/json", "yaml": "text/plain; charset=utf-8"}.get(path.suffix.lstrip("."))
        return FileResponse(path, media_type=media, filename=name)

    @r.get("/docs/{doc_id}/diff")
    def doc_diff(doc_id: int) -> dict[str, Any]:
        from jobradar.tailor.diff import document_diff

        c = conn()
        try:
            doc = db.get_document(c, doc_id)
        finally:
            c.close()
        if not doc:
            raise HTTPException(404, tr("Belge bulunamadı"))
        try:
            data = document_diff(cfg.applications_path / doc["folder"], profile())
        except FileNotFoundError as exc:
            raise HTTPException(404, tr("Bu sürümde tailored.json yok")) from exc
        data.update({"doc_id": doc_id, "job_id": doc["job_id"], "version": doc["version"],
                     "validation": doc.get("validation") or {}})
        return data

    @r.get("/jobs/{job_id}/answers")
    def job_answers_ep(job_id: str) -> dict[str, Any]:
        from jobradar.answers import ensure_answers_file, job_answers

        ensure_answers_file(cfg)
        c = conn()
        try:
            try:
                return job_answers(cfg, c, profile(), need_job(c, job_id))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        finally:
            c.close()

    @r.get("/answers")
    def answers_ep() -> dict[str, Any]:
        from jobradar.answers import ensure_answers_file, load_general, profile_items
        from jobradar.tailor.generate import default_document_language

        ensure_answers_file(cfg)
        try:
            general, missing = load_general(cfg)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"language": default_document_language(cfg), "missing": missing,
                "groups": [{"id": "profile", "title": tr("Profil"), "items": profile_items(profile())},
                           {"id": "general", "title": tr("Genel sorular"), "items": general}]}

    @r.get("/mail-signals")
    def mail_signals_ep(state: str = "pending", limit: int = 100) -> dict[str, Any]:
        c = conn()
        try:
            rows = db.mail_signals(c, state=None if state == "all" else state, limit=max(1, min(limit, 500)))
            return {"signals": [signal_view(c, x) for x in rows], "pending": db.pending_mail_signal_count(c),
                    "last_sync": db.get_meta(c, "last_mail_sync", ""),
                    "last_error": db.get_meta(c, "last_mail_sync_error", "")}
        finally:
            c.close()

    @r.post("/mail-sync", status_code=202)
    def mail_sync_ep() -> dict[str, Any]:
        from jobradar.mailsync import imap_credentials, sync_mail

        if not imap_credentials(cfg):
            raise HTTPException(503, tr("E-posta ayarlı değil."))

        def work() -> dict[str, Any]:
            c2 = conn()
            try:
                res = sync_mail(c2, cfg)
            finally:
                c2.close()
            if res.error:
                raise RuntimeError(res.error)
            return {"checked": res.checked, "relevant": res.relevant, "new": len(res.new), "pending": res.pending}

        return tasks.start("mail_sync", work)

    @r.post("/mail-signals/{signal_id}/apply")
    def mail_signal_apply(signal_id: int, body: SignalApplyIn) -> dict[str, Any]:
        from jobradar.mailsync import apply_signal

        c = conn()
        try:
            return apply_signal(c, signal_id, body.job_id or None)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            c.close()

    @r.post("/mail-signals/{signal_id}/dismiss")
    def mail_signal_dismiss(signal_id: int) -> dict[str, Any]:
        from jobradar.mailsync import dismiss_signal

        c = conn()
        try:
            dismiss_signal(c, signal_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        finally:
            c.close()
        return {"ok": True}

    @r.get("/gaps")
    def gaps_ep(min_score: float = 3.0, days: int = 120, limit: int = 25) -> dict[str, Any]:
        from jobradar.scoring.gaps import skill_gaps

        c = conn()
        try:
            return skill_gaps(c, min_score=min_score, days=max(1, days), limit=max(1, min(limit, 100)))
        finally:
            c.close()

    @r.post("/import/url")
    def import_url(body: UrlIn) -> dict[str, Any]:
        from jobradar.http import make_client
        from jobradar.pipeline import import_raws
        from jobradar.sources.importers import raw_from_url

        try:
            raw = raw_from_url(make_client(), body.url.strip())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, tr("İlan okunamadı: {error}", error=exc)) from exc
        c = conn()
        try:
            counts = import_raws(c, cfg, profile(), [raw], "import:url")
            jid = db.job_id_for_url(c, canonical_url(raw.url)[1])
        finally:
            c.close()
        return {"job_id": jid, "new": bool(counts.new)}

    @r.post("/run", status_code=202)
    def run() -> dict[str, Any]:
        started = start_cycle()
        return {"started": started, "running": True}

    @r.get("/tasks")
    def task_list() -> dict[str, Any]:
        return {"tasks": tasks.recent()}

    @r.get("/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        t = tasks.get(task_id)
        if not t:
            raise HTTPException(404, tr("görev bulunamadı"))
        return t

    @r.get("/stats")
    def stats() -> dict[str, Any]:
        c = conn()
        try:
            counts = db.status_counts(c)
            sources = db.source_counts(c)
            health = db.source_health(c)
            runs = [dict(x) for x in c.execute(
                "SELECT source, started_at, finished_at, found, new, error FROM source_runs ORDER BY id DESC LIMIT 30")]
        finally:
            c.close()
        funnel = [{"status": s, "label": tr(STATUS_LABELS_TR[s]), "count": counts.get(s, 0)} for s in
                  ("new", "shortlisted", "tailored", "approved", "applied", "interview", "offer", "rejected")]
        return {"funnel": funnel, "sources": sources, "health": health, "runs": runs}

    @r.get("/backup")
    def backup() -> FileResponse:
        fd, tmp = tempfile.mkstemp(prefix="jobradar-", suffix=".db")
        os.close(fd)
        write_backup(cfg.db_path, Path(tmp))
        return FileResponse(tmp, media_type="application/vnd.sqlite3", filename=f"jobradar-{today_iso()}.db",
                            background=BackgroundTask(os.unlink, tmp))

    return r


def write_backup(db_path: Path, target: Path) -> Path:
    """Consistent copy of the live database (safe while other processes write)."""
    src = db.connect(db_path)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target
