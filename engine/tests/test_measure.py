"""Measurement: your verdicts (labels), the rankings measured on them, and the record of model calls."""

from __future__ import annotations

import json
import math
import sqlite3
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from jobradar import db
from jobradar.cli import app as cli_app
from jobradar.models import RawJob
from jobradar.pipeline import evaluate_pending, import_raws
from jobradar.scoring import bench, usage
from jobradar.scoring.fake import FakeLLM
from jobradar.scoring.llm import BaseLLM, LLMError, LLMResult, OpenAICompatLLM, get_llm
from jobradar.web.app import create_app

DESC = ("Ihre Aufgaben\n• Entwicklung von FPGA-Designs in VHDL für Bildverarbeitung\n• Zynq SoC Integration\n"
        "Ihr Profil\n• Erfahrung mit VHDL\n• Gute Deutschkenntnisse\n" + "Wir bieten ein tolles Team. " * 15)
NOW = "2026-11-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_ranking_metrics_on_small_examples():
    assert bench.precision_at([2, 0, 1, 0], 2) == 0.5 and bench.precision_at([2, 0, 1, 0], 10) == 0.5
    assert bench.precision_at([], 5) is None
    assert bench.ndcg_at([2, 1, 0], 3) == 1.0 and bench.ndcg_at([0, 0], 3) is None
    assert bench.ndcg_at([0, 2], 2) == pytest.approx((2 / math.log2(3)) / 2, abs=1e-4)
    # every wanted posting above every unwanted one: 1.0; the reverse: 0.0; equal scores: 0.5
    assert bench.auc([(0.9, 2), (0.8, 1), (0.2, 0)]) == 1.0
    assert bench.auc([(0.1, 2), (0.8, 0)]) == 0.0
    assert bench.auc([(0.5, 2), (0.5, 0)]) == 0.5
    assert bench.auc([(3, 1), (2, 0), (2, 1), (1, 0)]) == pytest.approx(0.875)   # 3 wins and one tie of 4 pairs
    assert bench.auc([(1, 2), (2, 2)]) is None
    assert bench.cohen_kappa([(True, True), (False, False)] * 5) == 1.0
    assert bench.cohen_kappa([(True, False), (False, True)] * 5) == -1.0
    assert bench.cohen_kappa([(True, True)] * 4) is None and bench.cohen_kappa([]) is None
    # 7 of 10 agree; you say yes 6 times, the model 7 times: chance agreement 0.54
    pairs = [(True, True)] * 5 + [(False, False)] * 2 + [(False, True)] * 2 + [(True, False)]
    assert bench.cohen_kappa(pairs) == pytest.approx((0.7 - 0.54) / 0.46, abs=1e-4)


def test_what_you_did_with_a_posting_counts_as_a_verdict():
    assert bench.status_label("shortlisted", None) == 2 and bench.status_label("applied", NOW) == 2
    assert bench.status_label("skipped", None) == 0
    assert bench.status_label("rejected", NOW) == 2          # you applied; the company said no
    assert bench.status_label("rejected", None) is None and bench.status_label("closed", None) is None
    assert bench.status_label("new", None) is None and bench.status_label("filtered", None) is None


# ---------------------------------------------------------------------------
# A small world with known answers
# ---------------------------------------------------------------------------

TRACK_TR = "hiçbir hedef alana uymuyor"
TRACK_EN = "matches none of your target tracks"
# id: (status, quick score, AI score, filtered reason, applied)
JOBS = {
    "e1": ("new", 60, 4.6, None, None), "e2": ("new", 61, 4.2, None, None), "e3": ("new", 62, 4.0, None, None),
    "e4": ("new", 63, 3.6, None, None), "e5": ("new", 64, 3.0, None, None), "e6": ("new", 65, 2.5, None, None),
    "e7": ("new", 66, 2.0, None, None), "e8": ("new", 67, 4.4, None, None),
    "s1": ("shortlisted", 80, 4.5, None, None), "a1": ("applied", 75, None, None, NOW),
    "k1": ("skipped", 55, 3.8, None, None), "k2": ("skipped", 45, None, None, None),
    "r1": ("rejected", 68, 4.1, None, NOW), "r2": ("rejected", 58, None, None, None),
    "q1": ("new", 70, None, None, None), "q2": ("new", 50, None, None, None), "q3": ("new", 42, None, None, None),
    "l1": ("new", 30, None, None, None), "l2": ("new", 25, None, None, None), "l3": ("new", 20, None, None, None),
    "l4": ("new", 15, None, None, None), "l5": ("new", 10, None, None, None), "l6": ("new", 5, None, None, None),
    "l7": ("new", 3, None, None, None),
    "t1": ("filtered", 12, None, TRACK_TR, None), "t2": ("filtered", 11, None, TRACK_TR, None),
    "t3": ("filtered", 9, None, TRACK_TR, None), "t4": ("filtered", 8, None, TRACK_TR, None),
    "t5": ("filtered", 7, None, TRACK_TR, None), "t6": ("filtered", 6, None, TRACK_EN, None),
    "h1": ("filtered", 35, None, "kıdem: senior", None),
}
VERDICTS = {"e1": "good", "e2": "good", "e3": "maybe", "e4": "bad", "e5": "bad", "e6": "bad", "e7": "good",
            "q1": "good", "q2": "bad", "l1": "bad", "l2": "bad", "l3": "maybe", "l4": "bad", "l5": "bad",
            "l7": "skip", "t1": "good", "t2": "bad", "t3": "bad", "t4": "bad", "t5": "bad"}


