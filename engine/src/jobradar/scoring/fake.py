"""Offline stand-in for an LLM (demo mode and tests).

It reads the same prompts a real model gets and answers with simple keyword
overlap, so the whole pipeline can be tried without an API key.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from jobradar.processing.normalize import clean_title
from jobradar.scoring.llm import BaseLLM, LLMResult

_FACT = re.compile(r"^\[([A-Za-z0-9_.-]+)\] (.+?)(?:  \(skills: (.+)\))?$")
_STOP = {
    "und", "der", "die", "das", "mit", "für", "von", "the", "and", "with", "for", "you", "your", "our", "wir",
    "sie", "ihre", "eine", "einer", "einen", "this", "that", "from", "into", "auf", "bei", "aus", "als", "sowie",
    "work", "team", "will", "have", "haben", "sind", "werden", "über", "mehr", "auch", "oder", "nach",
}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-ZäöüÄÖÜß0-9+#]{3,}", text.lower()) if w not in _STOP}


def _section(prompt: str, start: str, end: str) -> str:
    i = prompt.find(start)
    if i == -1:
        return ""
    i += len(start)
    j = prompt.find(end, i)
    return prompt[i:] if j == -1 else prompt[i:j]


def _facts(prompt: str) -> list[tuple[str, str, str, str]]:
    """(fact_id, text, skills, entry_id)"""
    bank = _section(prompt, "## Fact bank\n", "\n## ")
    out = []
    entry = ""
    for line in bank.splitlines():
        if line.startswith("### "):
            m = re.match(r"### ([A-Za-z0-9_.-]+) ·", line)
            entry = m.group(1) if m else ""
            continue
        m = _FACT.match(line.strip())
        if m:
            out.append((m.group(1), m.group(2), m.group(3) or "", entry))
    return out


def _job_text(prompt: str) -> str:
    return _section(prompt, "<<<JOB\n", "\nJOB>>>")


def _field(prompt: str, name: str) -> str:
    m = re.search(rf"^{name}: (.*)$", prompt, re.M)
    return m.group(1).strip() if m else ""


def _requirements(job_text: str) -> list[str]:
    reqs = []
    for line in job_text.splitlines():
        s = line.strip()
        if s.startswith(("• ", "- ", "* ")) and 12 <= len(s) <= 220:
            reqs.append(s[2:].strip())
    return reqs[:8]


def _best_fact(req: str, facts: list[tuple[str, str, str, str]]) -> tuple[str | None, int]:
    rt = _tokens(req)
    best: tuple[str | None, int] = (None, 0)
    for fid, text, skills, _ in facts:
        overlap = len(rt & _tokens(text + " " + skills))
        if overlap > best[1]:
            best = (fid, overlap)
    return best


def fake_evaluate(prompt: str) -> dict:
    facts = _facts(prompt)
    job = _job_text(prompt)
    tracks = re.search(r"track must be one of: ([^)]+)\)", prompt)
    track_ids = [t.strip() for t in tracks.group(1).split(",")] if tracks else []
    reqs = []
    for r in _requirements(job):
        fid, ov = _best_fact(r, facts)
        match = "strong" if ov >= 2 else "partial" if ov == 1 else "gap"
        reqs.append({"requirement": r[:120], "importance": "must", "match": match,
                     "evidence": [fid] if fid and match != "gap" else [],
                     "note": "Anahtar kelime örtüşmesine göre (demo modu)"})
    if not reqs:
        reqs = [{"requirement": "Genel profil uyumu", "importance": "must", "match": "partial",
                 "evidence": [facts[0][0]] if facts else [], "note": "İlan metni kısa (demo modu)"}]
    cov = sum(1 if r["match"] == "strong" else 0.5 if r["match"] == "partial" else 0 for r in reqs) / len(reqs)
    score = round(min(5.0, 1.6 + 3.4 * cov), 1)
    title = clean_title(_field(prompt, "Title"))
    track = track_ids[0] if track_ids else None
    lowered = (title + " " + job).lower()
    for tid in track_ids:
        if tid.lower() in lowered:
            track = tid
            break
    strong = [r["requirement"] for r in reqs if r["match"] == "strong"][:3]
    gaps = [r["requirement"] for r in reqs if r["match"] == "gap"][:3]
    return {
        "track": track,
        "summary": f"Demo değerlendirmesi: '{title}' ilanındaki şartların yaklaşık %{cov * 100:.0f}'i profildeki "
                   "gerçeklerle eşleşiyor. Gerçek değerlendirme için bir LLM bağla.",
        "requirements": reqs,
        "dimensions": {"cv_match": score, "north_star": score, "comp": None, "culture": None, "red_flags": 4},
        "red_flags": [],
        "strengths": strong,
        "gaps": gaps,
        "global_score": score,
        "verdict": "apply" if score >= 4 else "maybe" if score >= 3.5 else "skip",
        "language": "de" if re.search(r"\b(und|wir|ihre|sie)\b", job.lower()) else "en",
        "legitimacy": "medium",
        "legitimacy_notes": "Demo modu: ilanın gerçekliği kontrol edilmedi.",
        "tailoring_hints": [f"{r['evidence'][0]} gerçeğini öne çıkar" for r in reqs if r["evidence"]][:3],
        "interview_topics": strong[:2] or ["Projelerini somut örneklerle anlat"],
    }


def fake_tailor(prompt: str) -> dict:
    lang = _field(prompt, "LANGUAGE") or "en"
    facts = _facts(prompt)
    job = _job_text(prompt)
    jt = _tokens(job + " " + _field(prompt, "Title"))
    by_entry: dict[str, list[tuple[int, str, str]]] = {}
    for fid, text, skills, entry in facts:
        if not entry or fid.endswith("-DEG") or fid.startswith("LANG-"):
            continue
        score = len(jt & _tokens(text + " " + skills))
        by_entry.setdefault(entry, []).append((score, fid, text))
    experience = []
    for entry, items in sorted(by_entry.items(), key=lambda kv: -max(s for s, _, _ in kv[1])):
        items.sort(key=lambda x: -x[0])
        keep = [i for i in items if i[0] > 0][:4] or items[:1]
        experience.append({"entry_id": entry, "bullets": [{"text": t, "facts": [f]} for _, f, t in keep]})
    skills_line = _section(prompt, "## Skills (pick only from here, exact spelling)\n", "\n## ").strip()
    skills = [s.strip() for s in skills_line.split(",") if s.strip()]
    skills.sort(key=lambda s: 0 if s.lower() in job.lower() else 1)
    top = sorted(((len(jt & _tokens(t + " " + sk)), fid, t) for fid, t, sk, _ in facts), key=lambda x: -x[0])[:3]
    title = clean_title(_field(prompt, "Title"))
    company = _field(prompt, "Company")
    if lang == "de":
        subject = f"Bewerbung als {title}"
        salutation = "Sehr geehrte Damen und Herren,"
        opening = f"mit großem Interesse habe ich Ihre Stellenausschreibung als {title} bei {company} gelesen."
        closing = "Mit freundlichen Grüßen"
        q = [("Warum möchten Sie bei uns arbeiten?", f"Die Aufgaben als {title} passen zu meinen bisherigen Projekten."),
             ("Wann können Sie anfangen?", "[Eintrittsdatum]"), ("Gehaltsvorstellung?", "[Gehaltsvorstellung]")]
    else:
        subject = f"Application for {title}"
        salutation = "Dear Hiring Team,"
        opening = f"I am writing to apply for the {title} position at {company}."
        closing = "Kind regards"
        q = [("Why do you want to join us?", f"The {title} role matches the projects I have worked on."),
             ("When can you start?", "[start date]"), ("Salary expectation?", "[salary expectation]")]
    paragraphs = [{"text": opening, "facts": []}]
    for _, fid, text in top:
        paragraphs.append({"text": text, "facts": [fid]})
    return {
        "headline": title,
        "summary": {"text": top[0][2] if top else "", "facts": [top[0][1]] if top else []},
        "experience": experience,
        "skills": skills[:12],
        "cover_letter": {"subject": subject, "salutation": salutation, "paragraphs": paragraphs, "closing": closing},
        "answers": [{"question": qq, "answer": aa, "facts": []} for qq, aa in q],
    }


def fake_review(prompt: str) -> dict:
    job = _job_text(prompt)
    draft = _section(prompt, "## Draft to review (JSON)\n", "\n## ")
    facts = _facts(prompt)
    jt = _tokens(job)
    supported = sorted({w for _, text, skills, _ in facts for w in _tokens(text + " " + skills) if w in jt})
    missing = [w for w in supported if w not in draft.lower()][:3]
    issues = [{"where": "letter.paragraph.1", "problem": "Giriş paragrafı genel (demo modu).",
               "suggestion": "İlandaki ilk şarta doğrudan bağlanan bir cümleyle başla."}]
    return {"verdict": "revise" if missing else "ok",
            "summary": "Demo incelemesi: taslak profildeki gerçeklere dayanıyor.",
            "issues": issues if missing else [], "supported_missing_keywords": missing,
            "generic_phrases": ["mit großem Interesse"] if "mit großem Interesse" in draft else []}


class FakeLLM(BaseLLM):
    provider = "demo"

    def __init__(self, responder: Callable[[str, str], str] | None = None):
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    def model_for(self, tier: str) -> str:
        return "demo-heuristic"

    def complete(self, system: str, user: str, *, tier: str = "fast", max_tokens: int = 4000) -> LLMResult:
        self.calls.append((system, user))
        if self.responder:
            text = self.responder(system, user)
        elif user.startswith("TASK: REVIEW"):
            text = json.dumps(fake_review(user), ensure_ascii=False)
        elif "TASK: TAILOR" in user:
            text = json.dumps(fake_tailor(user), ensure_ascii=False)
        else:
            text = json.dumps(fake_evaluate(user), ensure_ascii=False)
        return LLMResult(text=text, provider=self.provider, model="demo-heuristic")
