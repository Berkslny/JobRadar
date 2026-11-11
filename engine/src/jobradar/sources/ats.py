"""Company career boards via their public ATS endpoints (zero tokens).

Endpoint shapes follow career-ops' providers (MIT) and the vendors' public
job-board APIs.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import httpx

from jobradar.config import CompanySource
from jobradar.http import HTTPStatusError, get_json, get_text, post_json
from jobradar.models import RawJob
from jobradar.sources.base import Source, SourceContext, SourceError, search_terms
from jobradar.textutil import clean_text, html_to_text, parse_date, parse_relative_posted

# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------


def parse_greenhouse(data: Any, company: str) -> list[RawJob]:
    out = []
    for j in (data or {}).get("jobs") or []:
        title = clean_text(j.get("title") or "")
        url = j.get("absolute_url") or ""
        if not title or not url:
            continue
        out.append(RawJob(
            source="greenhouse", title=title, company=company,
            location=clean_text((j.get("location") or {}).get("name") or ""),
            url=url, apply_url=url, external_id=str(j.get("id") or ""),
            description=j.get("content") or "", description_html=True,
            posted_at=parse_date(j.get("first_published") or j.get("updated_at")),
            needs_location_check=True,
        ))
    return out


def fetch_greenhouse(client: httpx.Client, c: CompanySource) -> list[RawJob]:
    data = get_json(client, f"https://boards-api.greenhouse.io/v1/boards/{c.slug}/jobs", params={"content": "true"})
    return parse_greenhouse(data, c.name)


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------


def parse_lever(data: Any, company: str) -> list[RawJob]:
    out = []
    for j in data or []:
        if not isinstance(j, dict):
            continue
        title = clean_text(j.get("text") or "")
        url = j.get("hostedUrl") or ""
        if not title or not url:
            continue
        cats = j.get("categories") or {}
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description") or "")]
        for lst in j.get("lists") or []:
            parts.append(clean_text(lst.get("text") or ""))
            parts.append(html_to_text(lst.get("content") or ""))
        parts.append(j.get("additionalPlain") or html_to_text(j.get("additional") or ""))
        locs = cats.get("allLocations") or ([cats.get("location")] if cats.get("location") else [])
        out.append(RawJob(
            source="lever", title=title, company=company,
            location=" · ".join(str(x) for x in locs if x),
            url=url, apply_url=j.get("applyUrl") or url, external_id=str(j.get("id") or ""),
            description="\n\n".join(p for p in parts if p), description_html=False,
            posted_at=parse_date(j.get("createdAt")),
            employment_type=str(cats.get("commitment") or ""),
            remote=True if j.get("workplaceType") == "remote" else None,
            needs_location_check=True,
        ))
    return out


def fetch_lever(client: httpx.Client, c: CompanySource, eu: bool = False) -> list[RawJob]:
    host = "api.eu.lever.co" if eu else "api.lever.co"
    data = get_json(client, f"https://{host}/v0/postings/{c.slug}", params={"mode": "json"})
    return parse_lever(data, c.name)


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------


def parse_ashby(data: Any, company: str) -> list[RawJob]:
    out = []
    for j in (data or {}).get("jobs") or []:
        if j.get("isListed") is False:
            continue
        title = clean_text(j.get("title") or "")
        url = j.get("jobUrl") or ""
        if not title or not url:
            continue
        locs = [j.get("location") or ""]
        for sec in j.get("secondaryLocations") or []:
            if isinstance(sec, dict) and sec.get("location"):
                locs.append(sec["location"])
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        desc = j.get("descriptionPlain") or ""
        html = False
        if not desc:
            desc = j.get("descriptionHtml") or ""
            html = True
        raw = RawJob(
            source="ashby", title=title, company=company,
            location=" · ".join(x for x in locs if x),
            url=url, apply_url=j.get("applyUrl") or url, external_id=str(j.get("id") or ""),
            description=desc, description_html=html,
            posted_at=parse_date(j.get("publishedAt")),
            employment_type=str(j.get("employmentType") or ""),
            remote=True if j.get("isRemote") or j.get("workplaceType") == "Remote" else None,
            needs_location_check=True,
        )
        if comp:
            raw.extra["salary_text"] = comp
        out.append(raw)
    return out


def fetch_ashby(client: httpx.Client, c: CompanySource) -> list[RawJob]:
    data = get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{c.slug}",
                    params={"includeCompensation": "true"})
    return parse_ashby(data, c.name)


# ---------------------------------------------------------------------------
# Personio (XML feed, fallback: careers page payload)
# ---------------------------------------------------------------------------


def personio_host(c: CompanySource) -> str:
    if c.url:
        host = urlsplit(c.url).netloc.lower()
        if re.match(r"^[a-z0-9][a-z0-9-]*\.jobs\.personio\.(de|com)$", host):
            return host
    slug = (c.slug or "").strip().lower()
    if re.match(r"^[a-z0-9][a-z0-9-]*\.jobs\.personio\.(de|com)$", slug):
        return slug
    if re.match(r"^[a-z0-9][a-z0-9-]{0,62}$", slug):
        return f"{slug}.jobs.personio.de"
    raise SourceError(f"personio: '{c.name}' için slug ya da url geçersiz")


def parse_personio_xml(xml_text: str, company: str, host: str) -> list[RawJob]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for pos in root.iter("position"):
        pid = (pos.findtext("id") or "").strip()
        title = clean_text(pos.findtext("name") or "")
        if not pid or not title:
            continue
        offices = []
        for tag in ("office",):
            for el in pos.iter(tag):
                name = clean_text(el.text or "")
                if name and name not in offices:
                    offices.append(name)
        parts = []
        for jd in pos.iter("jobDescription"):
            name = clean_text(jd.findtext("name") or "")
            value = html_to_text(jd.findtext("value") or "")
            if value:
                parts.append(f"{name}\n{value}" if name else value)
        out.append(RawJob(
            source="personio", title=title, company=company,
            location=" · ".join(offices),
            url=f"https://{host}/job/{pid}", apply_url=f"https://{host}/job/{pid}", external_id=pid,
            description="\n\n".join(parts),
            posted_at=parse_date(pos.findtext("createdAt")),
            employment_type=clean_text(pos.findtext("schedule") or pos.findtext("employmentType") or ""),
            needs_location_check=True,
            extra={"seniority": clean_text(pos.findtext("seniority") or "")},
        ))
    return out


def _json_object_end(s: str, start: int) -> int:
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def parse_personio_listing(html: str, company: str, host: str) -> list[RawJob]:
    payload = ""
    for m in re.finditer(r"self\.__next_f\.push\((\[[\s\S]*?\])\)</script>", html or ""):
        try:
            chunk = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if chunk and chunk[0] == 1 and isinstance(chunk[1], str):
            payload += chunk[1]
    out: list[RawJob] = []
    seen: set[str] = set()
    pos = 0
    while True:
        start = payload.find('{"id":"', pos)
        if start == -1:
            break
        end = _json_object_end(payload, start)
        pos = start + 1
        if end == -1:
            continue
        try:
            obj = json.loads(payload[start:end])
        except json.JSONDecodeError:
            continue
        pid = str(obj.get("id") or "")
        if not pid.isdigit() or pid in seen or not isinstance(obj.get("name"), str):
            continue
        if not isinstance(obj.get("available_languages"), list):
            continue
        seen.add(pid)
        offices = [obj.get("main_office") or ""] + list(obj.get("additional_offices") or [])
        out.append(RawJob(
            source="personio", title=clean_text(obj["name"]), company=company,
            location=" · ".join(o for o in offices if o),
            url=f"https://{host}/job/{pid}", apply_url=f"https://{host}/job/{pid}", external_id=pid,
            posted_at=parse_date(obj.get("created_at")), needs_location_check=True,
            detail_ref=f"url:https://{host}/job/{pid}",
        ))
        pos = end
    return out


def fetch_personio(client: httpx.Client, c: CompanySource) -> list[RawJob]:
    host = personio_host(c)
    try:
        xml_text = get_text(client, f"https://{host}/xml")
        jobs = parse_personio_xml(xml_text, c.name, host)
        if jobs:
            return jobs
    except HTTPStatusError as exc:
        if exc.status not in (403, 404):
            raise
    html = get_text(client, f"https://{host}/")
    return parse_personio_listing(html, c.name, host)


# ---------------------------------------------------------------------------
# SmartRecruiters
# ---------------------------------------------------------------------------


def parse_smartrecruiters(data: Any, company: str, slug: str) -> list[RawJob]:
    out = []
    for j in (data or {}).get("content") or []:
        title = clean_text(j.get("name") or "")
        jid = str(j.get("id") or "")
        if not title or not jid:
            continue
        loc = j.get("location") or {}
        location = loc.get("fullLocation") or ", ".join(
            str(x) for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
        if loc.get("remote"):
            location = f"{location}, Remote" if location else "Remote"
        url = f"https://jobs.smartrecruiters.com/{slug}/{jid}"
        out.append(RawJob(
            source="smartrecruiters", title=title, company=company, location=location,
            url=url, apply_url=url, external_id=jid,
            posted_at=parse_date(j.get("releasedDate")),
            employment_type=str((j.get("typeOfEmployment") or {}).get("label") or ""),
            remote=True if loc.get("remote") else None,
            needs_location_check=True, detail_ref=f"sr:{slug}:{jid}",
            extra={"seniority": str((j.get("experienceLevel") or {}).get("label") or "")},
        ))
    return out


def fetch_smartrecruiters(client: httpx.Client, c: CompanySource) -> list[RawJob]:
    out: list[RawJob] = []
    for page in range(5):
        data = get_json(client, f"https://api.smartrecruiters.com/v1/companies/{c.slug}/postings",
                        params={"limit": 100, "offset": page * 100})
        batch = parse_smartrecruiters(data, c.name, c.slug)
        out += batch
        if len((data or {}).get("content") or []) < 100:
            break
    return out


def fetch_smartrecruiters_detail(client: httpx.Client, slug: str, jid: str) -> dict[str, Any]:
    data = get_json(client, f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}")
    sections = ((data or {}).get("jobAd") or {}).get("sections") or {}
    parts = []
    for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
        sec = sections.get(key) or {}
        text = html_to_text(sec.get("text") or "")
        if text:
            title = clean_text(sec.get("title") or "")
            parts.append(f"{title}\n{text}" if title else text)
    return {"description": "\n\n".join(parts)}


# ---------------------------------------------------------------------------
# Recruitee
# ---------------------------------------------------------------------------


def parse_recruitee(data: Any, company: str) -> list[RawJob]:
    out = []
    for j in (data or {}).get("offers") or []:
        title = clean_text(j.get("title") or "")
        url = j.get("careers_url") or j.get("url") or ""
        if not title or not url:
            continue
        names = [str(l.get("name") or "").strip() for l in (j.get("locations") or []) if isinstance(l, dict)]
        names = [n for n in names if n]
        location = " · ".join(dict.fromkeys(names)) if names else (j.get("location") or "")
        if j.get("country") and j.get("country") not in location:
            location = f"{location}, {j['country']}" if location else j["country"]
        desc = (j.get("description") or "") + "\n" + (j.get("requirements") or "")
        out.append(RawJob(
            source="recruitee", title=title, company=company, location=location,
            url=url, apply_url=j.get("careers_apply_url") or url, external_id=str(j.get("id") or ""),
            description=desc, description_html=True,
            posted_at=parse_date(j.get("published_at") or j.get("created_at")),
            employment_type=str(j.get("employment_type_code") or ""),
            remote=True if j.get("remote") else None, needs_location_check=True,
        ))
    return out


def fetch_recruitee(client: httpx.Client, c: CompanySource) -> list[RawJob]:
    host = urlsplit(c.url).netloc if c.url else f"{c.slug}.recruitee.com"
    data = get_json(client, f"https://{host}/api/offers/")
    return parse_recruitee(data, c.name)


# ---------------------------------------------------------------------------
# Workday
# ---------------------------------------------------------------------------


def workday_parts(url: str) -> tuple[str, str, str]:
    """careers URL -> (host, tenant, site)."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if not host.endswith("myworkdayjobs.com"):
        raise SourceError(f"workday: beklenmeyen adres {url}")
    tenant = host.split(".")[0]
    segs = [s for s in parts.path.split("/") if s]
    if segs and re.fullmatch(r"[a-z]{2}[-_][A-Za-z]{2}", segs[0]):
        segs = segs[1:]
    if not segs:
        raise SourceError(f"workday: site adı bulunamadı ({url})")
    return host, tenant, segs[0]


