import json
import plistlib

import httpx
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from jobradar import db
from jobradar.cli import app as cli_app, build_plist
from jobradar.http import make_client
from jobradar.models import RawJob
from jobradar.pipeline import enrich_pending, import_raws, refilter_all, run_scan
from jobradar.scoring.fake import FakeLLM
from jobradar.sources.base import Source
from jobradar.web.app import create_app

DESC = ("Ihre Aufgaben\n• Entwicklung von FPGA-Designs in VHDL für Bildverarbeitung\n• Zynq SoC Integration\n"
        "Ihr Profil\n• Erfahrung mit VHDL\n• Gute Deutschkenntnisse\n" + "Wir bieten ein tolles Team. " * 15)


class StaticSource(Source):
    def __init__(self, name, jobs):
        self.name = name
        self._jobs = jobs

    def fetch(self, ctx):
        ctx.warnings.append("demo warning")
        return list(self._jobs)


class BrokenSource(Source):
    name = "broken"

    def fetch(self, ctx):
        raise RuntimeError("site changed")


def test_scan_merges_across_sources_and_records_health(cfg, profile):
    conn = db.connect(cfg.db_path)
    a = RawJob(source="linkedin", title="FPGA-Entwickler (m/w/d)", company="Nordlicht Defence GmbH", location="München",
               url="https://www.linkedin.com/jobs/view/4100000101", description=DESC, posted_at="2026-11-05")
    b = RawJob(source="arbeitsagentur", title="FPGA Entwickler (w/m/d)", company="Nordlicht Defence",
               location="München", url="https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1-S",
               apply_url="https://karriere.nordlicht.example/job/1", posted_at="2026-11-03")
    c = RawJob(source="greenhouse:Helix", title="Hardware Engineer", company="Helix", location="London, UK",
               url="https://job-boards.greenhouse.io/helix/jobs/1", description="x", needs_location_check=True)
    reports = run_scan(conn, cfg, profile, log=lambda m: None, client=make_client(),
                       sources=[StaticSource("s1", [a, c]), StaticSource("s2", [b]), BrokenSource()])
    assert [r.new for r in reports[:2]] == [2, 0] and reports[1].merged == 1
    assert reports[2].error and "site changed" in reports[2].error
    jobs = db.list_jobs(conn, include_filtered=True)
    merged = next(j for j in jobs if "fpga" in j["title_norm"])
    assert {s["source"] for s in merged["sources"]} == {"linkedin", "arbeitsagentur"}
    assert merged["posted_at"] == "2026-11-03"
    assert merged["apply_url"] == "https://karriere.nordlicht.example/job/1"
    assert merged["flags"]["german_level"] == "B2"
    london = next(j for j in jobs if j["company"] == "Helix")
    assert london["status"] == "filtered" and "dışı konum" in london["filtered_reason"]
    health = {h["source"]: h for h in db.source_health(conn)}
    assert health["broken"]["error"] and health["s1"]["warnings"] == ["demo warning"]


def test_alert_import_then_enrich_merges_duplicate(cfg, profile):
    conn = db.connect(cfg.db_path)
    import_raws(conn, cfg, profile, [RawJob(source="greenhouse:Acme", title="FPGA Engineer", company="Acme GmbH",
                                            location="Berlin", url="https://job-boards.greenhouse.io/acme/jobs/5",
                                            description=DESC)])
    import_raws(conn, cfg, profile, [RawJob(source="alert:linkedin", title="FPGA Engineer",
                                            url="https://www.linkedin.com/jobs/view/4100000202",
                                            detail_ref="url:https://www.linkedin.com/jobs/view/4100000202")])
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
    page = ('<h1 class="top-card-layout__title">FPGA Engineer</h1><span class="topcard__flavor">Acme GmbH</span>'
            '<span class="topcard__flavor topcard__flavor--bullet">Berlin</span>'
            '<div class="show-more-less-html__markup">' + DESC + "</div>")
    client = make_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=page)))
    enrich_pending(conn, cfg, profile, client=client, log=lambda m: None, pause=0)
    rows = db.list_jobs(conn, include_filtered=True)
    assert len(rows) == 1 and {s["source"] for s in rows[0]["sources"]} == {"greenhouse:Acme", "alert:linkedin"}
    assert db.job_id_for_url(conn, "linkedin:4100000202") == rows[0]["id"]


def test_refilter_after_config_change(cfg, profile):
    conn = db.connect(cfg.db_path)
    import_raws(conn, cfg, profile, [RawJob(source="indeed", title="Werkstudent FPGA", company="X", location="Aachen",
                                            url="https://de.indeed.com/viewjob?jk=ws1", description=DESC)])
    assert db.list_jobs(conn)[0]["status"] == "new"
    cfg.search.employment_types = ["fulltime"]
    changed, kept = refilter_all(conn, cfg, profile)
    assert changed == 1 and kept == 0
    assert db.list_jobs(conn, include_filtered=True)[0]["status"] == "filtered"


def _client(cfg):
    return TestClient(create_app(cfg, llm_factory=lambda c: FakeLLM(), cycle_runner=lambda c: None))


