"""Daily digest by e-mail (Gmail SMTP with an app password, port 587 + STARTTLS).

Oracle Cloud blocks outbound port 25 but not 587, so this works from the server."""

from __future__ import annotations

import html
import json
import os
import smtplib
import sqlite3
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Optional

from jobradar.i18n import get_lang, t as tr
from jobradar import db
from jobradar.config import AppConfig, public_base_url
from jobradar.mailsync import KIND_TR
from jobradar.notify import follow_ups_due, health_alerts
from jobradar.processing.flags import flag_labels
from jobradar.processing.normalize import clean_title

MONTHS_TR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
             "Kasım", "Aralık"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
VERDICT_TR = {"apply": "başvur", "maybe": "belki", "skip": "geç"}


class MailError(Exception):
    pass


@dataclass
class SMTPSettings:
    host: str
    port: int
    user: str
    password: str
    to: str


def smtp_settings(cfg: AppConfig) -> Optional[SMTPSettings]:
    ec = cfg.notify.email
    user = os.environ.get(ec.user_env, "").strip()
    password = os.environ.get(ec.password_env, "").replace(" ", "").strip()
    if not ec.enabled or not user or not password:
        return None
    to = os.environ.get(ec.to_env, "").strip() or user
    return SMTPSettings(ec.host, ec.port, user, password, to)


