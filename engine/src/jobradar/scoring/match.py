"""Semantic matching: postings are compared with your tracks and your profile by meaning, not only by keywords.

What it adds to the keyword rules:

1. A semantic score per posting: how close it is to one of your tracks (what you look for) and to your
   profile (what you have done).
2. The order of the AI evaluations: keyword rank and semantic rank are fused (reciprocal rank fusion), so the
   evaluation budget goes first to the postings both signals agree on.
3. Promotion: a posting the keyword rules would never hand to the AI model (no keyword ties it to a track, or
   its quick score is low) is let through when its semantic score is as high as that of the postings that do
   match keywords. Rules you set yourself (title words, seniority, employment type ...) are never overridden.

Vectors are kept in SQLite (table `embeddings`), scores in `job_match`. The arithmetic is plain Python, so the
engine needs no numpy of its own.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional, Sequence

from jobradar import db
from jobradar.config import AppConfig
from jobradar.i18n import t
from jobradar.processing import guard
from jobradar.processing.filters import track_only_reasons
from jobradar.processing.normalize import clean_title
from jobradar.profile import Profile
from jobradar.scoring.embed import Embedder, dot, embed_all, get_embedder, model_key, pack, unpack
from jobradar.textutil import now_iso

Log = Callable[[str], None]

RRF_K = 60
MIN_REFERENCE = 20      # keyword matches with a semantic score needed before a bar for promotion is measured
HYSTERESIS = 0.9        # a promoted posting is taken back only when it falls clearly below the bar
JOBS_PER_BATCH = 12
META_LAST = "matching_last_run"
META_ERROR = "matching_last_error"
# postings you have decided on: their scores are needed for the measurements (bench)
DECIDED = ("shortlisted", "tailored", "approved", "applied", "interview", "offer", "rejected", "skipped")


@dataclass
class MatchReport:
    model: str = ""
    embedded: int = 0             # postings embedded in this run
    waiting: int = 0              # postings left for a later run (time budget)
    scored: int = 0               # postings scored or scored again
    promoted: int = 0
    demoted: int = 0
    threshold: Optional[float] = None
    reference: int = 0            # keyword matches the threshold was measured on
    seconds: float = 0.0
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Texts
# ---------------------------------------------------------------------------

_BULLET = re.compile(r"^\s*(?:[•\-\*–·▪■●○◦➤►✓✔]|\d{1,2}[.)])\s+")
# headings of the parts that say what the job is and whom it needs
_ROLE = re.compile(
    r"aufgaben|tätigkeit|taetigkeit|verantwort|profil|qualifikation|anforderung|voraussetzung|mitbring|kompetenz"
    r"|kenntnisse|erwartet|ihre rolle|deine rolle|das machst du|dein job|ihr job|stellenbeschreibung"
    r"|responsibilit|requirement|qualification|what you.ll do|what you will do|your role|the role|your tasks"
    r"|your profile|your mission|skills|must.have|nice.to.have|who you are|about you|what you bring"
    r"|what we.re looking for|what we are looking for|job description|key duties"
    r"|görev|nitelik|sorumluluk|aranan|iş tanımı"
    r"|missions|profil recherché|responsabilidades|requisitos|functie|wat ga je doen|requisiti|mansioni",
    re.IGNORECASE)
# headings of the parts that say little about the fit: the employer, the benefits, how to apply
_OTHER = re.compile(
    r"wir bieten|was wir bieten|das bieten wir|unser angebot|benefits|vorteile|what we offer|we offer|perks"
    r"|why join|why us|warum wir|über uns|ueber uns|about us|about the company|who we are|wer wir sind"
    r"|unternehmen|kontakt|contact|ansprechpartner|bewerbung|how to apply|apply now|jetzt bewerben"
    r"|equal opportunit|datenschutz|privacy|diversity|sunduklarımız|hakkımızda|neler sunuyoruz|başvuru"
    r"|ce que nous offrons|à propos|ofrecemos|sobre nosotros|wij bieden|over ons|cosa offriamo",
    re.IGNORECASE)


def _heading(line: str) -> Optional[int]:
    """0 for a heading of a role part, 2 for a heading of another part, None when the line is no such heading."""
    words = len(line.split())
    if len(line) > 70 or words > 8 or _BULLET.match(line) or line.endswith("."):
        return None
    if words <= 5 and _OTHER.search(line):
        return 2
    if _ROLE.search(line):
        return 0
    return None


def _pieces(text: str, size: int) -> list[str]:
    """Cut a long line at sentence ends or spaces into pieces of at most `size` characters."""
    out = []
    rest = text.strip()
    while len(rest) > size:
        cut = max(rest.rfind(". ", 0, size), rest.rfind("; ", 0, size))
        if cut < size * 0.4:
            cut = rest.rfind(" ", 0, size)
        if cut < size * 0.4:
            cut = size - 1
        out.append(rest[:cut + 1].strip())
        rest = rest[cut + 1:].strip()
    if rest:
        out.append(rest)
    return out


def job_chunks(title: str, description: str, *, max_chunks: int = 4, chunk_chars: int = 700) -> list[str]:
    """The pieces of a posting that are embedded: its title, then tasks and requirements.

    The parts about the employer and the benefits are used only when the posting has nothing else."""
    head = (clean_title(title or "") or (title or "")).strip()
    chunks = [head[:chunk_chars]] if head else []
    section = 1  # 0 = tasks and requirements, 1 = unknown, 2 = employer, benefits, how to apply
    lines: list[tuple[int, str]] = []
    for raw in (description or "").splitlines():
        raw = raw.strip()
        if not raw or guard.MARKER in raw:
            continue
        kind = _heading(raw)
        if kind is not None:
            section = kind
            if kind == 2:
                continue
        text = _BULLET.sub("", raw).strip()
        for piece in _pieces(text, chunk_chars):
            lines.append((section, piece))
    for wanted in (0, 1, 2):
        if len(chunks) >= max_chunks or (wanted == 2 and len(chunks) > 1):
            break
        buffer = ""
        for sec, text in lines:
            if sec != wanted:
                continue
            if buffer and len(buffer) + 1 + len(text) > chunk_chars:
                chunks.append(buffer)
                buffer = ""
                if len(chunks) >= max_chunks:
                    break
            buffer = f"{buffer}\n{text}" if buffer else text
        if buffer and len(chunks) < max_chunks:
            chunks.append(buffer)
    return chunks


def _cut(text: str, size: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= size else text[:size].rsplit(" ", 1)[0]


def track_queries(cfg: AppConfig, chunk_chars: int) -> list[tuple[str, str]]:
    """Per track: what the role is (name, north star, topics) and what such jobs are called (titles)."""
    out: list[tuple[str, str]] = []
    for tr in cfg.enabled_tracks():
        role = ". ".join(x.strip().rstrip(".") for x in (tr.name, tr.north_star) if x and x.strip())
        if tr.domain_keywords:
            role += ". " + ", ".join(tr.domain_keywords[:15])
        if role.strip():
            out.append((f"track:{tr.id}:role", _cut(role, chunk_chars)))
        titles = list(dict.fromkeys([*tr.search_terms, *tr.title_keywords]))[:25]
        if titles:
            out.append((f"track:{tr.id}:titles", _cut(", ".join(titles), chunk_chars)))
    return out


def profile_queries(profile: Optional[Profile], chunk_chars: int) -> list[tuple[str, str]]:
    """What you have done: a summary, your skills, and one text per job or project."""
    if profile is None or not profile.name.strip():
        return []
    out: list[tuple[str, str]] = []
    degrees = [f"{e.title}, {e.organization}" for e in profile.education if e.title]
    summary = ". ".join(x.strip().rstrip(".") for x in [profile.headline, *degrees,
                                                       *(f.text for f in profile.summary_facts)]
                        if x and x.strip() and "TODO" not in x)
    if summary:
        out.append(("profile:summary", _cut(summary, chunk_chars)))
    skills = profile.all_skills()
    if skills:
        out.append(("profile:skills", _cut(", ".join(skills[:60]), chunk_chars)))
    for entry in [*profile.experience, *profile.projects][:10]:
        facts = " ".join(f.text for f in entry.facts if "TODO" not in f.text)
        text = ". ".join(x for x in (", ".join(y for y in (entry.title, entry.organization) if y), facts) if x)
        if text.strip():
            out.append((f"profile:{entry.id}", _cut(text, chunk_chars)))
    return out


def query_texts(cfg: AppConfig, profile: Optional[Profile]) -> list[tuple[str, str]]:
    size = cfg.matching.chunk_chars
    return track_queries(cfg, size) + profile_queries(profile, size)


def _hash(*parts: str) -> str:
    return hashlib.sha1("\x1e".join(parts).encode("utf-8")).hexdigest()[:16]


def query_hash(cfg: AppConfig, texts: Sequence[tuple[str, str]]) -> str:
    """Changes whenever a score would: another model, other tracks, another profile, another weight."""
    body = "|".join(f"{key}={_hash(text)}" for key, text in sorted(texts))
    return _hash(model_key(cfg), f"{cfg.matching.profile_weight:.3f}", body)


def current_keys(cfg: AppConfig, profile: Optional[Profile]) -> tuple[str, str]:
    """(model key, query hash) that scores in `job_match` must carry to be current."""
    return model_key(cfg), query_hash(cfg, query_texts(cfg, profile))


def job_signature(cfg: AppConfig, title: str, description: str) -> str:
    return _hash(str(cfg.matching.max_chunks), str(cfg.matching.chunk_chars), title or "", description or "")


# ---------------------------------------------------------------------------
# Fusion of the keyword rank and the semantic rank
# ---------------------------------------------------------------------------


def fuse(items: Sequence[tuple[str, float, Optional[float]]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion. `items`: (id, keyword score, semantic score or None). Best first.

    score = 1 / (k + keyword rank) + 1 / (k + semantic rank). A posting without a semantic score counts with
    its keyword rank twice, so it is neither favoured nor punished. Semantic ranks are spread over the whole
    list when only a part of it has a semantic score."""
    by_keyword = sorted(items, key=lambda x: (-x[1], x[0]))
    kw_rank = {job_id: i + 1.0 for i, (job_id, _, _) in enumerate(by_keyword)}
    scored = sorted((x for x in items if x[2] is not None), key=lambda x: (-x[2], -x[1], x[0]))
    stretch = (len(items) - 1) / (len(scored) - 1) if len(scored) > 1 else 1.0
    sem_rank = {job_id: 1.0 + i * stretch for i, (job_id, _, _) in enumerate(scored)}
    fused = [(job_id, 1.0 / (k + kw_rank[job_id]) + 1.0 / (k + sem_rank.get(job_id, kw_rank[job_id])))
             for job_id, _, _ in items]
    return sorted(fused, key=lambda x: (-x[1], kw_rank[x[0]]))


