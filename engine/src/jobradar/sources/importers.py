"""Manual inputs and detail enrichment.

* add a posting from any URL (schema.org JobPosting JSON-LD, LinkedIn guest
  page, Arbeitsagentur detail) - this covers StepStone, XING and career pages
  that no API reaches;
* parse job-alert e-mails (LinkedIn, StepStone, Indeed, XING, Glassdoor,
  Arbeitsagentur) pasted as text or saved as .eml (career-ops idea, extended);
* fetch the description of postings that arrived without one.
"""

from __future__ import annotations

import email
import email.policy
import json
import re
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
from bs4 import BeautifulSoup

from jobradar.http import HTTPStatusError, get_text
from jobradar.models import RawJob
from jobradar.processing.normalize import canonical_url
from jobradar.sources import arbeitsagentur
from jobradar.sources.ats import fetch_smartrecruiters_detail, fetch_workday_detail
from jobradar.sources.base import SourceError
from jobradar.i18n import t
from jobradar.textutil import clean_text, html_to_text, parse_date, parse_relative_posted

# ---------------------------------------------------------------------------
# JSON-LD JobPosting
# ---------------------------------------------------------------------------


def _iter_jsonld(obj: Any):
    if isinstance(obj, list):
        for x in obj:
            yield from _iter_jsonld(x)
    elif isinstance(obj, dict):
        yield obj
        if "@graph" in obj:
            yield from _iter_jsonld(obj["@graph"])


def _is_jobposting(obj: dict[str, Any]) -> bool:
    t = obj.get("@type")
    if isinstance(t, list):
        return any(str(x).lower() == "jobposting" for x in t)
    return str(t or "").lower() == "jobposting"


def _jsonld_location(loc: Any) -> str:
    places = []
    for item in loc if isinstance(loc, list) else [loc]:
        if not isinstance(item, dict):
            continue
        addr = item.get("address") or {}
        if isinstance(addr, str):
            places.append(addr)
            continue
        parts = [addr.get("addressLocality"), addr.get("addressRegion")]
        country = addr.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        city = ", ".join(str(p) for p in parts if p)
        if country and str(country).upper() not in ("DE", "DEU", "GERMANY", "DEUTSCHLAND"):
            city = f"{city}, {country}" if city else str(country)
        if city and city not in places:
            places.append(city)
    return " · ".join(places)


def parse_jsonld_jobposting(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html or "", "html.parser")
    for script in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:
                data = json.loads(re.sub(r"[\x00-\x1f]", " ", raw))
            except json.JSONDecodeError:
                continue
        for obj in _iter_jsonld(data):
            if not _is_jobposting(obj):
                continue
            org = obj.get("hiringOrganization") or {}
            company = org.get("name") if isinstance(org, dict) else str(org)
            salary = obj.get("baseSalary") or {}
            sal: dict[str, Any] = {}
            if isinstance(salary, dict):
                val = salary.get("value") or {}
                if isinstance(val, dict):
                    sal = {"min": val.get("minValue") or val.get("value"), "max": val.get("maxValue"),
                           "currency": salary.get("currency") or "EUR",
                           "period": str(val.get("unitText") or "").lower()}
            remote = None
            if str(obj.get("jobLocationType") or "").upper() == "TELECOMMUTE":
                remote = True
            et = obj.get("employmentType")
            if isinstance(et, list):
                et = et[0] if et else ""
            return {
                "title": clean_text(obj.get("title") or ""),
                "company": clean_text(company or ""),
                "location": _jsonld_location(obj.get("jobLocation")),
                "description": html_to_text(obj.get("description") or ""),
                "posted_at": parse_date(obj.get("datePosted")),
                "valid_through": parse_date(obj.get("validThrough")),
                "employment_type": str(et or ""),
                "remote": remote,
                "salary": sal if sal.get("min") else None,
            }
    return None


def _meta(soup: BeautifulSoup, prop: str) -> str:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return clean_text(tag.get("content")) if tag and tag.get("content") else ""


def parse_generic_page(html: str) -> dict[str, Any]:
    """Fallback when a page has no JSON-LD: title from og:title/h1, main text."""
    soup = BeautifulSoup(html or "", "html.parser")
    title = _meta(soup, "og:title") or (clean_text(soup.h1.get_text()) if soup.h1 else "") or (
        clean_text(soup.title.get_text()) if soup.title else "")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "svg"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = html_to_text(str(main))
    return {"title": title, "company": _meta(soup, "og:site_name"), "description": text[:20000]}


# ---------------------------------------------------------------------------
# LinkedIn guest page
# ---------------------------------------------------------------------------

LINKEDIN_GUEST = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