def world(cfg):
    conn = db.connect(cfg.db_path)
    for job_id, (status, prescore, llm, reason, applied) in JOBS.items():
        db.insert_job(conn, {"id": job_id, "title": f"Posting {job_id}", "company": "Acme", "status": status,
                             "prescore": prescore, "llm_score": llm, "filtered_reason": reason, "applied_at": applied,
                             "description": DESC, "first_seen": NOW, "last_seen": NOW,
                             "url": f"https://example.com/{job_id}"})
    conn.commit()
    return conn


def test_label_queue_takes_turns_between_the_groups(cfg, profile):
    conn = world(cfg)
    ids, remaining = bench.label_queue(conn, cfg, limit=8)
    assert remaining == {"evaluated": 8, "queue": 3, "low_score": 7, "track_filtered": 6}
    assert [i[0] for i in ids] == ["e", "q", "l", "t", "e", "q", "l", "t"]    # one of each group in turn
    assert bench.label_queue(conn, cfg, limit=8)[0] == ids                    # the order is fixed, not random per call
    assert len(bench.label_queue(conn, cfg, limit=50)[0]) == 24               # decided and rule-filtered ones are not asked
    bench.set_label(conn, ids[0], "good")
    bench.set_label(conn, ids[1], "skip")
    again, remaining = bench.label_queue(conn, cfg, limit=8)
    assert ids[0] not in again and ids[1] not in again and remaining["evaluated"] == 7 and remaining["queue"] == 2
    with pytest.raises(ValueError):
        bench.set_label(conn, ids[2], "great")
    assert bench.set_label(conn, ids[0], "") is None and db.get_label(conn, ids[0]) is None


