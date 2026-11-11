import json
import subprocess

import httpx
import pytest

from jobradar import db
from jobradar.models import RawJob
from jobradar.pipeline import evaluate_pending, import_raws
from jobradar.scoring.evaluate import Evaluation, verify
from jobradar.scoring.fake import FakeLLM
from jobradar.scoring.llm import (AnthropicLLM, ClaudeCLILLM, LLMError, OllamaLLM, complete_json, extract_json,
                                  get_llm, is_fatal, llm_hint)
from jobradar.tailor.generate import tailor_job
from jobradar.tailor.validate import TailoredDocs, Validator, job_terms, strip_violations

JOB_TEXT = """Ihre Aufgaben
• Entwicklung von FPGA-Designs in VHDL
• Integration auf Zynq SoC Plattformen
• Testautomatisierung mit Python und Jenkins
Ihr Profil
• Erfahrung mit VHDL oder Verilog
• Kenntnisse in MATLAB von Vorteil
• Gute Deutschkenntnisse"""


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here: {"a": {"b": "x}"}} trailing') == {"a": {"b": "x}"}}
    with pytest.raises(ValueError):
        extract_json('{"a": 1')


def test_complete_json_retries_once():
    answers = iter(["not json at all", json.dumps({"summary": "ok", "global_score": 4.2})])
    llm = FakeLLM(responder=lambda s, u: next(answers))
    ev, _ = complete_json(llm, "sys", "user", Evaluation)
    assert ev.global_score == 4.2 and len(llm.calls) == 2
    assert "INVALID" in llm.calls[1][1]


def test_anthropic_client_request_shape():
    seen = {}

    def handler(request: httpx.Request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"x": 1}'}], "usage": {"input_tokens": 5}})

    llm = AnthropicLLM("sk-test", "claude-haiku-5-5", "claude-sonnet-5-5",
                       client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = llm.complete("SYS", "USER", tier="smart")
    assert res.text == '{"x": 1}' and res.model == "claude-sonnet-5-5"
    assert seen["headers"]["x-api-key"] == "sk-test" and seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["body"]["system"] == "SYS" and seen["body"]["messages"][0]["content"] == "USER"

    def bad(request):
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    with pytest.raises(LLMError, match="401"):
        AnthropicLLM("k", "a", "b", client=httpx.Client(transport=httpx.MockTransport(bad))).complete("s", "u")


def test_claude_cli_parsing():
    def runner(cmd, **kw):
        assert cmd[:4] == ["claude", "-p", "--output-format", "json"] and "--model" in cmd
        assert kw["input"].startswith("SYS")
        out = json.dumps({"type": "result", "is_error": False, "result": '{"ok": true}', "total_cost_usd": 0.01})
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    res = ClaudeCLILLM("claude", "haiku", "sonnet", runner=runner).complete("SYS", "USER")
    assert res.text == '{"ok": true}' and res.usage["api_equivalent_usd"] == 0.01


def test_claude_cli_lean_flags_with_fallback():
    calls: list[list[str]] = []

    def old_cli(cmd, **kw):
        calls.append(cmd)
        if "--tools" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error: unknown option '--tools'")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"is_error": False, "result": "OK"}), stderr="")

    llm = ClaudeCLILLM("claude", "haiku", "sonnet", runner=old_cli)
    assert llm.complete("s", "u").text == "OK" and llm.lean is False
    assert calls[0][-2:] == ["--tools", ""] and "--no-session-persistence" in calls[0]
    llm.complete("s", "u")
    assert len(calls) == 3 and "--tools" not in calls[2]


def test_claude_cli_never_passes_paid_credentials(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-paid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "x")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-sub")
    seen: dict = {}

    def runner(cmd, **kw):
        seen.update(kw["env"])
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"is_error": False, "result": "OK"}), stderr="")

    ClaudeCLILLM("claude", "haiku", "sonnet", runner=runner).complete("s", "u")
    assert seen["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-sub"
    assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"} & set(seen)


def test_usage_limit_stops_and_explains():
    msg = "Claude CLI: Claude AI usage limit reached|1762650000"
    assert is_fatal(msg)
    assert "extra usage" in llm_hint("claude_cli", msg)
    assert "/login" in llm_hint("claude_cli", "Failed to authenticate. OAuth session expired")


def test_ollama_native_api():
    seen: dict = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": '{"ok": true}'}, "eval_count": 4})

    llm = OllamaLLM("http://localhost:11434/v1", "qwen3:8b", "", 16384,
                    client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = llm.complete("SYS", "USER", tier="smart")
    assert seen["url"] == "http://localhost:11434/api/chat"
    body = seen["body"]
    assert body["format"] == "json" and body["stream"] is False and body["options"]["num_ctx"] == 16384
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert res.model == "qwen3:8b" and res.provider == "ollama" and json.loads(res.text) == {"ok": True}

    def missing(request):
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(LLMError, match="ollama pull"):
        OllamaLLM("http://localhost:11434", "nope", "", client=httpx.Client(transport=httpx.MockTransport(missing))
                  ).complete("s", "u")

    def failing(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"is_error": True, "result": "limit reached"}), stderr="")

    with pytest.raises(LLMError, match="limit"):
        ClaudeCLILLM("claude", "haiku", "sonnet", runner=failing).complete("s", "u")


