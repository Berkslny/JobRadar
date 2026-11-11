"""Render tailored documents: Markdown + print-ready HTML, PDF through
RenderCV (if installed) or a headless Chrome/Edge/Chromium."""

from __future__ import annotations

import html
import os
import platform
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

from jobradar.processing.normalize import clean_title
from jobradar.profile import Entry, Profile
from jobradar.tailor.validate import TailoredDocs

LABELS = {
    "de": {"profile": "Profil", "experience": "Berufserfahrung", "education": "Ausbildung", "projects": "Projekte",
           "skills": "Kenntnisse", "languages": "Sprachen", "present": "heute", "cv": "Lebenslauf",
           "letter": "Anschreiben", "answers": "Antworten auf Bewerbungsfragen", "attachments": "Anlagen",
           "attachments_list": "Lebenslauf, Zeugnisse"},
    "en": {"profile": "Profile", "experience": "Experience", "education": "Education", "projects": "Projects",
           "skills": "Skills", "languages": "Languages", "present": "Present", "cv": "CV",
           "letter": "Cover letter", "answers": "Application answers", "attachments": "Enclosures",
           "attachments_list": "CV, certificates"},
    "tr": {"profile": "Profil", "experience": "Deneyim", "education": "Eğitim", "projects": "Projeler",
           "skills": "Yetkinlikler", "languages": "Diller", "present": "Devam ediyor", "cv": "Özgeçmiş",
           "letter": "Ön yazı", "answers": "Başvuru sorularına cevaplar", "attachments": "Ekler",
           "attachments_list": "Özgeçmiş, belgeler"},
}
MONTHS_TR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım",
             "Aralık"]


def labels_for(lang: str) -> dict[str, str]:
    """Section labels of a document language; languages without their own set use the English ones."""
    return LABELS.get(lang) or LABELS["en"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
EXPERIENCE_KINDS = {"work", "internship", "werkstudent", "thesis", "volunteer"}


def _fmt_date(s: str, lang: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if s.lower() in ("present", "heute", "now", "aktuell", "today"):
        return labels_for(lang)["present"]
    parts = s.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[1]):02d}/{parts[0]}"
    return s


def _period(e: Entry, lang: str) -> str:
    a, b = _fmt_date(e.start, lang), _fmt_date(e.end, lang)
    if a and b:
        return f"{a} – {b}"
    return a or b


def _letter_date(lang: str, d: Optional[date] = None) -> str:
    d = d or date.today()
    if lang == "en":
        return f"{d.day} {MONTHS_EN[d.month - 1]} {d.year}"
    if lang == "tr":
        return f"{d.day} {MONTHS_TR[d.month - 1]} {d.year}"
    return d.strftime("%d.%m.%Y")


def _contact_line(p: Profile) -> list[str]:
    items = [x for x in (p.city, p.phone, p.email) if x]
    items += [v for v in p.links.values() if v]
    return items


def _sections(docs: TailoredDocs, profile: Profile) -> list[tuple[str, Entry, list[str]]]:
    out = []
    for block in docs.experience:
        e = profile.entry(block.entry_id)
        if e:
            out.append((e.kind, e, [b.text for b in block.bullets]))
    included = {e.id for _, e, _ in out}
    for e in profile.education:
        if e.id not in included:
            out.append((e.kind, e, []))
    return out


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def cv_markdown(docs: TailoredDocs, profile: Profile, lang: str) -> str:
    L = labels_for(lang)
    lines = [f"# {profile.name}", ""]
    if docs.headline:
        lines += [f"**{docs.headline}**", ""]
    lines += [" · ".join(_contact_line(profile)), ""]
    if docs.summary.text:
        lines += [f"## {L['profile']}", "", docs.summary.text, ""]
    secs = _sections(docs, profile)
    for kind_group, label in ((EXPERIENCE_KINDS, L["experience"]), ({"project"}, L["projects"]),
                              ({"education"}, L["education"])):
        items = [(e, bullets) for kind, e, bullets in secs if kind in kind_group]
        if not items:
            continue
        lines += [f"## {label}", ""]
        for e, bullets in items:
            lines.append(f"**{e.title}** – {e.organization}" + (f", {e.location}" if e.location else "")
                         + (f"  \n_{_period(e, lang)}_" if _period(e, lang) else ""))
            lines += [f"- {b}" for b in bullets]
            lines.append("")
    if docs.skills:
        lines += [f"## {L['skills']}", "", ", ".join(docs.skills), ""]
    if profile.languages:
        lines += [f"## {L['languages']}", "", ", ".join(f"{l.name} ({l.level})" for l in profile.languages), ""]
    return "\n".join(lines).strip() + "\n"