def parse_workday(data: Any, company: str, host: str, tenant: str, site: str) -> list[RawJob]:
    out = []
    for j in (data or {}).get("jobPostings") or []:
        title = clean_text(j.get("title") or "")
        path = j.get("externalPath") or ""
        if not title or not path:
            continue
        url = f"https://{host}/{site}{path}"
        bullet = j.get("bulletFields") or []
        out.append(RawJob(
            source="workday", title=title, company=company,
            location=clean_text(j.get("locationsText") or ""),
            url=url, apply_url=url, external_id=str(bullet[0]) if bullet else path,
            posted_at=parse_relative_posted(j.get("postedOn") or ""),
            needs_location_check=True,
            detail_ref=f"wd:{host}|{tenant}|{site}|{path}",
        ))
    return out


def fetch_workday(client: httpx.Client, c: CompanySource, terms: list[str]) -> list[RawJob]:
    host, tenant, site = workday_parts(c.url)
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    queries = [c.search] if c.search else (terms[:6] or [""])
    out: dict[str, RawJob] = {}
    for q in queries:
        for page in range(min(c.max_pages, 3)):
            payload = {"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": q}
            data = post_json(client, api, payload, headers={"Accept": "application/json"})
            batch = parse_workday(data, c.name, host, tenant, site)
            for r in batch:
                out.setdefault(r.url, r)
            if len((data or {}).get("jobPostings") or []) < 20:
                break
    return list(out.values())


