"""SQLite storage. One local file, no server (JobCtrl's local-first idea)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from jobradar.textutil import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  dedup_key TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  title_norm TEXT NOT NULL DEFAULT '',
  company TEXT NOT NULL DEFAULT '',
  company_norm TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  apply_url TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  lang TEXT NOT NULL DEFAULT '',
  posted_at TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  employment_type TEXT NOT NULL DEFAULT '',
  seniority TEXT NOT NULL DEFAULT '',
  remote TEXT NOT NULL DEFAULT '',
  salary_json TEXT,
  flags_json TEXT NOT NULL DEFAULT '{}',
  sources_json TEXT NOT NULL DEFAULT '[]',
  detail_ref TEXT NOT NULL DEFAULT '',
  needs_location_check INTEGER NOT NULL DEFAULT 0,
  track TEXT,
  prescore REAL NOT NULL DEFAULT 0,
  prescore_json TEXT NOT NULL DEFAULT '{}',
  llm_score REAL,
  verdict TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  status_changed_at TEXT,
  applied_at TEXT,
  notes TEXT NOT NULL DEFAULT '',
  filtered_reason TEXT,
  live_status TEXT,
  live_checked_at TEXT,
  enriched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_company_norm ON jobs(company_norm);
CREATE INDEX IF NOT EXISTS idx_jobs_dedup ON jobs(dedup_key);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS job_urls (
  url_key TEXT PRIMARY KEY,
  job_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  profile_hash TEXT NOT NULL DEFAULT '',
  score REAL,
  verdict TEXT,
  result_json TEXT NOT NULL,
  notes_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_eval_job ON evaluations(job_id);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  folder TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT '',
  files_json TEXT NOT NULL DEFAULT '[]',
  validation_json TEXT NOT NULL DEFAULT '{}',
  approved INTEGER NOT NULL DEFAULT 0,
  approved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_job ON documents(job_id);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);

CREATE TABLE IF NOT EXISTS source_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  found INTEGER NOT NULL DEFAULT 0,
  new INTEGER NOT NULL DEFAULT 0,
  merged INTEGER NOT NULL DEFAULT 0,
  filtered INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  warnings_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_runs_source ON source_runs(source);

CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  first_name TEXT NOT NULL DEFAULT '',
  last_name TEXT NOT NULL DEFAULT '',
  company TEXT NOT NULL DEFAULT '',
  company_norm TEXT NOT NULL DEFAULT '',
  position TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  connected_on TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_norm);

CREATE TABLE IF NOT EXISTS notifications (
  job_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  PRIMARY KEY (job_id, kind)
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mail_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL UNIQUE,
  job_id TEXT,
  received_at TEXT NOT NULL DEFAULT '',
  sender TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL DEFAULT '',
  snippet TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT '',
  proposed_status TEXT,
  candidates_json TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mail_signals_state ON mail_signals(state);
CREATE INDEX IF NOT EXISTS idx_mail_signals_job ON mail_signals(job_id);
"""

JSON_FIELDS = {
    "salary_json": "salary",
    "flags_json": "flags",
    "sources_json": "sources",
    "prescore_json": "prescore_detail",
}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Row <-> dict
# ---------------------------------------------------------------------------


