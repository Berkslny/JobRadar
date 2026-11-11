"""Text helpers shared across the pipeline: HTML to text, language guess,
keyword matching, date parsing and slugs."""

from __future__ import annotations

import html as _html
import math
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from bs4 import BeautifulSoup, Comment

from jobradar.processing import guard

# ---------------------------------------------------------------------------
# HTML / whitespace
# ---------------------------------------------------------------------------

_BLOCK_TAGS = [
    "p", "div", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table",
    "section", "article", "header", "footer", "blockquote", "pre",
]


def clean_text(text: Any) -> str:
    """Unescape entities, normalise whitespace, keep paragraph breaks."""
    if text is None:
        return ""
    if isinstance(text, float) and math.isnan(text):
        return ""
    s = _html.unescape(str(text))
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\xa0", " ")
    s, smuggled = guard.strip_invisible(s)
    if smuggled and guard.MARKER not in s:
        s += f"\n{guard.MARKER}"
    lines = [re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank == 1 and out:
                out.append("")
            continue
        blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def html_to_text(raw: Any) -> str:
    """Convert (possibly entity-escaped) HTML into readable plain text."""
    if not raw:
        return ""
    s = str(raw)
    # Greenhouse returns HTML that is itself entity-escaped ("&lt;p&gt;").
    if "&lt;" in s and s.count("<") < s.count("&lt;"):
        s = _html.unescape(s)
    if "<" not in s:
        return clean_text(s)
    soup = BeautifulSoup(s, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    # Hidden elements: keep normal hidden content ("read more"), drop text aimed at AI systems.
    for tag in soup.find_all(guard.is_hidden):
        if tag.parent is None:
            continue
        hidden_text, smuggled = guard.strip_invisible(tag.get_text(" "))
        if guard.suspicious_phrases(hidden_text + " " + smuggled):
            tag.replace_with(f"\n{guard.MARKER}\n")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
        li.insert_after("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    return clean_text(soup.get_text())


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    nl = cut.rfind("\n")
    if nl > limit * 0.8:
        cut = cut[:nl]
    return cut + "\n[...]"


# ---------------------------------------------------------------------------
# Language guess (German vs English job postings)
# ---------------------------------------------------------------------------

_DE_WORDS = {
    "und", "der", "die", "das", "mit", "für", "wir", "sie", "ihre", "ihr", "eine",
    "einen", "bei", "auf", "oder", "zu", "von", "im", "ist", "sind", "werden",
    "kenntnisse", "erfahrung", "aufgaben", "profil", "bieten", "unser", "unsere",
    "deine", "dein", "du", "dich", "uns", "einer", "nicht", "auch", "als", "über",
}
_EN_WORDS = {
    "and", "the", "with", "for", "we", "you", "your", "our", "are", "is", "will",
    "of", "to", "in", "experience", "skills", "requirements", "responsibilities",
    "team", "work", "about", "what", "offer", "this", "that", "be", "as", "on",
}


def detect_language(text: str) -> str:
    """Return 'de', 'en' or '' when undecided."""
    words = re.findall(r"[a-zäöüß]+", (text or "").lower()[:8000])
    de = sum(1 for w in words if w in _DE_WORDS)
    en = sum(1 for w in words if w in _EN_WORDS)
    if de + en < 4:
        return ""
    return "de" if de > en * 1.1 else "en"


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------


def compile_keyword(keyword: str) -> re.Pattern[str]:
    """Compile a config keyword.

    * ``=word``  -> whole-word match only.
    * keywords with 5+ characters match as substrings, so German compounds
      work ("entwickler" finds "Hardwareentwickler").
    * shorter keywords (FPGA, ESG, C++) need word boundaries.
    """
    k = keyword.strip()
    exact = k.startswith("=")
    if exact:
        k = k[1:].strip()
    esc = re.escape(k)
    if not exact and len(k) >= 5:
        return re.compile(esc, re.IGNORECASE)
    return re.compile(rf"(?<![\w+#]){esc}(?![\w+#])", re.IGNORECASE)


class KeywordSet:
    """A list of keywords compiled once and matched many times."""

    def __init__(self, keywords: Iterable[str]):
        self.items: list[tuple[str, re.Pattern[str]]] = []
        seen: set[str] = set()
        for kw in keywords or []:
            if not kw or not str(kw).strip():
                continue
            key = str(kw).strip().lower()
            if key in seen:
                continue
            seen.add(key)
            self.items.append((str(kw).strip().lstrip("="), compile_keyword(str(kw))))

    def find(self, text: str) -> list[str]:
        if not text:
            return []
        return [k for k, p in self.items if p.search(text)]

    def any(self, text: str) -> bool:
        if not text:
            return False
        return any(p.search(text) for _, p in self.items)

    def __len__(self) -> int:
        return len(self.items)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def today() -> date:
    return datetime.now().date()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_iso() -> str:
    return today().isoformat()


def parse_date(value: Any) -> str | None:
    """Parse many date shapes into 'YYYY-MM-DD' (or None)."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # pandas Timestamp and similar
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().date().isoformat()
        except Exception:  # pragma: no cover - defensive
            return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v <= 0:
            return None
        if v > 1e11:  # epoch milliseconds
            v /= 1000.0
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "null", "nat"}:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    if re.fullmatch(r"\d{10,13}", s):
        return parse_date(int(s))
    rel = parse_relative_posted(s)
    if rel:
        return rel
    return None


_REL_UNITS = {
    "minute": 0, "minuten": 0, "hour": 0, "hours": 0, "stunde": 0, "stunden": 0,
    "day": 1, "days": 1, "tag": 1, "tage": 1, "tagen": 1,
    "week": 7, "weeks": 7, "woche": 7, "wochen": 7,
    "month": 30, "months": 30, "monat": 30, "monate": 30, "monaten": 30,
}


def parse_relative_posted(text: str, ref: date | None = None) -> str | None:
    """Parse 'Posted 3 Days Ago', 'vor 2 Tagen', 'Heute', '30+ Days Ago'..."""
    ref = ref or today()
    s = (text or "").strip().lower()
    if not s:
        return None
    if re.search(r"\b(today|heute|just posted|gerade|soeben)\b", s):
        return ref.isoformat()
    if re.search(r"\b(yesterday|gestern)\b", s):
        return (ref - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\s*\+?\s*([a-zäöü]+)", s)
    if m:
        unit = m.group(2)
        factor = _REL_UNITS.get(unit)
        if factor is None:
            for key, val in _REL_UNITS.items():
                if unit.startswith(key):
                    factor = val
                    break
        if factor is not None:
            return (ref - timedelta(days=int(m.group(1)) * factor)).isoformat()
    return None


def days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return None
    return (today() - d).days


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def fold_umlauts(s: str) -> str:
    return (s or "").translate(_UMLAUTS)


def slugify(text: str, max_len: int = 40) -> str:
    s = fold_umlauts(text or "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return (s[:max_len].rstrip("-")) or "x"


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() in {"", "nan", "None", "NaT"}