def test_get_llm_never_picks_paid_api_by_default(cfg, monkeypatch):
    assert cfg.llm.allow_paid_api is False
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-y")
    cfg.llm.openai.fast_model = "gpt-x"
    cfg.llm.provider = "auto"
    assert get_llm(cfg) is None
    for prov in ("anthropic", "openai"):
        cfg.llm.provider = prov
        with pytest.raises(LLMError, match="Ücretli API kapalı"):
            get_llm(cfg)
    cfg.llm.openai.base_url = "http://localhost:1234/v1"
    assert get_llm(cfg).provider == "local"
    cfg.llm.allow_paid_api = True
    cfg.llm.provider = "anthropic"
    assert get_llm(cfg).provider == "anthropic"
    cfg.llm.provider = "auto"
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    assert get_llm(cfg).provider == "claude_cli"
    cfg.llm.provider = "claude_cli"
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(LLMError, match="bulunamadı"):
        get_llm(cfg)


def test_verify_enforces_evidence(cfg, profile):
    ev = Evaluation.model_validate({
        "track": "nonexistent", "summary": "s", "global_score": 4.8, "verdict": "apply",
        "requirements": [
            {"requirement": "VHDL", "importance": "must", "match": "strong", "evidence": ["FPGA-1", "FAKE-9"]},
            {"requirement": "MATLAB", "importance": "must", "match": "strong", "evidence": []},
            {"requirement": "Jenkins", "importance": "must", "match": "partial", "evidence": []},
            {"requirement": "Radar", "importance": "must", "match": "gap"},
        ],
        "dimensions": {"cv_match": 9, "north_star": "4"},
    })
    job = {"track": "fpga", "flags": {"german_gap": 2, "german_level": "C1", "clearance": "Ü2"}}
    ev, notes = verify(ev, profile, job, cfg)
    reqs = ev.requirements
    assert reqs[0].evidence == ["FPGA-1"]
    assert reqs[1].match == "partial" and reqs[2].match == "partial"
    assert ev.global_score <= 3.9 and ev.verdict in ("maybe", "skip")
    assert ev.dimensions.cv_match == 5.0
    assert ev.track == "fpga"
    assert any("Almanca" in r for r in ev.red_flags) and any("soruşturma" in r for r in ev.red_flags)
    assert notes


def test_verify_caps_unmet_citizenship(cfg, profile):
    ev = Evaluation.model_validate({"summary": "s", "global_score": 4.6, "requirements": [
        {"requirement": "VHDL", "match": "strong", "evidence": ["FPGA-1"]}]})
    ev, _ = verify(ev, profile, {"flags": {"citizenship": "DE", "citizenship_ok": False}}, cfg)
    assert ev.global_score == 2.5 and ev.verdict == "skip"


def test_validator_catches_fabrication(profile):
    job = {"description": JOB_TEXT, "company": "Nordlicht GmbH", "title": "FPGA-Entwickler"}
    v = Validator(profile, job)
    assert {"vhdl", "zynq", "python", "jenkins", "matlab"} <= job_terms(JOB_TEXT)
    docs = TailoredDocs.model_validate({
        "headline": "FPGA Engineer",
        "summary": {"text": "FPGA engineer.", "facts": ["GEN-1"]},
        "experience": [{"entry_id": "FPGA", "bullets": [
            {"text": "Developed VHDL designs for UAV vision systems.", "facts": ["FPGA-1"]},
            {"text": "Automated tests with Python and Jenkins.", "facts": ["FPGA-1"]},
            {"text": "Improved throughput by 40%.", "facts": ["FPGA-2"]},
            {"text": "Optimised charging with MILP.", "facts": ["THES-1"]},
            {"text": "Led the team.", "facts": []},
        ]}],
        "skills": ["FPGA", "VHDL", "MATLAB"],
        "cover_letter": {"subject": "Bewerbung", "salutation": "Hallo", "paragraphs": [
            {"text": "Bei Nordlicht GmbH möchte ich als FPGA-Entwickler meine Erfahrung mit VHDL einbringen.", "facts": ["FPGA-1"]},
            {"text": "Ich habe 5 Jahre MATLAB-Erfahrung.", "facts": []},
        ], "closing": "MfG"},
        "answers": [{"question": "Gehalt?", "answer": "[Gehaltsvorstellung]", "facts": []}],
    })
    rep = v.validate(docs)
    msgs = [f"{x.where}: {x.message}" for x in rep.errors]
    joined = "\n".join(msgs)
    assert "madde 2" in joined and "'python'" in joined and "'jenkins'" in joined
    assert "madde 3" in joined and "40" in joined
    assert "madde 4" in joined and "başka bir girişe ait" in joined
    assert "madde 5" in joined and "hiçbir gerçeğe dayanmıyor" in joined
    assert "'MATLAB'" in joined
    assert "paragraf 2" in joined and "matlab" in joined.lower()
    assert "madde 1" not in joined and "paragraf 1" not in joined and "Cevap" not in joined
    cleaned = strip_violations(docs, rep)
    assert [b.text for b in cleaned.experience[0].bullets] == ["Developed VHDL designs for UAV vision systems."]
    assert cleaned.skills == ["FPGA", "VHDL"] and len(cleaned.cover_letter.paragraphs) == 1
    assert v.validate(cleaned).ok