def letter_markdown(docs: TailoredDocs, profile: Profile, job: dict[str, Any], lang: str, city: str) -> str:
    L = labels_for(lang)
    letter = docs.cover_letter
    sender = [profile.name] + [x for x in (profile.address, profile.city, profile.phone, profile.email) if x]
    lines = ["  \n".join(sender), "", f"{job.get('company', '')}  \n{job.get('location', '')}", "",
             f"{city or profile.city}, {_letter_date(lang)}", "", f"**{letter.subject}**", "", letter.salutation, ""]
    for p in letter.paragraphs:
        lines += [p.text, ""]
    lines += [letter.closing, "", profile.name, "", f"{L['attachments']}: {L['attachments_list']}"]
    return "\n".join(lines).strip() + "\n"


def answers_markdown(docs: TailoredDocs, lang: str) -> str:
    lines = [f"# {labels_for(lang)['answers']}", ""]
    for a in docs.answers:
        lines += [f"**{a.question}**", "", a.answer, ""]
    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_CSS = """
@page { size: A4; margin: 16mm 17mm; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; color: #1d2329; font-size: 10.4pt;
       line-height: 1.42; margin: 0; }
.page { max-width: 176mm; margin: 0 auto; padding: 8mm 0; }
h1 { font-size: 22pt; margin: 0 0 2pt; letter-spacing: -0.3pt; }
.headline { font-size: 11.5pt; color: #34495e; margin: 0 0 4pt; }
.contact { font-size: 9.3pt; color: #4a5560; margin-bottom: 10pt; }
h2 { font-size: 11pt; text-transform: uppercase; letter-spacing: 0.8pt; color: #1f4e79;
     border-bottom: 1px solid #c9d3dc; padding-bottom: 2pt; margin: 13pt 0 6pt; }
.entry { margin-bottom: 7pt; page-break-inside: avoid; }
.entry-head { display: flex; justify-content: space-between; gap: 8pt; }
.entry-title { font-weight: 600; }
.entry-org { color: #34495e; }
.entry-date { color: #5d6b78; white-space: nowrap; font-size: 9.5pt; }
ul { margin: 2pt 0 0 14pt; padding: 0; }
li { margin: 1pt 0; }
.letter p { margin: 0 0 9pt; text-align: left; }
.sender { font-size: 9.3pt; color: #4a5560; margin-bottom: 16mm; }
.recipient { margin-bottom: 10mm; }
.date { text-align: right; margin-bottom: 8mm; }
.subject { font-weight: 700; margin-bottom: 7mm; }
.signature { margin-top: 10mm; }
.attachments { margin-top: 10mm; font-size: 9.3pt; color: #4a5560; }
"""


def _e(s: Any) -> str:
    return html.escape(str(s or ""))


def cv_html(docs: TailoredDocs, profile: Profile, lang: str) -> str:
    L = labels_for(lang)
    parts = [f"<!DOCTYPE html><html lang='{lang}'><head><meta charset='utf-8'><title>{_e(profile.name)} – {L['cv']}"
             f"</title><style>{_CSS}</style></head><body><div class='page'>",
             f"<h1>{_e(profile.name)}</h1>"]
    if docs.headline:
        parts.append(f"<div class='headline'>{_e(docs.headline)}</div>")
    parts.append(f"<div class='contact'>{' · '.join(_e(x) for x in _contact_line(profile))}</div>")
    if docs.summary.text:
        parts.append(f"<h2>{L['profile']}</h2><p>{_e(docs.summary.text)}</p>")
    secs = _sections(docs, profile)
    for kind_group, label in ((EXPERIENCE_KINDS, L["experience"]), ({"project"}, L["projects"]),
                              ({"education"}, L["education"])):
        items = [(e, b) for kind, e, b in secs if kind in kind_group]
        if not items:
            continue
        parts.append(f"<h2>{label}</h2>")
        for e, bullets in items:
            org = _e(e.organization) + (f", {_e(e.location)}" if e.location else "")
            parts.append(
                "<div class='entry'><div class='entry-head'><div><span class='entry-title'>"
                f"{_e(e.title)}</span> – <span class='entry-org'>{org}</span></div>"
                f"<div class='entry-date'>{_e(_period(e, lang))}</div></div>"
            )
            if bullets:
                parts.append("<ul>" + "".join(f"<li>{_e(b)}</li>" for b in bullets) + "</ul>")
            parts.append("</div>")
    if docs.skills:
        parts.append(f"<h2>{L['skills']}</h2><p>{_e(', '.join(docs.skills))}</p>")
    if profile.languages:
        langs = ", ".join(f"{l.name} ({l.level})" for l in profile.languages)
        parts.append(f"<h2>{L['languages']}</h2><p>{_e(langs)}</p>")
    parts.append("</div></body></html>")
    return "".join(parts)


