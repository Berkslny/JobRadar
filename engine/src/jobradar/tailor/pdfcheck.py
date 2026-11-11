"""Check generated PDFs the way an ATS and a recruiter see them.

* page count: CV at most `cv_max_pages`, cover letter at most `letter_max_pages`
* text layer: an ATS reads the embedded text, not the picture; it must exist
* contact details: name, e-mail and phone must be extractable as text
* requirement coverage: requirements the evaluation found supported by the
  fact bank should be visible in the CV text. Unsupported ones are never added.

Uses pypdf when installed, otherwise Poppler's pdfinfo/pdftotext, otherwise skips."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from jobradar.i18n import t
from jobradar.profile import Profile
from jobradar.textutil import fold_umlauts

_STOP = {
    "und", "oder", "der", "die", "das", "mit", "für", "von", "in", "im", "auf", "bei", "zur", "zum", "ein", "eine",
    "einer", "eines", "sehr", "gute", "guten", "gutes", "erste", "ersten", "fundierte", "fundierten", "kenntnisse",
    "erfahrung", "erfahrungen", "berufserfahrung", "mehrjährige", "idealerweise", "wünschenswert", "vorteil",
    "abgeschlossenes", "studium", "bereich", "sowie", "jahre", "jahren", "fähigkeit", "bereitschaft", "sicherer",
    "umgang", "the", "and", "or", "with", "for", "of", "in", "on", "a", "an", "to", "experience", "knowledge",
    "years", "year", "strong", "good", "solid", "skills", "ability", "degree", "plus", "preferred", "proven",
    "working", "familiarity", "understanding", "least", "relevant", "field", "similar", "excellent",
}


def extract(path: Path) -> tuple[Optional[int], Optional[str], str]:
    """(pages, text, engine). pages/text are None when nothing could read the file."""
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError:
        pypdf = None
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            return len(reader.pages), text, "pypdf"
        except Exception as exc:  # noqa: BLE001
            return None, None, t("pypdf hatası: {error}", error=exc)
    if shutil.which("pdfinfo") and shutil.which("pdftotext"):
        try:
            info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=30).stdout
            m = re.search(r"^Pages:\s+(\d+)", info, re.M)
            text = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True,
                                  timeout=60).stdout
            return (int(m.group(1)) if m else None), text, "poppler"
        except (OSError, subprocess.SubprocessError) as exc:
            return None, None, t("poppler hatası: {error}", error=exc)
    return None, None, t("yok")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", fold_umlauts(s.lower()))


def _key_terms(requirement: str) -> list[str]:
    words = re.findall(r"[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9+#./-]*[A-Za-zÄÖÜäöüß0-9+#]|[A-Za-z]", requirement)
    terms = [w.strip(".-/") for w in words if w.lower() not in _STOP and len(w) >= 2]
    technical = [t for t in terms if re.search(r"[A-Z]{2,}|\d|[+#]|[a-z][A-Z]", t)]
    if technical:
        return technical[:4]
    return sorted(terms, key=len, reverse=True)[:2]


def requirement_coverage(evaluation: Optional[dict[str, Any]], cv_text: str) -> dict[str, list[str]]:
    covered: list[str] = []
    missing: list[str] = []
    text = _norm(cv_text)
    for req in (evaluation or {}).get("requirements") or []:
        if req.get("match") not in ("strong", "partial"):
            continue  # not supported by the fact bank: never pushed into the CV
        terms = _key_terms(str(req.get("requirement") or ""))
        if not terms:
            continue
        variants = {v for t in terms for v in (t, re.split(r"[-/]", t)[0]) if len(v) >= 2}
        found = any(_norm(v) in text for v in variants)
        label = str(req.get("requirement") or "")[:120]
        (covered if found else missing).append(label)
    return {"covered": covered[:15], "missing": missing[:10]}


def _contact(profile: Profile, text: str) -> dict[str, bool]:
    squashed = re.sub(r"\s+", "", text.lower())
    digits = re.sub(r"\D", "", text)
    phone_digits = re.sub(r"\D", "", profile.phone or "")
    name_tokens = [t for t in re.split(r"\s+", profile.name.lower()) if len(t) > 1]
    return {
        "name": bool(name_tokens) and all(t in text.lower() for t in name_tokens),
        "email": bool(profile.email) and profile.email.lower().replace(" ", "") in squashed,
        "phone": bool(phone_digits) and phone_digits[-7:] in digits,
    }


def check_documents(folder: Path, files: list[str], profile: Profile, evaluation: Optional[dict[str, Any]], *,
                    cv_max_pages: int = 2, letter_max_pages: int = 1) -> dict[str, Any]:
    out: dict[str, Any] = {"engine": "", "issues": [], "ok": True}
    issues: list[str] = out["issues"]
    if "cv.pdf" in files:
        pages, text, engine = extract(folder / "cv.pdf")
        out["engine"] = engine
        if text is None:
            out["cv"] = {"pages": pages}
            issues.append(t("CV PDF okunamadı ({engine}); kontrol atlandı.", engine=engine))
        else:
            contact = _contact(profile, text)
            out["cv"] = {"pages": pages, "chars": len(text.strip()), "contact": contact}
            if pages and pages > cv_max_pages:
                issues.append(t("CV {pages} sayfa; en fazla {max} olmalı.", pages=pages, max=cv_max_pages))
            if len(text.strip()) < 300:
                issues.append(t("CV'nin metin katmanı boş ya da çok kısa: ATS içeriği okuyamayabilir."))
            missing = [k for k, ok in contact.items() if not ok and (k != "phone" or profile.phone)
                       and (k != "email" or profile.email)]
            if missing:
                names = {"name": t("ad"), "email": t("e-posta"), "phone": t("telefon")}
                issues.append(t("PDF metninde bulunamadı: {items}", items=", ".join(names[k] for k in missing)))
            out["keywords"] = requirement_coverage(evaluation, text)
            if out["keywords"]["missing"]:
                issues.append(t("Profilinin desteklediği {n} şart CV metninde geçmiyor.", n=len(out["keywords"]["missing"])))
    letter = next((f for f in files if f.endswith(".pdf") and f != "cv.pdf"), None)
    if letter:
        pages, text, engine = extract(folder / letter)
        out["engine"] = out["engine"] or engine
        out["letter"] = {"file": letter, "pages": pages, "chars": len((text or "").strip())}
        if pages and pages > letter_max_pages:
            issues.append(t("Ön yazı {pages} sayfa; en fazla {max} olmalı.", pages=pages, max=letter_max_pages))
    if not ("cv.pdf" in files or letter):
        out["engine"] = "pdf yok"
    out["ok"] = not issues
    return out
