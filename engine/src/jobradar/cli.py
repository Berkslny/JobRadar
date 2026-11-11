"""Command line interface."""

from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from jobradar import db
from jobradar.config import AppConfig, CompanySource, load_config
from jobradar.http import make_client
from jobradar.models import STATUS_LABELS_TR, STATUSES
from jobradar.processing.flags import flag_labels
from jobradar.processing.normalize import clean_title
from jobradar.profile import Profile, load_profile
from jobradar.textutil import now_iso, today_iso

app = typer.Typer(help="JobRadar: Almanya iş piyasası için yerel iş arama sistemi.", no_args_is_help=True,
                  add_completion=False)
schedule_app = typer.Typer(help="Günlük otomatik çalıştırma (macOS launchd / cron).", no_args_is_help=True)
app.add_typer(schedule_app, name="schedule")
console = Console()
TEMPLATES = Path(__file__).parent / "templates"

ConfigOpt = typer.Option(None, "--config", "-c", help="jobradar.yaml yolu")


def _load(config: Optional[Path]) -> tuple[AppConfig, Profile]:
    try:
        cfg = load_config(config)
        prof = load_profile(cfg.profile_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    return cfg, prof


def _job(conn, job_id: str) -> dict:
    job = db.get_job(conn, job_id) or db.find_job_by_prefix(conn, job_id)
    if not job:
        console.print(f"[red]İlan bulunamadı: {job_id}[/red]")
        raise typer.Exit(1)
    return job


def log(msg: str) -> None:
    console.print(msg, highlight=False)


# ---------------------------------------------------------------------------
# Full cycle (used by `run`, the scheduler and the dashboard button)
# ---------------------------------------------------------------------------


def process_inbox(cfg: AppConfig, conn, profile: Profile, log=log) -> int:
    from jobradar.pipeline import import_raws
    from jobradar.sources.importers import parse_alert_email

    inbox = cfg.inbox_path
    inbox.mkdir(parents=True, exist_ok=True)
    done_dir = inbox / "processed"
    total = 0
    for f in sorted(inbox.iterdir()):
        if not f.is_file() or f.suffix.lower() not in (".eml", ".txt", ".html", ".htm"):
            continue
        raws = parse_alert_email(f.read_bytes())
        if raws:
            counts = import_raws(conn, cfg, profile, raws, "import:inbox")
            total += counts.new
            log(f"  {f.name}: {counts.found} link, {counts.new} yeni")
        done_dir.mkdir(exist_ok=True)
        f.replace(done_dir / f.name)
    return total


def run_cycle(cfg: AppConfig, *, log=log, use_llm: bool = True, notify: bool = True,
              only: Optional[list[str]] = None, quick: bool = False) -> None:
    from jobradar.locks import cycle_lock

    with cycle_lock(cfg.data_path) as got:
        if not got:
            log("[yellow]Başka bir tarama zaten çalışıyor; bu çalıştırma atlandı.[/yellow]")
            return
        _run_cycle_locked(cfg, log=log, use_llm=use_llm, notify=notify, only=only, quick=quick)


def mail_sync_step(conn, cfg: AppConfig, log=log) -> None:
    """Read company replies (read only) and store status proposals. Never breaks the cycle."""
    from jobradar.mailsync import imap_credentials, sync_mail

    if not cfg.mail_sync.enabled or not imap_credentials(cfg):
        return
    try:
        res = sync_mail(conn, cfg)
    except Exception as exc:  # noqa: BLE001
        log(f"[yellow]E-posta yanıtları okunamadı: {exc}[/yellow]")
        return
    if res.error:
        log(f"[yellow]E-posta yanıtları: {res.error}[/yellow]")
    elif res.new:
        log(f"→ E-posta: {len(res.new)} yeni yanıt, {res.pending} tanesi onay bekliyor")


def instant_alert_step(conn, cfg: AppConfig, german_level: str, log=log) -> None:
    from jobradar.mailer import MailError, send_instant_alerts

    try:
        n = send_instant_alerts(conn, cfg, german_level)
    except MailError as exc:
        log(f"[yellow]Anlık e-posta gönderilemedi: {exc}[/yellow]")
        return
    except Exception as exc:  # noqa: BLE001
        log(f"[yellow]Anlık e-posta hatası: {exc}[/yellow]")
        return
    if n:
        log(f"→ Anlık e-posta: {n} güçlü ilan gönderildi")


def _run_cycle_locked(cfg: AppConfig, *, log=log, use_llm: bool = True, notify: bool = True,
                      only: Optional[list[str]] = None, quick: bool = False) -> None:
    from jobradar.notify import Telegram, digest_text, health_alerts, notify_new_matches
    from jobradar.pipeline import enrich_pending, evaluate_pending, run_scan
    from jobradar.scoring.llm import LLMError, get_llm

    if quick:
        cfg = cfg.model_copy(deep=True)  # page cap only for this run
        for c in cfg.sources.companies:
            c.max_pages = min(c.max_pages, max(1, cfg.quick.max_pages))
        if not only:
            only = list(cfg.quick.sources)
        log(f"→ Hızlı tarama: {', '.join(only)}")
    from jobradar.progress import CycleProgress

    conn = db.connect(cfg.db_path)
    progress = CycleProgress(conn, quick=quick)
    try:
        profile = load_profile(cfg.profile_path)
        client = make_client()
        reports = run_scan(conn, cfg, profile, only=only, log=log, client=client, progress=progress.on_source,
                           step=progress.on_source_step)
        progress.new_jobs = sum(r.new for r in reports)
        n = process_inbox(cfg, conn, profile, log)
        if n:
            log(f"→ gelen kutusu: {n} yeni ilan")
            progress.new_jobs += n
        enrich_pending(conn, cfg, profile, client=client, log=log, progress=progress.on_enrich)
        llm = None
        if use_llm:
            try:
                llm = get_llm(cfg)
            except LLMError as exc:
                log(f"[yellow]LLM: {exc}[/yellow]")
        if llm:
            log(f"→ LLM değerlendirmesi ({llm.provider}/{llm.model_for(cfg.llm.eval_tier)})")
            results = evaluate_pending(conn, cfg, profile, llm, log=log, client=client,
                                       limit=cfg.quick.max_evaluations if quick else None,
                                       progress=progress.on_evaluate)
            progress.evaluated = len(results or [])
        else:
            log("→ LLM bağlı değil: sadece ön puan kullanıldı")
        progress.stage("mail")
        mail_sync_step(conn, cfg, log)
        if notify:
            progress.stage("notify")
            instant_alert_step(conn, cfg, profile.german_level, log)
            tg = Telegram.from_config(cfg)
            if tg:
                sent = notify_new_matches(conn, cfg, tg, profile.german_level)
                if sent:
                    log(f"→ Telegram: {sent} yeni eşleşme gönderildi")
                tc = cfg.notify.telegram
                if tc.daily_digest and db.get_meta(conn, "last_digest") != today_iso():
                    if tg.send(digest_text(conn, cfg)):
                        db.set_meta(conn, "last_digest", today_iso())
                if tc.health_alerts and db.get_meta(conn, "last_health_alert") != today_iso():
                    alerts = health_alerts(conn)
                    if alerts and tg.send("\n".join(alerts)):
                        db.set_meta(conn, "last_health_alert", today_iso())
        db.set_meta(conn, "last_quick_cycle" if quick else "last_cycle", now_iso())
        progress.finish()
    except BaseException as exc:
        progress.finish(ok=False, message=f"{type(exc).__name__}: {exc}"[:300])
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def init(directory: Path = typer.Option(Path("."), "--dir", help="Kurulum klasörü"),
         force: bool = typer.Option(False, help="Var olan jobradar.yaml'ın üzerine yaz")) -> None:
    """Ayar dosyası, profil şablonu ve .env oluştur."""
    directory = directory.expanduser().resolve()
    (directory / "data" / "inbox").mkdir(parents=True, exist_ok=True)
    cfg_path = directory / "jobradar.yaml"
    if cfg_path.exists() and not force:
        console.print(f"jobradar.yaml zaten var: {cfg_path}")
    else:
        shutil.copy(TEMPLATES / "jobradar.yaml", cfg_path)
        console.print(f"[green]✓[/green] {cfg_path}")
    prof = directory / "data" / "profile.yaml"
    if not prof.exists():
        shutil.copy(TEMPLATES / "profile.example.yaml", prof)
        console.print(f"[green]✓[/green] {prof}  (kendi bilgilerinle doldur)")
    else:
        console.print(f"profil zaten var: {prof}")
    env = directory / ".env"
    if not env.exists():
        shutil.copy(TEMPLATES / "env.example", env)
        console.print(f"[green]✓[/green] {env}  (gizli ayarlar; ücretli API anahtarı gerekmez)")
    console.print("\nSıradaki adım: [bold]jobradar doctor[/bold]")


@app.command()
def doctor(config: Optional[Path] = ConfigOpt,
           live: bool = typer.Option(False, "--live", help="Her kaynağı küçük bir canlı sorguyla dene")) -> None:
    """Kurulumu kontrol et."""
    from jobradar.scoring.llm import LLMError, get_llm
    from jobradar.tailor.render import find_chrome

    cfg, prof = _load(config)
    t = Table(show_header=False, box=None)
    t.add_row("Ayar dosyası", str(cfg.config_path))
    t.add_row("Veri klasörü", str(cfg.data_path))
    facts = prof.fact_index()
    t.add_row("Profil", f"{prof.name}: {len(prof.entries())} giriş, {len(facts)} gerçek, {len(prof.all_skills())} beceri")
    todo = prof.todo_facts()
    if todo:
        t.add_row("[yellow]TODO[/yellow]", f"Tamamlanacak gerçekler: {', '.join(todo)}")
    raw_profile = cfg.profile_path.read_text(encoding="utf-8")
    todo_lines = [ln.strip() for ln in raw_profile.splitlines() if "TODO" in ln and not ln.strip().startswith("#")]
    if todo_lines:
        t.add_row("[yellow]TODO[/yellow]", f"profile.yaml içinde {len(todo_lines)} TODO satırı var")
    t.add_row("Hedef alanlar", ", ".join(f"{x.id} ({len(x.search_terms)} arama)" for x in cfg.enabled_tracks()))
    llm = None
    try:
        llm = get_llm(cfg)
        from jobradar.scoring.llm import COST_LABELS

        detail = ""
        if llm and llm.provider == "claude_cli":
            detail = ", oturum: Claude Code girişi"
        if llm:
            cost = COST_LABELS.get(llm.provider, "")
            color = "red" if llm.provider in ("anthropic", "openai") else "green"
            t.add_row("LLM", f"{llm.provider}: {llm.model_for('fast')} / {llm.model_for('smart')} "
                             f"[{color}]({cost}{detail})[/{color}]")
        else:
            t.add_row("LLM", "[yellow]yok[/yellow] (sadece ön puan; README > LLM)")
    except LLMError as exc:
        t.add_row("LLM", f"[red]{exc}[/red]")
    if cfg.llm.allow_paid_api:
        t.add_row("Ücretli API", "[red]izinli[/red] (llm.allow_paid_api: true)")
    else:
        t.add_row("Ücretli API", "[green]kapalı[/green] (hiçbir ücretli API çağrılmaz)")
        if os.environ.get(cfg.llm.anthropic.api_key_env):
            t.add_row("", f"{cfg.llm.anthropic.api_key_env} dolu ama kullanılmıyor; .env içinden silebilirsin")
    import importlib.util

    if importlib.util.find_spec("jobspy"):
        t.add_row("JobSpy", "kurulu")
    else:
        t.add_row("JobSpy", "[yellow]kurulu değil[/yellow]: pip install 'jobradar[jobspy]'")
    t.add_row("PDF", ("RenderCV + " if shutil.which("rendercv") else "") + (f"Chrome ({find_chrome(cfg.tailor.chrome_path)})"
              if find_chrome(cfg.tailor.chrome_path) else "[yellow]Chrome/Edge bulunamadı: sadece HTML[/yellow]"))
    from jobradar.mailer import smtp_settings
    from jobradar.web.auth import api_token

    from jobradar.answers import load_general
    from jobradar.mailsync import imap_credentials

    mail = smtp_settings(cfg)
    t.add_row("E-posta özeti", f"açık → {mail.to}" if mail else "kapalı (jobradar email ile ayarlanır)")
    if mail and cfg.notify.email.instant:
        t.add_row("Anlık e-posta", f"açık (puan ≥ {cfg.notify.email.instant_min_score:g})")
    t.add_row("Yanıt takibi", ("açık (Gmail IMAP, salt okunur)" if imap_credentials(cfg) else
                               "kapalı (jobradar email ile ayarlanır)") if cfg.mail_sync.enabled
              else "kapalı (mail_sync.enabled: false)")
    if cfg.answers_path.exists():
        try:
            filled, missing = load_general(cfg)
            t.add_row("Form cevapları", f"{len(filled)} dolu" + (f", [yellow]{len(missing)} TODO[/yellow]" if missing
                                                                   else "") + f" ({cfg.answers_path.name})")
        except ValueError as exc:
            t.add_row("Form cevapları", f"[red]{exc}[/red]")
    else:
        t.add_row("Form cevapları", "henüz yok: jobradar answers dosyayı oluşturur")
    if importlib.util.find_spec("pypdf"):
        t.add_row("PDF kontrolü", "pypdf kurulu")
    else:
        t.add_row("PDF kontrolü", "[yellow]pypdf yok[/yellow]: pip install -e . (ya da pip install pypdf)")
    t.add_row("Uzaktan erişim", ("API anahtarı var" + (f", adres {cfg.server.public_url}" if cfg.server.public_url else ""))
              if api_token(cfg) else "kapalı (sadece bu bilgisayar)")
    tc = cfg.notify.telegram
    has_tg = bool(os.environ.get(tc.token_env) and os.environ.get(tc.chat_id_env))
    t.add_row("Telegram", "açık" if tc.enabled and has_tg else ("açık ama token/chat id yok" if tc.enabled else "kapalı"))
    companies = [c for c in cfg.sources.companies if c.enabled]
    t.add_row("Kaynaklar", ", ".join(n for n, on in (("arbeitsagentur", cfg.sources.arbeitsagentur.enabled),
                                                      ("freehire", cfg.sources.freehire.enabled),
                                                      (f"{len(companies)} şirket", bool(companies)),
                                                      ("jobspy", cfg.sources.jobspy.enabled)) if on))
    console.print(t)
    if live:
        _live_probe(cfg, prof)
        if llm:
            from jobradar.scoring.llm import llm_hint

            try:
                res = llm.complete("You are a health check.", "Reply with exactly: OK", tier="fast", max_tokens=5)
                console.print(f"  [green]✓[/green] LLM ({llm.provider}/{res.model}) yanıt verdi: {res.text.strip()[:20]}")
            except LLMError as exc:
                console.print(f"  [red]✗[/red] LLM: {llm_hint(llm.provider, str(exc))}")


def _live_probe(cfg: AppConfig, prof: Profile) -> None:
    from jobradar.sources.arbeitsagentur import ArbeitsagenturSource
    from jobradar.sources.ats import fetch_company
    from jobradar.sources.base import SourceContext
    from jobradar.sources.freehire import FreehireSource
    from jobradar.sources.jobspy_src import JobSpySource

    console.print("\n[bold]Canlı deneme[/bold] (veritabanına yazılmaz)")
    probe = cfg.model_copy(deep=True)
    probe._base_dir, probe._config_path = cfg.base_dir, cfg.config_path
    for t in probe.tracks:
        t.search_terms = t.search_terms[:1]
    probe.tracks = probe.enabled_tracks()[:1]
    probe.sources.arbeitsagentur.angebotsart = probe.sources.arbeitsagentur.angebotsart[:1]
    probe.sources.freehire.max_queries = 1
    probe.sources.jobspy.max_queries = 1
    probe.sources.jobspy.results_wanted = 5
    probe.sources.jobspy.fetch_description = False
    client = make_client()
    for src in (ArbeitsagenturSource(), FreehireSource(), JobSpySource()):
        ctx = SourceContext(config=probe, profile=prof, client=client, log=lambda m: None)
        try:
            jobs = src.fetch(ctx)
            extra = f" · uyarı: {ctx.warnings[0][:120]}" if ctx.warnings else ""
            console.print(f"  [green]✓[/green] {src.name}: {len(jobs)} ilan{extra}")
        except Exception as exc:  # noqa: BLE001
            console.print(f"  [red]✗[/red] {src.name}: {str(exc)[:200]}")
    for c in cfg.sources.companies:
        if not c.enabled:
            continue
        c2 = c.model_copy(update={"max_pages": 1})
        try:
            jobs = fetch_company(client, c2, ["FPGA"])
            console.print(f"  [green]✓[/green] {c.name} ({c.ats}): {len(jobs)} ilan")
        except Exception as exc:  # noqa: BLE001
            console.print(f"  [red]✗[/red] {c.name} ({c.ats}): {str(exc)[:200]}")


@app.command()
def run(config: Optional[Path] = ConfigOpt,
        no_llm: bool = typer.Option(False, "--no-llm", help="LLM değerlendirmesi yapma"),
        no_notify: bool = typer.Option(False, "--no-notify", help="Telegram / e-posta bildirimi gönderme"),
        source: Optional[List[str]] = typer.Option(None, "--source", "-s", help="Sadece bu kaynak(lar)"),
        quick: bool = typer.Option(False, "--quick", help="Hızlı tarama: şirket kariyer sayfaları, az değerlendirme, "
                                                        "e-posta yanıtları, anlık bildirim (saatlik)")) -> None:
    """Tam döngü: tara, açıklamaları tamamla, değerlendir, e-posta yanıtlarını oku, bildir."""
    cfg, _ = _load(config)
    run_cycle(cfg, use_llm=not no_llm, notify=not no_notify, only=source, quick=quick)
    if not quick:
        console.print(f"\nPanel: [bold]jobradar serve[/bold] → {cfg.notify.dashboard_url}")


@app.command()
def scan(config: Optional[Path] = ConfigOpt,
         source: Optional[List[str]] = typer.Option(None, "--source", "-s",
                                                    help="arbeitsagentur, freehire, companies, jobspy")) -> None:
    """Sadece tara (LLM yok)."""
    from jobradar.pipeline import enrich_pending, run_scan

    cfg, prof = _load(config)
    conn = db.connect(cfg.db_path)
    client = make_client()
    try:
        run_scan(conn, cfg, prof, only=source, log=log, client=client)
        enrich_pending(conn, cfg, prof, client=client, log=log)
    finally:
        conn.close()


@app.command()
def evaluate(config: Optional[Path] = ConfigOpt, limit: int = typer.Option(None, help="En fazla kaç ilan"),
             job: Optional[List[str]] = typer.Option(None, "--job", "-j", help="Belirli ilan id'leri"),
             force: bool = typer.Option(False, help="Daha önce değerlendirilenleri de yeniden değerlendir")) -> None:
    """Ön puanı yüksek ilanları LLM ile değerlendir."""
    from jobradar.pipeline import evaluate_pending
    from jobradar.scoring.llm import LLMError, get_llm

    cfg, prof = _load(config)
    try:
        llm = get_llm(cfg)
    except LLMError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    if not llm:
        console.print("[red]LLM bağlı değil. Claude Code kuruluysa Terminal'de `claude` açıp /login ile giriş yap, "
                      "ya da jobradar.yaml içinde başka bir model seç.[/red]")
        raise typer.Exit(1)
    conn = db.connect(cfg.db_path)
    try:
        ids = [_job(conn, j)["id"] for j in job] if job else None
        res = evaluate_pending(conn, cfg, prof, llm, limit=limit, job_ids=ids, force=force, log=log)
        console.print(f"{len(res)} ilan değerlendirildi")
    finally:
        conn.close()


@app.command("api-token")
def api_token_cmd(config: Optional[Path] = ConfigOpt,
                  new: bool = typer.Option(False, "--new", help="Yeni anahtar üret (eskisi geçersiz olur)")) -> None:
    """Uzaktan erişim (Mac uygulaması, web paneli) için API anahtarı üret ya da göster."""
    import secrets

    from jobradar.config import set_env_value

    cfg, _ = _load(config)
    env_name = cfg.server.api_token_env
    current = os.environ.get(env_name, "").strip()
    if current and not new:
        console.print(f"Mevcut anahtar:\n\n[bold]{current}[/bold]\n\nMac uygulamasının ayarlarına bunu yapıştır.")
        return
    token = secrets.token_urlsafe(32)
    set_env_value(cfg.base_dir / ".env", env_name, token)
    console.print(f"[green]✓[/green] Yeni anahtar .env dosyasına kaydedildi:\n\n[bold]{token}[/bold]\n")
    console.print("Mac uygulamasının ayarlarına bunu yapıştır. Panel servisini yeniden başlat: "
                  "sudo systemctl restart jobradar-web")


@app.command()
def email(config: Optional[Path] = ConfigOpt,
          test: bool = typer.Option(False, "--test", help="Ayar sorma, sadece test maili gönder")) -> None:
    """Günlük e-posta özetini ayarla (Gmail uygulama şifresi) ve test maili gönder."""
    from jobradar.config import set_env_value
    from jobradar.mailer import MailError, send_mail, smtp_settings

    cfg, _ = _load(config)
    ec = cfg.notify.email
    if not test:
        user = typer.prompt("Gönderen Gmail adresi", default=os.environ.get(ec.user_env, "") or None).strip()
        password = typer.prompt("Gmail uygulama şifresi (16 hane, ekranda görünmez)", hide_input=True)
        password = password.replace(" ", "").strip()
        if len(password) != 16:
            console.print("[yellow]Uyarı: uygulama şifresi genelde 16 karakterdir.[/yellow]")
        to = typer.prompt("Özetin gideceği adres", default=os.environ.get(ec.to_env, "") or user).strip()
        env_path = cfg.base_dir / ".env"
        for key, value in ((ec.user_env, user), (ec.password_env, password), (ec.to_env, to)):
            set_env_value(env_path, key, value)
            os.environ[key] = value
        console.print(f"[green]✓[/green] Kaydedildi: {env_path}")
    settings = smtp_settings(cfg)
    if not settings:
        console.print("[red]E-posta ayarı eksik (SMTP_USER / SMTP_PASSWORD).[/red]")
        raise typer.Exit(1)
    try:
        send_mail(settings, "JobRadar test", "JobRadar e-posta ayarı çalışıyor. Günlük özet bu adrese gelecek.")
    except MailError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Test maili gönderildi: {settings.to}")


@app.command("mail-sync")
def mail_sync_cmd(config: Optional[Path] = ConfigOpt,
                  list_only: bool = typer.Option(False, "--list", help="Okumadan, onay bekleyenleri göster"),
                  apply: Optional[int] = typer.Option(None, "--apply", help="Bu yanıtın önerisini uygula (id)"),
                  dismiss: Optional[int] = typer.Option(None, "--dismiss", help="Bu yanıtı yok say (id)"),
                  job: Optional[str] = typer.Option(None, "--job", help="--apply ile: eşleşmeyen yanıt için ilan id")
                  ) -> None:
    """Şirketlerden gelen e-posta yanıtlarını oku (salt okunur) ve durum önerilerini göster."""
    from jobradar.mailsync import apply_signal, dismiss_signal, imap_credentials, signal_view, sync_mail

    cfg, _ = _load(config)
    conn = db.connect(cfg.db_path)
    try:
        if apply is not None or dismiss is not None:
            try:
                if apply is not None:
                    jid = _job(conn, job)["id"] if job else None
                    res = apply_signal(conn, apply, jid)
                    console.print(f"[green]✓[/green] Uygulandı: {res['job_id']} → "
                                  f"{STATUS_LABELS_TR.get(res['status'], res['status'])}")
                else:
                    dismiss_signal(conn, dismiss)
                    console.print("[green]✓[/green] Yok sayıldı")
            except (KeyError, ValueError) as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)
            return
        if not list_only:
            if not imap_credentials(cfg):
                console.print("[red]E-posta ayarı yok. Önce: jobradar email[/red]")
                raise typer.Exit(1)
            res = sync_mail(conn, cfg)
            if res.error:
                console.print(f"[red]✗ {res.error}[/red]")
                raise typer.Exit(1)
            console.print(f"[green]✓[/green] {res.checked} yeni mail kontrol edildi: {res.relevant} başvuru yanıtı, "
                          f"{len(res.new)} kayıt")
        pending = [signal_view(conn, x) for x in db.mail_signals(conn, state="pending")]
        if not pending:
            console.print("Onay bekleyen yanıt yok.")
            return
        t = Table(title=f"Onay bekleyen yanıtlar ({len(pending)})")
        for col in ("id", "tür", "ilan", "öneri", "konu"):
            t.add_column(col)
        for x in pending:
            job_text = f"{x['job_title'][:40]} @ {x['job_company'][:25]}" if x["job_id"] else "[yellow]eşleşmedi[/yellow]"
            t.add_row(str(x["id"]), x["kind_label"], job_text, x["proposed_label"] or "–", x["subject"][:60])
        console.print(t)
        console.print("Uygula: jobradar mail-sync --apply ID  (eşleşmeyende --job İLAN_ID)  ·  "
                      "Yok say: jobradar mail-sync --dismiss ID")
    finally:
        conn.close()


