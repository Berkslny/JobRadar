"""Application form answers: the questions every form asks, answered once, copied with one click.

Three sources, shown per job in the app and the panel:
  profile   live from data/profile.yaml (name, contact, citizenship, start date, salary, languages)
  general   data/answers.yaml, the user's own wording in German and English (notice period, relocation...)
  job       this posting: where it was found, its reference number, position, e-mail subject,
            and the answers generated together with the tailored documents (tailored.json)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Optional

import yaml

from jobradar.i18n import t
from jobradar import db
from jobradar.config import AppConfig
from jobradar.processing.normalize import clean_title
from jobradar.profile import Profile

TEMPLATE = Path(__file__).parent / "templates" / "answers.yaml"

SOURCE_TEXT = {
    "arbeitsagentur": ("Jobbörse der Bundesagentur für Arbeit", "Job board of the German Federal Employment Agency"),
    "linkedin": ("LinkedIn", "LinkedIn"),
    "indeed": ("Indeed", "Indeed"),
    "stepstone": ("StepStone", "StepStone"),
    "xing": ("XING", "XING"),
    "glassdoor": ("Glassdoor", "Glassdoor"),
    "google": ("Google Jobs", "Google Jobs"),
}
CAREERS = ("Karriereseite Ihres Unternehmens", "Your company's careers page")
# the same answers in Turkish, for users whose main application language is Turkish
SOURCE_TEXT_TR = {"arbeitsagentur": "Almanya Federal İş Ajansı iş ilanları sitesi"}
CAREERS_TR = "Şirketinizin kariyer sayfası"
# subject line of an application e-mail in the main application language
SUBJECT = {
    "de": "Bewerbung als {title}",
    "en": "Application for {title}",
    "tr": "{title} pozisyonu için başvuru",
    "fr": "Candidature au poste de {title}",
    "es": "Candidatura al puesto de {title}",
    "it": "Candidatura per la posizione di {title}",
    "nl": "Sollicitatie voor de functie {title}",
    "pt": "Candidatura à vaga de {title}",
    "pl": "Aplikacja na stanowisko {title}",
}
REF_RE = re.compile(
    r"(?:Referenz-?(?:nummer|nr\.?)|Kennziffer|Kennzahl|Stellen-?(?:ID|nummer|nr\.?)|Ausschreibungs-?(?:nummer|nr\.?)"
    r"|Job[- ]?(?:ID|Ref(?:erence)?)|Requisition(?: ID| No\.?)?|Reference(?: number| no\.?)?|Ref\.(?: ?Nr\.?)?)"
    r"\s*[:#.]?\s*([A-Za-z0-9][A-Za-z0-9\-_/.]{2,30})",
    re.IGNORECASE,
)
PROFILE_IDS = ("name", "email", "phone", "address", "links", "citizenship", "work_permit", "start", "salary",
               "languages")


def ensure_answers_file(cfg: AppConfig) -> Path:
    path = cfg.answers_path
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEMPLATE, path)
    return path


# standard questions: id -> (label in the template, Turkish source label for i18n)
STANDARD_LABELS = {
    "notice_period": ("Notice period", "İhbar süresi"),
    "relocation": ("Willingness to relocate", "Taşınmaya açıklık"),
    "travel": ("Willingness to travel", "Seyahate açıklık"),
    "driving_license": ("Driving licence", "Ehliyet"),
    "work_mode": ("Preferred way of working (on site / hybrid / remote)", "Çalışma şekli (ofis / hibrit / uzaktan)"),
    "interview_availability": ("Availability for interviews", "Mülakat için uygunluk"),
    "clearance": ("Security clearance", "Güvenlik soruşturması"),
}


def display_label(id_: str, label: str) -> str:
    """Standard questions follow the interface language unless the user renamed them."""
    std = STANDARD_LABELS.get(id_)
    if std and (not label or label == std[0]):
        return t(std[1])
    return label


def load_raw(cfg: AppConfig) -> list[dict[str, str]]:
    """Every row of answers.yaml for the editor, empty ones included (TODO shown as empty)."""
    path = ensure_answers_file(cfg)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(t("{name} okunamadı: {error}", name=path.name, error=exc)) from exc
    out = []
    for i, raw in enumerate(data.get("answers") or []):
        if isinstance(raw, dict):
            id_ = str(raw.get("id") or f"q{i + 1}")
            out.append({"id": id_, "label": display_label(id_, _filled(raw.get("label"))),
                        "primary": _filled(raw.get("de")), "en": _filled(raw.get("en"))})
    return out


def save_raw(cfg: AppConfig, items: list[dict[str, Any]]) -> None:
    """Write the editor's rows back; a standard question keeps its template label so it stays translatable."""
    rows, seen = [], set()
    for i, item in enumerate(items or []):
        label = " ".join(str(item.get("label") or "").split())
        id_ = re.sub(r"[^a-z0-9_]+", "_", str(item.get("id") or "").lower()).strip("_")
        if not id_:
            id_ = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:30] or f"q{i + 1}"
        while id_ in seen:
            id_ += "_2"
        seen.add(id_)
        if not label and id_ not in STANDARD_LABELS:
            continue
        std = STANDARD_LABELS.get(id_)
        if std and (not label or label in (std[0], std[1], t(std[1]))):
            label = std[0]
        rows.append({"id": id_, "label": label, "de": " ".join(str(item.get("primary") or "").split()) or "TODO",
                     "en": " ".join(str(item.get("en") or "").split()) or "TODO"})
    path = cfg.answers_path
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ("# Answers for application forms. de: the answer in your main application language, en: in English.\n"
              "# Rows that are still TODO are not shown.\n\n")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(header + yaml.safe_dump({"answers": rows}, allow_unicode=True, sort_keys=False, width=110),
                   encoding="utf-8")
    tmp.replace(path)