def fetch_workday_detail(client: httpx.Client, ref: str) -> dict[str, Any]:
    host, tenant, site, path = ref.split("|", 3)
    data = get_json(client, f"https://{host}/wday/cxs/{tenant}/{site}{path}", headers={"Accept": "application/json"})
    info = (data or {}).get("jobPostingInfo") or {}
    out: dict[str, Any] = {"description": html_to_text(info.get("jobDescription") or "")}
    if info.get("location"):
        out["location"] = clean_text(info["location"])
    if info.get("timeType"):
        out["employment_type"] = clean_text(info["timeType"])
    posted = parse_relative_posted(info.get("postedOn") or "") or parse_date(info.get("startDate"))
    if posted:
        out["posted_at"] = posted
    return out


# ---------------------------------------------------------------------------
# Softgarden widget
# ---------------------------------------------------------------------------


def softgarden_widget_url(c: CompanySource) -> str:
    raw = c.url or (f"https://{c.slug}.softgarden.io/de/widgets/jobs" if c.slug else "")
    parts = urlsplit(raw)
    host = parts.netloc.lower()
    if not host.endswith("softgarden.io"):
        raise SourceError(f"softgarden: '{c.name}' için *.softgarden.io adresi gerekli")
    if re.search(r"/widgets/jobs/?$", parts.path):
        return f"https://{host}{parts.path.rstrip('/')}"
    m = re.match(r"^/([a-z]{2})(/|$)", parts.path)
    lang = m.group(1) if m else "de"
    return f"https://{host}/{lang}/widgets/jobs"


