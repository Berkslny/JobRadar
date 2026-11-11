"""Progress of the running scan, for the progress bar in the Mac app and the panel.

Stored in the database (meta key `cycle_progress`) so it works whichever process runs the
cycle: the panel's background thread, `jobradar run` in a terminal or a server timer."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from jobradar import db
from jobradar.textutil import now_iso
from jobradar.i18n import t

KEY = "cycle_progress"

# stage → (label, start, end) as fractions of the whole run
STAGES: dict[str, tuple[str, float, float]] = {
    "queued": ("Başlatılıyor", 0.0, 0.0),
    "scan": ("İlanlar taranıyor", 0.0, 0.45),
    "enrich": ("Açıklamalar tamamlanıyor", 0.45, 0.6),
    "evaluate": ("LLM değerlendirmesi", 0.6, 0.95),
    "mail": ("E-posta yanıtları okunuyor", 0.95, 0.98),
    "notify": ("Bildirimler gönderiliyor", 0.98, 1.0),
}
SOURCE_NAMES = {"arbeitsagentur": "Arbeitsagentur", "freehire": "freehire (XING, EURES, şirketler)",
                "companies": "şirket kariyer sayfaları", "jobspy": "LinkedIn ve Indeed"}


def read(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        data = json.loads(db.get_meta(conn, KEY, "") or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def mark_queued(conn: sqlite3.Connection, quick: bool = False) -> None:
    """Called when a run is requested, before its thread or process starts."""
    try:
        db.set_meta(conn, KEY, json.dumps({"stage": "queued", "label": t(STAGES["queued"][0]), "detail": "",
                                           "done": 0, "total": 0, "fraction": 0.0, "quick": quick,
                                           "started_at": now_iso(), "updated_at": now_iso()}, ensure_ascii=False))
    except sqlite3.Error:
        pass  # a progress bar must never block a run


class CycleProgress:
    # seconds between two in-stage updates (stage changes and first steps are always written)
    THROTTLE = 0.3

    def __init__(self, conn: sqlite3.Connection, *, quick: bool = False):
        self.conn = conn
        self.quick = quick
        self.started_at = now_iso()
        self.new_jobs = 0
        self.evaluated = 0
        self._source: tuple[int, int, str] = (0, 0, "")
        self._last_write = 0.0
        self._write({"stage": "scan", "label": t(STAGES["scan"][0]), "detail": "", "done": 0, "total": 0,
                     "fraction": 0.0})

    def _write(self, data: dict[str, Any]) -> None:
        data.update({"quick": self.quick, "started_at": self.started_at, "updated_at": now_iso(),
                     "new_jobs": self.new_jobs, "evaluated": self.evaluated})
        self._last_write = time.monotonic()
        try:
            db.set_meta(self.conn, KEY, json.dumps(data, ensure_ascii=False))
        except sqlite3.Error:
            pass  # a progress bar must never break a run

    def stage(self, key: str, detail: str = "", done: int = 0, total: int = 0, *,
              part: float | None = None, throttle: bool = False) -> None:
        """Write stage `key`; `part` (0..1) overrides done/total. Throttled writes may be skipped."""
        if throttle and time.monotonic() - self._last_write < self.THROTTLE:
            return
        label, start, end = STAGES[key]
        label = t(label)
        if part is None:
            part = min(1.0, done / total) if total else 0.0
        part = max(0.0, min(1.0, part))
        self._write({"stage": key, "label": label, "detail": detail, "done": done, "total": total,
                     "fraction": round(start + (end - start) * part, 3)})

    # callbacks for pipeline functions -------------------------------------------------
    def _source_detail(self) -> str:
        i, n, name = self._source
        return f"{t(SOURCE_NAMES.get(name, name))} ({i + 1}/{n})"

    def on_source(self, i: int, n: int, name: str) -> None:
        self._source = (i, n, name)
        self.stage("scan", self._source_detail() if name else t("kaynaklar bitti"), i, n)

    def on_source_step(self, done: int, total: int, label: str = "") -> None:
        """Progress inside the current source: query or company `done` of `total`."""
        i, n, name = self._source
        if not n or not name or i >= n:
            return
        sub = min(1.0, done / total) if total else 0.0
        detail = self._source_detail()
        if label:
            detail += f" · {label} ({min(done + 1, total)}/{total})"
        self.stage("scan", detail, i, n, part=(i + sub) / n, throttle=done > 0)

    def on_enrich(self, i: int, n: int, label: str = "") -> None:
        detail = t("{i}/{n} ilan", i=min(i + 1, n), n=n) if n else ""
        if label and i < n:
            detail += f" · {label}"
        self.stage("enrich", detail, i, n, throttle=0 < i < n)

    def on_evaluate(self, i: int, n: int, label: str = "") -> None:
        detail = t("{i}/{n} ilan", i=min(i + 1, n), n=n) if n else t("değerlendirilecek ilan yok")
        if label and i < n:
            detail += f" · {label}"
        self.stage("evaluate", detail, i, n, throttle=0 < i < n)

    def finish(self, ok: bool = True, message: str = "") -> None:
        if not message:
            message = t("{new} yeni ilan, {evaluated} değerlendirme", new=self.new_jobs, evaluated=self.evaluated)
        self._write({"stage": "done" if ok else "failed", "label": t("Tamamlandı") if ok else t("Hata ile bitti"),
                     "detail": message, "done": 1, "total": 1, "fraction": 1.0, "ok": ok,
                     "finished_at": now_iso()})
