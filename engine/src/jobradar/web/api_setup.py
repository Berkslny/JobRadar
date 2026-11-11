"""Setup endpoints for the app: interface language, AI model, profile (and CV import), search, e-mail.

Everything a client changes here goes to data/settings.json (see jobradar.settings); secrets are only kept
in the process environment, the client stores them (Keychain) and hands them over again at start."""

from __future__ import annotations

import os
import shutil
import smtplib
import ssl
import subprocess
import time
from typing import Any, Callable, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from jobradar import __version__, db, i18n, profile_tools, searchsetup, settings
from jobradar.config import AppConfig
from jobradar.i18n import t
from jobradar.scoring.llm import BaseLLM, LLMError, cost_label, is_local_url, llm_hint

PROVIDERS = ("claude_cli", "anthropic", "openai", "ollama", "none")
CLAUDE_MODELS = ["haiku", "sonnet", "opus"]
_claude_cache: dict[str, Any] = {"at": 0.0, "value": None}


async def use_language(request: Request) -> None:
    """Texts of this request follow Accept-Language (async on purpose: the context reaches the endpoint)."""
    code = i18n.normalize(request.headers.get("x-jobradar-lang") or request.headers.get("accept-language"))
    if code:
        i18n.set_lang(code)


class AppSettingsIn(BaseModel):
    language: str = ""
    document_language: Optional[str] = None   # "" = by country and posting; else a language code
    output_language: Optional[str] = None     # language of evaluation texts; "auto" = interface language
    follow_up_days: Optional[int] = None


class AIIn(BaseModel):
    provider: str
    fast_model: str = ""
    smart_model: str = ""
    base_url: str = ""
    api_key: Optional[str] = None      # None: keep what is known, "": forget


class ProfileIn(BaseModel):
    profile: dict[str, Any]


class SuggestIn(BaseModel):
    roles: str
    country: str = ""
    where: str = ""


class DetectIn(BaseModel):
    url: str
    name: str = ""


class AnswersIn(BaseModel):
    items: list[dict[str, Any]]


class MailIn(BaseModel):
    user: Optional[str] = None
    password: Optional[str] = None     # None: keep, "": forget
    to: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    digest: Optional[bool] = None
    instant: Optional[bool] = None
    sync: Optional[bool] = None


def _invalid(exc: Exception) -> HTTPException:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", ()))
        message = f"{where}: {first.get('msg', '')}".strip(": ")
    else:
        message = str(exc)
    return HTTPException(422, t("Geçersiz ayar: {error}", error=message[:300]))


def claude_status(cfg: AppConfig) -> dict[str, Any]:
    """Is Claude Code installed? (The sign-in can only be checked with a real call: POST /ai/test.)"""
    now = time.monotonic()
    if _claude_cache["value"] is not None and now - _claude_cache["at"] < 30:
        return _claude_cache["value"]
    configured = cfg.llm.claude_cli.path
    path = shutil.which(configured) or (configured if os.path.isfile(configured) else None)
    out: dict[str, Any] = {"found": bool(path), "path": path or "", "version": ""}
    if path:
        try:
            proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
            out["version"] = (proc.stdout or proc.stderr or "").strip().splitlines()[0][:60] if proc.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    _claude_cache.update(at=now, value=out)
    return out


def ollama_status(base_url: str) -> dict[str, Any]:
    root = base_url.rstrip("/")
    root = root[:-3] if root.endswith("/v1") else root
    try:
        r = httpx.get(f"{root}/api/tags", timeout=2.0)
        if r.status_code == 200:
            return {"up": True, "models": sorted(m.get("name", "") for m in r.json().get("models", []) if m.get("name"))}
    except (httpx.HTTPError, ValueError):
        pass
    return {"up": False, "models": []}


def ai_view(cfg: AppConfig, llm_factory: Callable[[AppConfig], Optional[BaseLLM]]) -> dict[str, Any]:
    lc = cfg.llm
    provider = lc.provider
    section = {"claude_cli": lc.claude_cli, "anthropic": lc.anthropic, "openai": lc.openai,
               "ollama": lc.ollama}.get(provider)
    error, active, label = "", "", ""
    try:
        llm = llm_factory(cfg)
        if llm is not None:
            active = llm.provider
            label = cost_label(llm.provider)
    except LLMError as exc:
        error = str(exc)
    return {
        "provider": provider, "active": active, "ready": bool(active), "error": error, "label": label,
        "fast_model": getattr(section, "fast_model", "") if section else "",
        "smart_model": getattr(section, "smart_model", "") if section else "",
        "base_url": getattr(section, "base_url", "") if section else "",
        "key_set": {"anthropic": bool(os.environ.get(lc.anthropic.api_key_env)),
                    "openai": bool(os.environ.get(lc.openai.api_key_env))},
        "openai_base_url": lc.openai.base_url, "ollama_base_url": lc.ollama.base_url,
        "claude": claude_status(cfg),
        "eval_tier": lc.eval_tier, "tailor_tier": lc.tailor_tier,
        "output_language": lc.output_language,
    }


