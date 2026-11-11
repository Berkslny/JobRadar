"""Anti-fabrication validator for tailored CVs and cover letters.

Rules (JobCtrl's "drafts that invent facts fail validation", made stricter):
* every CV bullet cites existing fact IDs of the entry it sits under;
* every number in a text must appear in the cited facts;
* a tool/keyword that the job posting asks for may appear in a CV bullet only
  if the cited facts contain it (no keyword stuffing); in the letter, the
  profile's skills, the company and the role title are allowed as well;
* the skills list may only contain the profile's skills.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from jobradar.i18n import t
from jobradar.profile import Profile

# Common tech / domain terms worth guarding even when written in lowercase.
TECH_VOCAB = {
    "python", "matlab", "simulink", "labview", "altium", "kicad", "eagle", "orcad", "cadence", "vivado", "vitis",
    "quartus", "modelsim", "questa", "systemverilog", "verilog", "vhdl", "uvm", "fpga", "asic", "soc", "zynq",
    "pynq", "petalinux", "yocto", "linux", "rtos", "freertos", "zephyr", "autosar", "canoe", "canalyzer",
    "ethercat", "profinet", "modbus", "spi", "i2c", "uart", "pcie", "ethernet", "jtag", "cortex",
    "stm32", "c++", "c#", "java", "javascript", "typescript", "rust", "sql", "docker", "kubernetes", "git",
    "jenkins", "eplan", "autocad", "solidworks", "catia", "creo", "ansys", "comsol", "pspice", "ltspice", "plecs",
    "powerfactory", "neplan", "pscad", "etap", "sap", "power bi", "tableau", "gurobi", "cplex", "pyomo",
    "milp", "lca", "simapro", "gabi", "openlca", "csrd", "esrs", "iso 14001", "iso 50001", "iso 26262",
    "do-254", "do-178", "opencv", "tensorflow", "pytorch", "ros", "ros2", "px4", "ardupilot", "inav",
    "gazebo", "fusion 360", "aws", "azure", "gcp", "dspace", "lidar", "sigint", "elint", "pcb",
}
_CAPS_STOP = {
    "ihre", "wir", "sie", "das", "der", "die", "und", "mit", "für", "uns", "dein", "deine", "ihr", "was", "wer",
    "wie", "jobs", "job", "team", "bieten", "our", "you", "your", "the", "and", "with", "what", "about", "role",
    "hier", "jetzt", "neu", "new", "apply", "info", "kontakt", "profil", "gute", "top", "gmbh", "ag", "se", "kg",
    "eu", "de", "en", "ca", "ok", "hr", "it", "we", "us", "uk", "usa", "faq", "cv", "pdf", "ceo", "cto", "nrw",
    "vs", "id", "tbd", "pm", "am", "pm", "mwd", "wmd", "mfd", "all", "or", "oder", "bei", "bis", "vor", "ort",
}
_NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?:\s?%)?")
_PLACEHOLDER = re.compile(r"\[[^\]]{1,60}\]")


class Bullet(BaseModel):
    text: str
    facts: list[str] = Field(default_factory=list)

    @field_validator("facts", mode="before")
    @classmethod
    def _f(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return [str(x).strip() for x in v]


class ExperienceBlock(BaseModel):
    entry_id: str
    bullets: list[Bullet] = Field(default_factory=list)


class Letter(BaseModel):
    subject: str = ""
    salutation: str = ""
    paragraphs: list[Bullet] = Field(default_factory=list)
    closing: str = ""


class Answer(BaseModel):
    question: str
    answer: str
    facts: list[str] = Field(default_factory=list)

    @field_validator("facts", mode="before")
    @classmethod
    def _f(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return [str(x).strip() for x in v]


class TailoredDocs(BaseModel):
    headline: str = ""
    summary: Bullet = Field(default_factory=lambda: Bullet(text=""))
    experience: list[ExperienceBlock] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    cover_letter: Letter = Field(default_factory=Letter)
    answers: list[Answer] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, v: Any) -> Any:
        if isinstance(v, str):
            return {"text": v, "facts": []}
        return v or {"text": "", "facts": []}


@dataclass
class Violation:
    where: str
    message: str
    severity: Literal["error", "warning"] = "error"
    loc: tuple = ()

    def as_dict(self) -> dict[str, Any]:
        return {"where": self.where, "message": self.message, "severity": self.severity}


@dataclass
class ValidationReport:
    violations: list[Violation] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def messages(self) -> list[str]:
        return [f"{v.where}: {v.message}" for v in self.errors]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "violations": [v.as_dict() for v in self.violations], "removed": self.removed}


def _norm_num(s: str) -> str:
    s = s.replace(" ", "").rstrip("%")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):
        return s.replace(".", "").replace(",", "")
    return s.replace(",", ".")


def numbers_in(text: str) -> set[str]:
    clean = _PLACEHOLDER.sub(" ", text or "")
    return {_norm_num(m.group(0)) for m in _NUM.finditer(clean)}


def job_terms(job_text: str) -> set[str]:
    """Technical-looking terms in the posting: acronyms, CamelCase tools, known tools."""
    terms: set[str] = set()
    for line in (job_text or "").splitlines():
        letters = [c for c in line if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
            continue  # an all-caps heading, not acronyms
        for m in re.finditer(r"(?<![\w])[A-Z][A-Z0-9+#/-]{1,5}(?![\w])", line):
            tok = m.group(0).strip("/-")
            if len(tok) >= 2 and not tok.isdigit():
                terms.add(tok.lower())
        for m in re.finditer(r"\b[A-Za-z]*[a-z][A-Z][A-Za-z]+\b", line):  # CamelCase (SystemVerilog)
            terms.add(m.group(0).lower())
    low = (job_text or "").lower()
    for v in TECH_VOCAB:
        if re.search(rf"(?<![\w+#]){re.escape(v)}(?![\w+#])", low):
            terms.add(v)
    return {t for t in terms if t not in _CAPS_STOP}


def _contains(text_low: str, term: str) -> bool:
    return re.search(rf"(?<![\w+#]){re.escape(term)}(?![\w+#])", text_low) is not None


class Validator:
    def __init__(self, profile: Profile, job: dict[str, Any]):
        self.profile = profile
        self.index = profile.fact_index()
        self.skills = profile.all_skills()
        self.skill_low = {s.lower() for s in self.skills}
        self.profile_text = (profile.fact_bank_text() + "\n" + " ".join(self.skills)).lower()
        self.terms = job_terms(job.get("description") or "")
        self.job_context = " ".join([job.get("company") or "", job.get("title") or "", job.get("location") or ""]).lower()

    def _fact_text(self, ids: list[str]) -> str:
        parts = []
        for i in ids:
            if i in self.index:
                f, _ = self.index[i]
                parts.append(f.text + " " + " ".join(f.skills))
        return "\n".join(parts).lower()

    def _check(self, where: str, loc: tuple, text: str, facts: list[str], rep: ValidationReport, *,
               require_facts: bool, owner: Optional[str] = None, letter: bool = False) -> None:
        unknown = [f for f in facts if f not in self.index]
        if unknown:
            rep.violations.append(Violation(where, t("bilinmeyen gerçek kimliği: {ids}", ids=", ".join(unknown)), loc=loc))
        known = [f for f in facts if f in self.index]
        if owner is not None:
            foreign = [f for f in known if (self.index[f][1].id if self.index[f][1] else None) != owner]
            if foreign:
                rep.violations.append(Violation(where, t("başka bir girişe ait gerçek: {ids}", ids=", ".join(foreign)), loc=loc))
        if require_facts and not known:
            rep.violations.append(Violation(where, t("hiçbir gerçeğe dayanmıyor"), loc=loc))
        basis = self._fact_text(known) if known else self.profile_text
        allowed_nums = numbers_in(basis)
        for n in sorted(numbers_in(text)):
            if n not in allowed_nums:
                rep.violations.append(Violation(where, t("kaynak gerçeklerde olmayan sayı: {n}", n=n), loc=loc))
        allowed = basis
        if letter:
            allowed += "\n" + " ".join(self.skill_low) + "\n" + self.job_context
        low = (text or "").lower()
        for term in sorted(self.terms):
            if _contains(low, term) and not _contains(allowed, term):
                rep.violations.append(Violation(where, t("kanıtı olmayan terim: '{term}'", term=term), loc=loc))

    def validate(self, docs: TailoredDocs) -> ValidationReport:
        rep = ValidationReport()
        if docs.summary.text:
            self._check(t("Profil özeti"), ("summary",), docs.summary.text, docs.summary.facts, rep,
                        require_facts=False, letter=True)
        for block in docs.experience:
            entry = self.profile.entry(block.entry_id)
            if not entry:
                rep.violations.append(Violation(t("Giriş {id}", id=block.entry_id), t("profilde böyle bir giriş yok"),
                                                loc=("entry", block.entry_id)))
                continue
            for i, b in enumerate(block.bullets):
                self._check(t("{id} madde {n}", id=entry.organization, n=i + 1), ("bullet", entry.id, i), b.text, b.facts, rep,
                            require_facts=True, owner=entry.id)
        for s in docs.skills:
            if s.lower() not in self.skill_low:
                rep.violations.append(Violation(t("Beceriler"), t("profilde olmayan beceri: '{s}'", s=s), loc=("skill", s)))
        for i, p in enumerate(docs.cover_letter.paragraphs):
            self._check(t("Ön yazı paragraf {n}", n=i + 1), ("paragraph", i), p.text, p.facts, rep,
                        require_facts=False, letter=True)
        for i, a in enumerate(docs.answers):
            self._check(t("Cevap {n}", n=i + 1), ("answer", i), a.answer, a.facts, rep, require_facts=False, letter=True)
        if docs.headline:
            low = docs.headline.lower()
            for term in sorted(self.terms):
                if _contains(low, term) and not _contains(self.profile_text + " " + self.job_context, term):
                    rep.violations.append(Violation(t("Başlık"), t("kanıtı olmayan terim: '{term}'", term=term), "warning",
                                                    loc=("headline",)))
        return rep


def strip_violations(docs: TailoredDocs, rep: ValidationReport) -> TailoredDocs:
    """Last resort after a failed repair: drop every element that still fails."""
    bad_bullets = {(v.loc[1], v.loc[2]) for v in rep.errors if v.loc and v.loc[0] == "bullet"}
    bad_entries = {v.loc[1] for v in rep.errors if v.loc and v.loc[0] == "entry"}
    bad_skills = {v.loc[1].lower() for v in rep.errors if v.loc and v.loc[0] == "skill"}
    bad_pars = {v.loc[1] for v in rep.errors if v.loc and v.loc[0] == "paragraph"}
    bad_answers = {v.loc[1] for v in rep.errors if v.loc and v.loc[0] == "answer"}
    summary_bad = any(v.loc == ("summary",) for v in rep.errors)

    blocks = []
    for block in docs.experience:
        if block.entry_id in bad_entries:
            rep.removed.append(t("giriş {id}", id=block.entry_id))
            continue
        kept = []
        for i, b in enumerate(block.bullets):
            if (block.entry_id, i) in bad_bullets:
                rep.removed.append(t("{id} madde {n}: {text}", id=block.entry_id, n=i + 1, text=b.text[:60]))
            else:
                kept.append(b)
        block.bullets = kept
        if kept:
            blocks.append(block)
    docs.experience = blocks
    docs.skills = [s for s in docs.skills if s.lower() not in bad_skills]
    pars = []
    for i, p in enumerate(docs.cover_letter.paragraphs):
        if i in bad_pars:
            rep.removed.append(t("ön yazı paragraf {n}: {text}", n=i + 1, text=p.text[:60]))
        else:
            pars.append(p)
    docs.cover_letter.paragraphs = pars
    for i, a in enumerate(docs.answers):
        if i in bad_answers:
            a.answer = t("[Bu cevabı kendin yaz: taslak doğrulamadan geçemedi]")
            a.facts = []
    if summary_bad:
        rep.removed.append(t("profil özeti"))
        docs.summary = Bullet(text="", facts=[])
    return docs


class ReviewIssue(BaseModel):
    where: str = ""
    problem: str
    suggestion: str = ""

    @field_validator("where", "suggestion", mode="before")
    @classmethod
    def _s(cls, v: Any) -> str:
        return "" if v is None else str(v)


class ReviewResult(BaseModel):
    """Critique from the second-pass reviewer (see build_review_prompt)."""

    verdict: str = "ok"
    summary: str = ""
    issues: list[ReviewIssue] = Field(default_factory=list)
    supported_missing_keywords: list[str] = Field(default_factory=list)
    generic_phrases: list[str] = Field(default_factory=list)

    @field_validator("verdict", mode="before")
    @classmethod
    def _v(cls, v: Any) -> str:
        return "revise" if str(v or "").strip().lower().startswith("rev") else "ok"

    @field_validator("supported_missing_keywords", "generic_phrases", mode="before")
    @classmethod
    def _l(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return [str(x) for x in v if str(x).strip()]

    @field_validator("issues", mode="before")
    @classmethod
    def _i(cls, v: Any) -> list[Any]:
        out = []
        for item in v or []:
            if isinstance(item, str):
                out.append({"problem": item})
            elif isinstance(item, dict) and (item.get("problem") or item.get("issue")):
                item = dict(item)
                item.setdefault("problem", item.get("issue"))
                out.append(item)
        return out[:8]