def _filled(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return "" if not text or text.upper().startswith("TODO") else text


def load_general(cfg: AppConfig) -> tuple[list[dict[str, str]], list[str]]:
    """Filled entries from answers.yaml and the labels still marked TODO."""
    path = cfg.answers_path
    if not path.exists():
        return [], []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(t("{name} okunamadı: {error}", name=path.name, error=exc)) from exc
    items, missing = [], []
    for i, raw in enumerate(data.get("answers") or []):
        if not isinstance(raw, dict):
            continue
        label = (display_label(str(raw.get("id") or ""), _filled(raw.get("label"))) or _filled(raw.get("id"))
                 or t("Soru {n}", n=i + 1))
        de, en = _filled(raw.get("de")), _filled(raw.get("en"))
        if not de and not en:
            missing.append(label)
            continue
        items.append({"id": str(raw.get("id") or f"q{i + 1}"), "label": label, "de": de or en, "en": en or de})
    return items, missing


def _item(id_: str, label: str, de: str, en: str = "") -> dict[str, str]:
    return {"id": id_, "label": label, "de": de, "en": en or de}


def profile_items(prof: Profile) -> list[dict[str, str]]:
    out = []
    if prof.name:
        out.append(_item("name", t("Ad soyad"), prof.name))
    if prof.email:
        out.append(_item("email", t("E-posta"), prof.email))
    if prof.phone:
        out.append(_item("phone", t("Telefon"), prof.phone))
    if prof.address or prof.city:
        out.append(_item("address", t("Adres / şehir"), prof.address or prof.city))
    for key, url in (prof.links or {}).items():
        if url:
            out.append(_item(f"link_{key}", key.capitalize() if key.islower() else key, url))
    if prof.citizenships:
        out.append(_item("citizenship", t("Vatandaşlık"), ", ".join(prof.citizenships)))
    if prof.work_permit:
        out.append(_item("work_permit", t("Çalışma izni"), prof.work_permit))
    if prof.earliest_start:
        out.append(_item("start", t("En erken başlangıç"), prof.earliest_start))
    if prof.preferences.salary_expectation:
        out.append(_item("salary", t("Maaş beklentisi"), prof.preferences.salary_expectation))
    if prof.languages:
        out.append(_item("languages", t("Diller"), ", ".join(f"{lang.name} ({lang.level})" for lang in prof.languages)))
    return out


def _found_name(job: dict[str, Any]) -> str:
    """Name of the earliest source of the posting; empty when it is unknown."""
    sources = sorted(job.get("sources") or [], key=lambda s: str(s.get("seen") or ""))
    for s in sources:
        parts = str(s.get("source") or "").split(":")
        name = parts[1] if parts[0] in ("manual", "alert") and len(parts) > 1 else parts[0]
        if name:
            return name
    return ""


def found_via(job: dict[str, Any]) -> tuple[str, str]:
    """How the posting was found (earliest source), as an honest form answer in German and English."""
    return SOURCE_TEXT.get(_found_name(job), CAREERS)


def found_via_in(job: dict[str, Any], language: str) -> str:
    """The same answer in the main application language (German, Turkish; English for the others)."""
    de, en = found_via(job)
    if language == "de":
        return de
    if language == "tr":
        name = _found_name(job)
        if name in SOURCE_TEXT:
            return SOURCE_TEXT_TR.get(name, en)
        return CAREERS_TR
    return en


def reference_number(job: dict[str, Any]) -> str:
    for s in job.get("sources") or []:
        if str(s.get("source") or "").startswith("arbeitsagentur") and s.get("external_id"):
            return str(s["external_id"])
    ref = str(job.get("detail_ref") or "")
    if ref.startswith("aa:"):
        return ref[3:]
    m = REF_RE.search(job.get("description") or "")
    if m:
        value = m.group(1).rstrip(".,;:/-")
        if re.search(r"\d", value):
            return value
    return ""


def tailored_answers(cfg: AppConfig, conn, job_id: str) -> tuple[list[dict[str, str]], Optional[int]]:
    for doc in db.documents_for(conn, job_id):
        path = cfg.applications_path / doc["folder"] / "tailored.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items = []
        for i, a in enumerate(data.get("answers") or []):
            q, ans = _filled(a.get("question")), _filled(a.get("answer"))
            if q and ans:
                items.append(_item(f"tailored_{i + 1}", q, ans))
        return items, doc["version"]
    return [], None


def job_answers(cfg: AppConfig, conn, prof: Profile, job: dict[str, Any]) -> dict[str, Any]:
    general, missing = load_general(cfg)
    overrides = {g["id"]: g for g in general if g["id"] in PROFILE_IDS}
    profile_part = [overrides.pop(p["id"], p) for p in profile_items(prof)]
    general = [g for g in general if g["id"] not in PROFILE_IDS] + list(overrides.values())

    from jobradar.tailor.generate import default_document_language

    # the "de" field of every item holds the answer in the main application language
    primary = default_document_language(cfg)
    title = clean_title(job.get("title", ""))
    ref = reference_number(job)
    found_label = t("İlanı nerede buldun?")
    if primary == "de":
        found_label += " (Wie sind Sie auf uns aufmerksam geworden?)"
    job_part = [_item("source", found_label, found_via_in(job, primary), found_via(job)[1]),
                _item("position", t("Pozisyon"), title)]
    if ref:
        job_part.append(_item("reference", t("Referans numarası"), ref))
    suffix = f" (Ref. {ref})" if ref else ""
    job_part.append(_item("subject", t("E-posta konusu"), SUBJECT.get(primary, SUBJECT["en"]).format(title=title) + suffix,
                          SUBJECT["en"].format(title=title) + suffix))
    tailored, version = tailored_answers(cfg, conn, job["id"])
    groups = [
        {"id": "job", "title": t("Bu ilan"), "items": job_part},
        {"id": "profile", "title": t("Profil"), "items": profile_part},
        {"id": "general", "title": t("Genel sorular"), "items": general},
    ]
    if tailored:
        groups.append({"id": "tailored", "title": t("Belgelerle üretilen cevaplar (v{v})", v=version), "items": tailored})
    lang = "en" if (job.get("lang") or "").startswith("en") else "de"
    return {"language": lang, "primary": primary, "groups": groups, "missing": missing,
            "answers_file": str(cfg.answers_path.relative_to(cfg.base_dir)) if cfg.answers_path.is_relative_to(
                cfg.base_dir) else str(cfg.answers_path)}