def parse_softgarden(html: str, company: str, widget_url: str) -> list[RawJob]:
    out: list[RawJob] = []
    seen: set[str] = set()
    for block in (html or "").split('<div class="matchElement" id="job_id_')[1:]:
        m_id = re.match(r"(\d+)\"", block)
        if not m_id or m_id.group(1) in seen:
            continue
        link = re.search(r'<a href="([^"]*/job/[^"]+)"[^>]*>([\s\S]*?)</a>', block)
        if not link:
            continue
        title = clean_text(re.sub(r"<[^>]+>", " ", link.group(2)))
        if not title:
            continue
        url = urljoin(widget_url, clean_text(link.group(1)))
        cities = []
        for cm in re.finditer(r'class="location-view-item"[^>]*>([\s\S]*?)</span>', block):
            city = clean_text(re.sub(r"<[^>]+>", " ", cm.group(1)))
            if city and city not in cities:
                cities.append(city)
        date_m = re.search(r'class="matchValue date"[^>]*>([\s\S]*?)</div>', block)
        posted = None
        if date_m:
            ds = clean_text(re.sub(r"<[^>]+>", " ", date_m.group(1)))
            mm = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", ds)
            posted = parse_date(f"{mm.group(2)}.{mm.group(1)}.{mm.group(3)}") if mm else parse_date(ds)
        seen.add(m_id.group(1))
        out.append(RawJob(
            source="softgarden", title=title, company=company, location=" / ".join(cities),
            url=url, apply_url=url, external_id=m_id.group(1), posted_at=posted,
            needs_location_check=True, detail_ref=f"url:{url}",
        ))
    return out


