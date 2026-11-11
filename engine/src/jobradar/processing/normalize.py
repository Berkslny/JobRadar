"""Normalisation of titles, companies and URLs for cross-source dedup."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from jobradar.textutil import fold_umlauts

# --- titles --------------------------------------------------------------------

# "(m/w/d)", "(w/m/d)", "(m/f/d)", "(all genders)", "[m|w|d]", "(gn)", "(m/w/div)" ...
_GENDER_TOKEN = r"(?:m|w|d|f|x|i|v|div|divers|diverse|gn|nb|all\s*genders?|alle\s*geschlechter|gender\s*neutral)"
GENDER_RE = re.compile(
    rf"\s*[\(\[]\s*{_GENDER_TOKEN}(?:\s*[/|,.*\s-]\s*{_GENDER_TOKEN})*\s*\*?\s*[\)\]]",
    re.IGNORECASE,
)
TRAILING_GENDER_RE = re.compile(r"\s*[-–|,]?\s*\b[mwf]\s*/\s*[wmf]\s*/\s*[dxi]\b\s*$", re.IGNORECASE)
GENDER_SUFFIX_RE = re.compile(r"(\w)(?:\*|:|_|/-?)in(?:nen)?\b", re.IGNORECASE)


def clean_title(title: str) -> str:
    """Title for display: gender markers removed, whitespace tidied."""
    t = GENDER_RE.sub("", title or "")
    t = TRAILING_GENDER_RE.sub("", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    return t.strip(" -–|,")


def normalize_title(title: str) -> str:
    """Comparison key for titles (lowercase, no gender markers, no punctuation)."""
    t = (title or "").lower()
    t = GENDER_RE.sub(" ", t)
    t = TRAILING_GENDER_RE.sub(" ", t)
    t = GENDER_SUFFIX_RE.sub(r"\1", t)
    t = fold_umlauts(t)
    t = re.sub(r"[–—-]", " ", t)
    t = re.sub(r"[^\w\s+#]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# --- companies -----------------------------------------------------------------

_LEGAL = re.compile(
    r"\b(?:gmbh\s*&\s*co\.?\s*kgaa|gmbh\s*&\s*co\.?\s*kg|gmbh|ggmbh|mbh|ag|se|kgaa|kg|ohg|ug"
    r"|e\.\s?v\.|ev|inc|ltd|llc|plc|corp|corporation|co|company|holding|group|gruppe"
    r"|b\.\s?v\.|bv|s\.\s?a\.|sa|sas|srl|nv|limited|deutschland|germany)\b\.?",
    re.IGNORECASE,
)


def normalize_company(name: str) -> str:
    c = fold_umlauts((name or "").lower())
    c = c.replace("&", " & ")
    c = _LEGAL.sub(" ", c)
    c = re.sub(r"[^\w\s]", " ", c)
    c = re.sub(r"\s+", " ", c).strip()
    return c


# --- URLs ----------------------------------------------------------------------

_TRACKING_PARAMS = {
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "trk", "trkinfo", "trackingid", "refid",
    "ref", "referrer", "src", "source", "campaign", "cmp", "from", "origin", "lipi", "midtoken",
    "midsig", "eid", "otptoken", "alertaction", "savedsearchid", "position", "pagenum",
    "currentjobid", "geoid", "keywords", "location", "vjs", "tk", "advn", "adid", "sjdu",
    "acatk", "pub", "camk", "xkcb", "xpse", "from_page", "jobsearchid", "searchid",
}
_AGGREGATOR_HOSTS = (
    "linkedin.com", "indeed.", "glassdoor.", "stepstone.", "xing.com", "arbeitsagentur.de",
    "monster.", "ziprecruiter.", "google.com", "freehire.me", "kimeta.", "jobware.", "stellenanzeigen.de",
)


def is_aggregator(url: str) -> bool:
    host = urlsplit(url or "").netloc.lower()
    return any(h in host for h in _AGGREGATOR_HOSTS)


def canonical_url(url: str) -> tuple[str, str]:
    """Return (display_url, url_key).

    display_url keeps the path's case (some ATS WAFs reject lowercased paths);
    url_key is an order-independent identity used for dedup.
    """
    raw = (url or "").strip()
    if not raw:
        return "", ""
    if raw.startswith("//"):
        raw = "https:" + raw
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.IGNORECASE):
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return url, url
    host = parts.netloc.lower()
    if host.startswith("www."):
        host_key = host[4:]
    else:
        host_key = host
    path = parts.path or "/"
    query = dict(parse_qsl(parts.query, keep_blank_values=False))
    q_lower = {k.lower(): v for k, v in query.items()}

    # LinkedIn: /jobs/view/<id>, /comm/jobs/view/<id>, ?currentJobId=<id>
    if "linkedin.com" in host:
        m = re.search(r"/jobs/view/(?:[^/?#]*?-)?(\d{6,})", path)
        jid = m.group(1) if m else q_lower.get("currentjobid", "")
        if jid and jid.isdigit():
            clean = f"https://www.linkedin.com/jobs/view/{jid}"
            return clean, f"linkedin:{jid}"
    # Indeed: identity is the jk parameter
    if "indeed." in host:
        jk = q_lower.get("jk") or q_lower.get("vjk")
        if jk:
            return f"https://{host}/viewjob?jk={jk}", f"indeed:{jk.lower()}"
    # StepStone: ...--<id>-inline.html or /job/<id>
    if "stepstone." in host:
        m = re.search(r"-(\d{5,})(?:-inline)?\.html", path) or re.search(r"/(\d{6,})(?:/|$)", path)
        if m:
            return urlunsplit(("https", host, path, "", "")), f"stepstone:{m.group(1)}"
    # XING: /jobs/<slug>-<id>
    if "xing.com" in host:
        m = re.search(r"/jobs/(?:[^/]*?-)?(\d{5,})", path)
        if m:
            return urlunsplit(("https", host, path, "", "")), f"xing:{m.group(1)}"
    # Arbeitsagentur detail page
    if "arbeitsagentur.de" in host and "/jobdetail/" in path:
        ref = unquote(unquote(path.split("/jobdetail/", 1)[1])).strip("/")
        if ref:
            enc = quote(ref, safe="").replace("%2F", "%252F")
            return f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{enc}", f"aa:{ref}"
    # Glassdoor
    if "glassdoor." in host:
        jl = q_lower.get("jl") or q_lower.get("joblistingid")
        if jl:
            return urlunsplit(("https", host, path, f"jl={jl}", "")), f"glassdoor:{jl}"

    # Generic: drop tracking params, apply/thanks suffixes and fragments.
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
            if not (k.lower().startswith("utm_") or k.lower() in _TRACKING_PARAMS)]
    path_clean = re.sub(r"/(apply|application|thanks|thank-you)/?$", "", path, flags=re.IGNORECASE)
    if len(path_clean) > 1:
        path_clean = path_clean.rstrip("/")
    display = urlunsplit(("https", host, path_clean or "/", urlencode(kept), ""))
    key_query = urlencode(sorted((k.lower(), v) for k, v in kept))
    key = f"{host_key}{path_clean.lower()}" + (f"?{key_query}" if key_query else "")
    return display, key
