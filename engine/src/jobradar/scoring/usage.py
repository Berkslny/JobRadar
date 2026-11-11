"""A record of every call to the AI model: how big it was, how long it took, what it was for.

The numbers make changes measurable (a shorter prompt, another model). The prompt and the answer are
never stored, only their sizes. `get_llm` attaches the meter, so every provider is covered the same way.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator, Optional

from jobradar.textutil import now_iso

_TASK = re.compile(r"TASK: ([A-Z][A-Z ]+)")
PURPOSES = {"EVALUATE": "evaluate", "TAILOR": "tailor", "REVIEW": "review", "READ CV": "profile_import",
            "SET UP SEARCH": "search_setup"}
_tags: ContextVar[dict[str, Any]] = ContextVar("jobradar_llm_tags", default={})
_backlog: list[tuple[Path, dict[str, Any]]] = []
_backlog_lock = threading.Lock()
BACKLOG_MAX = 200
BUSY_SECONDS = 1.0   # how long a record waits for a database another writer holds


@contextmanager
def tagged(**tags: Any) -> Iterator[None]:
    """Calls made inside this block are recorded with these fields (job_id, purpose)."""
    token = _tags.set({**_tags.get(), **tags})
    try:
        yield
    finally:
        _tags.reset(token)


def purpose_of(user_prompt: str) -> str:
    m = _TASK.search(user_prompt[:400])
    return PURPOSES.get(m.group(1).strip(), "other") if m else "other"


def _int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def normalize(usage: dict[str, Any]) -> tuple[Optional[int], Optional[int], Optional[float]]:
    """(input tokens, output tokens, cost in USD) from the shapes the providers report.

    Anthropic and Claude Code: input_tokens (+ cache tokens), output_tokens; Claude Code adds what the call
    would have cost on the API. OpenAI-compatible: prompt_tokens, completion_tokens. Ollama: *_eval_count."""
    usage = usage or {}
    inp = _int(usage.get("input_tokens"))
    if inp is not None:
        inp += (_int(usage.get("cache_creation_input_tokens")) or 0) + (_int(usage.get("cache_read_input_tokens")) or 0)
    else:
        inp = _int(usage.get("prompt_tokens"))
        if inp is None:
            inp = _int(usage.get("prompt_eval_count"))
    out = _int(usage.get("output_tokens"))
    if out is None:
        out = _int(usage.get("completion_tokens"))
    if out is None:
        out = _int(usage.get("eval_count"))
    cost = usage.get("api_equivalent_usd")
    try:
        cost = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost = None
    return inp, out, cost


_COLUMNS = ("ts", "provider", "model", "tier", "purpose", "job_id", "ok", "error", "seconds", "prompt_chars",
            "output_chars", "input_tokens", "output_tokens", "cost_usd")


def _insert(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(f"INSERT INTO llm_calls ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})",
                 tuple(row.get(c) for c in _COLUMNS))


def _busy(exc: sqlite3.Error) -> bool:
    text = str(exc).lower()
    return isinstance(exc, sqlite3.OperationalError) and ("locked" in text or "busy" in text)


def _write(db_path: Path, rows: list[dict[str, Any]]) -> bool:
    """Own short-lived connection; gives up quickly when another writer holds the database.

    False only when the database was busy: then the rows are worth keeping for the next call. Rows that fail
    for any other reason would fail again, so they are given up (True)."""
    conn = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=BUSY_SECONDS)
        try:
            for row in rows:
                _insert(conn, row)
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            from jobradar import db  # a database made by an older version: add the new tables

            conn.rollback()
            conn.executescript(db.SCHEMA)
            for row in rows:
                _insert(conn, row)
        conn.commit()
        return True
    except sqlite3.Error as exc:
        return not _busy(exc)
    finally:
        if conn is not None:
            conn.close()


def record(db_path: Path, row: dict[str, Any]) -> None:
    """Store one call. A busy database never delays or breaks the call: the row waits for the next one."""
    with _backlog_lock:
        waiting = [r for p, r in _backlog if p == db_path]
        if _write(db_path, waiting + [row]):
            _backlog[:] = [(p, r) for p, r in _backlog if p != db_path]
        else:
            _backlog.append((db_path, row))
            del _backlog[:-BACKLOG_MAX]


def _record_quietly(db_path: Path, row: dict[str, Any]) -> None:
    try:
        record(db_path, row)
    except Exception:  # noqa: BLE001 - the meter must never break a call to the model
        pass


def attach(llm: Any, db_path: Path) -> Any:
    """Make `llm.complete` record its calls in the database at `db_path`. Returns the same object."""
    if getattr(llm, "_usage_db", None) == db_path:
        return llm
    inner = getattr(llm, "_usage_inner", None) or llm.complete

    def complete(system: str, user: str, *, tier: str = "fast", max_tokens: int = 4000):
        tags = _tags.get()
        row: dict[str, Any] = {
            "ts": now_iso(), "provider": getattr(llm, "provider", ""), "model": "", "tier": tier,
            "purpose": tags.get("purpose") or purpose_of(user), "job_id": tags.get("job_id"), "ok": 1, "error": "",
            "prompt_chars": len(system) + len(user), "output_chars": 0,
        }
        started = time.monotonic()
        try:
            res = inner(system, user, tier=tier, max_tokens=max_tokens)
        except Exception as exc:
            row.update(ok=0, error=str(exc)[:200], seconds=round(time.monotonic() - started, 2))
            try:
                row["model"] = llm.model_for(tier)
            except Exception:  # noqa: BLE001
                pass
            _record_quietly(db_path, row)
            raise
        try:
            inp, out, cost = normalize(res.usage)
            row.update(model=str(res.model or ""), provider=str(res.provider or row["provider"]),
                       output_chars=len(res.text or ""), seconds=round(time.monotonic() - started, 2),
                       input_tokens=inp, output_tokens=out, cost_usd=cost)
        except Exception:  # noqa: BLE001 - an answer of an unusual shape is still an answer
            row["seconds"] = round(time.monotonic() - started, 2)
        _record_quietly(db_path, row)
        return res

    llm._usage_inner = inner
    llm._usage_db = db_path
    llm.complete = complete
    return llm


def summary(conn: sqlite3.Connection, days: int = 30) -> dict[str, Any]:
    """Totals of the last `days` days, and per purpose."""
    since = f"-{max(1, int(days))} days"
    rows = conn.execute(
        """SELECT purpose, COUNT(*) AS calls, SUM(CASE WHEN ok = 1 THEN 0 ELSE 1 END) AS failed,
                  SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
                  SUM(CASE WHEN input_tokens IS NOT NULL THEN 1 ELSE 0 END) AS counted,
                  SUM(prompt_chars) AS prompt_chars, SUM(output_chars) AS output_chars,
                  SUM(seconds) AS seconds, SUM(cost_usd) AS cost_usd
           FROM llm_calls WHERE ts >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) GROUP BY purpose ORDER BY calls DESC""",
        (since,)).fetchall()
    by_purpose = []
    total = {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "seconds": 0.0}
    any_cost = False
    for r in rows:
        calls, counted = int(r["calls"]), int(r["counted"] or 0)
        item = {
            "purpose": r["purpose"], "calls": calls, "failed": int(r["failed"] or 0),
            "input_tokens": int(r["input_tokens"] or 0), "output_tokens": int(r["output_tokens"] or 0),
            "avg_input_tokens": round((r["input_tokens"] or 0) / counted) if counted else None,
            "avg_output_tokens": round((r["output_tokens"] or 0) / counted) if counted else None,
            "avg_prompt_chars": round((r["prompt_chars"] or 0) / calls) if calls else 0,
            "avg_seconds": round((r["seconds"] or 0) / calls, 1) if calls else 0.0,
            "cost_usd": round(r["cost_usd"], 4) if r["cost_usd"] is not None else None,
        }
        by_purpose.append(item)
        total["calls"] += calls
        total["failed"] += item["failed"]
        total["input_tokens"] += item["input_tokens"]
        total["output_tokens"] += item["output_tokens"]
        total["seconds"] += float(r["seconds"] or 0)
        if r["cost_usd"] is not None:
            any_cost = True
            total["cost_usd"] += float(r["cost_usd"])
    total["cost_usd"] = round(total["cost_usd"], 4) if any_cost else None
    total["seconds"] = round(total["seconds"], 1)
    return {"days": int(days), **total, "by_purpose": by_purpose}