@app.command()
def answers(job_id: Optional[str] = typer.Argument(None, help="İlan id'si (boşsa genel cevaplar)"),
            config: Optional[Path] = ConfigOpt,
            lang: Optional[str] = typer.Option(None, "--lang", help="de ya da en (varsayılan: ilanın dili)")) -> None:
    """Başvuru formu cevapları: data/answers.yaml + profil + ilana özel bilgiler (kopyala yapıştır için)."""
    from jobradar.answers import ensure_answers_file, job_answers, load_general, profile_items

    cfg, prof = _load(config)
    path = ensure_answers_file(cfg)
    try:
        general, missing = load_general(cfg)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    if not job_id:
        groups = [{"title": "Profil", "items": profile_items(prof)}, {"title": "Genel sorular", "items": general}]
        language = lang or "de"
    else:
        conn = db.connect(cfg.db_path)
        try:
            data = job_answers(cfg, conn, prof, _job(conn, job_id))
        finally:
            conn.close()
        groups, missing, language = data["groups"], data["missing"], lang or data["language"]
    for g in groups:
        if not g["items"]:
            continue
        console.print(f"\n[bold]{g['title']}[/bold]")
        for item in g["items"]:
            console.print(f"  [dim]{item['label']}:[/dim] {item.get(language) or item['de']}", highlight=False)
    if missing:
        console.print(f"\n[yellow]Doldurulmamış ({len(missing)}):[/yellow] " + ", ".join(missing))
    console.print(f"\nCevap dosyası: {path}")