def parse_linkedin_guest(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    title_el = soup.select_one(".top-card-layout__title, .topcard__title, h1, h2")
    company_el = soup.select_one(".topcard__org-name-link") or next(
        (el for el in soup.select(".topcard__flavor") if "topcard__flavor--bullet" not in (el.get("class") or [])),
        None,
    )
    loc_el = soup.select_one(".topcard__flavor--bullet")
    desc_el = soup.select_one(".show-more-less-html__markup, .description__text")
    posted_el = soup.select_one(".posted-time-ago__text")
    text = soup.get_text(" ", strip=True).lower()
    closed = bool(soup.select_one(".closed-job")) or "no longer accepting applications" in text
    criteria = {}
    for item in soup.select(".description__job-criteria-item"):
        k = item.select_one(".description__job-criteria-subheader")
        v = item.select_one(".description__job-criteria-text")
        if k and v:
            criteria[clean_text(k.get_text())] = clean_text(v.get_text())
    return {
        "title": clean_text(title_el.get_text()) if title_el else "",
        "company": clean_text(company_el.get_text()) if company_el else "",
        "location": clean_text(loc_el.get_text()) if loc_el else "",
        "description": html_to_text(str(desc_el)) if desc_el else "",
        "posted_at": parse_relative_posted(posted_el.get_text()) if posted_el else None,
        "closed": closed,
        "employment_type": criteria.get("Employment type", ""),
        "seniority": criteria.get("Seniority level", ""),
    }


# ---------------------------------------------------------------------------
# URL import / detail fetch
# ---------------------------------------------------------------------------


def _source_for_host(host: str) -> str:
    for key, name in (("linkedin.", "linkedin"), ("stepstone.", "stepstone"), ("indeed.", "indeed"),
                      ("xing.", "xing"), ("glassdoor.", "glassdoor"), ("arbeitsagentur.", "arbeitsagentur")):
        if key in host:
            return name
    return "web"


def fetch_url_details(client: httpx.Client, url: str) -> dict[str, Any]:
    """Fetch a posting page and extract what we can. Raises SourceError."""
    display, key = canonical_url(url)
    if key.startswith("linkedin:"):
        jid = key.split(":", 1)[1]
        html = get_text(client, LINKEDIN_GUEST.format(id=jid))
        data = parse_linkedin_guest(html)
        if not data.get("title"):
            raise SourceError(t("LinkedIn sayfasından ilan okunamadı (giriş duvarı ya da hız sınırı)"))
        return data
    if key.startswith("aa:"):
        return arbeitsagentur.fetch_detail(client, key.split(":", 1)[1])
    try:
        html = get_text(client, display or url, headers={"Accept": "text/html,application/xhtml+xml"})
    except HTTPStatusError as exc:
        raise SourceError(t("sayfa açılamadı: HTTP {status}", status=exc.status)) from exc
    data = parse_jsonld_jobposting(html)
    if data and data.get("title"):
        return data
    data = parse_generic_page(html)
    if not data.get("title"):
        raise SourceError(t("sayfada ilan bilgisi bulunamadı"))
    return data


def raw_from_url(client: httpx.Client, url: str) -> RawJob:
    data = fetch_url_details(client, url)
    host = urlsplit(url).netloc.lower()
    raw = RawJob(
        source=f"manual:{_source_for_host(host)}",
        title=data.get("title") or "",
        company=data.get("company") or "",
        location=data.get("location") or "",
        url=url,
        description=data.get("description") or "",
        posted_at=data.get("posted_at"),
        employment_type=data.get("employment_type") or "",
        remote=data.get("remote"),
    )
    sal = data.get("salary")
    if sal:
        raw.salary_min, raw.salary_max = sal.get("min"), sal.get("max")
        raw.salary_currency, raw.salary_period = sal.get("currency") or "EUR", sal.get("period") or ""
    if data.get("closed"):
        raw.extra["closed"] = True
    return raw


def fetch_job_details(client: httpx.Client, job: dict[str, Any]) -> dict[str, Any]:
    """Description (and missing fields) for a stored job, using its detail_ref."""
    ref = job.get("detail_ref") or ""
    if ref.startswith("aa:"):
        return arbeitsagentur.fetch_detail(client, ref[3:])
    if ref.startswith("sr:"):
        _, slug, jid = ref.split(":", 2)
        return fetch_smartrecruiters_detail(client, slug, jid)
    if ref.startswith("wd:"):
        return fetch_workday_detail(client, ref[3:])
    url = ref[4:] if ref.startswith("url:") else (job.get("url") or "")
    if not url:
        raise SourceError("ilan adresi yok")
    return fetch_url_details(client, url)


# ---------------------------------------------------------------------------
# Job alert e-mails
# ---------------------------------------------------------------------------

_JOB_URL_PATTERNS = [
    ("linkedin", re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?\s\"']*?-)?\d{6,}", re.I)),
    ("stepstone", re.compile(r"stepstone\.[a-z.]+/(?:stellenangebote--[^\s\"'?]+?-\d{5,}(?:-inline)?\.html|job/\d+)", re.I)),
    ("indeed", re.compile(r"indeed\.[a-z.]+/(?:rc/clk|viewjob|pagead/clk|m/viewjob)[^\s\"']*?[?&](?:jk|vjk)=[0-9a-f]+", re.I)),
    ("xing", re.compile(r"xing\.com/jobs/[^\s\"'?]*?\d{5,}", re.I)),
    ("glassdoor", re.compile(r"glassdoor\.[a-z.]+/[^\s\"']*?(?:jl|jobListingId)=\d+", re.I)),
    ("arbeitsagentur", re.compile(r"arbeitsagentur\.de/jobsuche/jobdetail/[^\s\"'?]+", re.I)),
]
_NOISE_TITLES = re.compile(
    r"^(?:view job|jetzt bewerben|apply now|apply|bewerben|mehr anzeigen|see all jobs|alle jobs|job ansehen|"
    r"details|zum job|stelle ansehen|unsubscribe|abmelden|einstellungen|settings|\d+ (?:neue )?jobs?.*)$",
    re.I,
)


