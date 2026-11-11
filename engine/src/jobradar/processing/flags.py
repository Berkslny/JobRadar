"""Deterministic signals detected in a posting (zero tokens).

German-market specifics that the four reference tools do not handle:
German language level demanded, security clearance (SÜG Ü1-Ü3) and
citizenship requirements, Werkstudent/Abschlussarbeit detection, tariff
groups (TV-L, TVöD, IG Metall/ERA) and recruiting agencies.
"""

from __future__ import annotations

import re
from typing import Any
from jobradar.i18n import t

from jobradar.profile import EU_CODES, NATO_CODES, Profile, cefr_rank

_F = re.IGNORECASE

# ---------------------------------------------------------------------------
# German language requirement
# ---------------------------------------------------------------------------

_DE = r"deutsch(?!land)\w*"
_GER = r"german(?!y)\w*"
_W = r"(?:[\w-]+\s+){0,3}"  # up to three filler words

_GERMAN_PHRASES: list[tuple[str, str]] = [
    (rf"{_DE}\s+(?:als\s+)?muttersprache|muttersprachlich\w*\s+{_DE}|{_DE}\s*\(\s*muttersprach", "C2"),
    (rf"native\s+(?:level\s+)?{_GER}|{_GER}\s+native|{_GER}\s*\(\s*native", "C2"),
    (rf"verhandlungssicher\w*\s+{_W}{_DE}|{_DE}\s+{_W}verhandlungssicher", "C1"),
    (rf"(?:sehr\s+gute|exzellente|ausgezeichnete|hervorragende|perfekte)\s+{_W}{_DE}", "C1"),
    (rf"{_DE}\s+{_W}(?:in\s+wort\s+und\s+schrift\s+)?(?:sehr\s+gut|exzellent|ausgezeichnet|hervorragend|perfekt)\b", "C1"),
    (rf"flie(?:ß|ss)end\w*\s+{_W}{_DE}|{_DE}\s+{_W}flie(?:ß|ss)end", "C1"),
    (rf"(?:business|professional)[\s-]+(?:fluent|fluency|level|proficiency)\s+(?:in\s+)?{_GER}", "C1"),
    (rf"{_GER}\s*\(?\s*(?:business|professional)[\s-]+(?:fluent|fluency|level)", "C1"),
    (rf"fluen(?:t|cy)\s+(?:in\s+)?{_W}{_GER}|{_GER}\s+{_W}fluen(?:t|cy)", "C1"),
    (rf"(?:very\s+good|excellent|strong|full\s+professional)\s+(?:command\s+of\s+|knowledge\s+of\s+)?{_GER}", "C1"),
    (rf"(?:gute|solide)\s+{_W}{_DE}|{_DE}\s+{_W}(?:gut|solide)\b", "B2"),
    (rf"good\s+(?:command\s+of\s+|knowledge\s+of\s+)?{_GER}|{_GER}\s+{_W}good\b", "B2"),
    (rf"(?:grundkenntnisse|basiskenntnisse|erste\s+kenntnisse)\s+{_W}{_DE}|{_DE}\w*\s*(?:grundkenntnisse|basiskenntnisse)", "A2"),
    (rf"basic\s+(?:knowledge\s+of\s+)?{_GER}|{_GER}\s+{_W}basic", "A2"),
]
_GERMAN_PHRASES_C = [(re.compile(p, _F), lv) for p, lv in _GERMAN_PHRASES]
_EXPLICIT_LANG_FIRST = re.compile(rf"(?:{_DE}|{_GER})[^.\n]{{0,45}}?\b([ABC][12])\b", _F)
_EXPLICIT_LEVEL_FIRST = re.compile(rf"\b([ABC][12])\b(?:[-\s]?niveau|[-\s]?level)?[^.\n]{{0,20}}?(?:{_DE}|{_GER})", _F)
_GERMAN_OPTIONAL = re.compile(
    rf"(?:{_DE}|{_GER})[^.\n]{{0,70}}?(?:von\s+vorteil|wünschenswert|ein\s+plus|ein\s+bonus|is\s+a\s+plus|"
    rf"would\s+be\s+a\s+plus|nice[\s-]to[\s-]have|an?\s+(?:advantage|asset|bonus)|beneficial|optional|"
    rf"preferred|desirable|not\s+required|nicht\s+erforderlich|keine\s+voraussetzung)"
    rf"|(?:von\s+vorteil|nice[\s-]to[\s-]have|a\s+plus|wünschenswert)[^.\n]{{0,40}}?(?:{_DE}|{_GER})",
    _F,
)
_CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]