@app.command()
def gaps(config: Optional[Path] = ConfigOpt,
         min_score: float = typer.Option(3.0, "--min-score", help="Sadece bu puan ve üstü ilanlar"),
         days: int = typer.Option(120, help="Son kaç günün değerlendirmeleri"),
         limit: int = typer.Option(20, help="En fazla kaç beceri")) -> None:
    """Değerlendirmelerde en sık eksik çıkan beceriler (neyi öğrenmeli?)."""
    from jobradar.scoring.gaps import skill_gaps

    cfg, _ = _load(config)
    conn = db.connect(cfg.db_path)
    try:
        data = skill_gaps(conn, min_score=min_score, days=days, limit=limit)
    finally:
        conn.close()
    if not data["terms"]:
        console.print(f"{data['jobs_considered']} değerlendirmede tekrar eden eksik beceri bulunmadı.")
        return
    t = Table(title=f"Eksik beceriler ({data['jobs_considered']} ilan, puan ≥ {min_score:g}, son {days} gün)")
    for col in ("beceri", "ilan", "eksik", "kısmen", "zorunlu", "ort. puan", "örnek"):
        t.add_column(col)
    for x in data["terms"]:
        ex = x["examples"][0] if x["examples"] else {}
        t.add_row(x["term"], str(x["jobs"]), str(x["gap"]), str(x["partial"]), str(x["must"]),
                  f"{x['avg_score']:.1f}" if x["avg_score"] is not None else "–",
                  f"{ex.get('title', '')[:30]} @ {ex.get('company', '')[:20]}" if ex else "")
    console.print(t)
    for o in data["other"]:
        console.print(f"  • {o['text'][:100]} ({o['jobs']} ilan)")


