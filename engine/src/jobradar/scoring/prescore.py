"""Stage 1 scoring: deterministic, zero tokens (career-ops 'zero-token scan',
JobNavigator 'light score'). Decides which postings deserve an LLM call."""

from __future__ import annotations

from typing import Any

from jobradar.config import AppConfig
from jobradar.profile import Profile
from jobradar.textutil import KeywordSet, days_since


class PreScorer:
    def __init__(self, cfg: AppConfig, profile: Profile):
        self.cfg = cfg
        self.profile = profile
        self.tracks = cfg.enabled_tracks()
        self.title_kw = {t.id: KeywordSet(t.title_keywords) for t in self.tracks}
        self.domain_kw = {t.id: KeywordSet(t.domain_keywords) for t in self.tracks}
        self.skills = KeywordSet(profile.all_skills())
        cities = [l.city for l in cfg.search.locations] + list(cfg.search.preferred_cities)
        self.cities = KeywordSet(cities)

    def score(self, job: dict[str, Any]) -> tuple[float, str | None, dict[str, Any]]:
        title = job.get("title", "")
        text = job.get("description", "")
        flags = job.get("flags") or {}
        best: tuple[float, str | None, dict[str, Any]] = (0.0, None, {})
        for t in self.tracks:
            detail: dict[str, Any] = {}
            title_hits = self.title_kw[t.id].find(title)
            if title_hits:
                pts_title = 40.0
            else:
                body_hits = self.title_kw[t.id].find(text)
                pts_title = 15.0 if len(body_hits) >= 2 else (6.0 if body_hits else 0.0)
                title_hits = body_hits[:3]
            detail["title"] = {"points": pts_title, "hits": title_hits[:5]}
            domain_hits = self.domain_kw[t.id].find(f"{title}\n{text}")
            pts_domain = min(10.0, 2.0 * len(domain_hits))
            detail["domain"] = {"points": pts_domain, "hits": domain_hits[:6]}
            # Small tie-breaker so the higher-priority track wins a draw.
            prio_bonus = max(0.0, 3.0 - 0.5 * (t.priority - 1))
            total = pts_title + pts_domain + prio_bonus
            if total > best[0]:
                best = (total, t.id, detail)
        base, track, detail = best

        skill_hits = self.skills.find(f"{title}\n{text}")
        pts_skills = min(30.0, 5.0 * len(skill_hits))
        detail["skills"] = {"points": pts_skills, "hits": skill_hits[:10]}

        age = days_since(job.get("posted_at"))
        pts_fresh = 0.0
        if age is not None:
            pts_fresh = 10.0 if age <= 2 else 6.0 if age <= 7 else 3.0 if age <= 14 else 0.0
        detail["freshness"] = {"points": pts_fresh, "days": age}

        loc = f"{job.get('location', '')}"
        pts_loc = 0.0
        if flags.get("remote") in ("remote", "hybrid") or self.cities.any(loc):
            pts_loc = 5.0
        detail["location"] = {"points": pts_loc}

        penalties: list[tuple[str, float]] = []
        if flags.get("seniority") == "lead":
            penalties.append(("lead/leitung", -30))
        elif flags.get("seniority") == "senior":
            penalties.append(("senior", -20))
        yrs = flags.get("years_required") or 0
        if yrs >= 5:
            penalties.append((f"{yrs}+ yıl deneyim", -15))
        elif yrs >= 3:
            penalties.append((f"{yrs}+ yıl deneyim", -5))
        gap = flags.get("german_gap") or 0
        if gap >= 2:
            penalties.append(("Almanca seviyesi", -20))
        elif gap == 1:
            penalties.append(("Almanca seviyesi", -8))
        if flags.get("citizenship_ok") is False:
            penalties.append(("vatandaşlık şartı", -30))
        elif flags.get("clearance") or flags.get("citizenship"):
            penalties.append(("güvenlik soruşturması/vatandaşlık", -8))
        if flags.get("agency"):
            penalties.append(("aracı firma", -5))
        et = flags.get("employment_type")
        if et and self.cfg.search.employment_types and et not in self.cfg.search.employment_types:
            penalties.append((f"çalışma türü {et}", -15))
        detail["penalties"] = penalties

        total = base + pts_skills + pts_fresh + pts_loc + sum(p for _, p in penalties)
        total = max(0.0, min(100.0, total))
        return round(total, 1), track, detail