def _seed(cfg, profile):
    conn = db.connect(cfg.db_path)
    import_raws(conn, cfg, profile, [RawJob(
        source="linkedin", title="FPGA-Entwickler (m/w/d)", company="Nordlicht GmbH", location="München",
        url="https://www.linkedin.com/jobs/view/4100000777", description=JOB_TEXT + "\n" + "Wir bieten viel. " * 20)])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    return conn, job_id


def test_evaluate_and_tailor_end_to_end_with_repair(cfg, profile):
    conn, job_id = _seed(cfg, profile)
    res = evaluate_pending(conn, cfg, profile, FakeLLM(), log=lambda m: None)
    assert res and res[0][0] == job_id
    assert db.latest_evaluation(conn, job_id)["result"]["requirements"]

    bad = {"headline": "FPGA", "summary": {"text": "x", "facts": []},
           "experience": [{"entry_id": "FPGA", "bullets": [{"text": "Built Jenkins pipelines.", "facts": ["FPGA-1"]}]}],
           "skills": ["FPGA"], "cover_letter": {"subject": "s", "salutation": "s", "paragraphs": [], "closing": "c"},
           "answers": []}
    good = {**bad, "experience": [{"entry_id": "FPGA", "bullets": [
        {"text": "Developed VHDL and Verilog FPGA designs for UAV vision.", "facts": ["FPGA-1"]}]}]}
    answers = iter([json.dumps(bad), json.dumps(good)])
    ok_review = json.dumps({"verdict": "ok", "summary": "iyi", "issues": []})
    llm = FakeLLM(responder=lambda s, u: ok_review if u.startswith("TASK: REVIEW") else next(answers))
    doc = tailor_job(cfg, profile, conn, job_id, llm)
    assert doc["version"] == 1 and doc["validation"]["ok"] and doc["validation"]["repair_rounds"] == 1
    assert doc["validation"]["review"]["verdict"] == "ok" and not doc["validation"]["review"]["applied"]
    assert "Validator rejected" not in llm.calls[0][1] and "validator rejected" in llm.calls[1][1].lower()
    folder = cfg.applications_path / doc["folder"]
    cv = (folder / "cv.md").read_text(encoding="utf-8")
    assert "Developed VHDL and Verilog FPGA designs" in cv and "Jenkins" not in cv
    assert (folder / "anschreiben.md").exists()  # German posting -> German letter file
    assert db.get_job(conn, job_id)["status"] == "tailored"

    # Second version: still-bad output after repair gets stripped, never shipped.
    answers2 = iter([json.dumps(bad), json.dumps(bad)])
    doc2 = tailor_job(cfg, profile, conn, job_id,
                      FakeLLM(responder=lambda s, u: ok_review if u.startswith("TASK: REVIEW") else next(answers2)))
    assert doc2["version"] == 2 and doc2["validation"]["removed"]
    cv2 = (cfg.applications_path / doc2["folder"] / "cv.md").read_text(encoding="utf-8")
    assert "Jenkins" not in cv2
    assert doc2["folder"].split("/")[0] == doc["folder"].split("/")[0]


def test_evaluation_stops_on_expired_login(cfg, profile):
    conn, job_id = _seed(cfg, profile)
    from jobradar.pipeline import import_raws as _imp
    from jobradar.models import RawJob as _R

    _imp(conn, cfg, profile, [_R(source="indeed", title="FPGA Engineer", company="Other GmbH", location="Köln",
                                 url="https://de.indeed.com/viewjob?jk=zz9", description=JOB_TEXT + " x" * 200)])
    calls = []

    class Expired(FakeLLM):
        provider = "claude_cli"

        def complete(self, system, user, *, tier="fast", max_tokens=4000):
            calls.append(1)
            raise LLMError("Claude CLI: Failed to authenticate: OAuth session expired and could not be refreshed")

    logs = []
    res = evaluate_pending(conn, cfg, profile, Expired(), log=logs.append)
    assert res == [] and len(calls) == 1
    assert any("/login" in m for m in logs)