def test_measurements_through_the_api(cfg, profile):
    world(cfg).close()
    client = TestClient(create_app(cfg, llm_factory=lambda c: FakeLLM(), cycle_runner=lambda c: None))
    queue = client.get("/api/v1/labels/queue?limit=4").json()
    assert len(queue["jobs"]) == 4 and queue["remaining"] == 24 and queue["judged"] == 0
    first = queue["jobs"][0]
    assert first["description"].startswith("Ihre Aufgaben") and first["title"].startswith("Posting")
    assert client.put("/api/v1/jobs/nope/label", json={"label": "good"}).status_code == 404
    bad = client.put("/api/v1/jobs/e1/label", json={"label": "great"}, headers={"X-JobRadar-Lang": "en"})
    assert bad.status_code == 422 and bad.json()["detail"] == "invalid label: great"
    for job_id, verdict in VERDICTS.items():
        assert client.put(f"/api/v1/jobs/{job_id}/label", json={"label": verdict}).json() == \
            {"job_id": job_id, "label": verdict}
    assert client.get("/api/v1/jobs/e3").json()["label"] == "maybe" and client.get("/api/v1/jobs/e8").json()["label"] is None
    queue = client.get("/api/v1/labels/queue?limit=50").json()
    assert {j["id"] for j in queue["jobs"]} == {"e8", "q3", "l6", "t6"} and queue["judged"] == 19

    data = client.get("/api/v1/bench", headers={"X-JobRadar-Lang": "en"}).json()
    assert data["labels"] == {"total": 24, "explicit": 19, "from_status": 5, "good": 8, "maybe": 2, "bad": 14,
                              "needed": 30, "enough": False}
    # rankings on the 24 judged postings: the quick score, and the AI score where there is one
    assert data["rankings"]["n"] == 24 and data["rankings"]["semantic"] is False
    quick, ai = data["rankings"]["rows"]
    assert (quick["id"], quick["name"], quick["n"], quick["wanted"]) == ("prescore", "Quick score (keywords)", 24, 10)
    assert quick["precision_at_10"] == 0.7 and quick["budget"] == 20 and quick["budget_hit_rate"] == 0.5
    gains = [2, 2, 2, 2, 2, 0, 0, 0, 1, 2]           # the first ten by quick score: s1 a1 q1 r1 e7 e6 e5 e4 e3 e2
    ideal = [2] * 8 + [1, 1]
    dcg = lambda seq: sum(g / math.log2(i + 2) for i, g in enumerate(seq))  # noqa: E731
    assert quick["ndcg_at_10"] == pytest.approx(dcg(gains) / dcg(ideal), abs=1e-3)
    assert quick["auc"] == pytest.approx(114 / 140, abs=1e-3)
    assert (ai["id"], ai["n"], ai["precision_at_10"]) == ("llm", 10, 0.6) and ai["auc"] == pytest.approx(20 / 24, abs=1e-3)
    # the gate: what the AI model sees (evaluated, queue) and what it never sees (low score, track rule)
    groups = {g["id"]: g for g in data["gate"]["groups"]}
    assert groups["evaluated"] == {"id": "evaluated", "postings": 11, "judged": 7, "wanted": 4, "rate": 0.5714,
                                   "estimated_wanted": 6.3}
    assert groups["queue"]["postings"] == 3 and groups["queue"]["rate"] is None            # too few verdicts
    assert groups["low_score"] == {"id": "low_score", "postings": 7, "judged": 5, "wanted": 1, "rate": 0.2,
                                   "estimated_wanted": 1.4}
    assert groups["track_filtered"]["postings"] == 6 and groups["track_filtered"]["estimated_wanted"] == 1.2
    assert data["gate"]["estimated_missed"] == 2.6 and data["gate"]["estimated_recall"] is None
    # the judge: the AI verdict next to yours on the ten postings that have both
    judge = data["judge"]
    assert (judge["n"], judge["both_yes"], judge["both_no"], judge["only_ai_yes"], judge["only_you_yes"]) == (10, 5, 2, 2, 1)
    assert judge["agreement"] == 0.7 and judge["hit_rate"] == 0.6 and judge["kappa"] == pytest.approx(0.3478, abs=1e-4)
    assert data["usage"]["calls"] == 0 and data["matching"] == {"enabled": False, "scored": 0}
    # only the verdicts you gave yourself
    own = client.get("/api/v1/bench?explicit=true").json()
    assert own["labels"]["total"] == 19 and own["labels"]["from_status"] == 0 and own["judge"]["n"] == 7
    # with verdicts in the queue group as well, the share the gate lets through can be estimated
    for job_id in ("q3", "e8"):
        client.put(f"/api/v1/jobs/{job_id}/label", json={"label": "bad"})
    conn = db.connect(cfg.db_path)
    for i in range(3):
        db.insert_job(conn, {"id": f"q9{i}", "title": "Q", "status": "new", "prescore": 44, "first_seen": NOW,
                             "last_seen": NOW})
        db.set_label(conn, f"q9{i}", 0)
    conn.commit()
    gate = client.get("/api/v1/bench").json()["gate"]
    inside = 11 * 4 / 8 + 6 * 1 / 6                    # evaluated: 4 of 8 wanted; queue: 1 of 6
    assert gate["estimated_recall"] == pytest.approx(inside / (inside + 2.6), abs=1e-3)