def row_to_job(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    for col, key in JSON_FIELDS.items():
        raw = d.pop(col, None)
        if raw:
            try:
                d[key] = json.loads(raw)
            except json.JSONDecodeError:
                d[key] = None
        else:
            d[key] = None if key == "salary" else ({} if key != "sources" else [])
    d["needs_location_check"] = bool(d.get("needs_location_check"))
    return d


def _job_columns(job: dict[str, Any]) -> dict[str, Any]:
    cols = {
        "id": job["id"],
        "dedup_key": job.get("dedup_key", ""),
        "title": job.get("title", ""),
        "title_norm": job.get("title_norm", ""),
        "company": job.get("company", ""),
        "company_norm": job.get("company_norm", ""),
        "location": job.get("location", ""),
        "url": job.get("url", ""),
        "apply_url": job.get("apply_url", ""),
        "description": job.get("description", ""),
        "lang": job.get("lang", ""),
        "posted_at": job.get("posted_at"),
        "first_seen": job.get("first_seen") or now_iso(),
        "last_seen": job.get("last_seen") or now_iso(),
        "employment_type": job.get("employment_type", ""),
        "seniority": job.get("seniority", ""),
        "remote": job.get("remote", ""),
        "salary_json": json.dumps(job["salary"], ensure_ascii=False) if job.get("salary") else None,
        "flags_json": json.dumps(job.get("flags") or {}, ensure_ascii=False),
        "sources_json": json.dumps(job.get("sources") or [], ensure_ascii=False),
        "detail_ref": job.get("detail_ref", ""),
        "needs_location_check": 1 if job.get("needs_location_check") else 0,
        "track": job.get("track"),
        "prescore": float(job.get("prescore") or 0),
        "prescore_json": json.dumps(job.get("prescore_detail") or {}, ensure_ascii=False),
        "llm_score": job.get("llm_score"),
        "verdict": job.get("verdict"),
        "status": job.get("status", "new"),
        "status_changed_at": job.get("status_changed_at"),
        "applied_at": job.get("applied_at"),
        "notes": job.get("notes", ""),
        "filtered_reason": job.get("filtered_reason"),
        "live_status": job.get("live_status"),
        "live_checked_at": job.get("live_checked_at"),
        "enriched_at": job.get("enriched_at"),
    }
    return cols


def insert_job(conn: sqlite3.Connection, job: dict[str, Any]) -> None:
    cols = _job_columns(job)
    names = ", ".join(cols)
    marks = ", ".join(f":{k}" for k in cols)
    conn.execute(f"INSERT INTO jobs ({names}) VALUES ({marks})", cols)


def update_job(conn: sqlite3.Connection, job: dict[str, Any]) -> None:
    cols = _job_columns(job)
    sets = ", ".join(f"{k} = :{k}" for k in cols if k != "id")
    conn.execute(f"UPDATE jobs SET {sets} WHERE id = :id", cols)


def update_fields(conn: sqlite3.Connection, job_id: str, **fields: Any) -> None:
    if not fields:
        return
    mapped: dict[str, Any] = {}
    for k, v in fields.items():
        if k in ("salary", "flags", "sources", "prescore_detail"):
            col = {"salary": "salary_json", "flags": "flags_json", "sources": "sources_json",
                   "prescore_detail": "prescore_json"}[k]
            mapped[col] = json.dumps(v, ensure_ascii=False) if v is not None else None
        else:
            mapped[k] = v
    sets = ", ".join(f"{k} = :{k}" for k in mapped)
    mapped["_id"] = job_id
    conn.execute(f"UPDATE jobs SET {sets} WHERE id = :_id", mapped)


def get_job(conn: sqlite3.Connection, job_id: str) -> Optional[dict[str, Any]]:
    return row_to_job(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def find_job_by_prefix(conn: sqlite3.Connection, prefix: str) -> Optional[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM jobs WHERE id LIKE ? LIMIT 2", (prefix + "%",)).fetchall()
    if len(rows) == 1:
        return row_to_job(rows[0])
    return None


def job_id_for_url(conn: sqlite3.Connection, url_key: str) -> Optional[str]:
    row = conn.execute("SELECT job_id FROM job_urls WHERE url_key = ?", (url_key,)).fetchone()
    return row["job_id"] if row else None


def add_url(conn: sqlite3.Connection, url_key: str, job_id: str) -> None:
    if url_key:
        conn.execute("INSERT OR IGNORE INTO job_urls (url_key, job_id) VALUES (?, ?)", (url_key, job_id))


def jobs_by_dedup_key(conn: sqlite3.Connection, key: str) -> list[dict[str, Any]]:
    return [row_to_job(r) for r in conn.execute("SELECT * FROM jobs WHERE dedup_key = ?", (key,))]


def jobs_by_company(conn: sqlite3.Connection, company_norm: str) -> list[dict[str, Any]]:
    if not company_norm:
        return []
    return [row_to_job(r) for r in conn.execute("SELECT * FROM jobs WHERE company_norm = ?", (company_norm,))]


def reassign_urls(conn: sqlite3.Connection, from_id: str, to_id: str) -> None:
    conn.execute("UPDATE OR IGNORE job_urls SET job_id = ? WHERE job_id = ?", (to_id, from_id))
    conn.execute("DELETE FROM job_urls WHERE job_id = ?", (from_id,))


def delete_job(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.execute("DELETE FROM job_urls WHERE job_id = ?", (job_id,))


def _job_filter(statuses: Iterable[str] | None, track: str | None, min_score: float | None,
                query: str | None, include_filtered: bool) -> tuple[str, list[Any]]:
    """WHERE clause shared by list_jobs and count_jobs."""
    where: list[str] = []
    params: list[Any] = []
    if statuses:
        st = list(statuses)
        where.append(f"status IN ({','.join('?' * len(st))})")
        params += st
    if not include_filtered:
        where.append("status != 'filtered'")
    if track:
        where.append("track = ?")
        params.append(track)
    if min_score is not None:
        where.append("COALESCE(llm_score * 20, prescore) >= ?")
        params.append(min_score)
    if query:
        where.append("(title LIKE ? OR company LIKE ? OR location LIKE ?)")
        q = f"%{query}%"
        params += [q, q, q]
    return (" WHERE " + " AND ".join(where)) if where else "", params


def list_jobs(
    conn: sqlite3.Connection,
    *,
    statuses: Iterable[str] | None = None,
    track: str | None = None,
    min_score: float | None = None,
    query: str | None = None,
    include_filtered: bool = False,
    order: str = "score",
    limit: int | None = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Postings matching the filters; `limit=None` returns all of them (from `offset`)."""
    clause, params = _job_filter(statuses, track, min_score, query, include_filtered)
    sql = "SELECT * FROM jobs" + clause
    if order == "date":
        sql += " ORDER BY COALESCE(posted_at, substr(first_seen, 1, 10)) DESC, prescore DESC"
    elif order == "company":
        sql += " ORDER BY company COLLATE NOCASE, title COLLATE NOCASE"
    else:
        sql += " ORDER BY (llm_score IS NULL), llm_score DESC, prescore DESC"
    sql += ", id"  # stable order, so pages do not overlap
    if limit is not None or offset:
        sql += " LIMIT ? OFFSET ?"
        params += [limit if limit is not None else -1, max(0, offset)]
    return [row_to_job(r) for r in conn.execute(sql, params)]


def count_jobs(
    conn: sqlite3.Connection,
    *,
    statuses: Iterable[str] | None = None,
    track: str | None = None,
    min_score: float | None = None,
    query: str | None = None,
    include_filtered: bool = False,
) -> int:
    clause, params = _job_filter(statuses, track, min_score, query, include_filtered)
    return int(conn.execute("SELECT COUNT(*) FROM jobs" + clause, params).fetchone()[0])


def set_status(conn: sqlite3.Connection, job_id: str, status: str, note: str = "") -> None:
    now = now_iso()
    fields: dict[str, Any] = {"status": status, "status_changed_at": now}
    if status == "applied":
        fields["applied_at"] = now
    update_fields(conn, job_id, **fields)
    add_event(conn, job_id, "status", f"{status}{(': ' + note) if note else ''}")


def add_event(conn: sqlite3.Connection, job_id: Optional[str], kind: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO events (job_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
        (job_id, now_iso(), kind, detail),
    )


def events_for(conn: sqlite3.Connection, job_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM events WHERE job_id = ? ORDER BY id DESC", (job_id,))]


# ---------------------------------------------------------------------------
# Evaluations & documents
# ---------------------------------------------------------------------------


def save_evaluation(
    conn: sqlite3.Connection, job_id: str, *, provider: str, model: str, profile_hash: str,
    score: float, verdict: str, result: dict, notes: list[str],
) -> int:
    cur = conn.execute(
        "INSERT INTO evaluations (job_id, created_at, provider, model, profile_hash, score, verdict, result_json, notes_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, now_iso(), provider, model, profile_hash, score, verdict,
         json.dumps(result, ensure_ascii=False), json.dumps(notes, ensure_ascii=False)),
    )
    update_fields(conn, job_id, llm_score=score, verdict=verdict)
    return int(cur.lastrowid)


def latest_evaluation(conn: sqlite3.Connection, job_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM evaluations WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["result"] = json.loads(d.pop("result_json"))
    d["notes"] = json.loads(d.pop("notes_json") or "[]")
    return d


def save_document(
    conn: sqlite3.Connection, job_id: str, *, version: int, folder: str, language: str,
    files: list[str], validation: dict,
) -> int:
    cur = conn.execute(
        "INSERT INTO documents (job_id, version, created_at, folder, language, files_json, validation_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, version, now_iso(), folder, language, json.dumps(files), json.dumps(validation, ensure_ascii=False)),
    )
    return int(cur.lastrowid)


def documents_for(conn: sqlite3.Connection, job_id: str) -> list[dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT * FROM documents WHERE job_id = ? ORDER BY version DESC", (job_id,)):
        d = dict(r)
        d["files"] = json.loads(d.pop("files_json") or "[]")
        d["validation"] = json.loads(d.pop("validation_json") or "{}")
        out.append(d)
    return out


def get_document(conn: sqlite3.Connection, doc_id: int) -> Optional[dict[str, Any]]:
    r = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["files"] = json.loads(d.pop("files_json") or "[]")
    d["validation"] = json.loads(d.pop("validation_json") or "{}")
    return d


def approve_document(conn: sqlite3.Connection, doc_id: int) -> None:
    doc = get_document(conn, doc_id)
    if not doc:
        return
    conn.execute("UPDATE documents SET approved = 0, approved_at = NULL WHERE job_id = ?", (doc["job_id"],))
    conn.execute("UPDATE documents SET approved = 1, approved_at = ? WHERE id = ?", (now_iso(), doc_id))


# ---------------------------------------------------------------------------
# Source runs
# ---------------------------------------------------------------------------


def start_source_run(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute("INSERT INTO source_runs (source, started_at) VALUES (?, ?)", (source, now_iso()))
    conn.commit()
    return int(cur.lastrowid)


def finish_source_run(
    conn: sqlite3.Connection, run_id: int, *, found: int, new: int, merged: int, filtered: int,
    error: str | None, warnings: list[str],
) -> None:
    conn.execute(
        "UPDATE source_runs SET finished_at = ?, found = ?, new = ?, merged = ?, filtered = ?, error = ?,"
        " warnings_json = ? WHERE id = ?",
        (now_iso(), found, new, merged, filtered, error, json.dumps(warnings[:20], ensure_ascii=False), run_id),
    )
    conn.commit()


def source_health(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT r.* FROM source_runs r
        JOIN (SELECT source, MAX(id) AS mid FROM source_runs GROUP BY source) m ON r.id = m.mid
        ORDER BY r.source
        """
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["warnings"] = json.loads(d.pop("warnings_json") or "[]")
        recent = conn.execute(
            "SELECT found, error FROM source_runs WHERE source = ? ORDER BY id DESC LIMIT 3", (d["source"],)
        ).fetchall()
        d["consecutive_empty"] = 0
        for rr in recent:
            if rr["error"] or rr["found"] == 0:
                d["consecutive_empty"] += 1
            else:
                break
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Contacts, notifications, meta
# ---------------------------------------------------------------------------


def replace_contacts(conn: sqlite3.Connection, contacts: list[dict[str, str]]) -> int:
    conn.execute("DELETE FROM contacts")
    for c in contacts:
        conn.execute(
            "INSERT INTO contacts (first_name, last_name, company, company_norm, position, url, connected_on)"
            " VALUES (:first_name, :last_name, :company, :company_norm, :position, :url, :connected_on)",
            c,
        )
    conn.commit()
    return len(contacts)


def contacts_for_company(conn: sqlite3.Connection, company_norm: str) -> list[dict[str, Any]]:
    if not company_norm or len(company_norm) < 3:
        return []
    rows = conn.execute("SELECT * FROM contacts WHERE company_norm != ''").fetchall()
    out = []
    for r in rows:
        cn = r["company_norm"]
        if cn == company_norm or (len(cn) >= 4 and len(company_norm) >= 4 and (
            cn.startswith(company_norm + " ") or company_norm.startswith(cn + " "))):
            out.append(dict(r))
    return out


def was_notified(conn: sqlite3.Connection, job_id: str, kind: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM notifications WHERE job_id = ? AND kind = ?", (job_id, kind)
    ).fetchone() is not None


def mark_notified(conn: sqlite3.Connection, job_id: str, kind: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO notifications (job_id, kind, sent_at) VALUES (?, ?, ?)", (job_id, kind, now_iso())
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")}


def source_counts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Per source: total jobs, evaluated, avg LLM score, applied."""
    stats: dict[str, dict[str, Any]] = {}
    for r in conn.execute("SELECT sources_json, llm_score, status FROM jobs WHERE status != 'filtered'"):
        try:
            sources = json.loads(r["sources_json"] or "[]")
        except json.JSONDecodeError:
            sources = []
        names = {s.get("source", "?").split(":")[0] for s in sources} or {"?"}
        for name in names:
            s = stats.setdefault(name, {"source": name, "jobs": 0, "evaluated": 0, "score_sum": 0.0,
                                        "strong": 0, "applied": 0})
            s["jobs"] += 1
            if r["llm_score"] is not None:
                s["evaluated"] += 1
                s["score_sum"] += r["llm_score"]
                if r["llm_score"] >= 4.0:
                    s["strong"] += 1
            if r["status"] in ("applied", "interview", "offer", "rejected"):
                s["applied"] += 1
    out = []
    for s in stats.values():
        s["avg_score"] = round(s["score_sum"] / s["evaluated"], 2) if s["evaluated"] else None
        s.pop("score_sum")
        out.append(s)
    return sorted(out, key=lambda x: -x["jobs"])


# ---------------------------------------------------------------------------
# Mail signals (replies from companies, see mailsync.py)
# ---------------------------------------------------------------------------


def _signal(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    try:
        d["candidates"] = json.loads(d.pop("candidates_json") or "[]")
    except json.JSONDecodeError:
        d["candidates"] = []
    return d


def mail_signal_exists(conn: sqlite3.Connection, message_id: str) -> bool:
    return conn.execute("SELECT 1 FROM mail_signals WHERE message_id = ?", (message_id,)).fetchone() is not None


def add_mail_signal(conn: sqlite3.Connection, sig: dict[str, Any]) -> Optional[int]:
    cur = conn.execute(
        """INSERT OR IGNORE INTO mail_signals (message_id, job_id, received_at, sender, subject, snippet, kind,
           proposed_status, candidates_json, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sig["message_id"], sig.get("job_id"), sig.get("received_at", ""), sig.get("sender", ""),
         sig.get("subject", ""), sig.get("snippet", ""), sig.get("kind", ""), sig.get("proposed_status"),
         json.dumps(sig.get("candidates") or [], ensure_ascii=False), sig.get("state", "pending"), now_iso()),
    )
    return cur.lastrowid if cur.rowcount else None


def get_mail_signal(conn: sqlite3.Connection, signal_id: int) -> Optional[dict[str, Any]]:
    return _signal(conn.execute("SELECT * FROM mail_signals WHERE id = ?", (signal_id,)).fetchone())


def mail_signals(conn: sqlite3.Connection, state: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
    if state:
        rows = conn.execute("SELECT * FROM mail_signals WHERE state = ? ORDER BY received_at DESC, id DESC LIMIT ?",
                            (state, limit))
    else:
        rows = conn.execute("SELECT * FROM mail_signals ORDER BY received_at DESC, id DESC LIMIT ?", (limit,))
    return [_signal(r) for r in rows]


def mail_signals_for_job(conn: sqlite3.Connection, job_id: str) -> list[dict[str, Any]]:
    return [_signal(r) for r in conn.execute(
        "SELECT * FROM mail_signals WHERE job_id = ? ORDER BY received_at DESC", (job_id,))]


def set_mail_signal_state(conn: sqlite3.Connection, signal_id: int, state: str, job_id: Optional[str] = None) -> None:
    if job_id is not None:
        conn.execute("UPDATE mail_signals SET state = ?, job_id = ?, decided_at = ? WHERE id = ?",
                     (state, job_id, now_iso(), signal_id))
    else:
        conn.execute("UPDATE mail_signals SET state = ?, decided_at = ? WHERE id = ?", (state, now_iso(), signal_id))


def pending_mail_signal_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM mail_signals WHERE state = 'pending'").fetchone()[0]