@app.command()
def backup(config: Optional[Path] = ConfigOpt,
           keep: Optional[int] = typer.Option(None, help="Kaç yedek saklansın")) -> None:
    """Veritabanının tutarlı bir yedeğini data/backups içine al, eskileri sil."""
    from jobradar.web.api import write_backup

    cfg, _ = _load(config)
    folder = cfg.data_path / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = write_backup(cfg.db_path, folder / f"jobradar-{today_iso()}.db")
    keep = keep or cfg.server.backups_keep
    old = sorted(folder.glob("jobradar-*.db"))[:-keep] if keep > 0 else []
    for p in old:
        p.unlink(missing_ok=True)
    console.print(f"[green]✓[/green] {target} ({target.stat().st_size // 1024} KB), {len(old)} eski yedek silindi")


@app.command("list")
def list_cmd(config: Optional[Path] = ConfigOpt, view: str = typer.Option("inbox", help="inbox|active|filtered|all"),
             track: Optional[str] = None, limit: int = 30) -> None:
    """İlanları listele."""
    cfg, prof = _load(config)
    conn = db.connect(cfg.db_path)
    try:
        statuses = {"inbox": ["new", "shortlisted"], "active": ["shortlisted", "tailored", "approved", "applied",
                    "interview"], "filtered": ["filtered"], "all": None}.get(view, ["new", "shortlisted"])
        rows = db.list_jobs(conn, statuses=statuses, track=track, include_filtered=view in ("filtered", "all"),
                            limit=limit)
    finally:
        conn.close()
    t = Table()
    for col in ("id", "puan", "ilan", "şirket", "konum", "işaretler", "durum"):
        t.add_column(col)
    for j in rows:
        score = f"{j['llm_score']:.1f}" if j.get("llm_score") is not None else f"[dim]{j['prescore']:.0f}[/dim]"
        flags = ", ".join(l for l, _ in flag_labels(j.get("flags") or {}, prof.german_level))[:40]
        t.add_row(j["id"][:8], score, clean_title(j["title"])[:50], (j["company"] or "")[:25], (j["location"] or "")[:20],
                  flags, STATUS_LABELS_TR.get(j["status"], j["status"]))
    console.print(t)


