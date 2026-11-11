"""Stage 2 scoring: LLM evaluation, then code-side verification.

The model must map each requirement to fact IDs (career-ops Block B +
JobCtrl's evidence-backed scoring). Code then removes unknown IDs, downgrades
"strong" claims without evidence and caps scores that the evidence does not
carry, so a confident-sounding model cannot inflate a match.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from jobradar.i18n import t
from jobradar.config import AppConfig
from jobradar.profile import Profile
from jobradar.scoring.llm import BaseLLM, complete_json
from jobradar.scoring.prompts import build_eval_prompt


def _clamp(v: Any, lo: float = 1.0, hi: float = 5.0) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, f))


class Requirement(BaseModel):
    requirement: str
    importance: Literal["must", "nice"] = "must"
    match: Literal["strong", "partial", "gap"] = "gap"
    evidence: list[str] = Field(default_factory=list)
    note: str = ""

    @field_validator("importance", mode="before")
    @classmethod
    def _imp(cls, v: Any) -> str:
        s = str(v or "must").lower()
        return "nice" if s.startswith(("nice", "plus", "optional", "bonus")) else "must"

    @field_validator("match", mode="before")
    @classmethod
    def _match(cls, v: Any) -> str:
        s = str(v or "gap").lower()
        return s if s in ("strong", "partial", "gap") else ("partial" if "part" in s else "gap")

    @field_validator("evidence", mode="before")
    @classmethod
    def _ev(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [x.strip() for x in v.replace(";", ",").split(",") if x.strip()]
        return [str(x).strip() for x in v if str(x).strip()]


class Dimensions(BaseModel):
    cv_match: Optional[float] = None
    north_star: Optional[float] = None
    comp: Optional[float] = None
    culture: Optional[float] = None
    red_flags: Optional[float] = None

    @field_validator("*", mode="before")
    @classmethod
    def _c(cls, v: Any) -> Optional[float]:
        return _clamp(v)


class Evaluation(BaseModel):
    track: Optional[str] = None
    summary: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    dimensions: Dimensions = Field(default_factory=Dimensions)
    red_flags: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    global_score: float = 3.0
    verdict: Literal["apply", "maybe", "skip"] = "maybe"
    language: Optional[str] = None
    legitimacy: Literal["high", "medium", "low"] = "medium"
    legitimacy_notes: str = ""
    tailoring_hints: list[str] = Field(default_factory=list)
    interview_topics: list[str] = Field(default_factory=list)

    @field_validator("global_score", mode="before")
    @classmethod
    def _gs(cls, v: Any) -> float:
        c = _clamp(v)
        return 3.0 if c is None else c

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, v: Any) -> str:
        s = str(v or "maybe").lower()
        return s if s in ("apply", "maybe", "skip") else "maybe"

    @field_validator("legitimacy", mode="before")
    @classmethod
    def _legit(cls, v: Any) -> str:
        s = str(v or "medium").lower()
        return s if s in ("high", "medium", "low") else "medium"

    @field_validator("red_flags", "strengths", "gaps", "tailoring_hints", "interview_topics", mode="before")
    @classmethod
    def _lst(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [str(x) for x in v if str(x).strip()]


def verify(ev: Evaluation, profile: Profile, job: dict[str, Any], cfg: AppConfig) -> tuple[Evaluation, list[str]]:
    """Code-side checks on a model evaluation. Returns (evaluation, notes)."""
    notes: list[str] = []
    valid = set(profile.fact_index())
    track_ids = {t.id for t in cfg.enabled_tracks()}
    for req in ev.requirements:
        bad = [e for e in req.evidence if e not in valid]
        if bad:
            req.evidence = [e for e in req.evidence if e in valid]
            notes.append(t("Bilinmeyen kanıt kimlikleri silindi: {ids}", ids=", ".join(bad)))
        if req.match == "strong" and not req.evidence:
            req.match = "partial"
            notes.append(t("'{req}' için kanıt yok; 'strong' -> 'partial'", req=req.requirement[:60]))
    must = [r for r in ev.requirements if r.importance == "must"]
    if must:
        def weight(r: Requirement) -> float:
            if r.match == "strong":
                return 1.0
            if r.match == "partial":
                return 0.6 if r.evidence else 0.3
            return 0.0

        coverage = sum(weight(r) for r in must) / len(must)
        if 0.5 <= coverage < 0.7 and ev.global_score > 4.4:
            notes.append(t("Zorunlu şartların kanıt kapsamı %{pct}; puan {cap} ile sınırlandı", pct=f"{coverage * 100:.0f}", cap="4.4"))
            ev.global_score = 4.4
        if coverage < 0.5 and ev.global_score > 3.9:
            notes.append(t("Zorunlu şartların kanıt kapsamı %{pct}; puan {cap} ile sınırlandı", pct=f"{coverage * 100:.0f}", cap="3.9"))
            ev.global_score = 3.9
        elif coverage < 0.3 and ev.global_score > 3.4:
            notes.append(t("Zorunlu şartların kanıt kapsamı %{pct}; puan {cap} ile sınırlandı", pct=f"{coverage * 100:.0f}", cap="3.4"))
            ev.global_score = 3.4
    flags = job.get("flags") or {}
    deterministic: list[str] = []
    if (flags.get("german_gap") or 0) >= 1:
        deterministic.append(t("Almanca şartı {req} (profil: {mine})", req=flags.get("german_level"),
                               mine=profile.german_level))
    if flags.get("citizenship_ok") is False:
        deterministic.append(t("Vatandaşlık şartı: {value}", value=flags.get("citizenship")))
        if ev.global_score > 2.5:
            ev.global_score = 2.5
            notes.append(t("Vatandaşlık şartı karşılanmıyor; puan 2.5 ile sınırlandı"))
    elif flags.get("clearance"):
        deterministic.append(t("Güvenlik soruşturması gerekli ({level})", level=flags.get("clearance")))
    for d in deterministic:
        if not any(d.split(" (")[0].lower()[:12] in rf.lower() for rf in ev.red_flags):
            ev.red_flags.append(d)
    if ev.track not in track_ids:
        ev.track = job.get("track") if job.get("track") in track_ids else (next(iter(track_ids), None))
    thr = cfg.scoring.apply_threshold
    ev.global_score = round(ev.global_score, 1)
    ev.verdict = "apply" if ev.global_score >= thr else ("maybe" if ev.global_score >= 3.5 else "skip")
    return ev, notes


def evaluate_job(cfg: AppConfig, profile: Profile, job: dict[str, Any], llm: BaseLLM) -> tuple[Evaluation, list[str], str, str]:
    system, user = build_eval_prompt(cfg, profile, job)
    ev, res = complete_json(llm, system, user, Evaluation, tier=cfg.llm.eval_tier, max_tokens=3500)
    ev, notes = verify(ev, profile, job, cfg)
    return ev, notes, res.provider, res.model
