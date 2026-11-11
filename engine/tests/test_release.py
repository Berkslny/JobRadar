"""Release features: two languages, app-managed settings, profile from a CV, search setup, AI settings."""

from __future__ import annotations

import io
import json
import time
import zipfile

import pytest
import yaml
from fastapi.testclient import TestClient

from jobradar import db, i18n, profile_tools, searchsetup, settings
from jobradar.config import load_config
from jobradar.processing.filters import location_in_country
from jobradar.scoring.fake import FakeLLM
from jobradar.web.app import create_app

CV_TEXT = """Alex Example
Backend Engineer · alex@example.com · Berlin

Experience
ACME GmbH, Backend Engineer, 03/2021 - present
- Built a billing service in Python (FastAPI, PostgreSQL) that processes 2 million invoices a month.
Education
Example University, B.Sc. Computer Science, 2016 - 2020
Languages: English C1, German B1
""" * 2

CV_JSON = {
    "name": "Alex Example", "headline": "Backend Engineer", "email": "alex@example.com", "city": "Berlin",
    "summary": ["Backend engineer with five years of experience."],
    "experience": [{"kind": "work", "organization": "ACME GmbH", "title": "Backend Engineer", "start": "2021-03",
                    "end": "present", "facts": [{"text": "Built a billing service in Python that processes 2 million "
                                                         "invoices a month.", "skills": ["Python", "FastAPI"]}]}],
    "education": [{"organization": "Example University", "title": "B.Sc. Computer Science", "start": "2016", "end": "2020"}],
    "skills": {"backend": ["Python", "FastAPI", "PostgreSQL"]},
    "languages": [{"name": "English", "level": "C1"}, {"name": "German", "level": "B1"}],
}
TRACKS_JSON = {"tracks": [{"id": "backend", "name": "Backend", "north_star": "Backend roles in Berlin.",
                           "title_keywords": ["Backend", "Python", "Softwareentwickl"],
                           "domain_keywords": ["FastAPI", "PostgreSQL"], "search_terms": ["Backend Engineer"]}],
               "title_exclude": ["Sales", "Backend"], "exclude_senior": True}


def responder(system: str, user: str) -> str:
    if user.startswith("TASK: READ CV"):
        return json.dumps(CV_JSON)
    if user.startswith("TASK: SET UP SEARCH"):
        return json.dumps(TRACKS_JSON)
    return json.dumps({"ok": True})


def wait_task(client: TestClient, task: dict) -> dict:
    for _ in range(200):
        state = client.get(f"/api/v1/tasks/{task['id']}").json()
        if state["status"] != "running":
            return state
        time.sleep(0.01)
    raise AssertionError("task did not finish")


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """A workspace as the app creates it: no profile, no tracks, no model."""
    monkeypatch.delenv("JOBRADAR_LANG", raising=False)
    i18n.set_default("")
    cfg = load_config(settings.ensure_workspace(tmp_path / "ws"))
    yield cfg
    i18n.set_default("")