def detect_german(text: str) -> dict[str, Any]:
    """Return {'german_level': 'C1'|None, 'german_optional': bool}."""
    if not text:
        return {"german_level": None, "german_optional": False}
    found: list[str] = []
    m = _EXPLICIT_LANG_FIRST.search(text)
    if m:
        found.append(m.group(1).upper())
    else:
        m2 = _EXPLICIT_LEVEL_FIRST.search(text)
        if m2:
            found.append(m2.group(1).upper())
    for pat, lv in _GERMAN_PHRASES_C:
        if pat.search(text):
            found.append(lv)
    level = None
    if found:
        level = max(found, key=lambda lv: _CEFR_ORDER.index(lv) if lv in _CEFR_ORDER else -1)
    optional = bool(_GERMAN_OPTIONAL.search(text))
    return {"german_level": level, "german_optional": optional}


# ---------------------------------------------------------------------------
# Security clearance / citizenship (defence sector)
# ---------------------------------------------------------------------------

_CLEARANCE = re.compile(
    r"sicherheits(?:überprüfung|ueberpruefung|bescheid)|\bS(?:Ü|UE)G\b|\b(?:Ü|UE)\s?[123]\b"
    r"|security\s+clearance|geheimschutz|\bVS[-\s]?NfD\b|verschlusssache|nato\s+secret"
    r"|ermächtigung\s+zum\s+umgang",
    _F,
)
_CLEARANCE_LEVEL = re.compile(r"\b(?:Ü|UE)\s?([123])\b", _F)
_CIT_DE = re.compile(
    r"deutsche\w*\s+staats(?:angehörigkeit|bürgerschaft)|german\s+(?:citizenship|nationality|citizen)"
    r"|deutsche[rn]?\s+(?:reise)?pass",
    _F,
)
_CIT_EU = re.compile(
    r"\b(?:eu|ewr|eea|european\s+union)[\s-]*(?:staats(?:angehörigkeit|bürgerschaft|bürger)|citizen(?:ship)?|bürger)"
    r"|staatsangehörigkeit\s+eines\s+(?:eu|ewr)",
    _F,
)
_CIT_NATO = re.compile(
    r"\bnato[\s-]*(?:staats(?:angehörigkeit|bürgerschaft)|citizen(?:ship)?|mitglied(?:s)?staat\w*|member\s+(?:state|country))"
    r"|staatsangehörigkeit\s+eines\s+nato",
    _F,
)


def detect_clearance(text: str) -> dict[str, Any]:
    clearance = None
    if text and _CLEARANCE.search(text):
        lv = _CLEARANCE_LEVEL.findall(text)
        clearance = f"Ü{max(int(x) for x in lv)}" if lv else "yes"
    citizenship = None
    if text:
        if _CIT_DE.search(text):
            citizenship = "DE"
        elif _CIT_NATO.search(text):
            citizenship = "NATO"
        elif _CIT_EU.search(text):
            citizenship = "EU"
    return {"clearance": clearance, "citizenship": citizenship}


def citizenship_ok(required: str | None, profile: Profile) -> bool | None:
    """True/False if decidable from profile.citizenships, None if unknown."""
    if not required:
        return True
    have = profile.citizenship_set()
    if not have:
        return None
    if required == "DE":
        return "DE" in have
    if required == "EU":
        return bool(have & EU_CODES)
    if required == "NATO":
        return bool(have & NATO_CODES)
    return None


