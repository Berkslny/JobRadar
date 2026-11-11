"""Hard filters (career-ops title_filter + JobNavigator include/exclude rules)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from jobradar import i18n
from jobradar.config import AppConfig
from jobradar.geo import COUNTRIES, country_code
from jobradar.i18n import t
from jobradar.processing.normalize import normalize_company
from jobradar.profile import Profile
from jobradar.textutil import KeywordSet, days_since, fold_umlauts

GERMAN_PLACES = [
    "germany", "deutschland", "bundesweit", "deutschlandweit", "aachen", "berlin", "hamburg", "münchen",
    "muenchen", "munich", "köln", "koeln", "cologne", "frankfurt", "stuttgart", "düsseldorf", "duesseldorf",
    "dortmund", "essen", "leipzig", "bremen", "dresden", "hannover", "hanover", "nürnberg", "nuremberg",
    "duisburg", "bochum", "wuppertal", "bielefeld", "bonn", "münster", "muenster", "mannheim", "karlsruhe",
    "augsburg", "wiesbaden", "mönchengladbach", "gelsenkirchen", "braunschweig", "kiel", "chemnitz",
    "aachen", "halle", "magdeburg", "freiburg", "krefeld", "mainz", "lübeck", "erfurt", "oberhausen",
    "rostock", "kassel", "hagen", "potsdam", "saarbrücken", "hamm", "ludwigshafen", "leverkusen",
    "oldenburg", "osnabrück", "heidelberg", "darmstadt", "solingen", "regensburg", "ingolstadt",
    "würzburg", "wolfsburg", "ulm", "heilbronn", "pforzheim", "göttingen", "bottrop", "reutlingen",
    "koblenz", "bremerhaven", "jena", "trier", "erlangen", "moers", "siegen", "hildesheim", "salzgitter",
    "cottbus", "kaiserslautern", "gütersloh", "witten", "schwerin", "gera", "iserlohn", "düren",
    "esslingen", "zwickau", "ratingen", "marl", "lünen", "hanau", "velbert", "ludwigsburg", "flensburg",
    "wilhelmshaven", "tübingen", "villingen", "konstanz", "neuss", "paderborn", "friedrichshafen",
    "ottobrunn", "taufkirchen", "manching", "unterlüß", "unterluess", "kassel", "kiel", "gilching",
    "oberkochen", "jülich", "juelich", "stolberg", "eschweiler", "heinsberg", "wachtberg", "garching",
    "immenstaad", "bremen", "überlingen", "ueberlingen", "ulm", "wedel", "schrobenhausen", "kiel",
    "bayern", "bavaria", "nordrhein-westfalen", "nrw", "baden-württemberg", "niedersachsen", "hessen",
    "sachsen", "thüringen", "brandenburg", "schleswig-holstein", "rheinland-pfalz", "saarland",
    "mecklenburg", "sachsen-anhalt",
]
def _variants(name: str) -> set[str]:
    stripped = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return {name, fold_umlauts(name), stripped}


_ALL_PLACES = {v for p in GERMAN_PLACES for v in _variants(p)}
_GERMAN_PLACES_RE = re.compile(
    r"\b(?:" + "|".join(sorted({re.escape(p) for p in _ALL_PLACES}, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_DE_CODE_RE = re.compile(r"(?:,|\s|\()\s*(?:de|deu|ger)\s*(?:\)|$|,)", re.IGNORECASE)
_REMOTE_RE = re.compile(r"\bremote\b|home\s*office|anywhere", re.IGNORECASE)
_REMOTE_OK_REGION = re.compile(r"\b(?:germany|deutschland|eu|europe|emea|dach|european)\b", re.IGNORECASE)


def location_in_germany(location: str, allow_unspecified_remote: bool = True) -> bool | None:
    """True if clearly Germany, False if clearly elsewhere, None if unknown/empty."""
    loc = (location or "").strip()
    if not loc:
        return None
    if _GERMAN_PLACES_RE.search(loc) or _GERMAN_PLACES_RE.search(fold_umlauts(loc)) or _DE_CODE_RE.search(loc):
        return True
    if _REMOTE_RE.search(loc):
        if _REMOTE_OK_REGION.search(loc):
            return True
        if re.fullmatch(r"\s*(?:remote|fully remote|remote\s*-\s*anywhere|anywhere)\s*", loc, re.IGNORECASE):
            return True if allow_unspecified_remote else None
        return False
    return False


_COUNTRY_WORDS: dict[str, list[str]] = {}


def _country_words() -> dict[str, list[str]]:
    """ISO code -> lowercase names a location line may use for that country."""
    if not _COUNTRY_WORDS:
        local = {"DE": ["deutschland"], "AT": ["österreich", "osterreich"], "CH": ["schweiz", "suisse", "svizzera"],
                 "TR": ["türkiye", "turkiye"], "ES": ["españa", "espana"], "IT": ["italia"], "NL": ["nederland"],
                 "FR": [], "GB": ["united kingdom", "england", "scotland", "wales", "great britain"],
                 "US": ["united states", "u.s."], "PL": ["polska"], "SE": ["sverige"], "DK": ["danmark"],
                 "NO": ["norge"], "FI": ["suomi"], "BE": ["belgië", "belgique"], "CZ": ["czechia", "česko"],
                 "AE": ["uae"], "BR": ["brasil"]}
        for code, name in COUNTRIES:
            _COUNTRY_WORDS[code] = [name.lower()] + local.get(code, [])
    return _COUNTRY_WORDS


def location_in_country(location: str, country: str, allow_unspecified_remote: bool = True) -> bool | None:
    """True if the location is clearly in ``country``, False if clearly elsewhere, None if unknown."""
    code = country_code(country)
    if code == "DE":
        return location_in_germany(location, allow_unspecified_remote)
    loc = fold_umlauts((location or "").strip()).lower()
    if not loc or not code:
        return None
    words = _country_words()

    def mentions(names: list[str]) -> bool:
        return any(re.search(rf"(?<![a-z]){re.escape(fold_umlauts(n))}(?![a-z])", loc) for n in names)

    if mentions(words.get(code, [])) or re.search(rf"(?:,|\(|\s)\s*{code.lower()}\s*(?:\)|,|$)", loc):
        return True
    if _REMOTE_RE.search(loc):
        elsewhere = any(mentions(names) for other, names in words.items() if other != code)
        if elsewhere:
            return False
        return True if allow_unspecified_remote else None
    if any(mentions(names) for other, names in words.items() if other != code):
        return False
    return None


TRACK_REASON = "hiçbir hedef alana uymuyor"


def track_only_reasons() -> tuple[str, str]:
    """`filtered_reason` of a posting that only the track rule filtered out, in both interface languages."""
    return TRACK_REASON, i18n.EN.get(TRACK_REASON, TRACK_REASON)


def promoted(job: dict[str, Any]) -> bool:
    """Semantic matching let this posting pass the keyword rules (see scoring/match.py)."""
    return bool(((job.get("flags") or {}).get("semantic") or {}).get("promoted"))


class FilterEngine:
    def __init__(self, cfg: AppConfig, profile: Profile):
        self.cfg = cfg
        self.profile = profile
        self.title_exclude = KeywordSet(cfg.filters.title_exclude)
        self.blacklist = [normalize_company(c) for c in cfg.filters.company_blacklist if c.strip()]
        self.track_title = {t.id: KeywordSet(t.title_keywords) for t in cfg.enabled_tracks()}
        self.track_domain = {t.id: KeywordSet(t.title_keywords + t.domain_keywords) for t in cfg.enabled_tracks()}
        self.wanted_types = set(cfg.search.employment_types)

    def reasons(self, job: dict[str, Any]) -> list[str]:
        """Return the reasons a job is filtered out (empty list = keep)."""
        out = self.hard_reasons(job)
        if self.track_mismatch(job) and not (self.cfg.matching.enabled and self.cfg.matching.promote
                                             and promoted(job)):
            out.append(t(TRACK_REASON))
        return out

    def hard_reasons(self, job: dict[str, Any]) -> list[str]:
        """Rules you set yourself (blocklist, title words, employment type, seniority, age, place, language,
        clearance, agencies). Semantic matching never overrides these."""
        cfg = self.cfg.filters
        flags = job.get("flags") or {}
        out: list[str] = []
        title = job.get("title", "")
        cn = job.get("company_norm", "")
        if cn and any(b and (cn == b or cn.startswith(b + " ")) for b in self.blacklist):
            out.append(t("şirket kara listede"))
        hits = self.title_exclude.find(title)
        if hits:
            out.append(t("başlıkta istenmeyen kelime: {word}", word=hits[0]))
        et = flags.get("employment_type") or ""
        if et and self.wanted_types and et not in self.wanted_types:
            out.append(t("çalışma türü istenmiyor: {type}", type=et))
        if cfg.exclude_senior and flags.get("seniority") in ("senior", "lead"):
            out.append(t("kıdem: {level}", level=flags.get("seniority")))
        age = days_since(job.get("posted_at"))
        if age is not None and age > self.cfg.search.max_age_days:
            out.append(t("ilan {age} günlük", age=age))
        if job.get("needs_location_check"):
            ok = location_in_country(job.get("location", ""), self.cfg.search.country, cfg.allow_unspecified_remote)
            if ok is False:
                out.append(t("{country} dışı konum: {loc}", country=self.cfg.search.country or "?",
                             loc=job.get("location", "")[:60]))
        if cfg.german_gap_policy == "exclude" and (flags.get("german_gap") or 0) >= 2:
            out.append(t("Almanca şartı ({level}) seviyenin çok üstünde", level=flags.get("german_level")))
        if cfg.clearance_policy == "exclude":
            if flags.get("citizenship_ok") is False:
                out.append(t("vatandaşlık şartı: {value}", value=flags.get("citizenship")))
            elif flags.get("clearance") and flags.get("citizenship_ok") is not True:
                out.append(t("güvenlik soruşturması: {level}", level=flags.get("clearance")))
        if cfg.exclude_agencies and flags.get("agency"):
            out.append(t("aracı firma ilanı"))
        return out

    def track_mismatch(self, job: dict[str, Any]) -> bool:
        """True when no keyword ties the posting to one of the tracks (and the track rule is on)."""
        if not (self.cfg.filters.require_track_match and self.track_title):
            return False
        title = job.get("title", "")
        text = job.get("description", "")
        if any(ks.any(title) for ks in self.track_title.values()):
            return False
        if len(text) >= 300:
            return not any(len(ks.find(text)) >= 3 for ks in self.track_domain.values())
        # Company boards list every opening; without a description the title is the only signal we have.
        return bool(job.get("needs_location_check"))