def list_models(cfg: AppConfig, provider: str, base_url: str = "") -> list[str]:
    lc = cfg.llm
    if provider == "claude_cli":
        return CLAUDE_MODELS
    if provider == "ollama":
        return ollama_status(base_url or lc.ollama.base_url)["models"]
    try:
        if provider == "anthropic":
            key = os.environ.get(lc.anthropic.api_key_env, "")
            r = httpx.get("https://api.anthropic.com/v1/models", params={"limit": 100}, timeout=15,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        elif provider == "openai":
            key = os.environ.get(lc.openai.api_key_env, "")
            root = (base_url or lc.openai.base_url).rstrip("/")
            r = httpx.get(f"{root}/models", timeout=15, headers={"Authorization": f"Bearer {key}"} if key else {})
        else:
            raise HTTPException(422, t("Bilinmeyen sağlayıcı: {name}", name=provider))
    except httpx.HTTPError as exc:
        raise HTTPException(502, t("bağlantı hatası: {error}", error=str(exc)[:200])) from exc
    if r.status_code in (401, 403):
        raise HTTPException(401, t("API anahtarı geçersiz."))
    if r.status_code >= 400:
        raise HTTPException(502, f"HTTP {r.status_code}: {r.text[:200]}")
    try:
        items = r.json().get("data") or r.json().get("models") or []
    except ValueError:
        items = []
    names = [str(m.get("id") or m.get("name") or "").removeprefix("models/") for m in items if isinstance(m, dict)]
    return sorted(n for n in names if n)


def mail_view(cfg: AppConfig, conn_factory: Callable[[], Any]) -> dict[str, Any]:
    ec = cfg.notify.email
    c = conn_factory()
    try:
        last_sync, last_error = db.get_meta(c, "last_mail_sync", ""), db.get_meta(c, "last_mail_sync_error", "")
    finally:
        c.close()
    user = os.environ.get(ec.user_env, "").strip()
    return {"user": user, "to": os.environ.get(ec.to_env, "").strip() or user,
            "has_password": bool(os.environ.get(ec.password_env, "").strip()),
            "smtp_host": ec.host, "smtp_port": ec.port, "imap_host": cfg.mail_sync.host, "imap_port": cfg.mail_sync.port,
            "digest": ec.enabled, "instant": ec.instant, "sync": cfg.mail_sync.enabled,
            "last_sync": last_sync, "last_error": last_error}


def mail_test(cfg: AppConfig) -> dict[str, Any]:
    """Send a test message (SMTP) and open the inbox read-only (IMAP)."""
    import imaplib

    from jobradar.mailer import MailError, SMTPSettings, send_mail

    ec = cfg.notify.email
    user = os.environ.get(ec.user_env, "").strip()
    password = os.environ.get(ec.password_env, "").replace(" ", "").strip()
    if not user or not password:
        raise RuntimeError(t("E-posta adresi ve uygulama şifresi gerekli."))
    out: dict[str, Any] = {"smtp": "", "imap": ""}
    try:
        send_mail(SMTPSettings(ec.host, ec.port, user, password, os.environ.get(ec.to_env, "").strip() or user),
                  t("JobRadar test e-postası"), t("Bu bir deneme e-postasıdır. E-posta ayarların çalışıyor."))
    except MailError as exc:
        out["smtp"] = str(exc)
    except (OSError, smtplib.SMTPException) as exc:
        out["smtp"] = t("SMTP girişi başarısız: {error}", error=str(exc)[:200])
    try:
        imap = imaplib.IMAP4_SSL(cfg.mail_sync.host, cfg.mail_sync.port, ssl_context=ssl.create_default_context(),
                                 timeout=30)
        try:
            imap.login(user, password)
            imap.select(cfg.mail_sync.folder or "INBOX", readonly=True)
        finally:
            try:
                imap.logout()
            except (OSError, imaplib.IMAP4.error):
                pass
    except imaplib.IMAP4.error:
        out["imap"] = t("E-posta sunucusu girişi reddetti. Uygulama şifresi doğru mu, IMAP açık mı?")
    except OSError as exc:
        out["imap"] = t("{host}:{port} bağlantısı kurulamadı: {error}", host=cfg.mail_sync.host, port=cfg.mail_sync.port,
                        error=str(exc)[:200])
    out["ok"] = not out["smtp"] and not out["imap"]
    return out


def build_setup_router(cfg: AppConfig, *, llm_factory: Callable[[AppConfig], Optional[BaseLLM]], tasks: Any) -> APIRouter:
    r = APIRouter(prefix="/api/v1", dependencies=[Depends(use_language)])

    def conn():
        return db.connect(cfg.db_path)

    def current_profile():
        try:
            return profile_tools.load_or_empty(cfg.profile_path)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, t("Profil geçersiz: {error}", error=str(exc)[:300])) from exc

    def optional_llm() -> Optional[BaseLLM]:
        try:
            return llm_factory(cfg)
        except LLMError:
            return None

    def need_llm() -> BaseLLM:
        try:
            llm = llm_factory(cfg)
        except LLMError as exc:
            raise HTTPException(503, str(exc)) from exc
        if llm is None:
            raise HTTPException(503, t("AI modeli bağlı değil"))
        return llm

    # -- overview --------------------------------------------------------------------------------
    @r.get("/setup")
    def setup_state() -> dict[str, Any]:
        """What a new user still has to do before the first scan."""
        try:
            prof = profile_tools.load_or_empty(cfg.profile_path)
            missing, profile_error = profile_tools.missing_basics(prof), ""
        except (ValueError, OSError) as exc:
            prof, missing, profile_error = None, ["name"], str(exc)[:300]
        ai = ai_view(cfg, llm_factory)
        tracks = len(cfg.enabled_tracks())
        return {
            "version": __version__, "language": i18n.default_lang(),
            "profile": {"exists": cfg.profile_path.exists(), "name": prof.name if prof else "", "missing": missing,
                        "error": profile_error, "todo_facts": len(prof.todo_facts()) if prof else 0},
            "ai": {"provider": ai["provider"], "ready": ai["ready"], "error": ai["error"]},
            "search": {"tracks": tracks, "country": cfg.search.country},
            "ready": not missing and tracks > 0,
        }

    def app_settings_view() -> dict[str, Any]:
        from jobradar.tailor.generate import default_document_language

        return {"language": i18n.default_lang(), "document_language": (cfg.tailor.default_language or "").strip().lower(),
                "document_language_effective": default_document_language(cfg),
                "output_language": (cfg.llm.output_language or "auto").strip().lower(),
                "follow_up_days": cfg.follow_up_days}

    @r.get("/app-settings")
    def app_settings() -> dict[str, Any]:
        return app_settings_view()

    @r.put("/app-settings")
    def put_app_settings(body: AppSettingsIn) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        code = i18n.normalize(body.language)
        if code:
            patch["language"] = code
        for value, section, key, fallback in ((body.document_language, "tailor", "default_language", ""),
                                              (body.output_language, "llm", "output_language", "auto")):
            if value is None:
                continue
            lang = value.strip().lower()
            if lang and lang != "auto" and not (2 <= len(lang) <= 3 and lang.isalpha()):
                raise HTTPException(422, t("Geçersiz dil kodu: {code}", code=value))
            patch.setdefault(section, {})[key] = lang or fallback
        if body.follow_up_days is not None:
            if not 1 <= body.follow_up_days <= 90:
                raise HTTPException(422, t("Takip süresi 1 ile 90 gün arasında olmalı."))
            patch["follow_up_days"] = body.follow_up_days
        if patch:
            settings.update(cfg, patch)
        if code:
            i18n.set_default(code)
        return app_settings_view()

    # -- AI model --------------------------------------------------------------------------------
    @r.get("/ai")
    def ai_get() -> dict[str, Any]:
        return ai_view(cfg, llm_factory)

    @r.put("/ai")
    def ai_put(body: AIIn) -> dict[str, Any]:
        provider = body.provider.strip().lower()
        if provider not in PROVIDERS:
            raise HTTPException(422, t("Bilinmeyen sağlayıcı: {name}", name=body.provider))
        lc = cfg.llm
        fast, smart = body.fast_model.strip(), body.smart_model.strip()
        llm_patch: dict[str, Any] = {"provider": provider}
        key_env = ""
        if provider == "claude_cli":
            llm_patch["claude_cli"] = {"fast_model": fast or "haiku", "smart_model": smart or fast or "sonnet"}
        elif provider == "anthropic":
            llm_patch.update(allow_paid_api=True, anthropic={
                "fast_model": fast or lc.anthropic.fast_model, "smart_model": smart or fast or lc.anthropic.smart_model})
            key_env = lc.anthropic.api_key_env
        elif provider == "openai":
            base = body.base_url.strip().rstrip("/") or lc.openai.base_url
            llm_patch["openai"] = {"base_url": base, "fast_model": fast, "smart_model": smart or fast}
            if not is_local_url(base):
                llm_patch["allow_paid_api"] = True
            key_env = lc.openai.api_key_env
        elif provider == "ollama":
            llm_patch["ollama"] = {"base_url": body.base_url.strip().rstrip("/") or lc.ollama.base_url,
                                   "fast_model": fast, "smart_model": smart or fast}
        try:
            settings.update(cfg, {"llm": llm_patch})
        except (ValidationError, ValueError) as exc:
            raise _invalid(exc) from exc
        if key_env and body.api_key is not None:
            if body.api_key.strip():
                os.environ[key_env] = body.api_key.strip()
            else:
                os.environ.pop(key_env, None)
        _claude_cache["value"] = None
        return ai_view(cfg, llm_factory)

    @r.get("/ai/models")
    def ai_models(provider: str, base_url: str = "") -> dict[str, Any]:
        return {"provider": provider, "models": list_models(cfg, provider.strip().lower(), base_url.strip())}

    @r.post("/ai/test", status_code=202)
    def ai_test() -> dict[str, Any]:
        llm = need_llm()

        def work() -> dict[str, Any]:
            started = time.monotonic()
            try:
                res = llm.complete("You are a connection test. Follow the instruction exactly.",
                                   'Reply with a JSON object: {"ok": true}', tier=cfg.llm.eval_tier, max_tokens=200)
            except LLMError as exc:
                raise RuntimeError(llm_hint(llm.provider, str(exc))) from exc
            if not res.text.strip():
                raise RuntimeError(t("Model boş yanıt verdi."))
            return {"ok": True, "provider": res.provider, "model": res.model, "reply": res.text.strip()[:200],
                    "seconds": round(time.monotonic() - started, 1), "message": t("Bağlantı çalışıyor.")}

        return tasks.start("ai_test", work)

    # -- profile ---------------------------------------------------------------------------------
    @r.get("/profile")
    def profile_get() -> dict[str, Any]:
        prof = current_profile()
        return {"exists": cfg.profile_path.exists(), "profile": profile_tools.with_lists(prof.model_dump()),
                "missing": profile_tools.missing_basics(prof), "todo_facts": prof.todo_facts(),
                "hash": prof.content_hash()}

    @r.put("/profile")
    def profile_put(body: ProfileIn) -> dict[str, Any]:
        try:
            prof = profile_tools.save_profile(cfg.profile_path, body.profile)
        except (ValidationError, ValueError) as exc:
            raise HTTPException(422, t("Profil geçersiz: {error}", error=str(exc)[:400])) from exc
        return {"exists": True, "profile": profile_tools.with_lists(prof.model_dump()),
                "missing": profile_tools.missing_basics(prof), "todo_facts": prof.todo_facts(),
                "hash": prof.content_hash()}

    @r.post("/profile/import", status_code=202)
    async def profile_import(request: Request, filename: str = "cv.pdf") -> dict[str, Any]:
        """Body: the CV file itself (PDF, .docx, text). The task result is a profile draft; nothing is saved."""
        data = await request.body()
        try:
            text = profile_tools.extract_text(filename, data)
        except profile_tools.CVError as exc:
            raise HTTPException(422, str(exc)) from exc
        llm = need_llm()
        old = current_profile() if cfg.profile_path.exists() else None

        def work() -> dict[str, Any]:
            try:
                draft = profile_tools.profile_from_cv(llm, text, tier=cfg.llm.tailor_tier)
            except LLMError as exc:
                raise RuntimeError(llm_hint(llm.provider, str(exc))) from exc
            return {"profile": profile_tools.with_lists(profile_tools.merge_keep_private(draft, old)),
                    "chars": len(text)}

        return tasks.start("profile_import", work)

    # -- search ----------------------------------------------------------------------------------
    @r.get("/search")
    def search_get() -> dict[str, Any]:
        return searchsetup.view(cfg)

    @r.put("/search")
    def search_put(body: dict[str, Any]) -> dict[str, Any]:
        try:
            searchsetup.save(cfg, body)
        except (ValidationError, ValueError, TypeError) as exc:
            raise _invalid(exc) from exc
        return searchsetup.view(cfg)

    @r.post("/search/suggest", status_code=202)
    def search_suggest(body: SuggestIn) -> dict[str, Any]:
        if not body.roles.strip():
            raise HTTPException(422, t("Önce hangi işleri aradığını yaz."))
        llm = optional_llm()
        prof = current_profile()
        lang = i18n.get_lang()

        def work() -> dict[str, Any]:
            try:
                return searchsetup.suggest(llm, prof, roles=body.roles, country=body.country or cfg.search.country,
                                           where=body.where, ui_lang=lang, tier=cfg.llm.tailor_tier)
            except LLMError as exc:
                raise RuntimeError(llm_hint(llm.provider if llm else "", str(exc))) from exc

        return tasks.start("search_suggest", work)

    @r.post("/companies/detect")
    def company_detect(body: DetectIn) -> dict[str, Any]:
        """Which careers system does this address use? Returns ready-made entries for sources.companies."""
        from jobradar.http import get_text, make_client
        from jobradar.sources.ats import detect_ats

        url = body.url.strip()
        found = detect_ats(url)
        if not found:
            try:
                found = detect_ats(get_text(make_client(), url))
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(422, t("sayfa açılamadı: HTTP {status}", status=str(exc)[:120])) from exc
        if not found:
            raise HTTPException(404, t("Bu adres tanınan bir kariyer sistemine ait değil."))
        guess = body.name.strip() or url.split("//")[-1].split("/")[0].replace("www.", "").split(".")[0].title()
        return {"companies": [{"name": guess, "ats": e["ats"], "slug": e.get("slug", ""), "url": e.get("url", ""),
                               "search": "", "max_pages": 20, "enabled": True} for e in found]}

    # -- form answers ----------------------------------------------------------------------------
    @r.get("/answers/edit")
    def answers_edit() -> dict[str, Any]:
        from jobradar.answers import load_raw
        from jobradar.tailor.generate import default_document_language

        try:
            return {"primary": default_document_language(cfg), "items": load_raw(cfg)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @r.put("/answers/edit")
    def answers_save(body: AnswersIn) -> dict[str, Any]:
        from jobradar.answers import load_raw, save_raw
        from jobradar.tailor.generate import default_document_language

        save_raw(cfg, body.items)
        return {"primary": default_document_language(cfg), "items": load_raw(cfg)}

    # -- e-mail ----------------------------------------------------------------------------------
    @r.get("/mail-settings")
    def mail_get() -> dict[str, Any]:
        return mail_view(cfg, conn)

    @r.put("/mail-settings")
    def mail_put(body: MailIn) -> dict[str, Any]:
        ec = cfg.notify.email
        for env, value in ((ec.user_env, body.user), (ec.to_env, body.to), (ec.password_env, body.password)):
            if value is None:
                continue
            if value.strip():
                os.environ[env] = value.strip()
            else:
                os.environ.pop(env, None)
        email: dict[str, Any] = {}
        sync: dict[str, Any] = {}
        for key, target, name in (("smtp_host", email, "host"), ("smtp_port", email, "port"), ("digest", email, "enabled"),
                                  ("instant", email, "instant"), ("imap_host", sync, "host"), ("imap_port", sync, "port"),
                                  ("sync", sync, "enabled")):
            value = getattr(body, key)
            if value is not None and value != "":
                target[name] = value
        patch: dict[str, Any] = {}
        if email:
            patch["notify"] = {"email": email}
        if sync:
            patch["mail_sync"] = sync
        if patch:
            try:
                settings.update(cfg, patch)
            except (ValidationError, ValueError) as exc:
                raise _invalid(exc) from exc
        return mail_view(cfg, conn)

    @r.post("/mail-settings/test", status_code=202)
    def mail_test_ep() -> dict[str, Any]:
        def work() -> dict[str, Any]:
            return mail_test(cfg)

        return tasks.start("mail_test", work)

    return r
