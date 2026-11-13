"""Measurement: do the rankings put the postings you want first, and what do the rules keep away from you?

The reference is your own verdict on a posting: an explicit label (fits / maybe / does not fit) or, where
there is none, what you did with it (shortlisted, applied ... = fits; skipped = does not fit).

Three questions are answered with it:

1. Rankings: when postings are ordered by the quick score, by the semantic score, by both fused or by the
   AI score, how many of the first ones do you want? (precision, NDCG, AUC)
2. The gate: the AI model only sees postings that pass the keyword rules. How many postings you would want
   are among those that never reach it? (labels on a random sample of each group)
3. The judge: how often does the AI verdict agree with yours? (Cohen's kappa)

Everything is plain arithmetic on a few hundred rows; no model is called.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from typing import Any, Optional, Sequence

from jobradar import db
from jobradar.config import AppConfig
from jobradar.i18n import t
from jobradar.processing.filters import track_only_reasons
from jobradar.profile import Profile
from jobradar.scoring import usage
from jobradar.textutil import now_iso

GOOD_STATUSES = ("shortlisted", "tailored", "approved", "applied", "interview", "offer")
MIN_LABELS = 30      # with fewer verdicts the numbers move too much to compare anything
MIN_PER_CLASS = 5    # and both kinds are needed: postings you want and postings you do not
MIN_SAMPLE = 5       # verdicts in a group before a share is reported for it
LLM_YES = 3.5        # an AI score from here on means "maybe" or "apply"
QUEUE_SEED = "jobradar-labels-1"
GROUPS = ("evaluated", "queue", "low_score", "track_filtered")
INSIDE = ("evaluated", "queue")          # the AI model has seen them or will
OUTSIDE = ("low_score", "track_filtered")  # the keyword rules keep them away from it
RANKERS = {"prescore": "Ön puan (anahtar kelimeler)", "semantic": "Anlamsal puan",
           "fused": "İkisi birlikte (yeni sıralama)", "llm": "AI puanı"}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def precision_at(labels: Sequence[int], k: int) -> Optional[float]:
    """Share of wanted postings (label 1 or 2) among the first k; `labels` is in ranking order."""
    top = list(labels[:k])
    return round(sum(1 for x in top if x >= 1) / len(top), 4) if top else None


def ndcg_at(labels: Sequence[int], k: int) -> Optional[float]:
    """Normalised discounted cumulative gain with the label as gain: 1.0 = the best possible order."""
    def dcg(seq: Sequence[int]) -> float:
        return sum(rel / math.log2(i + 2) for i, rel in enumerate(seq[:k]))

    ideal = dcg(sorted(labels, reverse=True))
    return round(dcg(labels) / ideal, 4) if ideal > 0 else None


def auc(pairs: Sequence[tuple[float, int]]) -> Optional[float]:
    """Chance that a wanted posting has a higher score than an unwanted one (ties count half). 0.5 = random."""
    pos = sum(1 for _, label in pairs if label >= 1)
    neg = len(pairs) - pos
    if not pos or not neg:
        return None
    ordered = sorted(pairs, key=lambda x: x[0])
    rank_sum = 0.0
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        average_rank = (i + j) / 2 + 1
        rank_sum += average_rank * sum(1 for x in ordered[i:j + 1] if x[1] >= 1)
        i = j + 1
    return round((rank_sum - pos * (pos + 1) / 2) / (pos * neg), 4)


def cohen_kappa(pairs: Sequence[tuple[bool, bool]]) -> Optional[float]:
    """Agreement of two yes/no judgements beyond what chance alone would give (1 = always, 0 = chance)."""
    n = len(pairs)
    if not n:
        return None
    observed = sum(1 for a, b in pairs if a == b) / n
    pa = sum(1 for a, _ in pairs if a) / n
    pb = sum(1 for _, b in pairs if b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected >= 1:
        return None
    return round((observed - expected) / (1 - expected), 4)


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def status_label(status: str, applied_at: Any) -> Optional[int]:
    """What you did with a posting, read as a verdict; None when it says nothing."""
    if status in GOOD_STATUSES:
        return 2
    if status in ("rejected", "closed") and applied_at:
        return 2  # you applied; how it ended says nothing about whether you wanted it
    if status == "skipped":
        return 0
    return None


def group_of(row: dict[str, Any], prescore_min: float, track_reasons: Sequence[str]) -> str:
    """Where a posting stands at the gate in front of the AI model."""
    if row["llm_score"] is not None:
        return "evaluated"
    status = row["status"]
    passes = (row["prescore"] or 0) >= prescore_min or bool(row["promoted"])
    if status in ("new", "shortlisted") and passes:
        return "queue"
    if status == "new":
        return "low_score"
    if status == "filtered" and row["filtered_reason"] in track_reasons:
        return "track_filtered"
    return "other"


def _rows(conn: sqlite3.Connection, cfg: AppConfig, profile: Optional[Profile]) -> list[dict[str, Any]]:
    """Every posting with what the measurements need (no texts)."""
    model = qhash = None
    if cfg.matching.enabled:
        from jobradar.scoring import match  # late: only needed when semantic matching is on

        model, qhash = match.current_keys(cfg, profile)
    reasons = track_only_reasons()
    out = []
    for r in conn.execute(
            """SELECT j.id, j.status, j.applied_at, j.prescore, j.llm_score, j.filtered_reason,
                      l.label AS explicit, m.semantic, m.model AS match_model, m.query_hash AS match_query,
                      COALESCE(m.promoted, 0) AS promoted
               FROM jobs j LEFT JOIN labels l ON l.job_id = j.id LEFT JOIN job_match m ON m.job_id = j.id"""):
        row = dict(r)
        current = model is not None and row["match_model"] == model and row["match_query"] == qhash
        row["semantic"] = row["semantic"] if current else None
        explicit = row["explicit"]
        # an explicit verdict wins; "cannot tell" (-1) leaves it to what you did with the posting
        row["is_explicit"] = explicit is not None and explicit >= 0
        row["label"] = explicit if row["is_explicit"] else status_label(row["status"], row["applied_at"])
        row["group"] = group_of(row, cfg.scoring.prescore_min, reasons)
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _ranker(rows: Sequence[dict[str, Any]], key: str, budget: int) -> Optional[dict[str, Any]]:
    scored = [r for r in rows if r.get(key) is not None]
    if not scored:
        return None
    ordered = sorted(scored, key=lambda r: (-float(r[key]), r["id"]))
    labels = [int(r["label"]) for r in ordered]
    return {"id": key, "name": t(RANKERS[key]), "n": len(scored), "wanted": sum(1 for x in labels if x >= 1),
            "precision_at_10": precision_at(labels, 10), "budget": budget,
            "budget_hit_rate": precision_at(labels, budget), "ndcg_at_10": ndcg_at(labels, 10),
            "auc": auc([(float(r[key]), int(r["label"])) for r in scored])}


def _rankings(labelled: Sequence[dict[str, Any]], budget: int) -> dict[str, Any]:
    """The rankings on the same postings: those with a semantic score when there are enough, else all."""
    with_semantic = [r for r in labelled if r["semantic"] is not None]
    comparable = len(with_semantic) >= MIN_LABELS
    rows = [dict(r) for r in (with_semantic if comparable else labelled)]
    keys = ["prescore"]
    if comparable:
        from jobradar.scoring.match import fuse

        fused = dict(fuse([(r["id"], float(r["prescore"] or 0), r["semantic"]) for r in rows]))
        for r in rows:
            r["fused"] = fused[r["id"]]
        keys += ["semantic", "fused"]
    for r in rows:
        r["llm"] = r["llm_score"]
    keys.append("llm")
    return {"n": len(rows), "semantic": comparable,
            "rows": [x for x in (_ranker(rows, key, budget) for key in keys) if x]}


def _gate(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Per group: how many postings, how many you judged yourself, and how many of those you want."""
    groups = []
    estimate = {"inside": 0.0, "outside": 0.0}
    known = {"inside": True, "outside": True}
    for name in GROUPS:
        members = [r for r in rows if r["group"] == name]
        judged = [r for r in members if r["is_explicit"]]
        wanted = sum(1 for r in judged if r["label"] >= 1)
        rate = round(wanted / len(judged), 4) if len(judged) >= MIN_SAMPLE else None
        side = "inside" if name in INSIDE else "outside"
        if rate is None:
            known[side] = known[side] and not members
        else:
            estimate[side] += rate * len(members)
        groups.append({"id": name, "postings": len(members), "judged": len(judged), "wanted": wanted,
                       "rate": rate, "estimated_wanted": round(rate * len(members), 1) if rate is not None else None})
    complete = known["inside"] and known["outside"]
    total = estimate["inside"] + estimate["outside"]
    return {"groups": groups,
            "estimated_missed": round(estimate["outside"], 1) if known["outside"] else None,
            "estimated_recall": round(estimate["inside"] / total, 4) if complete and total > 0 else None}