def test_web_flow(cfg, profile):
    conn = db.connect(cfg.db_path)
    import_raws(conn, cfg, profile, [RawJob(source="linkedin", title="FPGA-Entwickler (m/w/d)", company="Nordlicht GmbH",
                                            location="München", url="https://www.linkedin.com/jobs/view/4100000303",
                                            description=DESC)])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.close()
    c = _client(cfg)
    for path in ("/jobs", "/jobs?view=all", "/pipeline", "/stats", "/import", f"/jobs/{job_id}"):
        r = c.get(path)
        assert r.status_code == 200, path
    assert "FPGA-Entwickler" in c.get("/jobs").text
    r = c.post(f"/jobs/{job_id}/evaluate", follow_redirects=False)
    assert r.status_code == 303 and "De%C4%9Ferlendirildi" in r.headers["location"]
    r = c.post(f"/jobs/{job_id}/tailor", data={"language": "de"}, follow_redirects=False)
    assert r.status_code == 303
    conn = db.connect(cfg.db_path)
    doc = db.documents_for(conn, job_id)[0]
    conn.close()
    assert c.get(f"/files/{doc['id']}/cv.html").status_code == 200
    assert c.get(f"/files/{doc['id']}/..%2F..%2Fjobradar.db").status_code == 404
    assert c.get(f"/files/{doc['id']}/validation.json").status_code == 200
    r = c.post(f"/docs/{doc['id']}/approve", follow_redirects=False)
    assert r.status_code == 303
    c.post(f"/jobs/{job_id}/status", data={"status": "applied"})
    c.post(f"/jobs/{job_id}/notes", data={"notes": "Recruiter: Frau X"})
    conn = db.connect(cfg.db_path)
    job = db.get_job(conn, job_id)
    assert job["status"] == "applied" and job["applied_at"] and job["notes"] == "Recruiter: Frau X"
    assert db.documents_for(conn, job_id)[0]["approved"] == 1
    conn.close()
    page = c.get(f"/jobs/{job_id}").text
    assert "onaylandı" in page and "Recruiter: Frau X" in page
    r = c.post("/import/alert", data={"text": "FPGA Dev\nhttps://www.linkedin.com/jobs/view/4100000404\n"},
               follow_redirects=False)
    assert r.status_code == 303 and "1%20yeni" in r.headers["location"]
    csv = "Notes:\nsome preamble\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n" \
          "Ada,Lovelace,https://linkedin.com/in/ada,,Nordlicht GmbH,FPGA Lead,01 Jan 2025\n"
    c.post("/import/connections", files={"file": ("Connections.csv", csv, "text/csv")})
    assert "Ada Lovelace" in c.get(f"/jobs/{job_id}").text
    r = c.post("/cycle", follow_redirects=False)
    assert r.status_code == 303


def test_cli_init_doctor_list_and_plist(tmp_path, monkeypatch):
    runner = CliRunner()
    res = runner.invoke(cli_app, ["init", "--dir", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "jobradar.yaml").exists() and (tmp_path / "data" / "profile.yaml").exists()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = runner.invoke(cli_app, ["doctor"])
    assert res.exit_code == 0, res.output
    assert "Alex Example" in res.output
    res = runner.invoke(cli_app, ["list", "--view", "all"])
    assert res.exit_code == 0, res.output
    from jobradar.config import load_config

    plist = build_plist(load_config(tmp_path / "jobradar.yaml"), ["08:40", "17:15"])
    assert plist["StartCalendarInterval"] == [{"Hour": 8, "Minute": 40}, {"Hour": 17, "Minute": 15}]
    assert plist["ProgramArguments"][1:4] == ["-m", "jobradar", "run"]
    plistlib.dumps(plist)


def test_telegram_notifications_and_digest(cfg, profile):
    from jobradar.notify import Telegram, digest_text, health_alerts, notify_new_matches

    conn = db.connect(cfg.db_path)
    import_raws(conn, cfg, profile, [RawJob(source="linkedin", title="FPGA Engineer <script>", company="A&B GmbH",
                                            location="Köln", url="https://www.linkedin.com/jobs/view/4100000505",
                                            description=DESC)])
    jid = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    db.update_fields(conn, jid, llm_score=4.4)
    conn.commit()
    sent = []
    tg = Telegram("T", "C", client=httpx.Client(transport=httpx.MockTransport(
        lambda r: (sent.append(json.loads(r.content)), httpx.Response(200, json={"ok": True}))[1])))
    assert notify_new_matches(conn, cfg, tg) == 1
    assert notify_new_matches(conn, cfg, tg) == 0  # never twice
    text = sent[0]["text"]
    assert "&lt;script&gt;" in text and "A&amp;B GmbH" in text and sent[0]["parse_mode"] == "HTML"
    assert "günlük özet" in digest_text(conn, cfg)
    for _ in range(3):
        rid = db.start_source_run(conn, "jobspy")
        db.finish_source_run(conn, rid, found=0, new=0, merged=0, filtered=0, error="429", warnings=[])
    assert any("jobspy" in a for a in health_alerts(conn))


def test_set_env_value_keeps_other_lines(tmp_path):
    import os
    import stat

    from jobradar.config import set_env_value

    env = tmp_path / ".env"
    env.write_text("# comment\nANTHROPIC_API_KEY=\nTELEGRAM_BOT_TOKEN=abc\n", encoding="utf-8")
    set_env_value(env, "CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-a")
    set_env_value(env, "CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-b")
    text = env.read_text(encoding="utf-8")
    assert text.count("CLAUDE_CODE_OAUTH_TOKEN=") == 1 and "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-b" in text
    assert text.startswith("# comment\nANTHROPIC_API_KEY=\nTELEGRAM_BOT_TOKEN=abc\n")
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600