def llm_queue(conn: sqlite3.Connection, cfg: AppConfig, *, limit: int, force: bool = False) -> Optional[list[str]]:
    """Ids of the postings to evaluate next, best first. None when there are no semantic scores to use."""
    model = model_key(cfg)
    sql = ("SELECT j.id, j.prescore, m.semantic, m.model AS match_model FROM jobs j "
           "LEFT JOIN job_match m ON m.job_id = j.id WHERE j.status IN ('new','shortlisted') "
           + ("" if force else "AND j.llm_score IS NULL ") + "AND (j.prescore >= ? OR m.promoted = 1)")
    rows = conn.execute(sql, (cfg.scoring.prescore_min,)).fetchall()
    items = [(r["id"], float(r["prescore"] or 0), r["semantic"] if r["match_model"] == model else None)
             for r in rows]
    if not any(sem is not None for _, _, sem in items):
        return None
    return [job_id for job_id, _ in fuse(items)][:max(0, limit)]


# ---------------------------------------------------------------------------
# Vectors of the tracks and the profile
# ---------------------------------------------------------------------------


def _store(conn: sqlite3.Connection, kind: str, ref: str, model: str, text_hash: str,
           vectors: Sequence[Sequence[float]]) -> None:
    dim = len(vectors[0]) if vectors else 0
    conn.execute(
        "INSERT OR REPLACE INTO embeddings (kind, ref, model, text_hash, dim, n, vectors, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, ref, model, text_hash, dim, len(vectors), pack(vectors), now_iso()))


def ensure_queries(conn: sqlite3.Connection, cfg: AppConfig, texts: Sequence[tuple[str, str]],
                   embedder: Embedder) -> dict[str, Sequence[float]]:
    """Vectors of the query texts by key; only new or changed texts are embedded."""
    model = model_key(cfg)
    stored = {r["ref"]: r["text_hash"] for r in conn.execute(
        "SELECT ref, text_hash FROM embeddings WHERE kind = 'query' AND model = ?", (model,))}
    missing = [(key, text) for key, text in texts if stored.get(key) != _hash(text)]
    if missing:
        vectors = embed_all(embedder, [text for _, text in missing], query=True)
        for (key, text), vec in zip(missing, vectors):
            _store(conn, "query", key, model, _hash(text), [vec])
    wanted = {key for key, _ in texts}
    for ref in stored:
        if ref not in wanted:
            conn.execute("DELETE FROM embeddings WHERE kind = 'query' AND ref = ? AND model = ?", (ref, model))
    conn.commit()
    out: dict[str, Sequence[float]] = {}
    for r in conn.execute("SELECT ref, dim, vectors FROM embeddings WHERE kind = 'query' AND model = ?", (model,)):
        vectors = unpack(r["vectors"], r["dim"])
        if vectors and r["ref"] in wanted:
            out[r["ref"]] = vectors[0]
    return out


def _split_queries(queries: dict[str, Sequence[float]]) -> tuple[dict[str, list[Sequence[float]]], list[Sequence[float]]]:
    tracks: dict[str, list[Sequence[float]]] = {}
    profile: list[Sequence[float]] = []
    for key, vec in queries.items():
        kind, _, rest = key.partition(":")
        if kind == "track":
            tracks.setdefault(rest.rpartition(":")[0], []).append(vec)
        elif kind == "profile":
            profile.append(vec)
    return tracks, profile


def score_vectors(chunks: Sequence[Sequence[float]], tracks: dict[str, list[Sequence[float]]],
                  profile: Sequence[Sequence[float]], profile_weight: float
                  ) -> tuple[float, float, Optional[float], Optional[str]]:
    """(semantic, track similarity, profile similarity, closest track) of one posting; similarities are 0..1."""
    best_track, track_sim = None, 0.0
    for track_id, vectors in tracks.items():
        sim = max((dot(q, c) for q in vectors for c in chunks), default=0.0)
        if best_track is None or sim > track_sim:
            best_track, track_sim = track_id, sim
    track_sim = max(0.0, min(1.0, track_sim))
    profile_sim: Optional[float] = None
    if profile:
        profile_sim = max(0.0, min(1.0, max((dot(q, c) for q in profile for c in chunks), default=0.0)))
    if not tracks:
        semantic = profile_sim or 0.0
    elif profile_sim is None:
        semantic = track_sim
    else:
        semantic = (1.0 - profile_weight) * track_sim + profile_weight * profile_sim
    return round(semantic, 4), round(track_sim, 4), (round(profile_sim, 4) if profile_sim is not None else None), best_track


# ---------------------------------------------------------------------------
# Vectors and scores of the postings
# ---------------------------------------------------------------------------


def _stale_jobs(conn: sqlite3.Connection, cfg: AppConfig, model: str) -> list[tuple[str, str]]:
    """(id, signature) of the postings that need a vector, the most useful first."""
    have = {r["ref"]: r["text_hash"] for r in conn.execute(
        "SELECT ref, text_hash FROM embeddings WHERE kind = 'job' AND model = ?", (model,))}
    minimum = cfg.scoring.prescore_min
    decided = ",".join("?" * len(DECIDED))
    selections: list[tuple[str, tuple[Any, ...]]] = [
        # waiting for an evaluation: their order is what the semantic score changes first
        ("status IN ('new','shortlisted') AND llm_score IS NULL AND prescore >= ? ORDER BY prescore DESC", (minimum,)),
        # postings you have judged: the measurements compare the rankings on them
        (f"id IN (SELECT job_id FROM labels) OR status IN ({decided})", DECIDED),
    ]
    if cfg.matching.promote:
        selections += [
            ("status = 'new' AND llm_score IS NULL AND prescore < ? ORDER BY prescore DESC", (minimum,)),
            ("status = 'filtered' AND filtered_reason IN (?, ?) ORDER BY first_seen DESC", track_only_reasons()),
        ]
    todo: list[tuple[str, str]] = []
    seen: set[str] = set()
    for where, params in selections:
        for r in conn.execute(f"SELECT id, title, description FROM jobs WHERE {where}", params):
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            signature = job_signature(cfg, r["title"], r["description"])
            if have.get(r["id"]) != signature:
                todo.append((r["id"], signature))
    return todo


def _embed_jobs(conn: sqlite3.Connection, cfg: AppConfig, embedder: Embedder, model: str,
                todo: Sequence[tuple[str, str]], *, deadline: float,
                progress: Optional[Callable[..., None]] = None) -> int:
    done = 0
    mc = cfg.matching
    for start in range(0, len(todo), JOBS_PER_BATCH):
        if progress:
            progress(done, len(todo))
        if done and time.monotonic() > deadline:
            break
        batch = todo[start:start + JOBS_PER_BATCH]
        marks = ",".join("?" * len(batch))
        rows = {r["id"]: r for r in conn.execute(
            f"SELECT id, title, description FROM jobs WHERE id IN ({marks})", [job_id for job_id, _ in batch])}
        texts: list[str] = []
        spans: list[tuple[str, str, int, int]] = []
        for job_id, signature in batch:
            row = rows.get(job_id)
            if row is None:
                continue
            chunks = job_chunks(row["title"], row["description"], max_chunks=mc.max_chunks,
                                chunk_chars=mc.chunk_chars)
            if not chunks:
                continue
            spans.append((job_id, signature, len(texts), len(texts) + len(chunks)))
            texts += chunks
        vectors = embed_all(embedder, texts)
        for job_id, signature, a, b in spans:
            _store(conn, "job", job_id, model, signature, vectors[a:b])
        conn.commit()
        done += len(batch)
    if progress:
        progress(done, len(todo))
    return done


def _score_jobs(conn: sqlite3.Connection, cfg: AppConfig, model: str, qhash: str,
                queries: dict[str, Sequence[float]]) -> set[str]:
    """Score every posting whose vector, or whose counterpart (tracks, profile, model), has changed."""
    tracks, profile = _split_queries(queries)
    stale = [r["ref"] for r in conn.execute(
        """SELECT e.ref FROM embeddings e LEFT JOIN job_match m ON m.job_id = e.ref
           WHERE e.kind = 'job' AND e.model = ?
             AND (m.job_id IS NULL OR m.model != ? OR m.query_hash != ? OR m.text_hash != e.text_hash)""",
        (model, model, qhash))]
    now = now_iso()
    changed: set[str] = set()
    for start in range(0, len(stale), 200):  # vectors are read in portions: all of them can be large
        part = stale[start:start + 200]
        rows = conn.execute(
            f"SELECT ref, text_hash, dim, vectors FROM embeddings WHERE kind = 'job' AND model = ? "
            f"AND ref IN ({','.join('?' * len(part))})", (model, *part)).fetchall()
        for r in rows:
            chunks = unpack(r["vectors"], r["dim"])
            if not chunks:
                continue
            semantic, track_sim, profile_sim, best = score_vectors(chunks, tracks, profile,
                                                                   cfg.matching.profile_weight)
            conn.execute(
                """INSERT INTO job_match (job_id, model, query_hash, text_hash, semantic, track_sim, profile_sim,
                                          best_track, promoted, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                   ON CONFLICT(job_id) DO UPDATE SET model = excluded.model, query_hash = excluded.query_hash,
                     text_hash = excluded.text_hash, semantic = excluded.semantic, track_sim = excluded.track_sim,
                     profile_sim = excluded.profile_sim, best_track = excluded.best_track,
                     updated_at = excluded.updated_at""",
                (r["ref"], model, qhash, r["text_hash"], semantic, track_sim, profile_sim, best, now))
            changed.add(r["ref"])
        conn.commit()
    return changed


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------


def percentile(values: Sequence[float], pct: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * max(0.0, min(100.0, pct)) / 100.0
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def promotion_bar(conn: sqlite3.Connection, cfg: AppConfig, model: str, qhash: str) -> tuple[Optional[float], int]:
    """The semantic score a posting needs to be promoted, and on how many keyword matches that was measured.

    The bar is a percentile of the semantic score of the postings the keyword rules already accept; with
    too few of them there is no bar yet and nothing is promoted."""
    mc = cfg.matching
    if mc.promote_min_similarity > 0:
        return mc.promote_min_similarity, 0
    sims = [float(r[0]) for r in conn.execute(
        """SELECT m.semantic FROM job_match m JOIN jobs j ON j.id = m.job_id
           WHERE m.model = ? AND m.query_hash = ? AND m.promoted = 0 AND j.status != 'filtered' AND j.prescore >= ?""",
        (model, qhash, cfg.scoring.prescore_min))]
    if len(sims) < MIN_REFERENCE:
        return None, len(sims)
    return round(percentile(sims, mc.promote_percentile), 4), len(sims)


def _promote(conn: sqlite3.Connection, cfg: AppConfig, proc: Any, model: str, qhash: str, bar: float) -> int:
    limit = cfg.matching.promote_max_per_run
    if limit <= 0:
        return 0
    rows = conn.execute(
        """SELECT j.*, m.semantic AS m_semantic, m.best_track AS m_best_track FROM jobs j
           JOIN job_match m ON m.job_id = j.id
           WHERE m.model = ? AND m.query_hash = ? AND m.promoted = 0 AND m.semantic >= ?
             AND ((j.status = 'filtered' AND j.filtered_reason IN (?, ?))
                  OR (j.status = 'new' AND j.llm_score IS NULL AND j.prescore < ?))
           ORDER BY m.semantic DESC, j.id LIMIT ?""",
        (model, qhash, bar, *track_only_reasons(), cfg.scoring.prescore_min, limit * 8 + 20)).fetchall()
    promoted = 0
    for r in rows:
        if promoted >= limit:
            break
        job = db.row_to_job(r)
        sim, track = float(job.pop("m_semantic")), job.pop("m_best_track")
        flags = dict(job.get("flags") or {})
        flags["semantic"] = {"promoted": True, "track": track, "sim": round(sim, 3)}
        job["flags"] = flags
        proc.refresh(job)
        if job.get("status") != "new":
            continue  # a rule of your own applies by now: it stays filtered out
        db.update_job(conn, job)
        conn.execute("UPDATE job_match SET promoted = 1 WHERE job_id = ?", (job["id"],))
        db.add_event(conn, job["id"], "semantic_promoted", f"{track or '-'} · {sim:.2f}")
        promoted += 1
    conn.commit()
    return promoted


def _unpromote(conn: sqlite3.Connection, proc: Any, job: dict[str, Any], why: str) -> None:
    """Take a promotion back. A posting nobody has touched is filtered again; any other keeps its place."""
    flags = dict(job.get("flags") or {})
    flags.pop("semantic", None)
    job["flags"] = flags
    if job.get("status") == "new" and job.get("llm_score") is None:
        proc.refresh(job)
        db.update_job(conn, job)
    else:
        db.update_fields(conn, job["id"], flags=flags)
    conn.execute("UPDATE job_match SET promoted = 0 WHERE job_id = ?", (job["id"],))
    db.add_event(conn, job["id"], "semantic_demoted", why)


def _demote(conn: sqlite3.Connection, proc: Any, changed: set[str], bar: float) -> int:
    """Postings promoted earlier whose score changed (new description, other tracks) and fell below the bar."""
    demoted = 0
    rows = conn.execute("SELECT j.*, m.semantic AS m_semantic FROM jobs j JOIN job_match m ON m.job_id = j.id "
                        "WHERE m.promoted = 1").fetchall()
    for r in rows:
        job = db.row_to_job(r)
        sim = float(job.pop("m_semantic"))
        if job["id"] not in changed or sim >= bar * HYSTERESIS:
            continue
        if job.get("status") != "new" or job.get("llm_score") is not None:
            continue  # evaluated or handled by you: it stays
        _unpromote(conn, proc, job, f"{sim:.2f} < {bar:.2f}")
        demoted += 1
    conn.commit()
    return demoted


def clear_promotions(conn: sqlite3.Connection, cfg: AppConfig, profile: Profile) -> int:
    """Matching or promotion was turned off: promoted postings go back to what the keyword rules say."""
    from jobradar.pipeline import Processor  # late: the pipeline imports this module

    proc = Processor(cfg, profile)
    rows = conn.execute("SELECT j.* FROM jobs j JOIN job_match m ON m.job_id = j.id WHERE m.promoted = 1").fetchall()
    for r in rows:
        _unpromote(conn, proc, db.row_to_job(r), "off")
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------


def run_matching(conn: sqlite3.Connection, cfg: AppConfig, profile: Profile, embedder: Embedder | None = None, *,
                 log: Log = print, progress: Optional[Callable[..., None]] = None,
                 max_seconds: float | None = None) -> MatchReport:
    """Embed what is new, score, promote. Raises EmbedError when the embedding model cannot be used."""
    from jobradar.pipeline import Processor  # late: the pipeline imports this module

    started = time.monotonic()
    model = model_key(cfg)
    report = MatchReport(model=model)
    texts = query_texts(cfg, profile)
    if not texts:
        report.note = t("Eşleştirilecek hedef alan ya da profil yok.")
        return report
    if progress:
        progress(0, 0, t("Eşleştirme modeli hazırlanıyor"))
    embedder = embedder or get_embedder(cfg)
    queries = ensure_queries(conn, cfg, texts, embedder)
    qhash = query_hash(cfg, texts)
    # the model works: vectors of a model used before are of no use any more
    conn.execute("DELETE FROM embeddings WHERE model != ?", (model,))
    conn.commit()
    budget = max_seconds if max_seconds is not None else cfg.matching.max_seconds_per_run
    todo = _stale_jobs(conn, cfg, model)
    report.embedded = _embed_jobs(conn, cfg, embedder, model, todo, deadline=started + budget, progress=progress)
    report.waiting = len(todo) - report.embedded
    changed = _score_jobs(conn, cfg, model, qhash, queries)
    report.scored = len(changed)
    if cfg.matching.promote:
        bar, reference = promotion_bar(conn, cfg, model, qhash)
        report.threshold, report.reference = bar, reference
        if bar is not None:
            proc = Processor(cfg, profile)
            report.demoted = _demote(conn, proc, changed, bar)
            report.promoted = _promote(conn, cfg, proc, model, qhash, bar)
    report.seconds = round(time.monotonic() - started, 1)
    db.set_meta(conn, META_LAST, json.dumps({"at": now_iso(), **report.as_dict()}, ensure_ascii=False))
    db.set_meta(conn, META_ERROR, "")
    log(f"→ eşleştirme: {report.embedded} ilan işlendi" + (f", {report.waiting} sonraya kaldı" if report.waiting else "")
        + (f", {report.promoted} öne çıkarıldı" if report.promoted else ""))
    return report


def status(conn: sqlite3.Connection, cfg: AppConfig) -> dict[str, Any]:
    """Numbers for the settings page: how many postings have a current score, how many were promoted."""
    model = model_key(cfg)
    scored = conn.execute("SELECT COUNT(*) FROM job_match WHERE model = ?", (model,)).fetchone()[0]
    promoted = conn.execute("SELECT COUNT(*) FROM job_match WHERE promoted = 1").fetchone()[0]
    try:
        last = json.loads(db.get_meta(conn, META_LAST, "") or "{}")
    except json.JSONDecodeError:
        last = {}
    return {"scored": int(scored), "promoted": int(promoted), "last_run": last if isinstance(last, dict) else {},
            "last_error": db.get_meta(conn, META_ERROR, "")}


def job_view(conn: sqlite3.Connection, cfg: AppConfig, job_id: str) -> Optional[dict[str, Any]]:
    """The semantic score of one posting for the detail page; None when it has none from the current model."""
    r = conn.execute("SELECT * FROM job_match WHERE job_id = ?", (job_id,)).fetchone()
    if r is None or r["model"] != model_key(cfg):
        return None
    track = cfg.track(r["best_track"])
    return {"semantic": r["semantic"], "track_sim": r["track_sim"], "profile_sim": r["profile_sim"],
            "track": r["best_track"], "track_name": track.name if track else None,
            "promoted": bool(r["promoted"]), "model": r["model"], "updated_at": r["updated_at"]}