# ---------------------------------------------------------------------------
# Employment type, seniority, experience
# ---------------------------------------------------------------------------

_ET_TITLE = [
    ("werkstudent", r"werkstudent|working\s+student|studentische[rn]?\s+(?:mitarbeit|hilfskraft|aushilfe)|\bhiwi\b|student\s+assistant|studentenjob|student\s+job"),
    ("thesis", r"abschlussarbeit|masterarbeit|bachelorarbeit|master'?s?\s+thesis|bachelor'?s?\s+thesis|\bthesis\b|diplomarbeit"),
    ("internship", r"praktikum|praktikant|internship|\bintern\b|pflichtpraktikum"),
    ("trainee", r"trainee|graduate\s+program|absolventenprogramm|einstiegsprogramm|direkteinstieg"),
    ("apprenticeship", r"ausbildung\b|ausbildung\s+zum|azubi|auszubildende|duales\s+studium|dual\s+stud"),
    ("freelance", r"freelanc|freiberuf|\bcontractor\b|interim"),
    ("parttime", r"teilzeit|part[\s-]time|minijob"),
]
_ET_TITLE_C = [(name, re.compile(p, _F)) for name, p in _ET_TITLE]
_RAW_ET = {
    "fulltime": "fulltime", "full_time": "fulltime", "full-time": "fulltime", "fulltime_permanent": "fulltime",
    "vollzeit": "fulltime", "permanent": "fulltime", "full time": "fulltime",
    "parttime": "parttime", "part_time": "parttime", "part-time": "parttime", "teilzeit": "parttime",
    "internship": "internship", "intern": "internship", "praktikum": "internship",
    "contract": "contract", "temporary": "contract", "freelance": "freelance",
    "werkstudent": "werkstudent", "working student": "werkstudent",
}


def detect_employment_type(title: str, text: str, raw_type: str = "") -> str:
    t = title or ""
    for name, pat in _ET_TITLE_C:
        if pat.search(t):
            return name
    raw = (raw_type or "").strip().lower().replace("é", "e")
    for key, val in _RAW_ET.items():
        if raw == key or raw.startswith(key):
            return val
    body = (text or "")[:4000]
    if re.search(r"\bwerkstudent", body, _F) and not re.search(r"vollzeit|full[\s-]time", body, _F):
        return "werkstudent"
    if re.search(r"vollzeit|full[\s-]?time|unbefristet|festanstellung|permanent\s+(?:position|contract)", body, _F):
        return "fulltime"
    return ""


_LEAD = re.compile(
    r"\b(?:head\s+of|director|direktor\w*|chief|vp|vice\s+president|principal|staff\s+engineer|cto|ceo"
    r"|(?:team|abteilungs|bereichs|gruppen|projekt|fach|labor|entwicklungs|standort|niederlassungs|bau)?leiter(?!platt)\w*"
    r"|(?:team|abteilungs|bereichs|gruppen|projekt)?leitung|teamlead\w*|team\s*lead\w*)\b",
    _F,
)
_SENIOR = re.compile(r"\b(?:senior|sr\.?|expert\w*|experte|fachexperte|architect|architekt\w*)\b", _F)
_JUNIOR = re.compile(
    r"\b(?:junior|jr\.?|entry[\s-]level|graduate|berufseinsteiger\w*|absolvent\w*|young\s+professional|"
    r"einsteiger\w*|associate|trainee|career\s+starter|hochschulabsolvent\w*)\b",
    _F,
)
_YEARS_DE = re.compile(
    r"(?:mindestens|mind\.|min\.|über|mehr\s+als|ab)?\s*(\d{1,2})\s*\+?\s*(?:-|–|bis)?\s*(?:\d{1,2}\s*)?jahr\w*\s+(?:[\w-]+\s+){0,3}(?:berufs|praxis|projekt|arbeits)?erfahrung",
    _F,
)
_YEARS_EN = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(?:\d{1,2}\s*)?(?:years?|yrs?)\s+(?:of\s+)?(?:[\w-]+\s+){0,4}experience",
    _F,
)