def letter_html(docs: TailoredDocs, profile: Profile, job: dict[str, Any], lang: str, city: str) -> str:
    L = labels_for(lang)
    letter = docs.cover_letter
    sender = " · ".join(_e(x) for x in (profile.name, profile.address, profile.city, profile.phone, profile.email) if x)
    body = "".join(f"<p>{_e(p.text)}</p>" for p in letter.paragraphs)
    return (
        f"<!DOCTYPE html><html lang='{lang}'><head><meta charset='utf-8'><title>{L['letter']} – {_e(job.get('company'))}"
        f"</title><style>{_CSS}</style></head><body><div class='page letter'>"
        f"<div class='sender'>{sender}</div>"
        f"<div class='recipient'>{_e(job.get('company'))}<br>{_e(job.get('location'))}</div>"
        f"<div class='date'>{_e(city or profile.city)}, {_e(_letter_date(lang))}</div>"
        f"<div class='subject'>{_e(letter.subject)}</div>"
        f"<p>{_e(letter.salutation)}</p>{body}"
        f"<p class='signature'>{_e(letter.closing)}<br><br>{_e(profile.name)}</p>"
        f"<div class='attachments'>{L['attachments']}: {L['attachments_list']}</div>"
        "</div></body></html>"
    )


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

_CHROME_CANDIDATES = {
    "Darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
               "/Applications/Chromium.app/Contents/MacOS/Chromium",
               "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
               "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
               "/Applications/Arc.app/Contents/MacOS/Arc"],
    "Windows": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"],
}


