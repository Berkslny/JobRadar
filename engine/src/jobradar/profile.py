"""Candidate profile as a fact bank.

Every claim the system may ever write about the candidate lives here as a
fact with a stable ID (idea from JobCtrl: tailored bullets must point to the
fact behind them). Evaluations and CV/cover-letter drafts cite these IDs and
are validated against them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

from jobradar.i18n import t
CEFR_RANK = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "NATIVE": 7}

EU_CODES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}
NATO_CODES = {
    "AL", "BE", "BG", "CA", "HR", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IS", "IT", "LV", "LT", "LU", "ME", "NL", "MK", "NO", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "TR", "GB", "US",
}


def cefr_rank(level: str | None) -> int:
    if not level:
        return 0
    lv = level.strip().upper()
    if lv in {"MUTTERSPRACHE", "NATIVE", "MOTHER TONGUE", "ANADIL"}:
        lv = "NATIVE"
    return CEFR_RANK.get(lv, 0)


class Fact(BaseModel):
    id: str
    text: str
    skills: list[str] = Field(default_factory=list)


class Entry(BaseModel):
    """An experience, education or project entry with its facts."""

    id: str
    kind: Literal["work", "internship", "werkstudent", "thesis", "education", "project", "volunteer"] = "work"
    organization: str
    title: str
    location: str = ""
    start: str = ""
    end: str = ""
    facts: list[Fact] = Field(default_factory=list)


class Language(BaseModel):
    name: str
    level: str


class Preferences(BaseModel):
    dealbreakers: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    salary_expectation: str = ""
    notes: str = ""


class Profile(BaseModel):
    name: str
    headline: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    address: str = ""
    links: dict[str, str] = Field(default_factory=dict)
    summary_facts: list[Fact] = Field(default_factory=list)
    experience: list[Entry] = Field(default_factory=list)
    education: list[Entry] = Field(default_factory=list)
    projects: list[Entry] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    languages: list[Language] = Field(default_factory=list)
    german_level: str = "B1"
    citizenships: list[str] = Field(default_factory=list)
    work_permit: str = ""
    earliest_start: str = ""
    preferences: Preferences = Field(default_factory=Preferences)

    @model_validator(mode="after")
    def _unique_ids(self) -> "Profile":
        seen: set[str] = set()
        for entry in self.entries():
            if entry.id in seen:
                raise ValueError(t("profil: '{id}' kimliği iki kez kullanılmış", id=entry.id))
            seen.add(entry.id)
        for fid in self._iter_fact_ids():
            if fid in seen:
                raise ValueError(t("profil: '{id}' kimliği iki kez kullanılmış", id=fid))
            seen.add(fid)
        return self

    # -- accessors -------------------------------------------------------------
    def entries(self) -> list[Entry]:
        return [*self.experience, *self.education, *self.projects]

    def _iter_fact_ids(self):
        for f in self.summary_facts:
            yield f.id
        for e in self.entries():
            for f in e.facts:
                yield f.id

    def implicit_facts(self) -> list[tuple[Fact, Optional[Entry]]]:
        """Facts derived from structured fields so they can be cited too:
        one per degree (``<EDU-ID>-DEG``) and one per language (``LANG-n``)."""
        explicit = set(self._iter_fact_ids())
        out: list[tuple[Fact, Optional[Entry]]] = []
        for e in self.education:
            fid = f"{e.id}-DEG"
            if fid in explicit:
                continue
            period = " – ".join(p for p in (e.start, e.end) if p)
            text = f"{e.title}, {e.organization}" + (f", {e.location}" if e.location else "") + (f" ({period})" if period else "")
            out.append((Fact(id=fid, text=text), e))
        for i, lang in enumerate(self.languages, 1):
            fid = f"LANG-{i}"
            if fid not in explicit:
                out.append((Fact(id=fid, text=f"Language: {lang.name} ({lang.level})"), None))
        return out

    def fact_index(self) -> dict[str, tuple[Fact, Optional[Entry]]]:
        idx: dict[str, tuple[Fact, Optional[Entry]]] = {}
        for f in self.summary_facts:
            idx[f.id] = (f, None)
        for e in self.entries():
            for f in e.facts:
                idx[f.id] = (f, e)
        for f, e in self.implicit_facts():
            idx[f.id] = (f, e)
        return idx

    def entry(self, entry_id: str) -> Optional[Entry]:
        for e in self.entries():
            if e.id == entry_id:
                return e
        return None

    def all_skills(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for items in self.skills.values():
            for s in items:
                if s.lower() not in seen:
                    seen.add(s.lower())
                    out.append(s)
        for f, _ in self.fact_index().values():
            for s in f.skills:
                if s.lower() not in seen:
                    seen.add(s.lower())
                    out.append(s)
        return out

    def german_rank(self) -> int:
        return cefr_rank(self.german_level)

    def citizenship_set(self) -> set[str]:
        return {c.strip().upper() for c in self.citizenships if c.strip()}

    def todo_facts(self) -> list[str]:
        """Fact IDs whose text still contains a TODO marker."""
        return [fid for fid, (f, _) in self.fact_index().items() if "TODO" in f.text]

    def content_hash(self) -> str:
        blob = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]

    # -- prompt rendering ------------------------------------------------------
    def fact_bank_text(self) -> str:
        implicit = {e.id if e else None: [] for _, e in self.implicit_facts()}
        for f, e in self.implicit_facts():
            implicit.setdefault(e.id if e else None, []).append(f)
        lines: list[str] = []
        if self.summary_facts:
            lines.append("### Allgemein / General")
            for f in self.summary_facts:
                lines.append(f"[{f.id}] {f.text}")
        for e in self.entries():
            period = " – ".join(p for p in [e.start, e.end] if p)
            head = f"### {e.id} · {e.title} @ {e.organization}"
            if e.location:
                head += f" · {e.location}"
            if period:
                head += f" ({period})"
            head += f" [{e.kind}]"
            lines.append(head)
            for f in implicit.get(e.id, []):
                lines.append(f"[{f.id}] {f.text}")
            for f in e.facts:
                extra = f"  (skills: {', '.join(f.skills)})" if f.skills else ""
                lines.append(f"[{f.id}] {f.text}{extra}")
        if self.skills:
            lines.append("### Skills")
            for cat, items in self.skills.items():
                lines.append(f"- {cat}: {', '.join(items)}")
        langs = implicit.get(None, [])
        if langs:
            lines.append("### Languages")
            for f in langs:
                lines.append(f"[{f.id}] {f.text}")
        return "\n".join(lines)


def load_profile(path: Path) -> Profile:
    if not path.exists():
        raise FileNotFoundError(t("Profil henüz yok. Önce profilini oluştur.") + f" ({path})")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Profile.model_validate(data)