def _unwrap_redirect(url: str) -> str:
    """Some alert links wrap the real URL in a query parameter."""
    m = re.search(r"[?&](?:url|u|redirect|target|dest)=([^&]+)", url, re.I)
    if m:
        inner = unquote(m.group(1))
        if inner.startswith("http"):
            return inner
    return url


def _classify(url: str) -> tuple[str, str] | None:
    u = _unwrap_redirect(url)
    for name, pat in _JOB_URL_PATTERNS:
        m = pat.search(u)
        if m:
            full = u if u.startswith("http") else "https://" + m.group(0)
            if not full.startswith("http"):
                full = "https://" + m.group(0)
            return name, full
    return None


def _email_bodies(content: str | bytes) -> tuple[str, str]:
    """Return (html, text) bodies of an .eml, or treat the input as raw text/html."""
    data = content.encode("utf-8", "ignore") if isinstance(content, str) else content
    head = data[:2000].decode("utf-8", "ignore")
    looks_like_eml = bool(re.search(r"^(?:From|Subject|Received|MIME-Version|Content-Type):", head, re.M | re.I))
    if looks_like_eml:
        msg = email.message_from_bytes(data, policy=email.policy.default)
        html_parts, text_parts = [], []
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.is_multipart():
                continue
            try:
                payload = part.get_content()
            except (LookupError, KeyError, ValueError):
                raw = part.get_payload(decode=True) or b""
                payload = raw.decode("utf-8", "ignore")
            if not isinstance(payload, str):
                continue
            if ctype == "text/html":
                html_parts.append(payload)
            elif ctype == "text/plain":
                text_parts.append(payload)
        return "\n".join(html_parts), "\n".join(text_parts)
    text = data.decode("utf-8", "ignore")
    if re.search(r"<a\s[^>]*href=", text, re.I):
        return text, ""
    return "", text


def parse_alert_email(content: str | bytes) -> list[RawJob]:
    html, text = _email_bodies(content)
    found: dict[str, RawJob] = {}

    def add(kind: str, url: str, title: str, company: str = "", location: str = "") -> None:
        display, key = canonical_url(url)
        if not key or key in found:
            if key in found and title and not found[key].title:
                found[key].title = title
            return
        found[key] = RawJob(source=f"alert:{kind}", title=title, company=company, location=location,
                            url=display, detail_ref=f"url:{display}")

    if html:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            cls = _classify(a["href"])
            if not cls:
                continue
            kind, url = cls
            title = clean_text(a.get_text(" "))
            if _NOISE_TITLES.match(title or "") or len(title) > 160:
                title = ""
            company = location = ""
            # Alert layouts usually put company and place in the next lines of the card.
            container = a.find_parent(["td", "div", "li", "table"])
            if container is not None and title:
                lines = [clean_text(x) for x in container.get_text("\n").split("\n")]
                lines = [l for l in lines if l and l != title]
                if lines:
                    first = re.split(r"\s+[·•|]\s+", lines[0])
                    company = first[0][:80] if first else ""
                    if len(first) > 1:
                        location = first[1][:80]
                    elif len(lines) > 1:
                        location = lines[1][:80]
            add(kind, url, title, company if not _NOISE_TITLES.match(company or "") else "", location)
    if text:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            for m in re.finditer(r"https?://[^\s<>\"']+", line):
                cls = _classify(m.group(0))
                if not cls:
                    continue
                kind, url = cls
                # The card above the link: lines back to the previous blank line / link.
                block: list[str] = []
                for back in range(1, 5):
                    if i - back < 0:
                        break
                    cand = clean_text(lines[i - back])
                    if not cand or cand.startswith("http") or "://" in cand:
                        break
                    if not _NOISE_TITLES.match(cand):
                        block.insert(0, cand[:160])
                title = block[0] if block else ""
                company = location = ""
                if len(block) >= 2:
                    parts = re.split(r"\s*[,·•|]\s*", block[1], maxsplit=1)
                    company = parts[0][:80]
                    location = parts[1][:80] if len(parts) > 1 else ""
                add(kind, url, title, company, location)
    for raw in found.values():
        if not raw.title:
            # Last resort: words from the URL slug (LinkedIn/StepStone slugs carry the title).
            path = urlsplit(raw.url).path
            slug = re.sub(r"[-_]\d{5,}.*$", "", path.rsplit("/", 1)[-1])
            slug = re.sub(r"^stellenangebote--", "", slug)
            raw.title = clean_text(re.sub(r"[-_]+", " ", unquote(slug))).title() or "(başlıksız ilan)"
    return list(found.values())