def find_chrome(configured: str = "") -> Optional[str]:
    if configured and Path(configured).exists():
        return configured
    for p in _CHROME_CANDIDATES.get(platform.system(), []):
        for candidate in (Path(p), Path.home() / p.lstrip("/")):
            if candidate.exists():
                return str(candidate)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def html_to_pdf(html_path: Path, pdf_path: Path, chrome: str) -> bool:
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--print-to-pdf-no-header",
           f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.insert(1, "--no-sandbox")
    try:
        subprocess.run(cmd, capture_output=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return pdf_path.exists() and pdf_path.stat().st_size > 1000


def find_helper() -> Optional[str]:
    """A program that turns HTML into PDF without a browser: the JobRadar Mac app sets JOBRADAR_PDF_HELPER
    to itself (it renders with the system's WebKit). Called as: helper --html-to-pdf in.html out.pdf"""
    path = os.environ.get("JOBRADAR_PDF_HELPER", "").strip()
    return path if path and os.path.isfile(path) and os.access(path, os.X_OK) else None


def helper_to_pdf(html_path: Path, pdf_path: Path, helper: str) -> bool:
    try:
        proc = subprocess.run([helper, "--html-to-pdf", str(html_path), str(pdf_path)], capture_output=True,
                              timeout=90)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and pdf_path.exists() and pdf_path.stat().st_size > 1000


def rendercv_yaml(docs: TailoredDocs, profile: Profile, lang: str) -> dict[str, Any]:
    L = labels_for(lang)

    def rc_date(s: str) -> Optional[str]:
        s = (s or "").strip()
        if not s:
            return None
        if s.lower() in ("present", "heute", "now", "aktuell"):
            return "present"
        return s

    sections: dict[str, list[Any]] = {}
    if docs.summary.text:
        sections[L["profile"]] = [docs.summary.text]
    for kind, e, bullets in _sections(docs, profile):
        if kind == "education":
            item = {"institution": e.organization, "area": e.title, "location": e.location or None,
                    "start_date": rc_date(e.start), "end_date": rc_date(e.end), "highlights": bullets or None}
            sections.setdefault(L["education"], []).append({k: v for k, v in item.items() if v})
        elif kind == "project":
            item = {"name": e.title, "start_date": rc_date(e.start), "end_date": rc_date(e.end),
                    "highlights": bullets or None}
            sections.setdefault(L["projects"], []).append({k: v for k, v in item.items() if v})
        else:
            item = {"company": e.organization, "position": e.title, "location": e.location or None,
                    "start_date": rc_date(e.start), "end_date": rc_date(e.end), "highlights": bullets or None}
            sections.setdefault(L["experience"], []).append({k: v for k, v in item.items() if v})
    if docs.skills:
        sections[L["skills"]] = [{"label": L["skills"], "details": ", ".join(docs.skills)}]
    if profile.languages:
        sections[L["languages"]] = [{"label": L["languages"],
                                     "details": ", ".join(f"{l.name} ({l.level})" for l in profile.languages)}]
    cv: dict[str, Any] = {"name": profile.name, "location": profile.city or None, "email": profile.email or None,
                          "phone": profile.phone or None, "headline": docs.headline or None, "sections": sections}
    cv = {k: v for k, v in cv.items() if v}
    return {
        "cv": cv,
        "design": {"theme": "engineeringresumes"},
        "locale": {"language": "german" if lang == "de" else "english"},
        "settings": {"render_command": {"output_folder": ".", "dont_generate_png": True,
                                        "dont_generate_html": True, "dont_generate_markdown": True}},
    }


def render_with_rendercv(docs: TailoredDocs, profile: Profile, lang: str, folder: Path) -> Optional[Path]:
    exe = shutil.which("rendercv")
    if not exe:
        return None
    yml = folder / "cv_rendercv.yaml"
    yml.write_text(yaml.safe_dump(rendercv_yaml(docs, profile, lang), allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    try:
        subprocess.run([exe, "render", str(yml.name)], cwd=str(folder), capture_output=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    pdfs = sorted(folder.glob("*_CV.pdf"))
    if pdfs:
        target = folder / "cv.pdf"
        pdfs[0].replace(target)
        return target
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def write_documents(docs: TailoredDocs, profile: Profile, job: dict[str, Any], lang: str, folder: Path, *,
                    pdf_engine: str = "auto", chrome_path: str = "", sender_city: str = "") -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    letter_name = {"de": "anschreiben", "tr": "on_yazi"}.get(lang, "cover_letter")
    files: dict[str, str] = {
        "cv.md": cv_markdown(docs, profile, lang),
        "cv.html": cv_html(docs, profile, lang),
        f"{letter_name}.md": letter_markdown(docs, profile, job, lang, sender_city),
        f"{letter_name}.html": letter_html(docs, profile, job, lang, sender_city),
        "answers.md": answers_markdown(docs, lang),
    }
    for name, content in files.items():
        (folder / name).write_text(content, encoding="utf-8")
    written = list(files)
    if pdf_engine == "none":
        return written
    cv_pdf = None
    if pdf_engine in ("auto", "rendercv"):
        cv_pdf = render_with_rendercv(docs, profile, lang, folder)
    chrome = find_chrome(chrome_path) if pdf_engine in ("auto", "chrome", "rendercv") else None
    helper = find_helper() if pdf_engine in ("auto", "helper") else None

    def to_pdf(html: Path, pdf: Path) -> bool:
        """A Chromium browser when there is one, else the app's own renderer."""
        if chrome and html_to_pdf(html, pdf, chrome):
            return True
        return bool(helper) and helper_to_pdf(html, pdf, helper)

    if cv_pdf is None and to_pdf(folder / "cv.html", folder / "cv.pdf"):
        cv_pdf = folder / "cv.pdf"
    if cv_pdf:
        written.append("cv.pdf")
    if to_pdf(folder / f"{letter_name}.html", folder / f"{letter_name}.pdf"):
        written.append(f"{letter_name}.pdf")
    return written


def job_title_for_files(job: dict[str, Any]) -> str:
    return clean_title(job.get("title") or "")
