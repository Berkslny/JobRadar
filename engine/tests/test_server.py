import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from jobradar import db
from jobradar.cli import app as cli_app
from jobradar.config import load_config
from jobradar.locks import cycle_lock, cycle_running
from jobradar.mailer import MailError, build_digest, send_mail, smtp_settings
from jobradar.models import RawJob
from jobradar.pipeline import import_raws
from jobradar.scoring.fake import FakeLLM
from jobradar.web.app import create_app

DESC = ("Ihre Aufgaben\n• Entwicklung von FPGA-Designs in VHDL für Bildverarbeitung\n• Zynq SoC Integration\n"
        "Ihr Profil\n• Erfahrung mit VHDL\n• Gute Deutschkenntnisse\n" + "Wir bieten ein tolles Team. " * 15)
TOKEN = "test-token-1234567890"


def _seed(cfg, profile, n=1):
    conn = db.connect(cfg.db_path)
    raws = [RawJob(source="linkedin", title=f"FPGA-Entwickler {i} (m/w/d)", company=f"Nordlicht {i} GmbH",
                   location="München", url=f"https://www.linkedin.com/jobs/view/41000009{i:02d}", description=DESC)
            for i in range(n)]
    import_raws(conn, cfg, profile, raws)
    ids = [r["id"] for r in conn.execute("SELECT id FROM jobs ORDER BY id")]
    conn.close()
    return ids


def _app(cfg, runs=None):
    def runner(c):
        if runs is not None:
            runs.append(1)

    return create_app(cfg, llm_factory=lambda c: FakeLLM(), cycle_runner=runner)