@app.command()
def show(job_id: str, config: Optional[Path] = ConfigOpt) -> None:
    """Bir ilanın ayrıntıları."""
    cfg, prof = _load(config)
    conn = db.connect(cfg.db_path)
    try:
        job = _job(conn, job_id)
        ev = db.latest_evaluation(conn, job["id"])
    finally:
        conn.close()
    console.print(f"[bold]{clean_title(job['title'])}[/bold] – {job['company']} ({job['location']})")
    console.print(f"{job['url']}\nDurum: {STATUS_LABELS_TR[job['status']]} · ön puan {job['prescore']}"
                  + (f" · LLM {job['llm_score']}" if job.get("llm_score") is not None else ""))
    labels = ", ".join(l for l, _ in flag_labels(job.get("flags") or {}, prof.german_level))
    if labels:
        console.print(f"İşaretler: {labels}")
    if job.get("filtered_reason"):
        console.print(f"[yellow]Elendi: {job['filtered_reason']}[/yellow]")
    if ev:
        r = ev["result"]
        console.print(f"\n[bold]Değerlendirme {ev['score']}/5 ({ev['verdict']})[/bold]\n{r.get('summary', '')}")
        for q in r.get("requirements") or []:
            console.print(f"  [{q['match']}] {q['requirement']} ← {', '.join(q.get('evidence') or []) or '-'}")


