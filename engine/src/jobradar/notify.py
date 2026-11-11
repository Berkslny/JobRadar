"""Telegram notifications (JobNavigator idea): new strong matches, a daily
digest and source-health alerts."""

from __future__ import annotations

import html
import os
import sqlite3
from typing import Any

import httpx

from jobradar.i18n import t
from jobradar import db
from jobradar.config import AppConfig
from jobradar.processing.flags import flag_labels
from jobradar.processing.normalize import clean_title
from jobradar.textutil import days_since, today_iso


class Telegram:
    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None):
        self.token = token
        self.chat_id = chat_id
        self.client = client or httpx.Client(timeout=20)

    @classmethod
    def from_config(cls, cfg: AppConfig) -> "Telegram | None":
        tc = cfg.notify.telegram
        if not tc.enabled:
            return None
        token, chat = os.environ.get(tc.token_env, ""), os.environ.get(tc.chat_id_env, "")
        if not token or not chat:
            return None
        return cls(token, chat)

    def send(self, text: str) -> bool:
        chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
        ok = True
        for chunk in chunks:
            try:
                r = self.client.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": chunk, "parse_mode": "HTML",
                          "disable_web_page_preview": True},
                )
                ok = ok and r.status_code == 200
            except httpx.HTTPError:
                ok = False
        return ok


def _e(s: Any) -> str:
    return html.escape(str(s or ""), quote=False)


def format_job(job: dict[str, Any], cfg: AppConfig, german_level: str = "") -> str:
    score = job.get("llm_score")
    score_txt = f"⭐ {score:.1f}/5" if score is not None else t("ön puan {score}", score=f"{job.get('prescore', 0):.0f}")
    badges = ", ".join(lbl for lbl, _ in flag_labels(job.get("flags") or {}, german_level))
    lines = [f"<b>{_e(clean_title(job.get('title', '')))}</b>",
             f"{_e(job.get('company'))} · {_e(job.get('location'))}",
             f"{score_txt}" + (f" · {_e(badges)}" if badges else "")]
    url = job.get("apply_url") or job.get("url")
    if url:
        lines.append(f"<a href=\"{_e(url)}\">{t('İlana git')}</a> · <a href=\"{_e(cfg.notify.dashboard_url)}/jobs/{job['id']}\">JobRadar</a>")
    return "\n".join(lines)


def notify_new_matches(conn: sqlite3.Connection, cfg: AppConfig, tg: Telegram, german_level: str = "") -> int:
    tc = cfg.notify.telegram
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status IN ('new','shortlisted') AND "
        "((llm_score IS NOT NULL AND llm_score >= ?) OR (llm_score IS NULL AND prescore >= ?)) "
        "ORDER BY COALESCE(llm_score * 20, prescore) DESC LIMIT 15",
        (tc.min_score, tc.min_prescore_without_llm),
    ).fetchall()
    jobs = [db.row_to_job(r) for r in rows]
    fresh = [j for j in jobs if not db.was_notified(conn, j["id"], "match")]
    if not fresh:
        return 0
    text = f"🎯 <b>{t('Yeni güçlü eşleşmeler')}</b>\n\n" + "\n\n".join(format_job(j, cfg, german_level) for j in fresh)
    if tg.send(text):
        for j in fresh:
            db.mark_notified(conn, j["id"], "match")
        conn.commit()
        return len(fresh)
    return 0


def digest_text(conn: sqlite3.Connection, cfg: AppConfig) -> str:
    counts = db.status_counts(conn)
    new_today = conn.execute("SELECT COUNT(*) FROM jobs WHERE substr(first_seen,1,10) = ? AND status != 'filtered'",
                             (today_iso(),)).fetchone()[0]
    lines = [f"📋 <b>{t('JobRadar günlük özet')}</b> ({today_iso()})",
             t("Bugün yeni: {n}", n=new_today) + " · "
             + t("Kısa liste: {a} · Başvurulan: {b} · Mülakat: {c}", a=counts.get("shortlisted", 0),
                 b=counts.get("applied", 0), c=counts.get("interview", 0))]
    top = conn.execute(
        "SELECT * FROM jobs WHERE status IN ('new','shortlisted') AND llm_score IS NOT NULL "
        "ORDER BY llm_score DESC LIMIT 5").fetchall()
    if top:
        lines.append(f"\n<b>{t('En iyi açık ilanlar')}</b>")
        for r in top:
            j = db.row_to_job(r)
            lines.append(f"• {j['llm_score']:.1f} – {_e(clean_title(j['title']))} @ {_e(j['company'])}")
    due = follow_ups_due(conn, cfg)
    if due:
        lines.append(f"\n<b>{t('Takip zamanı gelenler')}</b>")
        for j in due[:5]:
            lines.append(f"• {_e(clean_title(j['title']))} @ {_e(j['company'])} ({days_since(j.get('applied_at'))} {t('gün')})")
    return "\n".join(lines)


def follow_ups_due(conn: sqlite3.Connection, cfg: AppConfig) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM jobs WHERE status = 'applied' AND applied_at IS NOT NULL").fetchall()
    out = []
    for r in rows:
        j = db.row_to_job(r)
        age = days_since((j.get("applied_at") or "")[:10])
        last_change = days_since((j.get("status_changed_at") or "")[:10])
        if age is not None and age >= cfg.follow_up_days and (last_change is None or last_change >= cfg.follow_up_days):
            out.append(j)
    return out


def health_alerts(conn: sqlite3.Connection) -> list[str]:
    out = []
    for h in db.source_health(conn):
        if h.get("consecutive_empty", 0) >= 3:
            reason = h.get("error") or t("3 çalıştırmadır 0 ilan")
            out.append(t("⚠️ Kaynak '{source}' çalışmıyor olabilir: {reason}", source=h["source"], reason=reason[:200]))
    return out