def send_mail(settings: SMTPSettings, subject: str, text: str, html_body: str | None = None,
              smtp_factory=None) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"JobRadar <{settings.user}>"
    msg["To"] = settings.to
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    try:
        with (smtp_factory or smtplib.SMTP)(settings.host, settings.port, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.user, settings.password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(tr("E-posta sunucusu girişi reddetti. Gmail için normal şifre değil, 16 haneli uygulama "
                           "şifresi gerekir (myaccount.google.com/apppasswords).")) from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(tr("E-posta gönderilemedi ({host}:{port}): {error}", host=settings.host, port=settings.port,
                           error=exc)) from exc


def date_tr(dt: datetime) -> str:
    months = MONTHS_EN if get_lang() == "en" else MONTHS_TR
    return f"{dt.day} {months[dt.month - 1]}"


def job_link(base: str, job_id: str = "") -> str:
    """Link into the web panel, or (when the Mac app runs the engine) a link that opens the app."""
    if os.environ.get("JOBRADAR_APP_LINKS", "").strip() == "1":
        return f"{base}/open/job/{job_id}" if job_id else f"{base}/open"
    return f"{base}/jobs/{job_id}" if job_id else f"{base}/jobs"


def open_label() -> str:
    return tr("JobRadar'ı aç") if os.environ.get("JOBRADAR_APP_LINKS", "").strip() == "1" else tr("Paneli aç")


def _since(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def recent_evaluations(conn: sqlite3.Connection, hours: int = 24) -> list[dict[str, Any]]:
    """Latest evaluation per job created in the last `hours`, best first."""
    rows = conn.execute(
        """
        SELECT e.* FROM evaluations e
        JOIN (SELECT job_id, MAX(id) AS mid FROM evaluations WHERE created_at >= ? GROUP BY job_id) m
          ON e.id = m.mid
        ORDER BY e.score DESC
        """,
        (_since(hours),),
    ).fetchall()
    out = []
    for r in rows:
        job = db.get_job(conn, r["job_id"])
        if not job or job.get("status") in ("filtered", "skipped", "closed"):
            continue
        try:
            result = json.loads(r["result_json"])
        except (TypeError, json.JSONDecodeError):
            result = {}
        out.append({"job": job, "score": r["score"], "verdict": r["verdict"], "result": result})
    return out


def _esc(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def _job_card(item: dict[str, Any], base: str, german_level: str) -> tuple[list[str], str]:
    """Plain text lines and an HTML card for one evaluated job (digest and instant alert)."""
    e = _esc
    job, res = item["job"], item["result"]
    title = clean_title(job.get("title", ""))
    badges = ", ".join(lbl for lbl, _ in flag_labels(job.get("flags") or {}, german_level))
    verdict = tr(VERDICT_TR.get(item["verdict"] or "", item["verdict"] or ""))
    link = job_link(base, job["id"])
    posting = job.get("apply_url") or job.get("url") or ""
    summary = (res.get("summary") or "").strip()
    t = [f"• {item['score']:.1f}/5 ({verdict}) {title} @ {job.get('company', '')}, {job.get('location', '')}"]
    if badges:
        t.append(f"  {badges}")
    if summary:
        t.append(f"  {summary[:300]}")
    t.append(f"  JobRadar: {link}")
    if posting:
        t.append(f"  {tr('İlan')}: {posting}")
    color = "#1a7f37" if item["score"] >= 4.0 else "#9a6700"
    card = (
        f'<div style="border:1px solid #d0d7de;border-radius:8px;padding:12px 14px;margin:0 0 10px">'
        f'<div style="font-size:15px;font-weight:600"><a href="{e(link)}" style="color:#0969da;'
        f'text-decoration:none">{e(title)}</a></div>'
        f'<div style="color:#57606a;font-size:13px;margin:2px 0 6px">{e(job.get("company"))} · '
        f'{e(job.get("location"))}</div>'
        f'<div style="font-size:13px"><b style="color:{color}">{item["score"]:.1f}/5</b> · {e(verdict)}'
        + (f' · <span style="color:#57606a">{e(badges)}</span>' if badges else "")
        + "</div>"
        + (f'<div style="font-size:13px;margin-top:6px;line-height:1.45">{e(summary[:400])}</div>'
           if summary else "")
        + (f'<div style="font-size:12px;margin-top:6px"><a href="{e(posting)}" style="color:#0969da">'
           f'{e(tr("İlana git"))}</a></div>' if posting else "")
        + "</div>"
    )
    return t, card


@dataclass
class Digest:
    subject: str
    text: str
    html: str
    strong: int


def build_digest(conn: sqlite3.Connection, cfg: AppConfig, german_level: str = "",
                 now: datetime | None = None) -> Digest:
    ec = cfg.notify.email
    now = now or datetime.now()
    base = public_base_url(cfg)
    evals = recent_evaluations(conn)
    strong = [e for e in evals if (e["score"] or 0) >= ec.min_score][: ec.max_jobs]
    counts = db.status_counts(conn)
    new_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE first_seen >= ? AND status != 'filtered'",
                            (_since(24),)).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('new','shortlisted') AND llm_score IS NULL AND prescore >= ?",
        (cfg.scoring.prescore_min,)).fetchone()[0]
    due = follow_ups_due(conn, cfg)
    alerts = health_alerts(conn)
    replies = db.mail_signals(conn, state="pending", limit=8)

    day = date_tr(now)
    subject = (tr("JobRadar · {day}: {n} yeni güçlü ilan", day=day, n=len(strong)) if strong
               else tr("JobRadar · {day}: yeni güçlü ilan yok", day=day))

    t: list[str] = [tr("JobRadar günlük özet, {day}", day=day), ""]
    t.append(tr("Son 24 saatte: {new} yeni ilan, {evals} değerlendirme. Değerlendirme bekleyen: {pending}.",
                new=new_jobs, evals=len(evals), pending=pending))
    pipeline_line = tr("Kısa liste: {a} · Başvurulan: {b} · Mülakat: {c}", a=counts.get("shortlisted", 0),
                       b=counts.get("applied", 0), c=counts.get("interview", 0))
    t.append(pipeline_line)
    t.append("")
    e = _esc
    cards: list[str] = []
    if strong:
        t.append(tr("Puanı {score} ve üstü yeni ilanlar:", score=f"{ec.min_score:g}"))
        for item in strong:
            lines, card = _job_card(item, base, german_level)
            t.extend(lines)
            cards.append(card)
    else:
        t.append(tr("Bugün eşiği geçen yeni ilan yok."))
    if due:
        t.append("")
        t.append(tr("Takip zamanı gelen başvurular:"))
        for j in due[:6]:
            t.append(f"• {clean_title(j['title'])} @ {j['company']}")
    if replies:
        t.append("")
        t.append(tr("Onay bekleyen e-posta yanıtları:"))
        for r in replies:
            t.append(f"• {tr(KIND_TR.get(r['kind'], r['kind']))}: {r['subject'][:90]}")
    if alerts:
        t.append("")
        t.extend(alerts)
    t.append("")
    t.append(f"JobRadar: {job_link(base)}")
    text = "\n".join(t)

    due_html = "".join(f"<li>{e(clean_title(j['title']))} @ {e(j['company'])}</li>" for j in due[:6])
    alerts_html = "".join(f"<li>{e(a)}</li>" for a in alerts)
    replies_html = "".join(f"<li>{e(tr(KIND_TR.get(r['kind'], r['kind'])))}: {e(r['subject'][:90])}</li>" for r in replies)
    html_body = (
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:640px;'
        'margin:0 auto;color:#1f2328">'
        f'<h2 style="font-size:18px;margin:0 0 4px">{e(tr("JobRadar günlük özet"))}</h2>'
        f'<div style="color:#57606a;font-size:13px;margin-bottom:14px">{e(day)} · '
        + e(tr("son 24 saatte {new} yeni ilan, {evals} değerlendirme · bekleyen {pending}", new=new_jobs,
               evals=len(evals), pending=pending)) + "</div>"
        f'<div style="font-size:13px;margin-bottom:14px">{e(pipeline_line)}</div>'
        + ("".join(cards) if cards else f'<p style="font-size:14px">{e(tr("Bugün eşiği geçen yeni ilan yok."))}</p>')
        + (f'<h3 style="font-size:15px;margin:18px 0 6px">{e(tr("Takip zamanı gelenler"))}</h3>'
           f'<ul style="font-size:13px">{due_html}</ul>' if due else "")
        + (f'<h3 style="font-size:15px;margin:18px 0 6px">{e(tr("Onay bekleyen e-posta yanıtları"))}</h3>'
           f'<ul style="font-size:13px">{replies_html}</ul>' if replies else "")
        + (f'<h3 style="font-size:15px;margin:18px 0 6px">{e(tr("Kaynak uyarıları"))}</h3><ul style="font-size:13px">'
           f"{alerts_html}</ul>" if alerts else "")
        + f'<p style="font-size:13px;margin-top:18px"><a href="{e(job_link(base))}" style="color:#0969da">'
          f"{e(open_label())}</a></p></div>"
    )
    return Digest(subject=subject, text=text, html=html_body, strong=len(strong))


# ---------------------------------------------------------------------------
# Instant alert: one short mail as soon as a fresh evaluation is strong enough
# ---------------------------------------------------------------------------


def instant_candidates(conn: sqlite3.Connection, cfg: AppConfig, hours: int = 3) -> list[dict[str, Any]]:
    """Strong jobs evaluated in the last `hours` that have not been mailed yet (best first).

    The time window keeps the first run after enabling this from mailing old evaluations."""
    ec = cfg.notify.email
    out = []
    for item in recent_evaluations(conn, hours=hours):
        job = item["job"]
        if (item["score"] or 0) < ec.instant_min_score or job.get("status") not in ("new", "shortlisted"):
            continue
        if db.was_notified(conn, job["id"], "instant_email"):
            continue
        out.append(item)
    return out


def build_instant_alert(items: list[dict[str, Any]], cfg: AppConfig, german_level: str = "") -> Digest:
    base = public_base_url(cfg)
    if len(items) == 1:
        job = items[0]["job"]
        subject = tr("JobRadar · Yeni güçlü ilan: {title} @ {company} ({score}/5)",
                     title=clean_title(job.get("title", ""))[:70], company=job.get("company", "")[:40],
                     score=f"{items[0]['score']:.1f}")
    else:
        subject = tr("JobRadar · {n} yeni güçlü ilan", n=len(items))
    t = [tr("Az önce değerlendirilen ve eşiği geçen ilanlar. Erken başvuru şansını artırır."), ""]
    cards = []
    for item in items:
        lines, card = _job_card(item, base, german_level)
        t.extend(lines)
        cards.append(card)
    t += ["", f"JobRadar: {job_link(base)}"]
    html_body = (
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:640px;'
        'margin:0 auto;color:#1f2328">'
        f'<h2 style="font-size:18px;margin:0 0 4px">{_esc(tr("Yeni güçlü ilan"))}</h2>'
        f'<div style="color:#57606a;font-size:13px;margin-bottom:14px">'
        f'{_esc(tr("Az önce değerlendirildi. Erken başvuru şansını artırır."))}</div>'
        + "".join(cards)
        + f'<p style="font-size:13px;margin-top:18px"><a href="{_esc(job_link(base))}" style="color:#0969da">'
          f"{_esc(open_label())}</a></p></div>"
    )
    return Digest(subject=subject, text="\n".join(t), html=html_body, strong=len(items))


def send_instant_alerts(conn: sqlite3.Connection, cfg: AppConfig, german_level: str = "", *,
                        smtp_factory=None) -> int:
    """Mail fresh strong matches once. Returns how many jobs were included (0 if off or nothing new)."""
    ec = cfg.notify.email
    if not ec.instant:
        return 0
    settings = smtp_settings(cfg)
    if not settings:
        return 0
    items = instant_candidates(conn, cfg)[: max(1, ec.instant_max_jobs)]
    if not items:
        return 0
    alert = build_instant_alert(items, cfg, german_level)
    send_mail(settings, alert.subject, alert.text, alert.html, smtp_factory=smtp_factory)
    for item in items:
        db.mark_notified(conn, item["job"]["id"], "instant_email")
        db.add_event(conn, item["job"]["id"], "instant_alert", f"e-posta: {item['score']:.1f}/5")
    conn.commit()
    return len(items)