def detect_seniority(title: str, text: str, raw_level: str = "") -> str:
    t = title or ""
    if _LEAD.search(t):
        return "lead"
    if _SENIOR.search(t):
        return "senior"
    if _JUNIOR.search(t):
        return "junior"
    raw = (raw_level or "").lower()
    if raw:
        if any(x in raw for x in ("director", "executive", "lead", "principal")):
            return "lead"
        if "senior" in raw or "mid-senior" in raw:
            return "senior"
        if any(x in raw for x in ("entry", "intern", "junior", "associate")):
            return "junior"
    return "mid"


def detect_years_required(text: str) -> int | None:
    vals: list[int] = []
    for pat in (_YEARS_DE, _YEARS_EN):
        for m in pat.finditer(text or ""):
            try:
                v = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if 0 < v <= 15:
                vals.append(v)
    return max(vals) if vals else None


# ---------------------------------------------------------------------------
# Remote / salary / tariff / agency
# ---------------------------------------------------------------------------

_REMOTE_FULL = re.compile(
    r"100\s*%\s*remote|fully\s+remote|full[\s-]remote|remote[\s-]first|vollständig\s+remote|komplett\s+remote"
    r"|ortsunabhängig|deutschlandweit\s+remote|remote\s*\(?\s*(?:germany|deutschland|de|eu)\)?\s*$|^remote$",
    _F,
)
_HYBRID = re.compile(r"\bhybrid\b|mobiles?\s+arbeiten|home[\s-]?office|remote[\s-]anteil|teilweise\s+remote|\bremote\b", _F)
_ONSITE = re.compile(r"\bvor\s+ort\b|\bon[\s-]?site\b|präsenzpflicht", _F)


def detect_remote(title: str, location: str, text: str, raw_remote: bool | None) -> str:
    if raw_remote is True:
        return "remote"
    if re.search(r"\bremote\b|\b100\s*%\s*home\s*office\b", title or "", _F):
        return "remote"
    for s in (title or "", location or ""):
        if _REMOTE_FULL.search(s.strip()):
            return "remote"
    body = (text or "")[:6000]
    if _REMOTE_FULL.search(body):
        return "remote"
    if _HYBRID.search(body) or _HYBRID.search(location or ""):
        return "hybrid"
    if _ONSITE.search(body):
        return "onsite"
    return ""


_AMOUNT = r"(\d{1,3}(?:[.\s,]\d{3})+(?:,\d{2})?|\d{2,6}(?:,\d{2})?\s?[kK]?|\d+[.,]\d{1,2})"
_CUR = r"(?:€|eur\b|euro\b)"
_SALARY_RANGE = re.compile(
    rf"(?:{_CUR}\s*)?{_AMOUNT}\s*(?:{_CUR})?\s*(?:-|–|—|bis|to)\s*(?:{_CUR}\s*)?{_AMOUNT}\s*(?:{_CUR})",
    _F,
)
_SALARY_RANGE_PREFIX = re.compile(rf"{_CUR}\s*{_AMOUNT}\s*(?:-|–|—|bis|to)\s*(?:{_CUR}\s*)?{_AMOUNT}", _F)
_SALARY_SINGLE = re.compile(rf"(?:{_CUR}\s*{_AMOUNT}|{_AMOUNT}\s*{_CUR})", _F)
_TARIFF = re.compile(
    r"\b(TV[-\s]?L|TVöD(?:[-\s]?(?:Bund|VKA))?|TV[-\s]?ÖD|TV[-\s]?AVH|TV[-\s]?N|TV[-\s]?V|TV[-\s]?Ärzte|ERA[-\s]?TV|ERA|IG\s+Metall|IG\s+BCE)\b",
)
_TARIFF_GENERIC = re.compile(r"\b(Tarifvertrag|tariflich\w*|Tarifbindung)\b", re.IGNORECASE)
_TARIFF_GROUP = re.compile(r"\b(?:E|EG|Entgeltgruppe|Entgeltstufe)\s?(\d{1,2}[a-z]?)\b")


