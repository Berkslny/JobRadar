"""Tailoring orchestration: draft -> validate -> one repair round -> reviewer critique and one revision
-> strip anything still unsupported -> render -> PDF checks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from jobradar.i18n import t
from jobradar import db
from jobradar.config import AppConfig
from jobradar.processing.normalize import clean_title
from jobradar.profile import Profile
from jobradar.scoring.llm import BaseLLM, LLMError, complete_json
from jobradar.scoring.prompts import (build_repair_prompt, build_review_prompt, build_revision_prompt,
                                      build_tailor_prompt)
from jobradar.tailor.pdfcheck import check_documents
from jobradar.tailor.render import write_documents
from jobradar.tailor.validate import ReviewResult, TailoredDocs, ValidationReport, Validator, strip_violations
from jobradar.textutil import slugify, today_iso


def choose_language(job: dict[str, Any], evaluation: Optional[dict[str, Any]], override: str | None = None,
                    default: str = "") -> str:
    """Language of the CV and letter: the override, else the posting's language, else the configured default.
    German, English and Turkish have their own section labels; other languages use English labels."""
    def code(value: Any) -> str:
        v = str(value or "").strip().lower()[:2]
        return v if len(v) == 2 and v.isalpha() else ""

    return code(override) or code((evaluation or {}).get("language")) or code(job.get("lang")) or code(default) or "de"


def default_document_language(cfg: AppConfig) -> str:
    """tailor.default_language, else German for Germany and Austria and English elsewhere."""
    explicit = (cfg.tailor.default_language or "").strip().lower()
    if explicit:
        return explicit
    country = (cfg.search.country or "").strip().lower()
    return "de" if country in ("germany", "deutschland", "almanya", "austria", "österreich") else "en"


def evaluation_report_md(job: dict[str, Any], ev: Optional[dict[str, Any]], profile: Profile) -> str:
    lines = [f"# {clean_title(job.get('title', ''))} – {job.get('company', '')}", "",
             f"- {t('Konum')}: {job.get('location', '')}", f"- {t('İlan')}: {job.get('url', '')}"]
    if job.get("apply_url") and job.get("apply_url") != job.get("url"):
        lines.append(f"- {t('Başvuru')}: {job['apply_url']}")
    if not ev:
        return "\n".join(lines) + f"\n\n{t('(Değerlendirme yok)')}\n"
    r = ev.get("result") or {}
    idx = profile.fact_index()
    lines += ["", f"## Puan: {ev.get('score')} / 5 ({ev.get('verdict')})", "", r.get("summary", ""), "",
              f"## {t('Şartlar ve kanıtlar')}", "", t("| Şart | Önem | Eşleşme | Kanıt |"), "|---|---|---|---|"]
    for q in r.get("requirements") or []:
        ev_txt = "; ".join(f"{i}: {idx[i][0].text[:80]}" for i in q.get("evidence") or [] if i in idx) or "–"
        req = str(q.get("requirement", "")).replace("|", "/")
        lines.append(f"| {req} | {q.get('importance')} | {q.get('match')} | {ev_txt.replace('|', '/')} |")
    for title, key in (("Güçlü yanlar", "strengths"), ("Eksikler", "gaps"), ("Riskler", "red_flags"),
                       ("Mülakat hazırlığı", "interview_topics"), ("Uyarlama ipuçları", "tailoring_hints")):
        items = r.get(key) or []
        if items:
            lines += ["", f"## {t(title)}", ""] + [f"- {x}" for x in items]
    if r.get("legitimacy_notes"):
        lines += ["", f"## {t('İlanın güvenilirliği')}", "", f"{r.get('legitimacy')}: {r.get('legitimacy_notes')}"]
    if ev.get("notes"):
        lines += ["", f"## {t('Kod tarafı düzeltmeler')}", ""] + [f"- {n}" for n in ev["notes"]]
    return "\n".join(lines) + "\n"


def review_and_revise(cfg: AppConfig, profile: Profile, job: dict[str, Any], evaluation: Optional[dict[str, Any]],
                      lang: str, docs: TailoredDocs, report: ValidationReport, validator: Validator, llm: BaseLLM,
                      system: str, user: str) -> tuple[dict[str, Any], Optional[tuple[TailoredDocs, ValidationReport]]]:
    """Second pass: a reviewer critiques the draft; one revision is kept only if it adds no unsupported claims."""
    tier = cfg.llm.tailor_tier
    draft_json = docs.model_dump_json(indent=1)
    try:
        rsys, ruser = build_review_prompt(cfg, profile, job, evaluation, draft_json, lang)
        review, _ = complete_json(llm, rsys, ruser, ReviewResult, tier=tier, max_tokens=3000)
    except LLMError as exc:
        return {"enabled": True, "error": str(exc)[:300]}, None
    info: dict[str, Any] = {"enabled": True, "applied": False, **review.model_dump()}
    if review.verdict != "revise" or not (review.issues or review.supported_missing_keywords):
        return info, None
    try:
        docs2, _ = complete_json(llm, system, build_revision_prompt(user, draft_json, review), TailoredDocs,
                                 tier=tier, max_tokens=7000)
    except LLMError as exc:
        info["revision_error"] = str(exc)[:300]
        return info, None
    report2 = validator.validate(docs2)
    if len(report2.errors) <= len(report.errors):
        info["applied"] = True
        return info, (docs2, report2)
    info["rejected"] = t("Düzeltilmiş taslakta profilde olmayan yeni iddialar vardı; ilk taslak korundu.")
    return info, None


def tailor_job(cfg: AppConfig, profile: Profile, conn: sqlite3.Connection, job_id: str, llm: BaseLLM, *,
               language: str | None = None) -> dict[str, Any]:
    job = db.get_job(conn, job_id)
    if not job:
        raise ValueError(t("ilan bulunamadı: {id}", id=job_id))
    ev = db.latest_evaluation(conn, job_id)
    ev_result = ev["result"] if ev else None
    lang = choose_language(job, ev_result, language, default_document_language(cfg))
    system, user = build_tailor_prompt(cfg, profile, job, ev_result, lang)
    tier = cfg.llm.tailor_tier
    docs, res = complete_json(llm, system, user, TailoredDocs, tier=tier, max_tokens=7000)
    validator = Validator(profile, job)
    report = validator.validate(docs)
    rounds = 0
    if not report.ok:
        rounds = 1
        repair = build_repair_prompt(user, docs.model_dump_json(indent=1), report.messages()[:30])
        try:
            docs2, _ = complete_json(llm, system, repair, TailoredDocs, tier=tier, max_tokens=7000)
            report2 = validator.validate(docs2)
            if len(report2.errors) <= len(report.errors):
                docs, report = docs2, report2
        except LLMError:
            pass
    review_info: dict[str, Any] = {"enabled": False}
    if cfg.tailor.review:
        review_info, revised = review_and_revise(cfg, profile, job, ev_result, lang, docs, report, validator, llm,
                                                 system, user)
        if revised:
            docs, report = revised
    first_errors = [v.as_dict() for v in report.errors]
    if not report.ok:
        docs = strip_violations(docs, report)
        removed = report.removed
        report = validator.validate(docs)
        report.removed = removed
    # Degree and language facts are header information, not achievements: never list them as bullets.
    implicit_ids = {f.id for f, _ in profile.implicit_facts()}
    for block in docs.experience:
        block.bullets = [b for b in block.bullets if not (b.facts and all(f in implicit_ids for f in b.facts))]
    versions = db.documents_for(conn, job_id)
    version = (versions[0]["version"] + 1) if versions else 1
    base = f"{today_iso()}_{slugify(job.get('company') or 'firma', 30)}_{slugify(clean_title(job.get('title', '')), 40)}"
    existing_folder = versions[0]["folder"] if versions else None
    parent = cfg.applications_path / (Path(existing_folder).parts[0] if existing_folder else base)
    folder = parent / f"v{version}"
    files = write_documents(docs, profile, job, lang, folder, pdf_engine=cfg.tailor.pdf_engine,
                            chrome_path=cfg.tailor.chrome_path, sender_city=cfg.tailor.sender_city)
    (folder / "tailored.json").write_text(docs.model_dump_json(indent=2), encoding="utf-8")
    validation = report.as_dict()
    validation["repair_rounds"] = rounds
    validation["errors_before_strip"] = first_errors
    validation["provider"] = f"{res.provider}/{res.model}"
    validation["review"] = review_info
    validation["pdf_check"] = check_documents(folder, files, profile, ev_result, cv_max_pages=cfg.tailor.cv_max_pages,
                                              letter_max_pages=cfg.tailor.letter_max_pages)
    (folder / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "evaluation.md").write_text(evaluation_report_md(job, ev, profile), encoding="utf-8")
    files += ["tailored.json", "validation.json", "evaluation.md"]
    rel_folder = folder.relative_to(cfg.applications_path).as_posix()
    doc_id = db.save_document(conn, job_id, version=version, folder=rel_folder, language=lang, files=files,
                              validation=validation)
    if job.get("status") in ("new", "shortlisted"):
        db.set_status(conn, job_id, "tailored", f"belgeler v{version}")
    else:
        db.add_event(conn, job_id, "tailor", f"belgeler v{version}")
    conn.commit()
    return db.get_document(conn, doc_id) or {}