def _wait(client, task, headers=None, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = client.get(f"/api/v1/tasks/{task['id']}", headers=headers or {}).json()
        if t["status"] != "running":
            return t
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def test_no_token_only_direct_local_requests(cfg, profile, monkeypatch):
    monkeypatch.delenv("JOBRADAR_API_TOKEN", raising=False)
    _seed(cfg, profile)
    c = TestClient(_app(cfg))
    assert c.get("/api/v1/summary").status_code == 200
    assert c.get("/jobs").status_code == 200
    r = c.get("/api/v1/summary", headers={"cf-connecting-ip": "203.0.113.5"})
    assert r.status_code == 403 and "JOBRADAR_API_TOKEN" in r.json()["detail"]
    assert c.get("/api/v1/health", headers={"cf-connecting-ip": "203.0.113.5"}).json()["ok"] is True


def test_token_protects_api_and_panel(cfg, profile, monkeypatch):
    monkeypatch.setenv("JOBRADAR_API_TOKEN", TOKEN)
    _seed(cfg, profile)
    c = TestClient(_app(cfg))
    assert c.get("/api/v1/summary").status_code == 401
    assert c.get("/api/v1/summary", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = c.get("/api/v1/summary", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200 and ok.json()["views"]["inbox"] == 1
    r = c.get("/jobs", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert c.get("/files/1/cv.html").status_code == 401
    r = c.post("/login", data={"token": "nope", "next": "/stats"}, follow_redirects=False)
    assert "error=" in r.headers["location"] and "jr_session" not in r.cookies
    r = c.post("/login", data={"token": TOKEN, "next": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/jobs" and "jr_session" in r.cookies
    page = c.get("/jobs")
    assert page.status_code == 200 and "Çıkış" in page.text
    c.post("/logout")
    c.cookies.clear()
    assert c.get("/jobs", follow_redirects=False).status_code == 303


def test_login_rate_limit(cfg, monkeypatch):
    monkeypatch.setenv("JOBRADAR_API_TOKEN", TOKEN)
    c = TestClient(_app(cfg))
    for _ in range(8):
        c.post("/login", data={"token": "bad"}, follow_redirects=False)
    r = c.post("/login", data={"token": TOKEN}, follow_redirects=False)
    assert "%C3%87ok%20fazla" in r.headers["location"] and "jr_session" not in r.cookies


def test_api_flow(cfg, profile, monkeypatch):
    monkeypatch.setenv("JOBRADAR_API_TOKEN", TOKEN)
    h = {"Authorization": f"Bearer {TOKEN}"}
    job_id = _seed(cfg, profile, n=2)[0]
    runs: list[int] = []
    c = TestClient(_app(cfg, runs))
    jobs = c.get("/api/v1/jobs", params={"view": "inbox", "order": "score"}, headers=h).json()["jobs"]
    assert len(jobs) == 2 and {"id", "title", "badges", "llm_score", "status_label"} <= set(jobs[0])
    assert any(b["label"].startswith("Almanca") for b in jobs[0]["badges"])

    task = c.post(f"/api/v1/jobs/{job_id}/evaluate", headers=h)
    assert task.status_code == 202 and task.json()["kind"] == "evaluate"
    done = _wait(c, task.json(), h)
    assert done["status"] == "done" and 0 <= done["result"]["score"] <= 5
    detail = c.get(f"/api/v1/jobs/{job_id}", headers=h).json()
    ev = detail["evaluation"]
    assert ev and ev["result"]["requirements"] and detail["description"].startswith("Ihre Aufgaben")
    used = {e for req in ev["result"]["requirements"] for e in (req.get("evidence") or [])}
    assert set(detail["facts"]) == used & set(detail["facts"])

    task = c.post(f"/api/v1/jobs/{job_id}/tailor", json={"language": "de"}, headers=h).json()
    done = _wait(c, task, h)
    assert done["status"] == "done" and done["result"]["doc_id"]
    doc_id = done["result"]["doc_id"]
    docs = c.get(f"/api/v1/jobs/{job_id}", headers=h).json()["documents"]
    assert docs[0]["id"] == doc_id and "cv.html" in docs[0]["files"]
    f = c.get(f"/api/v1/docs/{doc_id}/files/cv.html", headers=h)
    assert f.status_code == 200 and "html" in f.headers["content-type"]
    assert c.get(f"/api/v1/docs/{doc_id}/files/..%2Fjobradar.db", headers=h).status_code == 404
    assert c.post(f"/api/v1/docs/{doc_id}/approve", headers=h).json()["ok"]

    r = c.post(f"/api/v1/jobs/{job_id}/status", json={"status": "applied", "note": "portal"}, headers=h)
    assert r.json()["status"] == "applied"
    assert c.post(f"/api/v1/jobs/{job_id}/status", json={"status": "bogus"}, headers=h).status_code == 400
    assert c.post(f"/api/v1/jobs/{job_id}/notes", json={"notes": "HR: Frau X"}, headers=h).json()["ok"]
    assert c.get(f"/api/v1/jobs/{job_id}", headers=h).json()["notes"] == "HR: Frau X"
    assert c.get("/api/v1/jobs/doesnotexist", headers=h).status_code == 404

    stats = c.get("/api/v1/stats", headers=h).json()
    assert {x["status"] for x in stats["funnel"]} >= {"new", "applied"}
    assert c.post("/api/v1/run", headers=h).json()["started"] is True
    deadline = time.time() + 5
    while not runs and time.time() < deadline:
        time.sleep(0.02)
    assert runs == [1]

    b = c.get("/api/v1/backup", headers=h)
    assert b.status_code == 200 and b.content[:16] == b"SQLite format 3\x00"
    path = cfg.data_path / "restored.db"
    path.write_bytes(b.content)
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


def test_evaluate_without_llm_returns_503(cfg, profile, monkeypatch):
    monkeypatch.delenv("JOBRADAR_API_TOKEN", raising=False)
    job_id = _seed(cfg, profile)[0]
    c = TestClient(create_app(cfg, llm_factory=lambda c: None))
    r = c.post(f"/api/v1/jobs/{job_id}/evaluate")
    assert r.status_code == 503


def test_cycle_lock(tmp_path):
    with cycle_lock(tmp_path) as got:
        assert got and cycle_running(tmp_path)
        with cycle_lock(tmp_path) as second:
            assert second is False
    assert not cycle_running(tmp_path)


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        if password != "abcdefghijklmnop":
            import smtplib

            raise smtplib.SMTPAuthenticationError(535, b"bad")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_digest_and_mail(cfg, profile, monkeypatch):
    monkeypatch.setenv("SMTP_USER", "me@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.delenv("MAIL_TO", raising=False)
    monkeypatch.setenv("JOBRADAR_PUBLIC_URL", "https://jobradar.example.com/")
    cfg = load_config(cfg.config_path)
    s = smtp_settings(cfg)
    assert s and s.password == "abcdefghijklmnop" and s.to == "me@example.com"
    job_id = _seed(cfg, profile)[0]
    conn = db.connect(cfg.db_path)
    db.save_evaluation(conn, job_id, provider="fake", model="m", profile_hash="h", score=4.3, verdict="apply",
                       result={"summary": "Güçlü FPGA eşleşmesi"}, notes=[])
    conn.commit()
    d = build_digest(conn, cfg, profile.german_level)
    conn.close()
    assert d.strong == 1 and "1 yeni güçlü ilan" in d.subject
    assert "https://jobradar.example.com/jobs/" + job_id in d.text and "Güçlü FPGA eşleşmesi" in d.html
    FakeSMTP.sent = []
    send_mail(s, d.subject, d.text, d.html, smtp_factory=FakeSMTP)
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "me@example.com" and msg.is_multipart()
    s.password = "wrong"
    with pytest.raises(MailError, match="uygulama şifresi"):
        send_mail(s, "x", "y", smtp_factory=FakeSMTP)
    monkeypatch.setenv("SMTP_PASSWORD", "")
    assert smtp_settings(cfg) is None


def test_cli_api_token_backup_and_email_digest(workspace, profile, monkeypatch):
    runner = CliRunner()
    cfg_path = str(workspace / "jobradar.yaml")
    monkeypatch.delenv("JOBRADAR_API_TOKEN", raising=False)
    res = runner.invoke(cli_app, ["api-token", "-c", cfg_path])
    assert res.exit_code == 0, res.output
    env = (workspace / ".env").read_text(encoding="utf-8")
    token = env.split("JOBRADAR_API_TOKEN=")[1].split()[0]
    assert len(token) >= 40
    monkeypatch.delenv("JOBRADAR_API_TOKEN", raising=False)

    cfg = load_config(cfg_path)
    _seed(cfg, profile)
    res = runner.invoke(cli_app, ["backup", "-c", cfg_path])
    assert res.exit_code == 0, res.output
    assert len(list((workspace / "data" / "backups").glob("jobradar-*.db"))) == 1

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    FakeSMTP.sent = []
    res = runner.invoke(cli_app, ["email", "-c", cfg_path],
                        input="me@example.com\nabcd efgh ijkl mnop\n\n")
    assert res.exit_code == 0, res.output
    assert "SMTP_PASSWORD=abcdefghijklmnop" in (workspace / ".env").read_text(encoding="utf-8")
    assert FakeSMTP.sent and FakeSMTP.sent[0]["Subject"] == "JobRadar test"
    res = runner.invoke(cli_app, ["digest", "--email", "-c", cfg_path])
    assert res.exit_code == 0 and "gönderildi" in res.output
    res = runner.invoke(cli_app, ["digest", "--email", "-c", cfg_path])
    assert "zaten gönderildi" in res.output and len(FakeSMTP.sent) == 2
    for key in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"):
        monkeypatch.delenv(key, raising=False)


def test_env_overrides(workspace, monkeypatch):
    monkeypatch.setenv("JOBRADAR_PUBLIC_URL", "https://jobradar.example.com/")
    monkeypatch.setenv("JOBRADAR_CHROME_PATH", "/opt/chrome/chrome")
    monkeypatch.setenv("JOBRADAR_CLAUDE_PATH", "/home/u/.local/bin/claude")
    cfg = load_config(workspace / "jobradar.yaml")
    assert cfg.notify.dashboard_url == "https://jobradar.example.com" == cfg.server.public_url
    assert cfg.tailor.chrome_path == "/opt/chrome/chrome" and cfg.llm.claude_cli.path.endswith("/claude")


def test_serve_refuses_public_host_without_token(workspace, monkeypatch):
    monkeypatch.delenv("JOBRADAR_API_TOKEN", raising=False)
    res = CliRunner().invoke(cli_app, ["serve", "-c", str(workspace / "jobradar.yaml"), "--host", "0.0.0.0",
                                       "--no-open"])
    assert res.exit_code == 1 and "api-token" in res.output


def test_summary_shape(cfg, profile, monkeypatch):
    monkeypatch.delenv("JOBRADAR_API_TOKEN", raising=False)
    _seed(cfg, profile)
    data = TestClient(_app(cfg)).get("/api/v1/summary").json()
    assert {"views", "counts", "pending_evaluation", "strong_open", "running", "llm", "tracks", "statuses"} <= set(data)
    assert json.dumps(data)
