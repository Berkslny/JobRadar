"""Dashboard (FastAPI + Jinja2) and JSON API. Binds to 127.0.0.1; on a server it is
reached through Cloudflare Tunnel and protected by JOBRADAR_API_TOKEN (see web/auth.py)."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jobradar import db, profile_tools
from jobradar.config import AppConfig
from jobradar.answers import ensure_answers_file, job_answers
from jobradar.locks import cycle_running
from jobradar.progress import mark_queued, read as read_progress
from jobradar.mailsync import (KIND_TR, apply_signal, dismiss_signal, imap_credentials, signal_view, sync_mail,
                               tracked_jobs)
from jobradar.scoring.gaps import skill_gaps
from jobradar.web import auth
from jobradar.web.api import TaskRunner, build_router
from jobradar.web.api_setup import build_setup_router
from jobradar.connections import parse_connections_csv
from jobradar.models import PIPELINE_COLUMNS, STATUS_LABELS_TR, STATUSES
from jobradar.notify import follow_ups_due
from jobradar.pipeline import Processor, enrich_one, evaluate_pending, import_raws
from jobradar.processing.flags import flag_labels
from jobradar.processing.normalize import canonical_url, clean_title
from jobradar.profile import Profile
from jobradar.scoring.llm import BaseLLM, LLMError, get_llm
from jobradar.sources.importers import parse_alert_email, raw_from_url
from jobradar.http import make_client
from jobradar.textutil import days_since

HERE = Path(__file__).parent
_scan_lock = threading.Lock()
WEB_LIST_LIMIT = 2000  # rows on one panel page; above that the page says how many are left out


def _redirect(url: str, msg: str = "", kind: str = "ok") -> RedirectResponse:
    if msg:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}msg={quote(msg)}&kind={kind}"
    return RedirectResponse(url, status_code=303)


def create_app(cfg: AppConfig, *, llm_factory: Optional[Callable[[AppConfig], Optional[BaseLLM]]] = None,
               cycle_runner: Optional[Callable[[AppConfig], Any]] = None) -> FastAPI:
    app = FastAPI(title="JobRadar", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    llm_factory = llm_factory or get_llm
    limiter = auth.LoginLimiter()
    open_paths = {"/login", "/api/v1/health", "/favicon.ico", "/open"}

    @app.middleware("http")
    async def require_auth(request: Request, call_next):
        path = request.url.path
        if path.startswith("/static/") or path.startswith("/open/") or path in open_paths:
            return await call_next(request)
        token = auth.api_token(cfg)
        if not token:
            if auth.is_direct_local(request):
                return await call_next(request)
            return JSONResponse({"detail": "Uzak erişim kapalı: sunucuda JOBRADAR_API_TOKEN tanımlı değil."},
                                status_code=403)
        if auth.bearer_ok(token, request.headers.get("authorization")) or \
                auth.valid_session(token, request.cookies.get(auth.COOKIE)):
            return await call_next(request)
        if path.startswith("/api/") or path.startswith("/files/"):
            return JSONResponse({"detail": "Yetkisiz: geçerli bir API anahtarı gerekli."}, status_code=401)
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)

    @app.get("/open", response_class=HTMLResponse)
    @app.get("/open/job/{job_id}", response_class=HTMLResponse)
    def open_in_app(job_id: str = "") -> HTMLResponse:
        """Links in e-mails: hand over to the Mac app (jobradar://). Carries no data, so it needs no sign-in."""
        safe = "".join(ch for ch in job_id if ch.isalnum() or ch in "-_")[:64]
        target = f"jobradar://job/{safe}" if safe else "jobradar://open"
        return HTMLResponse(
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>JobRadar</title>"
            f"<meta http-equiv='refresh' content='0;url={target}'></head>"
            "<body style='font-family:-apple-system,sans-serif;padding:40px;text-align:center'>"
            f"<p><a href='{target}'>JobRadar</a></p></body></html>")

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = "/jobs", error: str = "") -> HTMLResponse:
        return templates.TemplateResponse(request, "login.html", {"next": next, "error": error})

    @app.post("/login")
    def login(request: Request, token: str = Form(...), next: str = Form("/jobs")) -> RedirectResponse:
        key = auth.client_ip(request)
        if limiter.blocked(key):
            return RedirectResponse("/login?error=" + quote("Çok fazla deneme. 15 dakika sonra tekrar dene."),
                                    status_code=303)
        expected = auth.api_token(cfg)
        if not expected or not auth.bearer_ok(expected, f"Bearer {token.strip()}"):
            limiter.fail(key)
            return RedirectResponse(f"/login?next={quote(next, safe='')}&error=" + quote("Anahtar hatalı."),
                                    status_code=303)
        limiter.reset(key)
        target = next if next.startswith("/") and not next.startswith(("//", "/\\")) else "/jobs"
        resp = RedirectResponse(target, status_code=303)
        resp.set_cookie(auth.COOKIE, auth.make_session(expected, cfg.server.session_days),
                        max_age=cfg.server.session_days * 86400, httponly=True, samesite="lax",
                        secure=auth.is_https(request))
        return resp

    @app.post("/logout")
    def logout() -> RedirectResponse:
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(auth.COOKIE)
        return resp

    env = templates.env
    env.globals.update(STATUS_LABELS=STATUS_LABELS_TR, STATUSES=STATUSES, PIPELINE_COLUMNS=PIPELINE_COLUMNS,
                       TRACK_NAMES={t.id: t.name for t in cfg.tracks})
    env.filters["clean_title"] = clean_title
    env.filters["days_since"] = days_since
    value_labels = {
        "seniority": {"junior": "Junior", "mid": "Orta", "senior": "Senior", "lead": "Lead / Leitung"},
        "remote": {"remote": "Tam uzaktan", "hybrid": "Hibrit", "onsite": "Ofiste"},
        "employment": {"fulltime": "Tam zamanlı", "parttime": "Yarı zamanlı", "werkstudent": "Werkstudent",
                       "internship": "Praktikum", "thesis": "Abschlussarbeit", "trainee": "Trainee",
                       "apprenticeship": "Ausbildung", "freelance": "Freelance", "contract": "Sözleşmeli"},
        "legitimacy": {"high": "yüksek", "medium": "orta", "low": "düşük"},
        "period": {"year": "yıl", "month": "ay", "hour": "saat", "week": "hafta", "day": "gün"},
    }

    def money(value: Any) -> str:
        try:
            return f"{float(value):,.0f}".replace(",", ".")
        except (TypeError, ValueError):
            return str(value or "")

    env.filters["money"] = money
    env.filters["label"] = lambda value, kind: value_labels.get(kind, {}).get(value or "", value or "–")

    def score_class(job: dict[str, Any]) -> str:
        s = job.get("llm_score")
        if s is None:
            p = job.get("prescore") or 0
            return "pre-hi" if p >= 70 else "pre-mid" if p >= 45 else "pre-lo"
        return "s-hi" if s >= 4.0 else "s-mid" if s >= 3.5 else "s-lo"

    env.filters["score_class"] = score_class

    def conn():
        return db.connect(cfg.db_path)

    def profile() -> Profile:
        return profile_tools.load_or_empty(cfg.profile_path)

    def badges(job: dict[str, Any], german: str) -> list[tuple[str, str]]:
        return flag_labels(job.get("flags") or {}, german)

    def render(request: Request, name: str, **ctx: Any) -> HTMLResponse:
        ctx.setdefault("msg", request.query_params.get("msg", ""))
        ctx.setdefault("kind", request.query_params.get("kind", "ok"))
        ctx["cfg"] = cfg
        ctx["auth_enabled"] = bool(auth.api_token(cfg))
        c = conn()
        try:
            ctx.setdefault("pending_replies", db.pending_mail_signal_count(c))
            ctx.setdefault("progress", read_progress(c))
        finally:
            c.close()
        # list and status pages reload once when a scan ends; other pages only update the bar
        ctx.setdefault("reload_after_scan", "running" in ctx)
        ctx.setdefault("running", _running())
        return templates.TemplateResponse(request, name, ctx)

    def base_url(request: Request) -> str:
        if cfg.server.public_url:
            return cfg.server.public_url.rstrip("/")
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("host") or request.url.netloc
        return f"{proto}://{host}"

    def bookmarklet(request: Request) -> str:
        return ("javascript:(function(){window.open('" + base_url(request) + "/add?url='+encodeURIComponent("
                "location.href)+'&title='+encodeURIComponent(document.title),'_blank');})();")

    # ------------------------------------------------------------------ pages
    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/jobs", status_code=303)

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request, view: str = "inbox", track: str = "", q: str = "", order: str = "score",
             min: str = "") -> HTMLResponse:
        c = conn()
        try:
            views = {
                "inbox": ["new", "shortlisted"],
                "active": ["shortlisted", "tailored", "approved", "applied", "interview"],
                "done": ["offer", "rejected", "skipped", "closed"],
                "filtered": ["filtered"],
                "all": None,
            }
            statuses = views.get(view, views["inbox"])
            min_score = float(min) if min.strip() else None
            filters = {"statuses": statuses, "track": track or None, "query": q or None,
                       "include_filtered": view in ("filtered", "all"), "min_score": min_score}
            rows = db.list_jobs(c, order=order, limit=WEB_LIST_LIMIT, **filters)
            shown_total = db.count_jobs(c, **filters)
            counts = db.status_counts(c)
            prof = profile()
            for r in rows:
                r["badges"] = badges(r, prof.german_level)
            running = _running()
        finally:
            c.close()
        tab_counts = {k: sum(counts.get(s, 0) for s in (v or counts.keys())) for k, v in views.items()}
        return render(request, "jobs.html", rows=rows, view=view, track=track, q=q, order=order, min=min,
                      tab_counts=tab_counts, tracks=cfg.enabled_tracks(), running=running, total=shown_total)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(request: Request, job_id: str) -> HTMLResponse:
        c = conn()
        try:
            job = db.get_job(c, job_id)
            if not job:
                raise HTTPException(404, "İlan bulunamadı")
            ev = db.latest_evaluation(c, job_id)
            docs = db.documents_for(c, job_id)
            events = db.events_for(c, job_id)
            contacts = db.contacts_for_company(c, job.get("company_norm", ""))
            replies = [signal_view(c, x) for x in db.mail_signals_for_job(c, job_id)]
            prof = profile()
            ensure_answers_file(cfg)
            try:
                answers = job_answers(cfg, c, prof, job)
            except ValueError as exc:
                answers = {"groups": [], "missing": [], "language": "de", "error": str(exc)}
        finally:
            c.close()
        facts = {fid: f.text for fid, (f, _) in prof.fact_index().items()}
        track = cfg.track(job.get("track"))
        return render(request, "job.html", job=job, ev=ev, docs=docs, events=events, contacts=contacts,
                      facts=facts, badges=badges(job, prof.german_level), track=track,
                      todo_facts=prof.todo_facts(), has_llm=_llm_available(), answers=answers, replies=replies,
                      KIND_TR=KIND_TR)

    def _llm_available() -> bool:
        try:
            return llm_factory(cfg) is not None
        except LLMError:
            return False

    @app.get("/pipeline", response_class=HTMLResponse)
    def pipeline(request: Request) -> HTMLResponse:
        c = conn()
        try:
            cols = {s: db.list_jobs(c, statuses=[s], order="date", limit=200) for s in PIPELINE_COLUMNS}
            due = {j["id"] for j in follow_ups_due(c, cfg)}
        finally:
            c.close()
        return render(request, "pipeline.html", cols=cols, due=due)

    @app.get("/stats", response_class=HTMLResponse)
    def stats(request: Request) -> HTMLResponse:
        c = conn()
        try:
            counts = db.status_counts(c)
            sources = db.source_counts(c)
            health = db.source_health(c)
            runs = [dict(r) for r in c.execute("SELECT * FROM source_runs ORDER BY id DESC LIMIT 25")]
            due = follow_ups_due(c, cfg)
            running = _running()
            last_cycle = db.get_meta(c, "last_cycle", "")
            last_error = db.get_meta(c, "last_cycle_error", "")
            last_quick = db.get_meta(c, "last_quick_cycle", "")
            gaps = skill_gaps(c, min_score=3.0, days=120, limit=15)
        finally:
            c.close()
        funnel = [(STATUS_LABELS_TR[s], counts.get(s, 0)) for s in
                  ("new", "shortlisted", "tailored", "approved", "applied", "interview", "offer", "rejected")]
        return render(request, "stats.html", counts=counts, sources=sources, health=health, runs=runs, due=due,
                      funnel=funnel, running=running, last_cycle=last_cycle, last_error=last_error,
                      last_quick=last_quick, gaps=gaps)

    @app.get("/import", response_class=HTMLResponse)
    def import_page(request: Request) -> HTMLResponse:
        return render(request, "import.html", bookmarklet=bookmarklet(request))

    @app.get("/add", response_class=HTMLResponse)
    def add_page(request: Request, url: str = "", title: str = "") -> HTMLResponse:
        """Target of the "JobRadar'a ekle" bookmarklet: confirm, then the normal URL import runs."""
        url = url.strip()
        error = ""
        existing = None
        if not url.lower().startswith(("http://", "https://")):
            error = "Geçerli bir ilan adresi gelmedi."
        elif url.startswith(base_url(request)):
            error = "Bu JobRadar'ın kendi sayfası. Yer imini bir ilan sayfasındayken tıkla."
        else:
            c = conn()
            try:
                jid = db.job_id_for_url(c, canonical_url(url)[1])
                existing = db.get_job(c, jid) if jid else None
            finally:
                c.close()
        return render(request, "add.html", url=url, page_title=title.strip()[:200], error=error, existing=existing)

    @app.get("/docs/{doc_id}/diff", response_class=HTMLResponse)
    def doc_diff_page(request: Request, doc_id: int) -> HTMLResponse:
        from jobradar.tailor.diff import document_diff

        c = conn()
        try:
            doc = db.get_document(c, doc_id)
            job = db.get_job(c, doc["job_id"]) if doc else None
        finally:
            c.close()
        if not doc or not job:
            raise HTTPException(404, "Belge bulunamadı")
        try:
            diff = document_diff(cfg.applications_path / doc["folder"], profile())
        except FileNotFoundError:
            return _redirect(f"/jobs/{job['id']}#docs", "Bu sürümde tailored.json yok", "err")
        return render(request, "diff.html", doc=doc, job=job, diff=diff)

    @app.get("/mail", response_class=HTMLResponse)
    def mail_page(request: Request) -> HTMLResponse:
        c = conn()
        try:
            pending = [signal_view(c, x) for x in db.mail_signals(c, state="pending", limit=100)]
            recent = [signal_view(c, x) for x in db.mail_signals(c, limit=60) if x["state"] != "pending"]
            tracked = [{"id": j["id"], "label": f"{clean_title(j['title'])[:60]} · {j['company'][:30]}"}
                       for j in tracked_jobs(c)]
            last_sync = db.get_meta(c, "last_mail_sync", "")
            last_error = db.get_meta(c, "last_mail_sync_error", "")
        finally:
            c.close()
        return render(request, "mail.html", pending=pending, recent=recent, tracked=tracked, last_sync=last_sync,
                      last_error=last_error, configured=bool(imap_credentials(cfg)), enabled=cfg.mail_sync.enabled,
                      pending_replies=len(pending))

    # ---------------------------------------------------------------- actions
    @app.post("/jobs/{job_id}/status")
    def set_status(job_id: str, status: str = Form(...), note: str = Form(""), back: str = Form("")) -> RedirectResponse:
        if status not in STATUSES:
            raise HTTPException(400, "geçersiz durum")
        c = conn()
        try:
            db.set_status(c, job_id, status, note)
            c.commit()
        finally:
            c.close()
        return _redirect(back or f"/jobs/{job_id}", f"Durum: {STATUS_LABELS_TR[status]}")

    @app.post("/jobs/{job_id}/notes")
    def save_notes(job_id: str, notes: str = Form("")) -> RedirectResponse:
        c = conn()
        try:
            db.update_fields(c, job_id, notes=notes)
            c.commit()
        finally:
            c.close()
        return _redirect(f"/jobs/{job_id}", "Not kaydedildi")

    @app.post("/jobs/{job_id}/enrich")
    def enrich(job_id: str) -> RedirectResponse:
        c = conn()
        try:
            job = db.get_job(c, job_id)
            if not job:
                raise HTTPException(404)
            ok, info = enrich_one(c, Processor(cfg, profile()), make_client(), job)
        finally:
            c.close()
        if ok and info != job_id:
            return _redirect(f"/jobs/{info}", "İlan başka bir kayıtla birleştirildi")
        return _redirect(f"/jobs/{job_id}", "Açıklama güncellendi" if ok else f"Açıklama alınamadı: {info}",
                         "ok" if ok else "err")

    @app.post("/jobs/{job_id}/evaluate")
    def evaluate(job_id: str) -> RedirectResponse:
        try:
            llm = llm_factory(cfg)
        except LLMError as exc:
            return _redirect(f"/jobs/{job_id}", str(exc), "err")
        if llm is None:
            return _redirect(f"/jobs/{job_id}", "LLM bağlı değil (README: LLM ayarları)", "err")
        c = conn()
        logs: list[str] = []
        try:
            res = evaluate_pending(c, cfg, profile(), llm, job_ids=[job_id], log=logs.append)
        finally:
            c.close()
        if res:
            return _redirect(f"/jobs/{job_id}", f"Değerlendirildi: {res[0][1]:.1f}/5")
        return _redirect(f"/jobs/{job_id}", "Değerlendirilemedi: " + (logs[-1] if logs else "bilinmeyen hata"), "err")

    @app.post("/jobs/{job_id}/tailor")
    def tailor(job_id: str, language: str = Form("")) -> RedirectResponse:
        from jobradar.tailor.generate import tailor_job

        try:
            llm = llm_factory(cfg)
        except LLMError as exc:
            return _redirect(f"/jobs/{job_id}", str(exc), "err")
        if llm is None:
            return _redirect(f"/jobs/{job_id}", "LLM bağlı değil (README: LLM ayarları)", "err")
        c = conn()
        try:
            doc = tailor_job(cfg, profile(), c, job_id, llm, language=language or None)
        except (LLMError, ValueError) as exc:
            return _redirect(f"/jobs/{job_id}", f"Belgeler oluşturulamadı: {exc}", "err")
        finally:
            c.close()
        v = doc.get("validation") or {}
        note = "Belgeler hazır" + ("" if v.get("ok") else " (doğrulama uyarıları var, kontrol et)")
        return _redirect(f"/jobs/{job_id}#docs", note, "ok" if v.get("ok") else "warn")

    @app.post("/docs/{doc_id}/approve")
    def approve(doc_id: int) -> RedirectResponse:
        c = conn()
        try:
            doc = db.get_document(c, doc_id)
            if not doc:
                raise HTTPException(404)
            db.approve_document(c, doc_id)
            job = db.get_job(c, doc["job_id"])
            if job and job["status"] in ("new", "shortlisted", "tailored"):
                db.set_status(c, doc["job_id"], "approved", f"belgeler v{doc['version']} onaylandı")
            c.commit()
        finally:
            c.close()
        return _redirect(f"/jobs/{doc['job_id']}#docs", f"v{doc['version']} onaylandı. Başvuruyu kendin gönder, sonra 'Başvurdum' de.")

    @app.get("/files/{doc_id}/{name}")
    def files(doc_id: int, name: str) -> FileResponse:
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
        return FileResponse(path, media_type=media)

    @app.post("/import/url")
    def import_url(url: str = Form(...)) -> RedirectResponse:
        try:
            raw = raw_from_url(make_client(), url.strip())
        except Exception as exc:  # noqa: BLE001
            return _redirect("/import", f"İlan okunamadı: {exc}", "err")
        c = conn()
        try:
            counts = import_raws(c, cfg, profile(), [raw], "import:url")
            jid = db.job_id_for_url(c, canonical_url(raw.url)[1])
        finally:
            c.close()
        target = f"/jobs/{jid}" if jid else "/jobs"
        return _redirect(target, "İlan eklendi" if counts.new else "İlan zaten vardı, güncellendi")

    @app.post("/mail-sync")
    def mail_sync_action() -> RedirectResponse:
        if not imap_credentials(cfg):
            return _redirect("/mail", "E-posta ayarı yok: önce `jobradar email`", "err")
        c = conn()
        try:
            res = sync_mail(c, cfg)
        finally:
            c.close()
        if res.error:
            return _redirect("/mail", res.error, "err")
        return _redirect("/mail", f"{res.checked} yeni mail kontrol edildi: {len(res.new)} başvuru yanıtı kaydedildi")

    @app.post("/mail-signals/{signal_id}/apply")
    def mail_signal_apply(signal_id: int, job_id: str = Form(""), back: str = Form("/mail")) -> RedirectResponse:
        c = conn()
        try:
            res = apply_signal(c, signal_id, job_id or None)
        except (KeyError, ValueError) as exc:
            return _redirect(_safe_back(back), str(exc), "err")
        finally:
            c.close()
        label = STATUS_LABELS_TR.get(res["status"], res["status"])
        return _redirect(_safe_back(back), f"Uygulandı: durum {label}" if res["changed"] else "Geçmişe eklendi")

    @app.post("/mail-signals/{signal_id}/dismiss")
    def mail_signal_dismiss(signal_id: int, back: str = Form("/mail")) -> RedirectResponse:
        c = conn()
        try:
            dismiss_signal(c, signal_id)
        except KeyError as exc:
            return _redirect(_safe_back(back), str(exc), "err")
        finally:
            c.close()
        return _redirect(_safe_back(back), "Yok sayıldı")

    def _safe_back(back: str) -> str:
        return back if back.startswith("/") and not back.startswith(("//", "/\\")) else "/mail"

    @app.post("/import/alert")
    async def import_alert(text: str = Form(""), file: UploadFile | None = File(None)) -> RedirectResponse:
        content: bytes | str = text
        if file is not None and file.filename:
            content = await file.read()
        if not content:
            return _redirect("/import", "Metin ya da dosya ver", "err")
        raws = parse_alert_email(content)
        if not raws:
            return _redirect("/import", "İçinde ilan linki bulunamadı", "err")
        c = conn()
        try:
            counts = import_raws(c, cfg, profile(), raws, "import:alert")
        finally:
            c.close()
        return _redirect("/jobs", f"{counts.found} link okundu: {counts.new} yeni, {counts.merged} mevcut, "
                                  f"{counts.filtered} elendi")

    @app.post("/import/connections")
    async def import_connections(file: UploadFile = File(...)) -> RedirectResponse:
        raw = await file.read()
        text = raw.decode("utf-8-sig", "ignore")
        contacts = parse_connections_csv(text)
        c = conn()
        try:
            n = db.replace_contacts(c, contacts)
        finally:
            c.close()
        return _redirect("/import", f"{n} LinkedIn bağlantısı yüklendi")

    def _running() -> bool:
        return _scan_lock.locked() or cycle_running(cfg.data_path)

    def start_cycle() -> bool:
        """Start a full run in the background. False if one is already running anywhere."""
        if _running() or not _scan_lock.acquire(blocking=False):
            return False
        try:
            c = conn()
            try:
                mark_queued(c)
            finally:
                c.close()
        except Exception:  # noqa: BLE001 - the progress bar is optional, the run is not
            traceback.print_exc()
        try:
            threading.Thread(target=_run_cycle_bg, name="jobradar-cycle", daemon=True).start()
        except BaseException:
            _scan_lock.release()
            raise
        return True

    @app.post("/cycle")
    def cycle() -> RedirectResponse:
        if not start_cycle():
            return _redirect("/stats", "Tarama zaten çalışıyor", "warn")
        return _redirect("/stats", "Tarama başladı. Bu sayfayı birkaç dakika sonra yenile.")

    def _run_cycle_bg() -> None:
        from jobradar.cli import run_cycle

        runner = cycle_runner or run_cycle
        err = ""
        try:
            runner(cfg)
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        finally:
            _scan_lock.release()
            c = conn()
            try:
                db.set_meta(c, "last_cycle_error", err)
            finally:
                c.close()

    @app.get("/api/status")
    def api_status() -> JSONResponse:
        c = conn()
        try:
            return JSONResponse({"running": _running(), "last_cycle": db.get_meta(c, "last_cycle", ""),
                                 "progress": read_progress(c)})
        finally:
            c.close()

    task_runner = TaskRunner()
    app.include_router(build_router(cfg, llm_factory=llm_factory, start_cycle=start_cycle, tasks=task_runner,
                                    is_running=_running))
    app.include_router(build_setup_router(cfg, llm_factory=llm_factory, tasks=task_runner))
    return app