def test_rankings_are_compared_on_the_postings_that_have_a_semantic_score(cfg, profile):
    from jobradar.scoring import embed, match

    cfg.matching.enabled = True
    conn = db.connect(cfg.db_path)
    model, qhash = match.current_keys(cfg, profile)
    assert model == embed.model_key(cfg)
    # 40 judged postings: the quick score is blind (wanted and unwanted alternate), the semantic score sees them
    for i in range(40):
        wanted = i % 2 == 0
        db.insert_job(conn, {"id": f"j{i:02d}", "title": "T", "status": "shortlisted" if wanted else "skipped",
                             "prescore": 50 + i, "first_seen": NOW, "last_seen": NOW})
        conn.execute("INSERT INTO job_match (job_id, model, query_hash, text_hash, semantic, track_sim, updated_at) "
                     "VALUES (?, ?, ?, 't', ?, 0, ?)",
                     (f"j{i:02d}", model, qhash if i < 36 else "stale", (0.8 if wanted else 0.2) + i / 1000, NOW))
    conn.commit()
    data = bench.report(conn, cfg, profile)
    assert data["labels"]["total"] == 40 and data["labels"]["enough"] is True
    assert data["matching"] == {"enabled": True, "scored": 36}     # four scores belong to an earlier profile
    rankings = data["rankings"]
    assert rankings["n"] == 36 and rankings["semantic"] is True
    rows = {r["id"]: r for r in rankings["rows"]}
    assert set(rows) == {"prescore", "semantic", "fused"} and all(r["n"] == 36 for r in rows.values())
    assert rows["semantic"]["auc"] == 1.0 and rows["semantic"]["precision_at_10"] == 1.0
    assert rows["prescore"]["precision_at_10"] == 0.5 and 0.4 < rows["prescore"]["auc"] < 0.6
    assert rows["prescore"]["auc"] < rows["fused"]["auc"] <= 1.0
    # with matching off, the stored scores are not used
    cfg.matching.enabled = False
    assert bench.report(conn, cfg, profile)["rankings"]["semantic"] is False


def test_bench_and_label_commands(workspace, profile):
    from jobradar.config import load_config

    cfg = load_config(workspace / "jobradar.yaml")
    world(cfg).close()
    runner = CliRunner()
    args = ["-c", str(workspace / "jobradar.yaml")]
    assert runner.invoke(cli_app, ["label", "e1", "good", *args]).exit_code == 0
    res = runner.invoke(cli_app, ["label", "e2", "great", *args])
    assert res.exit_code == 1 and "great" in res.output
    assert "etiket silindi" in runner.invoke(cli_app, ["label", "e1", "clear", *args]).output
    for job_id, verdict in VERDICTS.items():
        assert runner.invoke(cli_app, ["label", job_id, verdict, *args]).exit_code == 0
    res = runner.invoke(cli_app, ["bench", *args])
    assert res.exit_code == 0, res.output
    assert "24 ilan" in res.output and "Sıralamalar" in res.output and "kappa 0.35" in res.output
    assert "~2.6" in res.output and "en az 30 karar" in res.output
    data = json.loads(runner.invoke(cli_app, ["bench", "--json", "--explicit", *args]).output)
    assert data["labels"]["total"] == 19 and data["explicit_only"] is True
    res = runner.invoke(cli_app, ["match", "--status", *args])
    assert res.exit_code == 0 and "puanlı ilan: 0" in res.output
    res = runner.invoke(cli_app, ["match", *args])
    assert res.exit_code == 1 and "matching.enabled" in res.output


# ---------------------------------------------------------------------------
# The record of model calls
# ---------------------------------------------------------------------------


def test_usage_shapes_of_the_providers():
    assert usage.normalize({"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 5,
                            "cache_read_input_tokens": 7, "api_equivalent_usd": 0.0123}) == (112, 20, 0.0123)
    assert usage.normalize({"prompt_tokens": 50, "completion_tokens": 9, "total_tokens": 59}) == (50, 9, None)
    assert usage.normalize({"prompt_eval_count": 40, "eval_count": 8}) == (40, 8, None)
    assert usage.normalize({"prompt_eval_count": None, "eval_count": None}) == (None, None, None)
    assert usage.normalize({}) == (None, None, None) and usage.normalize(None) == (None, None, None)
    assert usage.purpose_of("TASK: EVALUATE\nOUTPUT...") == "evaluate"
    assert usage.purpose_of("TASK: READ CV\n\n## CV text") == "profile_import"
    assert usage.purpose_of("TASK: SET UP SEARCH\nCOUNTRY") == "search_setup"
    assert usage.purpose_of("Reply with a JSON object") == "other"