def test_i18n_follows_request_language_and_default(fresh):
    client = TestClient(create_app(fresh, llm_factory=lambda c: None, cycle_runner=lambda c: None))
    assert client.post("/api/v1/jobs/nope/status", json={"status": "new"}).json()["detail"] == "İlan bulunamadı"
    r = client.post("/api/v1/jobs/nope/status", json={"status": "new"}, headers={"Accept-Language": "en-US,en;q=0.9"})
    assert r.json()["detail"] == "Job not found"
    summary = client.get("/api/v1/summary", headers={"X-JobRadar-Lang": "en"}).json()
    assert {"id": "applied", "label": "Applied"} in summary["statuses"] and summary["language"] == "en"
    assert summary["llm"] == "none" and summary["llm_ready"] is False and "name" in summary["profile_missing"]
    # the app can change the default for background work
    put = client.put("/api/v1/app-settings", json={"language": "en"}).json()
    assert put["language"] == "en" and put["output_language"] in ("auto", "tr") and put["document_language"] == ""
    more = client.put("/api/v1/app-settings", json={"document_language": "TR", "output_language": "", "follow_up_days": 7}).json()
    assert (more["document_language"], more["document_language_effective"], more["output_language"],
            more["follow_up_days"], more["language"]) == ("tr", "tr", "auto", 7, "en")
    assert fresh.tailor.default_language == "tr" and fresh.follow_up_days == 7
    assert client.put("/api/v1/app-settings", json={"document_language": "klingon"}).status_code == 422
    assert client.put("/api/v1/app-settings", json={"follow_up_days": 0}).status_code == 422
    assert client.put("/api/v1/app-settings", json={"document_language": ""}).json()["document_language"] == ""
    assert i18n.t("Tamamlandı") == "Finished" and client.get("/api/v1/summary").json()["language"] == "en"
    assert load_config(fresh.config_path).language == "en"
    i18n.set_default("tr")
    assert i18n.t("{yrs}+ yıl deneyim", yrs=3) == "3+ yıl deneyim" and i18n.t("no such key") == "no such key"