def fetch_softgarden(client: httpx.Client, c: CompanySource) -> list[RawJob]:
    widget = softgarden_widget_url(c)
    html = get_text(client, widget, headers={"Accept": "text/html"})
    return parse_softgarden(html, c.name, widget)


# ---------------------------------------------------------------------------
# Rheinmetall (server-rendered vacancy list)
# ---------------------------------------------------------------------------


def rheinmetall_list_url(c: CompanySource) -> str:
    raw = c.url or "https://www.rheinmetall.com/en/career/vacancies"
    parts = urlsplit(raw)
    host = parts.netloc.lower()
    if host == "rheinmetall.com":
        host = "www.rheinmetall.com"
    if not host.endswith("rheinmetall.com"):
        raise SourceError("rheinmetall: rheinmetall.com adresi gerekli")
    if re.search(r"/career/vacancies/?$", parts.path):
        return f"https://{host}{parts.path.rstrip('/')}"
    return f"https://{host}/en/career/vacancies"


def parse_rheinmetall(html: str, origin: str, company: str) -> list[RawJob]:
    out: list[RawJob] = []
    seen: set[str] = set()
    for block in (html or "").split('<div class="flex gap-0.5 group">')[1:]:
        link = re.search(r'href="(/[a-z]{2}/job/[^"]+/(\d+))"', block)
        if not link or link.group(2) in seen:
            continue
        title_m = re.search(r'md:text-xl[^"]*">([\s\S]*?)</div>', block)
        if title_m:
            title = clean_text(re.sub(r"<[^>]+>", " ", title_m.group(1)))
        else:
            slug = link.group(1).split("/")[3] if len(link.group(1).split("/")) > 3 else ""
            title = clean_text(slug.replace("_", " "))
        if not title:
            continue
        org_m = re.search(r'class="flex flex-wrap mr-6">([\s\S]*?)</div>', block)
        org = clean_text(re.sub(r"<[^>]+>", " ", org_m.group(1))) if org_m else ""
        city = org.split("|")[-1].strip() if "|" in org else ""
        seen.add(link.group(2))
        url = origin + link.group(1)
        out.append(RawJob(
            source="rheinmetall", title=title, company=company, location=city,
            url=url, apply_url=url, external_id=link.group(2), needs_location_check=bool(city),
            detail_ref=f"url:{url}", extra={"organisation": org},
        ))
    return out