def _judge(labelled: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The AI verdict next to yours, on the postings that have both."""
    both = [r for r in labelled if r["llm_score"] is not None]
    pairs = [(r["label"] >= 1, float(r["llm_score"]) >= LLM_YES) for r in both]
    n = len(pairs)
    return {
        "n": n,
        "hit_rate": round(sum(1 for you, _ in pairs if you) / n, 4) if n else None,
        "agreement": round(sum(1 for you, ai in pairs if you == ai) / n, 4) if n else None,
        "kappa": cohen_kappa(pairs) if n >= 10 else None,
        "both_yes": sum(1 for you, ai in pairs if you and ai),
        "both_no": sum(1 for you, ai in pairs if not you and not ai),
        "only_ai_yes": sum(1 for you, ai in pairs if ai and not you),
        "only_you_yes": sum(1 for you, ai in pairs if you and not ai),
    }


def report(conn: sqlite3.Connection, cfg: AppConfig, profile: Optional[Profile] = None, *, days: int = 30,
           explicit_only: bool = False) -> dict[str, Any]:
    rows = _rows(conn, cfg, profile)
    labelled = [r for r in rows if r["label"] is not None and (r["is_explicit"] or not explicit_only)]
    wanted = sum(1 for r in labelled if r["label"] >= 1)
    unwanted = len(labelled) - wanted
    labels = {
        "total": len(labelled), "explicit": sum(1 for r in labelled if r["is_explicit"]),
        "from_status": sum(1 for r in labelled if not r["is_explicit"]),
        "good": sum(1 for r in labelled if r["label"] == 2), "maybe": sum(1 for r in labelled if r["label"] == 1),
        "bad": unwanted, "needed": MIN_LABELS,
        "enough": len(labelled) >= MIN_LABELS and wanted >= MIN_PER_CLASS and unwanted >= MIN_PER_CLASS,
    }
    semantic_rows = sum(1 for r in rows if r["semantic"] is not None)
    return {
        "generated_at": now_iso(), "explicit_only": explicit_only, "labels": labels,
        "rankings": _rankings(labelled, max(1, cfg.scoring.llm_max_per_run)),
        "gate": _gate(rows), "judge": _judge(labelled), "usage": usage.summary(conn, days),
        "matching": {"enabled": cfg.matching.enabled, "scored": semantic_rows},
    }


# ---------------------------------------------------------------------------
# What to judge next
# ---------------------------------------------------------------------------


def label_queue(conn: sqlite3.Connection, cfg: AppConfig, limit: int = 10) -> tuple[list[str], dict[str, int]]:
    """Ids of unjudged postings, taken in turn from the four groups at the gate, in a fixed random order.

    Random within a group, so the shares measured on them hold for the whole group. Returns the ids and how
    many unjudged postings each group still has."""
    rows = [r for r in _rows(conn, cfg, None) if r["explicit"] is None and r["group"] in GROUPS
            and r["status"] in ("new", "filtered")]
    by_group: dict[str, list[str]] = {name: [] for name in GROUPS}
    for r in rows:
        by_group[r["group"]].append(r["id"])
    for ids in by_group.values():
        ids.sort(key=lambda job_id: hashlib.sha1(f"{QUEUE_SEED}:{job_id}".encode("utf-8")).hexdigest())
    remaining = {name: len(ids) for name, ids in by_group.items()}
    picked: list[str] = []
    position = 0
    while len(picked) < limit and any(position < len(ids) for ids in by_group.values()):
        for name in GROUPS:
            if position < len(by_group[name]) and len(picked) < limit:
                picked.append(by_group[name][position])
        position += 1
    return picked, remaining


def label_name(value: Optional[int]) -> Optional[str]:
    return {2: "good", 1: "maybe", 0: "bad", -1: "skip"}.get(value) if value is not None else None


def set_label(conn: sqlite3.Connection, job_id: str, name: str, note: str = "") -> Optional[str]:
    """Store your verdict ("good", "maybe", "bad"; "skip" = cannot tell; "" = take it back). Returns the name."""
    name = (name or "").strip().lower()
    if not name:
        db.clear_label(conn, job_id)
        conn.commit()
        return None
    values = {**db.LABELS, "skip": -1}
    if name not in values:
        raise ValueError(t("geçersiz etiket: {name}", name=name))
    db.set_label(conn, job_id, values[name], note)
    conn.commit()
    return name