def _to_number(s: str) -> float | None:
    s = s.strip().replace(" ", "")
    mult = 1.0
    if s.lower().endswith("k"):
        mult = 1000.0
        s = s[:-1]
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+(?:,\d{2})?", s):
        if s.count(",") == 1 and s.endswith(tuple(f",{d:02d}" for d in range(100))) and "." in s:
            s = s.rsplit(",", 1)[0]
        s = s.replace(".", "").replace(",", "")
    elif re.fullmatch(r"\d+,\d{1,2}", s):
        s = s.replace(",", ".")
    try:
        return float(s) * mult
    except ValueError:
        return None


def _period(context: str, amount: float) -> str:
    c = context.lower()
    if re.search(r"monat|month|mtl|/m\b|p\.m\.", c):
        return "month"
    if re.search(r"stunde|hour|/h\b|std\.", c):
        return "hour"
    if re.search(r"jahr|year|annual|p\.a\.|jährlich", c):
        return "year"
    if amount >= 15000:
        return "year"
    if amount >= 1000:
        return "month"
    return "hour"


def detect_salary(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    for pat in (_SALARY_RANGE, _SALARY_RANGE_PREFIX):
        m = pat.search(text)
        if m:
            lo, hi = _to_number(m.group(1)), _to_number(m.group(2))
            if lo and hi and hi >= lo and hi < 10 * lo:
                ctx = text[max(0, m.start() - 40): m.end() + 40]
                return {"min": lo, "max": hi, "currency": "EUR", "period": _period(ctx, hi),
                        "text": m.group(0).strip(), "source": "description"}
    m = _SALARY_SINGLE.search(text)
    if m:
        val = _to_number(m.group(1) or m.group(2) or "")
        if val and val >= 10:
            ctx = text[max(0, m.start() - 40): m.end() + 40]
            if re.search(r"gehalt|vergütung|salary|brutto|gross|compensation|verdienst|lohn|pay", ctx, _F):
                return {"min": val, "max": None, "currency": "EUR", "period": _period(ctx, val),
                        "text": m.group(0).strip(), "source": "description"}
    return None


def detect_tariff(text: str) -> str | None:
    if not text:
        return None
    m = _TARIFF.search(text)
    if not m:
        return "Tarifvertrag" if _TARIFF_GENERIC.search(text) else None
    name = re.sub(r"\s+", " ", m.group(1)).replace("TV L", "TV-L").replace("TVL", "TV-L")
    window = text[max(0, m.start() - 80): m.end() + 80]
    g = _TARIFF_GROUP.search(window)
    return f"{name} E{g.group(1)}" if g else name


_AGENCY_TEXT = re.compile(
    r"personalvermittlung|personaldienstleist|arbeitnehmerüberlassung|zeitarbeit|für\s+unseren\s+kunden"
    r"|im\s+auftrag\s+unseres\s+(?:kunden|mandanten)|unser\s+(?:kunde|mandant)\b|our\s+client\b"
    r"|on\s+behalf\s+of\s+(?:our|a)\s+client|recruitment\s+agency|headhunter|executive\s+search",
    _F,
)
_AGENCY_NAMES = re.compile(
    r"\b(?:hays|randstad|adecco|manpower|brunel|ferchau|amadeus\s+fire|michael\s+page|page\s+personnel"
    r"|robert\s+half|orizon|persona\s+service|dis\s+ag|gulp|etengo|jobot|kelly\s+services|allgeier\s+experts"
    r"|experis|people\s+partner|avantgarde\s+experts|bindan|i\.k\.\s+hofmann|tempton|piening)\b",
    _F,
)


def detect_agency(company: str, text: str) -> bool:
    return bool(_AGENCY_NAMES.search(company or "") or _AGENCY_TEXT.search((text or "")[:5000]))


# ---------------------------------------------------------------------------
# All together
# ---------------------------------------------------------------------------


def detect_all(
    *, title: str, company: str, location: str, text: str, raw_employment: str = "",
    raw_remote: bool | None = None, raw_level: str = "", profile: Profile | None = None,
) -> dict[str, Any]:
    full = f"{title}\n{text}"
    flags: dict[str, Any] = {}
    flags.update(detect_german(full))
    flags.update(detect_clearance(full))
    flags["employment_type"] = detect_employment_type(title, text, raw_employment)
    flags["seniority"] = detect_seniority(title, text, raw_level)
    flags["years_required"] = detect_years_required(text)
    flags["remote"] = detect_remote(title, location, text, raw_remote)
    flags["tariff"] = detect_tariff(text)
    flags["agency"] = detect_agency(company, text)
    if profile is not None:
        req = flags.get("german_level")
        gap = 0
        if req and not flags.get("german_optional"):
            gap = max(0, cefr_rank(req) - profile.german_rank())
        flags["german_gap"] = gap
        flags["citizenship_ok"] = citizenship_ok(flags.get("citizenship"), profile)
    return flags


def flag_labels(flags: dict[str, Any], profile_german: str = "") -> list[tuple[str, str]]:
    """Human-readable badges (label, severity) for the UI and notifications."""
    out: list[tuple[str, str]] = []
    if flags.get("injection"):
        out.append((t("Şüpheli gizli metin / AI talimatı"), "bad"))
    lv = flags.get("german_level")
    if lv:
        if flags.get("german_optional"):
            out.append((t("Almanca {lv} (artı)", lv=lv), "info"))
        else:
            gap = flags.get("german_gap") or 0
            sev = "bad" if gap >= 2 else ("warn" if gap == 1 else "ok")
            out.append((t("Almanca {lv} (sen {you})", lv=lv, you=profile_german) if profile_german and gap
                        else t("Almanca {lv}", lv=lv), sev))
    if flags.get("clearance"):
        lbl = (t("Güvenlik soruşturması {level}", level=flags["clearance"]) if flags["clearance"] != "yes"
               else t("Güvenlik soruşturması"))
        out.append((lbl, "warn"))
    if flags.get("citizenship"):
        ok = flags.get("citizenship_ok")
        sev = "bad" if ok is False else ("ok" if ok else "warn")
        out.append((t("Vatandaşlık: {value}", value=flags["citizenship"]), sev))
    et = flags.get("employment_type")
    if et and et != "fulltime":
        names = {"werkstudent": "Werkstudent", "thesis": "Abschlussarbeit", "internship": "Praktikum",
                 "trainee": "Trainee", "apprenticeship": "Ausbildung", "freelance": "Freelance",
                 "parttime": "Teilzeit", "contract": "Befristet/Contract"}
        out.append((t(names.get(et, et)), "info"))
    if flags.get("seniority") in ("senior", "lead"):
        out.append(("Senior" if flags["seniority"] == "senior" else t("Lead/Leitung"), "warn"))
    yrs = flags.get("years_required")
    if yrs and yrs >= 3:
        out.append((t("{yrs}+ yıl deneyim", yrs=yrs), "warn" if yrs >= 5 else "info"))
    if flags.get("remote") == "remote":
        out.append(("Remote", "ok"))
    elif flags.get("remote") == "hybrid":
        out.append((t("Hibrit"), "ok"))
    if flags.get("tariff"):
        out.append((flags["tariff"], "info"))
    if flags.get("agency"):
        out.append((t("Aracı firma"), "warn"))
    if flags.get("stale"):
        out.append((t("Eski/tekrar yayınlanmış ilan"), "warn"))
    return out