@app.command()
def tailor(job_id: str, config: Optional[Path] = ConfigOpt,
           lang: Optional[str] = typer.Option(None, help="de veya en (varsayılan: ilanın dili)")) -> None:
    """Bir ilan için CV, Anschreiben ve cevap taslakları üret (doğrulamalı)."""
    from jobradar.scoring.llm import LLMError, get_llm
    from jobradar.tailor.generate import tailor_job

    cfg, prof = _load(config)
    llm = get_llm(cfg)
    if not llm:
        console.print("[red]LLM bağlı değil.[/red]")
        raise typer.Exit(1)
    conn = db.connect(cfg.db_path)
    try:
        job = _job(conn, job_id)
        doc = tailor_job(cfg, prof, conn, job["id"], llm, language=lang)
    except LLMError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()
    v = doc.get("validation") or {}
    folder = cfg.applications_path / doc["folder"]
    console.print(f"[green]✓[/green] v{doc['version']} → {folder}")
    console.print("Doğrulama: " + ("temiz" if v.get("ok") else f"[yellow]{len(v.get('violations', []))} uyarı[/yellow]"))
    for r in v.get("removed") or []:
        console.print(f"  çıkarıldı: {r}")


@app.command()
def status(job_id: str, new_status: str = typer.Argument(..., help=", ".join(STATUSES)),
           note: str = typer.Option("", help="Not"), config: Optional[Path] = ConfigOpt) -> None:
    """Bir ilanın durumunu değiştir (örn. applied, interview, rejected)."""
    if new_status not in STATUSES:
        console.print(f"[red]Geçersiz durum. Seçenekler: {', '.join(STATUSES)}[/red]")
        raise typer.Exit(1)
    cfg, _ = _load(config)
    conn = db.connect(cfg.db_path)
    try:
        job = _job(conn, job_id)
        db.set_status(conn, job["id"], new_status, note)
        conn.commit()
    finally:
        conn.close()
    console.print(f"{clean_title(job['title'])}: {STATUS_LABELS_TR[new_status]}")


@app.command("add-url")
def add_url(url: str, config: Optional[Path] = ConfigOpt) -> None:
    """Herhangi bir ilan linkini ekle (StepStone, XING, şirket sayfası...)."""
    from jobradar.pipeline import import_raws
    from jobradar.sources.importers import raw_from_url

    cfg, prof = _load(config)
    try:
        raw = raw_from_url(make_client(), url)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Okunamadı: {exc}[/red]")
        raise typer.Exit(1)
    conn = db.connect(cfg.db_path)
    try:
        counts = import_raws(conn, cfg, prof, [raw], "import:url")
    finally:
        conn.close()
    console.print(f"{raw.title} – {raw.company}: " + ("eklendi" if counts.new else "zaten vardı, güncellendi")
                  + (" (filtreye takıldı)" if counts.filtered else ""))


@app.command("import-alert")
def import_alert(path: Path = typer.Argument(..., help=".eml/.txt dosyası ya da '-' (stdin)"),
                 config: Optional[Path] = ConfigOpt) -> None:
    """İş alarmı e-postasındaki ilan linklerini ekle."""
    from jobradar.pipeline import import_raws
    from jobradar.sources.importers import parse_alert_email

    cfg, prof = _load(config)
    content = sys.stdin.buffer.read() if str(path) == "-" else path.read_bytes()
    raws = parse_alert_email(content)
    if not raws:
        console.print("[yellow]İlan linki bulunamadı[/yellow]")
        raise typer.Exit(1)
    conn = db.connect(cfg.db_path)
    try:
        counts = import_raws(conn, cfg, prof, raws, "import:alert")
    finally:
        conn.close()
    console.print(f"{counts.found} link: {counts.new} yeni, {counts.merged} mevcut, {counts.filtered} elendi")


@app.command()
def inbox(config: Optional[Path] = ConfigOpt) -> None:
    """data/inbox klasöründeki alarm e-postalarını oku."""
    cfg, prof = _load(config)
    conn = db.connect(cfg.db_path)
    try:
        n = process_inbox(cfg, conn, prof)
    finally:
        conn.close()
    console.print(f"{n} yeni ilan")


@app.command()
def connections(path: Path, config: Optional[Path] = ConfigOpt) -> None:
    """LinkedIn Connections.csv dosyasını yükle (tanıdık eşleştirme)."""
    from jobradar.connections import load_connections_file

    cfg, _ = _load(config)
    contacts = load_connections_file(path)
    conn = db.connect(cfg.db_path)
    try:
        n = db.replace_contacts(conn, contacts)
    finally:
        conn.close()
    console.print(f"{n} bağlantı yüklendi")


