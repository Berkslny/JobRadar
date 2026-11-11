"""Before/after view of a tailored document: every CV bullet, letter paragraph and
answer next to the original profile facts it is based on, plus what was left out."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jobradar.profile import Profile
from jobradar.tailor.validate import TailoredDocs


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip().rstrip(".").lower()


def _sources(ids: list[str], index: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for fid in ids:
        hit = index.get(fid)
        out.append({"id": fid, "text": hit[0].text if hit else "(profilde yok)"})
    return out


def _item(text: str, ids: list[str], index: dict[str, Any]) -> dict[str, Any]:
    sources = _sources(ids, index)
    original = " ".join(s["text"] for s in sources)
    return {"text": text, "sources": sources, "changed": _norm(text) != _norm(original)}


def document_diff(folder: Path, profile: Profile) -> dict[str, Any]:
    path = folder / "tailored.json"
    if not path.is_file():
        raise FileNotFoundError("tailored.json yok")
    docs = TailoredDocs.model_validate(json.loads(path.read_text(encoding="utf-8")))
    index = profile.fact_index()
    entries = {e.id: e for e in profile.entries()}
    used_entries: set[str] = set()
    experience = []
    for block in docs.experience:
        entry = entries.get(block.entry_id)
        used_entries.add(block.entry_id)
        cited = {f for b in block.bullets for f in b.facts}
        experience.append({
            "entry_id": block.entry_id,
            "title": entry.title if entry else block.entry_id,
            "organization": entry.organization if entry else "",
            "bullets": [_item(b.text, b.facts, index) for b in block.bullets],
            "left_out": [{"id": f.id, "text": f.text} for f in (entry.facts if entry else []) if f.id not in cited],
        })
    omitted = [{"entry_id": e.id, "title": e.title, "organization": e.organization}
               for e in profile.entries() if e.id not in used_entries and e.kind not in ("education",)]
    chosen = list(docs.skills)
    chosen_lower = {s.lower() for s in chosen}
    letter = docs.cover_letter
    return {
        "headline": {"text": docs.headline, "original": profile.headline},
        "summary": _item(docs.summary.text, docs.summary.facts, index),
        "experience": experience,
        "omitted_entries": omitted,
        "skills": {"chosen": chosen, "not_chosen": [s for s in profile.all_skills() if s.lower() not in chosen_lower]},
        "letter": {
            "subject": letter.subject,
            "paragraphs": [_item(p.text, p.facts, index) for p in letter.paragraphs],
        },
        "answers": [dict(_item(a.answer, a.facts, index), question=a.question) for a in docs.answers],
    }