def test_every_translatable_string_has_english():
    """Each literal passed to t()/tr() in the package has an entry in the English table."""
    import ast
    from pathlib import Path

    root = Path(i18n.__file__).parent
    missing = []
    for path in root.rglob("*.py"):
        if path.name in ("cli.py", "demo.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("t", "tr") \
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                text = node.args[0].value
                if text not in i18n.EN and any(ch in text for ch in "çğıöşüÇĞİÖŞÜ") or (
                        text not in i18n.EN and text.isascii() and len(text) > 3 and path.name != "i18n.py"):
                    missing.append(f"{path.name}: {text}")
    assert not missing, missing


def test_overlay_keeps_yaml_and_applies_in_place(fresh):
    before = fresh.config_path.read_text(encoding="utf-8")
    settings.update(fresh, {"scoring": {"llm_max_per_run": 7}, "search": {"country": "Germany"}})
    assert fresh.scoring.llm_max_per_run == 7 and fresh.scoring.prescore_min == 40
    assert fresh.config_path.read_text(encoding="utf-8") == before
    again = load_config(fresh.config_path)
    assert again.scoring.llm_max_per_run == 7 and again.search.country == "Germany"
    with pytest.raises(ValueError):
        settings.update(fresh, {"data_dir": "/tmp"})
    with pytest.raises(Exception):
        settings.update(fresh, {"scoring": {"llm_max_per_run": "many"}})
    assert load_config(fresh.config_path).scoring.llm_max_per_run == 7


def test_profile_from_cv_and_save(fresh):
    llm = FakeLLM(responder)
    client = TestClient(create_app(fresh, llm_factory=lambda c: llm, cycle_runner=lambda c: None))
    state = client.get("/api/v1/setup").json()
    assert state["ready"] is False and state["profile"]["exists"] is False and "name" in state["profile"]["missing"]
    assert client.get("/api/v1/profile").json()["exists"] is False
    # scanned or empty files are refused before the model is called
    bad = client.post("/api/v1/profile/import?filename=cv.pdf", content=b"%PDF-1.4 broken")
    assert bad.status_code == 422
    assert client.post("/api/v1/profile/import?filename=cv.exe", content=b"x" * 500).status_code == 422
    task = client.post("/api/v1/profile/import?filename=cv.txt", content=CV_TEXT.encode(), headers={"X-JobRadar-Lang": "en"})
    assert task.status_code == 202
    done = wait_task(client, task.json())
    assert done["status"] == "done", done
    draft = done["result"]["profile"]
    assert draft["name"] == "Alex Example" and draft["german_level"] == "B1"
    assert draft["experience"][0]["id"] == "ACME" and draft["experience"][0]["facts"][0]["id"] == "ACME-1"
    assert draft["summary_facts"][0]["id"] == "GEN-1" and draft["education"][0]["kind"] == "education"
    assert not fresh.profile_path.exists()  # a draft is not saved
    # the editor adds a fact without an id and an empty row; ids stay stable, the empty row is dropped
    draft["experience"][0]["facts"].append({"text": "Led a team of 3.", "skills": []})
    draft["projects"] = [{"organization": "", "title": "", "facts": []}]
    assert [g["name"] for g in draft["skill_groups"]] == list(draft["skills"])
    # the list forms win and keep their order (a client's JSON objects may reorder keys)
    draft["skill_groups"] = list(reversed(draft["skill_groups"])) + [{"name": "Tools", "items": ["Jira", " "]}]
    draft["link_list"] = [{"name": "Portfolio", "url": "https://example.com/me"}, {"name": "", "url": "x"}]
    order = [g["name"] for g in draft["skill_groups"]]
    saved = client.put("/api/v1/profile", json={"profile": draft}).json()
    assert list(saved["profile"]["skills"]) == order and saved["profile"]["skills"]["Tools"] == ["Jira"]
    assert saved["profile"]["links"] == {"Portfolio": "https://example.com/me"}
    assert saved["profile"]["link_list"] == [{"name": "Portfolio", "url": "https://example.com/me"}]
    facts = saved["profile"]["experience"][0]["facts"]
    assert [f["id"] for f in facts] == ["ACME-1", "ACME-2"] and saved["profile"]["projects"] == []
    assert saved["missing"] == [] and fresh.profile_path.exists()
    assert yaml.safe_load(fresh.profile_path.read_text(encoding="utf-8"))["name"] == "Alex Example"
    assert client.put("/api/v1/profile", json={"profile": {"name": 5, "experience": "x"}}).status_code == 422


def test_cv_text_from_docx():
    doc = io.BytesIO()
    body = ("<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body>"
            + "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in CV_TEXT.splitlines() if line)
            + "</w:body></w:document>")
    with zipfile.ZipFile(doc, "w") as z:
        z.writestr("word/document.xml", body)
    text = profile_tools.extract_text("cv.docx", doc.getvalue())
    assert "ACME GmbH, Backend Engineer" in text and "Languages: English C1" in text
    with pytest.raises(profile_tools.CVError):
        profile_tools.extract_text("cv.txt", b"too short")


def test_assign_ids_keeps_existing_and_never_collides():
    data = {"summary_facts": [{"text": "a"}, {"id": "GEN-1", "text": "b"}],
            "experience": [{"id": "ACME", "organization": "ACME", "title": "x", "facts": [{"id": "ACME-1", "text": "kept"},
                                                                                         {"text": "new"}]},
                           {"organization": "ACME GmbH", "title": "y", "facts": [{"text": "other"}]},
                           {"organization": "Ünïversität Köln", "title": "z", "facts": []}]}
    out = profile_tools.assign_ids(data)
    ids = [f["id"] for f in out["summary_facts"]] + [e["id"] for e in out["experience"]] + \
          [f["id"] for e in out["experience"] for f in e["facts"]]
    assert len(ids) == len(set(ids))
    assert out["experience"][0]["facts"][0]["id"] == "ACME-1" and out["experience"][1]["id"] == "ACME2"
    assert out["experience"][2]["id"] == "UENIVERS" and out["summary_facts"][1]["id"] == "GEN-1"


def test_search_setup_suggest_and_save(fresh):
    llm = FakeLLM(responder)
    client = TestClient(create_app(fresh, llm_factory=lambda c: llm, cycle_runner=lambda c: None))
    view = client.get("/api/v1/search").json()
    assert view["tracks"] == [] and view["country"] == "" and view["sources"]["arbeitsagentur"]["enabled"] is False
    assert {"code": "DE", "name": "Germany"} in view["options"]["countries"]
    assert client.post("/api/v1/search/suggest", json={"roles": " "}).status_code == 422
    done = wait_task(client, client.post("/api/v1/search/suggest", json={"roles": "Backend engineer", "country": "DE",
                                                                         "where": "Berlin"}).json())
    assert done["status"] == "done", done
    tracks = done["result"]["tracks"]
    assert tracks[0]["id"] == "backend" and tracks[0]["priority"] == 1
    assert done["result"]["title_exclude"] == ["Sales"]  # never excludes one of the keywords
    saved = client.put("/api/v1/search", json={
        "country": "DE", "locations": [{"city": "Berlin", "radius_km": 40}], "tracks": tracks + [{"name": "Data"}],
        "employment_types": ["fulltime", "nonsense"], "filters": {"title_exclude": ["Sales"], "exclude_senior": False},
        "sources": {"jobspy": {"enabled": True, "sites": ["linkedin"]},
                    "companies": [{"name": "Acme", "ats": "greenhouse", "slug": "acme"}]},
        "scoring": {"llm_max_per_run": 30}}).json()
    assert saved["country"] == "DE" and saved["country_name"] == "Germany"
    assert saved["sources"]["arbeitsagentur"] == {"enabled": True, "available": True}
    assert [t["id"] for t in saved["tracks"]] == ["backend", "data"] and saved["tracks"][1]["search_terms"] == []
    assert saved["employment_types"] == ["fulltime"] and saved["filters"]["exclude_senior"] is False
    assert saved["sources"]["companies"][0]["slug"] == "acme" and saved["scoring"]["llm_max_per_run"] == 30
    reloaded = load_config(fresh.config_path)
    assert reloaded.search.locations[0].city == "Berlin" and reloaded.sources.freehire.countries == ["DE"]
    assert reloaded.tailor.sender_city == "Berlin" and reloaded.sources.jobspy.sites == ["linkedin"]
    # moving to another country turns the Germany-only source off
    moved = client.put("/api/v1/search", json={"country": "NL"}).json()
    assert moved["country_name"] == "Netherlands" and moved["sources"]["arbeitsagentur"]["enabled"] is False
    assert client.put("/api/v1/search", json={"scoring": {"llm_max_per_run": "x"}}).status_code == 422
    # without a model the wish itself becomes the track
    assert searchsetup.suggest(None, None, roles="Nurse, Midwife", country="", where="", ui_lang="en")["tracks"][1]["name"] == "Midwife"


def test_ai_settings_and_test_call(fresh, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from jobradar.scoring.llm import get_llm

    client = TestClient(create_app(fresh, llm_factory=get_llm, cycle_runner=lambda c: None))
    assert client.get("/api/v1/ai").json()["provider"] == "none"
    assert client.put("/api/v1/ai", json={"provider": "magic"}).status_code == 422
    no_key = client.put("/api/v1/ai", json={"provider": "anthropic", "fast_model": "claude-haiku-5-5"},
                        headers={"X-JobRadar-Lang": "en"}).json()
    assert no_key["ready"] is False and "API key is missing" in no_key["error"]
    with_key = client.put("/api/v1/ai", json={"provider": "anthropic", "fast_model": "claude-haiku-5-5",
                                              "smart_model": "claude-sonnet-5-5", "api_key": " sk-test "}).json()
    assert with_key["ready"] is True and with_key["active"] == "anthropic" and with_key["key_set"]["anthropic"] is True
    assert "sk-test" not in settings.overlay_path(fresh).read_text(encoding="utf-8")  # secrets never reach the disk
    assert load_config(fresh.config_path).llm.allow_paid_api is True
    local = client.put("/api/v1/ai", json={"provider": "openai", "base_url": "http://localhost:1234/v1/",
                                           "fast_model": "qwen"}).json()
    assert local["ready"] is True and local["active"] == "local" and local["base_url"] == "http://localhost:1234/v1"
    assert client.put("/api/v1/ai", json={"provider": "ollama"}).json()["ready"] is False
    assert client.get("/api/v1/ai/models?provider=claude_cli").json()["models"] == ["haiku", "sonnet", "opus"]
    assert client.put("/api/v1/ai", json={"provider": "none"}).json()["provider"] == "none"
    assert client.post("/api/v1/ai/test").status_code == 503

    llm = FakeLLM(responder)
    client2 = TestClient(create_app(fresh, llm_factory=lambda c: llm, cycle_runner=lambda c: None))
    done = wait_task(client2, client2.post("/api/v1/ai/test", headers={"X-JobRadar-Lang": "en"}).json())
    assert done["status"] == "done" and done["result"]["message"] == "The connection works."


def test_answers_editor_and_standard_labels(fresh):
    client = TestClient(create_app(fresh, llm_factory=lambda c: None, cycle_runner=lambda c: None))
    en = client.get("/api/v1/answers/edit", headers={"X-JobRadar-Lang": "en"}).json()
    tr = client.get("/api/v1/answers/edit").json()
    assert en["items"][0] == {"id": "notice_period", "label": "Notice period", "primary": "", "en": ""}
    assert tr["items"][0]["label"] == "İhbar süresi"
    items = tr["items"]
    items[0]["primary"], items[0]["en"] = "Dört hafta", "Four weeks"
    items.append({"id": "", "label": "Portfolio", "primary": "https://example.com", "en": ""})
    saved = client.put("/api/v1/answers/edit", json={"items": items}, headers={"X-JobRadar-Lang": "en"}).json()
    assert saved["items"][0] == {"id": "notice_period", "label": "Notice period", "primary": "Dört hafta", "en": "Four weeks"}
    assert saved["items"][-1]["id"] == "portfolio"
    general = client.get("/api/v1/answers", headers={"X-JobRadar-Lang": "en"}).json()
    labels = [i["label"] for g in general["groups"] for i in g["items"]]
    assert "Notice period" in labels and "Portfolio" in labels and "Willingness to travel" in general["missing"]


def test_mail_settings_stay_in_memory(fresh, monkeypatch):
    client = TestClient(create_app(fresh, llm_factory=lambda c: None, cycle_runner=lambda c: None))
    assert client.get("/api/v1/mail-settings").json()["has_password"] is False
    saved = client.put("/api/v1/mail-settings", json={"user": "me@example.com", "password": "abcd efgh", "imap_host": "imap.mail.me.com",
                                                      "smtp_host": "smtp.mail.me.com", "digest": False}).json()
    assert saved["user"] == "me@example.com" and saved["to"] == "me@example.com" and saved["has_password"] is True
    assert saved["imap_host"] == "imap.mail.me.com" and saved["digest"] is False and saved["sync"] is True
    assert "abcd" not in settings.overlay_path(fresh).read_text(encoding="utf-8")
    assert client.put("/api/v1/mail-settings", json={"password": ""}).json()["has_password"] is False
    monkeypatch.delenv("SMTP_USER", raising=False)


def test_scan_needs_a_profile_and_serves_without_one(fresh):
    """The engine starts in an empty workspace; evaluating without a profile explains what is missing."""
    llm = FakeLLM(responder)
    client = TestClient(create_app(fresh, llm_factory=lambda c: llm, cycle_runner=lambda c: None))
    assert client.get("/api/v1/jobs").json() == {"jobs": [], "view": "inbox", "total": 0, "offset": 0}
    c = db.connect(fresh.db_path)
    db.insert_job(c, {"id": "j1", "title": "Backend Engineer", "company": "Acme", "url": "https://example.com/1",
                      "status": "new", "prescore": 60})
    c.commit()
    r = client.post("/api/v1/jobs/j1/evaluate", headers={"X-JobRadar-Lang": "en"})
    assert r.status_code == 409 and "Create your profile first" in r.json()["detail"]
    assert client.get("/open/job/j1").status_code == 200 and "jobradar://job/j1" in client.get("/open/job/j1").text


def test_location_filter_for_other_countries():
    assert location_in_country("Amsterdam, Netherlands", "Netherlands") is True
    assert location_in_country("Berlin, Germany", "Netherlands") is False
    assert location_in_country("Rotterdam", "Netherlands") is None  # unknown city: keep
    assert location_in_country("Remote", "Netherlands") is True
    assert location_in_country("Remote, USA", "Netherlands") is False
    assert location_in_country("London, UK", "Germany") is False and location_in_country("Aachen", "Germany") is True
    assert location_in_country("Istanbul, TR", "Turkey") is True and location_in_country("İzmir, Türkiye", "Turkey") is True


def test_job_answers_follow_the_main_application_language(fresh):
    from jobradar import db
    from jobradar.answers import found_via_in, job_answers
    from jobradar.profile_tools import load_or_empty

    job = {"id": "j1", "title": "Data Analyst (m/f/d)", "sources": [{"source": "linkedin", "seen": "2026-01-01"}],
           "description": "", "lang": "en"}
    assert found_via_in(job, "tr") == "LinkedIn" and found_via_in({"sources": []}, "tr") == "Şirketinizin kariyer sayfası"
    assert found_via_in({"sources": [{"source": "greenhouse:acme"}]}, "fr") == "Your company's careers page"
    fresh.tailor.default_language = "tr"
    conn = db.connect(fresh.db_path)
    try:
        token = i18n.set_lang("en")
        try:
            ans = job_answers(fresh, conn, load_or_empty(fresh.profile_path), job)
        finally:
            i18n.reset(token)
    finally:
        conn.close()
    groups = {g["id"]: g for g in ans["groups"]}
    items = {i["id"]: i for i in groups["job"]["items"]}
    assert ans["primary"] == "tr" and ans["language"] == "en" and groups["job"]["title"] == "This posting"
    assert items["subject"]["de"] == "Data Analyst pozisyonu için başvuru" and items["position"]["label"] == "Position"
    assert items["subject"]["en"] == "Application for Data Analyst" and items["source"]["label"] == "Where did you find the posting?"


def test_sample_data_folder_is_built_once_and_never_replaces_other_folders(tmp_path):
    import pytest

    from jobradar.demo import DEMO_MARKER, ensure_demo

    target = tmp_path / "demo"
    cfg = ensure_demo(target, log=lambda m: None)
    assert (target / DEMO_MARKER).exists() and cfg.profile_path.exists()
    stamp = (target / "jobradar.yaml").stat().st_mtime_ns
    again = ensure_demo(target, log=lambda m: None)
    assert again.db_path == cfg.db_path and (target / "jobradar.yaml").stat().st_mtime_ns == stamp
    other = tmp_path / "mine"
    other.mkdir()
    (other / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ValueError):
        ensure_demo(other, log=lambda m: None)
    assert (other / "notes.txt").read_text(encoding="utf-8") == "keep me"


def test_model_label_uses_names_people_know():
    from jobradar import i18n
    from jobradar.scoring.fake import FakeLLM
    from jobradar.scoring.llm import ClaudeCLILLM, llm_label

    token = i18n.set_lang("en")
    try:
        assert llm_label(ClaudeCLILLM("claude", "haiku", "sonnet")) == "Claude Code · your Claude plan"
        assert llm_label(FakeLLM()).startswith("Demo")
    finally:
        i18n.reset(token)


def test_sample_data_can_be_built_inside_the_working_directory(tmp_path, monkeypatch):
    """The Mac app starts the engine with the sample folder as its working directory."""
    import os

    from jobradar.demo import ensure_demo

    target = tmp_path / "sample-data"
    target.mkdir()
    monkeypatch.chdir(target)
    cfg = ensure_demo(target, log=lambda m: None)
    assert os.getcwd() == str(target.resolve()) and cfg.profile_path.exists()
    # a build that stopped halfway is repeated instead of being taken for someone's own folder
    (target / ".jobradar-demo").write_text("building\n", encoding="utf-8")
    (target / "data" / "jobradar.db").unlink()
    again = ensure_demo(target, log=lambda m: None)
    assert again.db_path.exists() and (target / ".jobradar-demo").read_text(encoding="utf-8").startswith("ready")