@app.command()
def recheck(config: Optional[Path] = ConfigOpt) -> None:
    """Kısa listedeki ilanlar hâlâ açık mı?"""
    from jobradar.liveness import recheck as do_recheck

    cfg, _ = _load(config)
    conn = db.connect(cfg.db_path)
    try:
        stats = do_recheck(conn, make_client(), log=log)
    finally:
        conn.close()
    console.print(f"açık {stats['live']} · kapanmış {stats['closed']} · belirsiz {stats['uncertain']}")


@app.command()
def refilter(config: Optional[Path] = ConfigOpt) -> None:
    """Filtre ve ön puanları (ayar/profil değişikliğinden sonra) yeniden uygula."""
    from jobradar.pipeline import refilter_all

    cfg, prof = _load(config)
    conn = db.connect(cfg.db_path)
    try:
        changed, kept = refilter_all(conn, cfg, prof)
    finally:
        conn.close()
    console.print(f"{changed} ilan değişti, {kept} ilan gelen kutusunda")


@app.command()
def digest(config: Optional[Path] = ConfigOpt, send: bool = typer.Option(False, help="Telegram'a gönder"),
           email: bool = typer.Option(False, "--email", help="E-posta özetini gönder (günde bir kez)"),
           force: bool = typer.Option(False, help="Bugün gönderilmiş olsa da tekrar gönder")) -> None:
    """Günlük özeti göster, Telegram'a ya da e-postaya gönder."""
    import re

    from jobradar.notify import Telegram, digest_text

    cfg, prof = _load(config)
    if email:
        from jobradar.mailer import MailError, build_digest, send_mail, smtp_settings

        settings = smtp_settings(cfg)
        if not settings:
            console.print("[red]E-posta ayarlı değil. Önce: jobradar email[/red]")
            raise typer.Exit(1)
        conn = db.connect(cfg.db_path)
        try:
            if not force and db.get_meta(conn, "last_email_digest") == today_iso():
                console.print("Bugünün özeti zaten gönderildi (--force ile tekrar gönderilir).")
                return
            d = build_digest(conn, cfg, prof.german_level)
            try:
                send_mail(settings, d.subject, d.text, d.html)
            except MailError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)
            db.set_meta(conn, "last_email_digest", today_iso())
        finally:
            conn.close()
        console.print(f"[green]✓[/green] Özet gönderildi: {settings.to} ({d.subject})")
        return
    conn = db.connect(cfg.db_path)
    try:
        text = digest_text(conn, cfg)
    finally:
        conn.close()
    if send:
        tg = Telegram.from_config(cfg)
        if not tg:
            console.print("[red]Telegram ayarlı değil[/red]")
            raise typer.Exit(1)
        console.print("gönderildi" if tg.send(text) else "[red]gönderilemedi[/red]")
    else:
        console.print(re.sub(r"</?b>", "", text))


@app.command()
def stats(config: Optional[Path] = ConfigOpt) -> None:
    """Huni ve kaynak istatistikleri."""
    cfg, _ = _load(config)
    conn = db.connect(cfg.db_path)
    try:
        counts = db.status_counts(conn)
        srcs = db.source_counts(conn)
        health = db.source_health(conn)
    finally:
        conn.close()
    t = Table(title="Durumlar")
    t.add_column("durum")
    t.add_column("adet", justify="right")
    for s in STATUSES:
        if counts.get(s):
            t.add_row(STATUS_LABELS_TR[s], str(counts[s]))
    console.print(t)
    t2 = Table(title="Kaynaklar")
    for col in ("kaynak", "ilan", "değerlendirilen", "ort. puan", "4.0+", "başvuru"):
        t2.add_column(col)
    for s in srcs:
        t2.add_row(s["source"], str(s["jobs"]), str(s["evaluated"]), str(s["avg_score"] or "–"), str(s["strong"]),
                   str(s["applied"]))
    console.print(t2)
    for h in health:
        if h.get("error"):
            console.print(f"[red]✗ {h['source']}: {h['error'][:160]}[/red]")


@app.command("detect-ats")
def detect_ats_cmd(url: str, name: Optional[str] = typer.Option(None, help="Şirket adı")) -> None:
    """Bir kariyer sayfasının hangi ATS'i kullandığını bul ve config satırını üret."""
    from jobradar.http import get_text
    from jobradar.sources.ats import detect_ats, fetch_company

    client = make_client()
    found = detect_ats(url)
    if not found:
        try:
            found = detect_ats(get_text(client, url))
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Sayfa açılamadı: {exc}[/red]")
            raise typer.Exit(1)
    if not found:
        console.print("[yellow]Bilinen bir ATS bulunamadı. İlanları tek tek 'jobradar add-url' ile ekleyebilirsin.[/yellow]")
        raise typer.Exit(1)
    company = name or url.split("//")[-1].split("/")[0].replace("www.", "").split(".")[0].title()
    for entry in found:
        c = CompanySource(name=company, ats=entry["ats"], slug=entry.get("slug", ""), url=entry.get("url", ""),
                          max_pages=1)
        try:
            n = len(fetch_company(client, c, ["Engineer"]))
            note = f"{n} ilan okundu"
        except Exception as exc:  # noqa: BLE001
            note = f"doğrulanamadı: {str(exc)[:100]}"
        fields = ", ".join(f"{k}: {v}" if k != "url" else f'url: "{v}"' for k, v in entry.items() if k != "ats")
        console.print(f"    - {{name: {company}, ats: {entry['ats']}, {fields}}}   # {note}")
    console.print("\nBu satırı jobradar.yaml > sources > companies altına ekle.")