def calls(cfg):
    conn = db.connect(cfg.db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM llm_calls ORDER BY id")]
    finally:
        conn.close()


def test_every_model_call_is_recorded_without_its_text(cfg, profile):
    conn = db.connect(cfg.db_path)
    import_raws(conn, cfg, profile, [RawJob(source="linkedin", title="FPGA-Entwickler (m/w/d)", company="Nordlicht",
                                            location="München", url="https://www.linkedin.com/jobs/view/4100000701",
                                            description=DESC)])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    llm = usage.attach(FakeLLM(), cfg.db_path)
    assert usage.attach(llm, cfg.db_path) is llm                  # attaching twice records once
    assert evaluate_pending(conn, cfg, profile, llm, log=lambda m: None)
    rows = calls(cfg)
    assert len(rows) == 1
    row = rows[0]
    assert (row["purpose"], row["job_id"], row["ok"], row["provider"], row["model"]) == \
        ("evaluate", job_id, 1, "demo", "demo-heuristic")
    assert row["prompt_chars"] > 1000 and row["output_chars"] > 100 and row["input_tokens"] is None
    assert not any("FPGA" in str(v) for v in row.values())        # sizes only, no prompt and no answer

    class Broken(BaseLLM):
        provider = "broken"

        def model_for(self, tier):
            return "m1"

        def complete(self, system, user, *, tier="fast", max_tokens=4000):
            raise LLMError("usage limit reached")

    broken = usage.attach(Broken(), cfg.db_path)
    with pytest.raises(LLMError):
        with usage.tagged(purpose="test"):
            broken.complete("s", "TASK: TAILOR\n...")
    row = calls(cfg)[-1]
    assert (row["ok"], row["purpose"], row["model"], row["job_id"]) == (0, "test", "m1", None)
    assert "usage limit" in row["error"]

    class Counted(BaseLLM):
        provider = "claude_cli"

        def model_for(self, tier):
            return "haiku"

        def complete(self, system, user, *, tier="fast", max_tokens=4000):
            return LLMResult(text="{}", provider=self.provider, model="haiku",
                             usage={"input_tokens": 900, "output_tokens": 100, "cache_read_input_tokens": 100,
                                    "api_equivalent_usd": 0.02})

    counted = usage.attach(Counted(), cfg.db_path)
    counted.complete("s", "TASK: TAILOR\n...")
    counted.complete("s", "TASK: REVIEW\n...")
    summary = usage.summary(conn, days=30)
    assert (summary["calls"], summary["failed"], summary["input_tokens"], summary["output_tokens"]) == (4, 1, 2000, 200)
    assert summary["cost_usd"] == 0.04
    by = {p["purpose"]: p for p in summary["by_purpose"]}
    assert by["tailor"]["avg_input_tokens"] == 1000 and by["evaluate"]["avg_input_tokens"] is None
    assert by["test"]["failed"] == 1 and by["review"]["cost_usd"] == 0.02
    assert bench.report(conn, cfg, profile)["usage"]["calls"] == 4


def test_get_llm_records_and_a_busy_database_never_blocks_a_call(cfg, monkeypatch):
    cfg.llm.provider = "openai"
    cfg.llm.openai.base_url = "http://localhost:1234/v1"
    cfg.llm.openai.fast_model = "local-model"
    llm = get_llm(cfg)
    assert isinstance(llm, OpenAICompatLLM)                       # the same object, only its calls are recorded
    llm.client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "choices": [{"message": {"content": "{\"ok\": true}"}}], "usage": {"prompt_tokens": 11, "completion_tokens": 7}})))
    assert llm.complete("system", "user").text == '{"ok": true}'
    row = calls(cfg)[-1]
    assert (row["provider"], row["model"], row["input_tokens"], row["output_tokens"], row["purpose"]) == \
        ("local", "local-model", 11, 7, "other")
    # another writer holds the database: the call returns at once, its record is written with the next one
    monkeypatch.setattr(usage, "BUSY_SECONDS", 0.05)
    holder = sqlite3.connect(str(cfg.db_path), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    llm.complete("system", "user")
    assert time.monotonic() - started < 2 and len(calls(cfg)) == 1
    holder.execute("COMMIT")
    holder.close()
    llm.complete("system", "user")
    assert len(calls(cfg)) == 3


def test_databases_of_earlier_versions_get_the_new_tables(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(str(path))
    old.executescript(db.SCHEMA.split("-- Your own verdict")[0])   # the tables of version 1.0
    old.commit()
    assert not old.execute("SELECT 1 FROM sqlite_master WHERE name = 'llm_calls'").fetchone()
    old.close()
    usage.record(path, {"ts": NOW, "provider": "p", "model": "m", "tier": "fast", "purpose": "other", "ok": 1,
                        "error": "", "seconds": 0.1, "prompt_chars": 1, "output_chars": 1})
    conn = sqlite3.connect(str(path))
    assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 0
    conn.close()
    # opening it the normal way adds the rest and keeps what was there
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM job_match").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 1