def fetch_rheinmetall(client: httpx.Client, c: CompanySource, pause: float = 0.2) -> list[RawJob]:
    list_url = rheinmetall_list_url(c)
    origin = "https://" + urlsplit(list_url).netloc
    out: list[RawJob] = []
    seen: set[str] = set()
    stale_pages = 0
    for page in range(1, max(1, c.max_pages) + 1):
        if page > 1 and pause:
            time.sleep(pause)
        html = get_text(client, f"{list_url}?page={page}", headers={"Accept": "text/html"})
        rows = parse_rheinmetall(html, origin, c.name)
        if not rows:
            break  # past the last page
        fresh = [r for r in rows if r.external_id not in seen]
        # The list order is not stable between requests, so a page of repeats
        # does not mean the end; stop only after several in a row.
        stale_pages = 0 if fresh else stale_pages + 1
        if stale_pages >= 3:
            break
        for r in fresh:
            seen.add(r.external_id)
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Dispatcher + ATS detection
# ---------------------------------------------------------------------------


def fetch_company(client: httpx.Client, c: CompanySource, terms: list[str]) -> list[RawJob]:
    fetchers: dict[str, Callable[[], list[RawJob]]] = {
        "greenhouse": lambda: fetch_greenhouse(client, c),
        "lever": lambda: fetch_lever(client, c),
        "lever_eu": lambda: fetch_lever(client, c, eu=True),
        "ashby": lambda: fetch_ashby(client, c),
        "personio": lambda: fetch_personio(client, c),
        "smartrecruiters": lambda: fetch_smartrecruiters(client, c),
        "recruitee": lambda: fetch_recruitee(client, c),
        "workday": lambda: fetch_workday(client, c, terms),
        "softgarden": lambda: fetch_softgarden(client, c),
        "rheinmetall": lambda: fetch_rheinmetall(client, c),
    }
    jobs = fetchers[c.ats]()
    for j in jobs:
        j.source = f"{c.ats.replace('_eu', '')}:{c.name}"
    return jobs


class CompanyBoardsSource(Source):
    name = "companies"

    def fetch(self, ctx: SourceContext) -> list[RawJob]:
        companies = [c for c in ctx.config.sources.companies if c.enabled]
        terms = [t for t, _ in search_terms(ctx)]
        out: list[RawJob] = []
        errors: list[str] = []
        for ci, c in enumerate(companies):
            ctx.report(ci, len(companies), c.name)
            try:
                jobs = fetch_company(ctx.client, c, terms)
                ctx.log(f"  {c.name} ({c.ats}): {len(jobs)} ilan")
                out += jobs
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{c.name} ({c.ats}): {exc}")
        ctx.report(len(companies), len(companies))
        ctx.warnings.extend(errors)
        if companies and not out and errors:
            raise SourceError("; ".join(errors[:3]))
        return out


_DETECTORS: list[tuple[str, re.Pattern[str]]] = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)", re.I)),
    ("lever_eu", re.compile(r"jobs\.eu\.lever\.co/([a-z0-9_.-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.%-]+)", re.I)),
    ("personio", re.compile(r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([a-z0-9_-]+)", re.I)),
    ("recruitee", re.compile(r"([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("softgarden", re.compile(r"([a-z0-9-]+)\.softgarden\.io", re.I)),
    ("workday", re.compile(r"(https?://[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?[A-Za-z0-9_-]+)", re.I)),
    ("rheinmetall", re.compile(r"(rheinmetall\.com)", re.I)),
]


def detect_ats(text: str) -> list[dict[str, str]]:
    """Find ATS boards referenced in a URL or an HTML page."""
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ats, pat in _DETECTORS:
        for m in pat.finditer(text or ""):
            val = m.group(1)
            if ats in ("greenhouse", "lever", "lever_eu", "ashby", "smartrecruiters") and val.lower() in {
                "embed", "api", "v1", "jobs", "js", "static", "assets"}:
                continue
            key = (ats, val.lower())
            if key in seen:
                continue
            seen.add(key)
            entry = {"ats": ats}
            if ats == "workday":
                entry["url"] = val
            elif ats == "rheinmetall":
                entry["url"] = "https://www.rheinmetall.com/en/career/vacancies"
            elif ats == "softgarden":
                entry["url"] = f"https://{val}.softgarden.io/de/widgets/jobs"
            else:
                entry["slug"] = val
            found.append(entry)
    return found