@app.command()
def serve(config: Optional[Path] = ConfigOpt, host: str = "127.0.0.1", port: Optional[int] = None,
          open_browser: bool = typer.Option(True, "--open/--no-open", help="Tarayıcıyı aç"),
          workspace: Optional[Path] = typer.Option(None, "--workspace", help="Çalışma klasörü; yoksa boş olarak oluşturulur"),
          demo_mode: bool = typer.Option(False, "--demo", help="Örnek verilerle çalış: --workspace bir örnek veri klasörü olur")) -> None:
    """Yerel paneli başlat."""
    import uvicorn

    from jobradar.web.app import create_app

    from jobradar.web.auth import api_token

    if demo_mode:
        from jobradar.demo import ensure_demo
        from jobradar.scoring.fake import FakeLLM

        if workspace is None:
            console.print("[red]--demo için --workspace gerekli.[/red]")
            raise typer.Exit(1)
        try:
            cfg = ensure_demo(workspace, log=log)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        os.chdir(workspace.expanduser())
        port = port or cfg.dashboard_port
        # sample data only: an offline stand-in answers instead of a model, and nothing is scanned
        uvicorn.run(create_app(cfg, llm_factory=lambda c: FakeLLM(), cycle_runner=lambda c: None),
                    host="127.0.0.1", port=port, log_level="warning")
        return
    if workspace is not None:
        from jobradar.settings import ensure_workspace

        config = ensure_workspace(workspace)
        os.chdir(workspace.expanduser())
    try:
        cfg = load_config(config)   # the profile may not exist yet: the app creates it during setup
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    port = port or cfg.dashboard_port
    if host not in ("127.0.0.1", "localhost", "::1") and not api_token(cfg):
        console.print("[red]Panel dışarıya açılacak ama JOBRADAR_API_TOKEN yok. Önce: jobradar api-token[/red]")
        raise typer.Exit(1)
    url = f"http://{host}:{port}"
    console.print(f"Panel: [bold]{url}[/bold]  (durdurmak için Ctrl+C)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="warning")


@app.command()
def demo(directory: Path = typer.Option(Path("jobradar-demo"), "--dir"),
         serve_after: bool = typer.Option(True, "--serve/--no-serve"), port: int = 8788) -> None:
    """Örnek ilanlar ve çevrimdışı sahte LLM ile sistemi dene (anahtar gerekmez)."""
    from jobradar.demo import build_demo

    cfg = build_demo(directory, log=log)
    if serve_after:
        import uvicorn

        from jobradar.scoring.fake import FakeLLM
        from jobradar.web.app import create_app

        url = f"http://127.0.0.1:{port}"
        console.print(f"Demo paneli: [bold]{url}[/bold]  (Ctrl+C ile durdur)")
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
        uvicorn.run(create_app(cfg, llm_factory=lambda c: FakeLLM(), cycle_runner=lambda c: None),
                    host="127.0.0.1", port=port, log_level="warning")


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

LAUNCHD_LABEL = "com.jobradar.daily"


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def build_plist(cfg: AppConfig, times: list[str]) -> dict:
    intervals = []
    for t in times:
        h, _, m = t.partition(":")
        intervals.append({"Hour": int(h), "Minute": int(m or 0)})
    cfg.logs_path.mkdir(parents=True, exist_ok=True)
    path_env = os.environ.get("PATH", "")
    extra = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"), "/usr/bin", "/bin"]
    path_value = ":".join(dict.fromkeys([p for p in path_env.split(":") if p] + extra))
    return {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [sys.executable, "-m", "jobradar", "run", "--config", str(cfg.config_path)],
        "StartCalendarInterval": intervals if len(intervals) > 1 else intervals[0],
        "WorkingDirectory": str(cfg.base_dir),
        "StandardOutPath": str(cfg.logs_path / "daily.log"),
        "StandardErrorPath": str(cfg.logs_path / "daily.err.log"),
        "EnvironmentVariables": {"PATH": path_value, "PYTHONIOENCODING": "utf-8"},
        "ProcessType": "Background",
    }


@schedule_app.command("install")
def schedule_install(config: Optional[Path] = ConfigOpt,
                     time: List[str] = typer.Option(["08:40"], "--time", "-t", help="SS:DD, birden fazla verilebilir")) -> None:
    """Her gün belirtilen saat(ler)de `jobradar run` çalıştır."""
    cfg, _ = _load(config)
    system = platform.system()
    if system == "Darwin":
        path = _plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            plistlib.dump(build_plist(cfg, time), f)
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(path)], capture_output=True)
        res = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
        if res.returncode != 0:  # older macOS
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
            res = subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
        if res.returncode == 0:
            console.print(f"[green]✓[/green] Zamanlandı: her gün {', '.join(time)} ({path})")
            console.print(f"Kayıtlar: {cfg.logs_path / 'daily.log'}. Mac uykudaysa uyanınca çalışır.")
        else:
            console.print(f"[red]launchctl hatası: {res.stderr.strip()}[/red]")
    elif system == "Linux":
        cmd = f"cd {cfg.base_dir} && {sys.executable} -m jobradar run --config {cfg.config_path} >> {cfg.logs_path}/daily.log 2>&1"
        console.print("crontab -e ile şu satır(lar)ı ekle:")
        for t in time:
            h, _, m = t.partition(":")
            console.print(f"{int(m or 0)} {int(h)} * * * {cmd}")
    else:
        console.print("Windows Görev Zamanlayıcı için:")
        for i, t in enumerate(time):
            console.print(f'schtasks /Create /SC DAILY /ST {t} /TN "JobRadar{i}" /TR "\\"{sys.executable}\\" -m jobradar run --config \\"{cfg.config_path}\\""')


@schedule_app.command("remove")
def schedule_remove() -> None:
    """Zamanlamayı kaldır (macOS)."""
    path = _plist_path()
    if path.exists():
        res = subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
        if res.returncode != 0:
            subprocess.run(["launchctl", "unload", "-w", str(path)], capture_output=True)
        path.unlink()
        console.print("Zamanlama kaldırıldı")
    else:
        console.print("Zamanlama yok")


@schedule_app.command("show")
def schedule_show() -> None:
    """Mevcut zamanlamayı göster (macOS)."""
    path = _plist_path()
    if not path.exists():
        console.print("Zamanlama yok")
        return
    with path.open("rb") as f:
        data = plistlib.load(f)
    console.print(data.get("StartCalendarInterval"))
    console.print(" ".join(data.get("ProgramArguments", [])))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
