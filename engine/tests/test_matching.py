"""Semantic matching: embedding backends, scores, the fused evaluation order and promotions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import types

import httpx
import pytest
from fastapi.testclient import TestClient

from jobradar import db
from jobradar.cli import run_cycle
from jobradar.http import make_client
from jobradar.models import RawJob
from jobradar.pipeline import enrich_pending, evaluation_queue, import_raws, refilter_all
from jobradar.scoring import embed, match
from jobradar.scoring.fake import FakeLLM
from jobradar.sources.base import Source
from jobradar.web.app import create_app

DESC = ("Ihre Aufgaben\n• Entwicklung von FPGA-Designs in VHDL für Bildverarbeitung\n• Zynq SoC Integration\n"
        "Ihr Profil\n• Erfahrung mit VHDL\n• Gute Deutschkenntnisse\n" + "Wir bieten ein tolles Team. " * 15)
# close to the FPGA track in meaning, but without a title keyword and with fewer than three keywords in the text
HIDDEN = ("Your tasks\n- You take part in the development of programmable logic and hardware for aerospace and "
          "sensor systems\n- You write and verify digital circuits for flight computers\nYour profile\n"
          "- Degree in electrical engineering, junior or career starter\n"
          "- You enjoy hardware close work in a small team anywhere in Germany\n"
          + "We are a friendly company with a long history. " * 5)
OFF = ("Your tasks\n- You prepare the monthly accounts and the annual report\n- You support the tax advisers\n"
       "Your profile\n- Training in bookkeeping\n- Careful way of working with numbers and invoices\n"
       + "We are a friendly company with a long history. " * 5)


# no keyword and nothing in common with any track: what the keyword rules turn away in every scan
OFFICE = ("Deine Aufgaben\n- Du begrüßt Gäste am Empfang und nimmst Anrufe entgegen\n- Du buchst Besprechungsräume und "
          "bestellst das Mittagessen\nDas bringst du mit\n- Freundliches Auftreten und Freude am Telefonieren\n"
          "- Du hältst das Büro ordentlich und kümmerst dich um die Post\n" + "Unser Haus liegt mitten in der Altstadt. " * 6)


class WordEmbedder:
    """Stand-in for an embedding model: texts that share words get similar vectors. Records what it is asked."""

    provider, model = "fake", "words"

    def __init__(self):
        self.calls: list[tuple[list[str], bool]] = []

    def embed(self, texts, *, query=False):
        self.calls.append((list(texts), query))
        out = []
        for text in texts:
            vec = [0.0] * 96
            for word in re.findall(r"[a-zäöüß]{3,}", text.lower()):
                vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 96] += 1.0
            out.append(embed.unit(vec))
        return out

    def documents(self) -> int:
        return sum(len(texts) for texts, query in self.calls if not query)

    def queries(self) -> int:
        return sum(len(texts) for texts, query in self.calls if query)


def fpga_jobs(n=22):
    return [RawJob(source="linkedin", title=f"FPGA-Entwickler {i} (m/w/d)", company=f"Nordlicht {i} GmbH",
                   location="München", url=f"https://www.linkedin.com/jobs/view/41000009{i:02d}", description=DESC)
            for i in range(n)]


def hidden_job(i=1, description=HIDDEN, **extra):
    return RawJob(source="indeed", title=f"Ingenieur programmierbare Logik {i}", company=f"Himmel {i} AG",
                  location="Bremen", url=f"https://de.indeed.com/viewjob?jk=h{i}", description=description, **extra)


def office_jobs(n=12):
    return [RawJob(source="indeed", title=f"Empfangskraft {i}", company=f"Büro {i} KG", location="Bremen",
                   url=f"https://de.indeed.com/viewjob?jk=e{i}", description=OFFICE) for i in range(n)]


def seed(cfg, profile, raws):
    cfg.matching.enabled = True
    conn = db.connect(cfg.db_path)
    import_raws(conn, cfg, profile, raws)
    return conn


def by_title(conn, start):
    return db.row_to_job(conn.execute("SELECT * FROM jobs WHERE title LIKE ?", (start + "%",)).fetchone())


def match_row(conn, job_id):
    row = conn.execute("SELECT * FROM job_match WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Texts, fusion, vectors
# ---------------------------------------------------------------------------


def test_job_chunks_prefer_tasks_and_requirements():
    text = ("Über uns\nWir sind ein führendes Unternehmen der Luftfahrt mit 500 Mitarbeitern.\n\n"
            "Ihre Aufgaben\n• Entwicklung von FPGA-Designs in VHDL\n• Zynq SoC Integration\nIhr Profil\n"
            "• Erfahrung mit VHDL\nWir bieten\n• 30 Tage Urlaub\n• Jobrad\nKontakt\nFrau Muster, Tel. 123")
    chunks = match.job_chunks("FPGA-Entwickler (m/w/d)", text)
    assert chunks[0] == "FPGA-Entwickler"                       # gender marker gone, the title stands alone
    assert len(chunks) == 2 and chunks[1].startswith("Ihre Aufgaben\nEntwicklung von FPGA-Designs")
    assert "Erfahrung mit VHDL" in chunks[1]
    assert not any(word in " ".join(chunks) for word in ("Urlaub", "Jobrad", "führendes", "Frau Muster"))
    # a posting without headings is cut into pieces of the allowed size; a posting without a text is its title
    plain = match.job_chunks("X", "Plain text without any heading. " * 60, max_chunks=3, chunk_chars=300)
    assert len(plain) == 3 and all(len(c) <= 300 for c in plain)
    assert match.job_chunks("Hardware Engineer", "") == ["Hardware Engineer"]
    # a sentence that only mentions a company is no heading; when a posting has nothing else, that part is used
    assert match._heading("Erfahrung in einem Unternehmen der Luftfahrt") is None
    assert match.job_chunks("Y", "Wir bieten\n• 30 Tage Urlaub") == ["Y", "30 Tage Urlaub"]


def test_fuse_combines_keyword_and_semantic_rank():
    order = [job_id for job_id, _ in match.fuse([("a", 90, 0.2), ("b", 80, 0.9), ("c", 70, 0.1), ("d", 60, 0.95)])]
    # d is last by keywords and first by meaning: it overtakes c, which is third and last
    assert order == ["a", "b", "d", "c"]
    scores = dict(match.fuse([("a", 90, 0.2), ("b", 80, 0.9)]))
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62) and scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert match.fuse([]) == [] and match.fuse([("x", 50, None)])[0][0] == "x"
    # without semantic scores the keyword order is kept
    assert [i for i, _ in match.fuse([("a", 3, None), ("b", 9, None), ("c", 5, None)])] == ["b", "c", "a"]
    # a part of the list has no semantic score: those keep their keyword rank and are not pushed to the end
    mixed = [i for i, _ in match.fuse([("a", 90, None), ("b", 80, 0.1), ("c", 70, 0.9), ("d", 10, None)])]
    assert mixed.index("a") < mixed.index("d") and mixed.index("c") < mixed.index("b")


def test_vectors_are_stored_as_float32_of_length_one():
    vec = embed.unit([3.0, 4.0])
    assert vec == pytest.approx([0.6, 0.8]) and embed.unit([0.0, 0.0]) == [0.0, 0.0]
    blob = embed.pack([vec, [1.0, 0.0]])
    assert len(blob) == 16
    back = embed.unpack(blob, 2)
    assert [list(v) for v in back] == [pytest.approx([0.6, 0.8]), [1.0, 0.0]]
    assert embed.dot(back[0], back[1]) == pytest.approx(0.6)
    # models that expect an instruction in front of a query get it; documents stay as they are
    assert embed.query_prefix("Qwen/Qwen3-Embedding-0.6B-Q").startswith("Instruct: ")
    assert embed.passage_prefix("Qwen/Qwen3-Embedding-0.6B-Q") == ""
    assert (embed.query_prefix("intfloat/multilingual-e5-large"), embed.passage_prefix("intfloat/multilingual-e5-large")) \
        == ("query: ", "passage: ")
    assert embed.query_prefix(embed.DEFAULT_MODELS["fastembed"]) == ""


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def test_ollama_and_openai_compatible_backends():
    seen = []

    def ollama(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if body["model"] == "missing":
            return httpx.Response(404, json={"error": "model not found"})
        return httpx.Response(200, json={"embeddings": [[3.0, 4.0] for _ in body["input"]]})

    client = httpx.Client(transport=httpx.MockTransport(ollama))
    backend = embed.OllamaEmbedBackend("http://localhost:11434/v1", "bge-m3", client=client)
    assert backend.embed(["a", "b"]) == [pytest.approx([0.6, 0.8])] * 2
    assert seen[0] == ("/api/embed", {"model": "bge-m3", "input": ["a", "b"]})
    with pytest.raises(embed.EmbedError, match="ollama pull missing"):
        embed.OllamaEmbedBackend("http://localhost:11434", "missing", client=client).embed(["a"])
    down = httpx.Client(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused"))))
    with pytest.raises(embed.EmbedError, match="Ollama"):
        embed.OllamaEmbedBackend("http://localhost:11434", "bge-m3", client=down).embed(["a"])

    def openai(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path, request.headers.get("authorization"), body))
        items = [{"index": i, "embedding": [float(i + 1), 0.0]} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": list(reversed(items))})

    backend = embed.OpenAIEmbedBackend("http://localhost:1234/v1/", "key", "nomic-embed-text-v1.5",
                                       client=httpx.Client(transport=httpx.MockTransport(openai)))
    assert backend.embed(["x", "y"], query=True) == [[1.0, 0.0], [1.0, 0.0]]   # sorted by index, length one
    path, auth, body = seen[-1]
    assert (path, auth) == ("/v1/embeddings", "Bearer key")
    assert body == {"model": "nomic-embed-text-v1.5", "input": ["search_query: x", "search_query: y"]}
    assert embed.OllamaEmbedBackend("http://x", "m", client=client).embed([]) == []


def test_paid_embedding_service_needs_the_same_permission_as_a_paid_model(cfg):
    cfg.matching.provider, cfg.matching.model = "openai", "text-embedding-3-small"
    cfg.llm.openai.base_url = "https://api.openai.com/v1"
    with pytest.raises(embed.EmbedError):
        embed.get_embedder(cfg)                                  # llm.allow_paid_api is false
    cfg.matching.base_url = "http://localhost:1234/v1"
    backend = embed.get_embedder(cfg)                            # a server on this computer is free
    assert backend.base_url == "http://localhost:1234/v1" and embed.model_key(cfg) == "openai:text-embedding-3-small"
    cfg.matching.model = ""
    with pytest.raises(embed.EmbedError):
        embed.get_embedder(cfg)                                  # no default model for this provider
    cfg.matching.provider = "ollama"
    cfg.matching.base_url = ""
    assert embed.get_embedder(cfg).model == "bge-m3" and embed.base_url(cfg) == "http://localhost:11434"


def test_builtin_backend_loads_once_and_reports_problems(monkeypatch, tmp_path):
    made = []

    class TextEmbedding:
        def __init__(self, model_name, cache_dir=None, threads=None, **kwargs):
            if model_name == "bad/model":
                raise ValueError("Model bad/model is not supported in TextEmbedding.")
            if model_name == "offline/model":
                raise OSError("could not download")
            made.append((model_name, cache_dir, threads))

        def embed(self, documents, batch_size=256, **kwargs):
            made.append(list(documents))
            for _ in documents:
                yield types.SimpleNamespace(tolist=lambda: [0.0, 2.0])

    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=TextEmbedding))
    monkeypatch.setattr(embed, "fastembed_installed", lambda: True)
    cache = tmp_path / "models"
    backend = embed.FastEmbedBackend("Qwen/Qwen3-Embedding-0.6B-Q", cache, threads=2)
    assert backend.embed(["what I look for"], query=True) == [[0.0, 1.0]]
    assert backend.embed(["a posting"]) == [[0.0, 1.0]]
    assert made[0] == ("Qwen/Qwen3-Embedding-0.6B-Q", str(cache), 2) and cache.is_dir()
    assert made[1][0].startswith("Instruct: ") and made[1][0].endswith("Query:what I look for")
    assert made[2] == ["a posting"] and len(made) == 3            # the model was loaded once
    with pytest.raises(embed.EmbedError, match="bad/model"):
        embed.FastEmbedBackend("bad/model", cache).embed(["x"])
    with pytest.raises(embed.EmbedError, match="could not download"):
        embed.FastEmbedBackend("offline/model", cache).embed(["x"])
    monkeypatch.setattr(embed, "fastembed_installed", lambda: False)
    with pytest.raises(embed.EmbedError, match="fastembed"):
        embed.FastEmbedBackend("any", cache).embed(["x"])


def test_builtin_backend_against_the_installed_library(tmp_path):
    """With fastembed installed: its real constructor refuses a model it does not know (no download needed)."""
    pytest.importorskip("fastembed")
    with pytest.raises(embed.EmbedError, match="no/such-model"):
        embed.FastEmbedBackend("no/such-model", tmp_path / "models").embed(["x"])
    from fastembed import TextEmbedding

    known = {m["model"] for m in TextEmbedding.list_supported_models()}
    assert {m["id"] for m in embed.BUILTIN_MODELS} <= known       # every model the app offers exists


# ---------------------------------------------------------------------------
# Scores and promotions
# ---------------------------------------------------------------------------


def test_matching_scores_promotes_and_does_nothing_twice(cfg, profile):
    conn = seed(cfg, profile, fpga_jobs() + office_jobs() + [hidden_job(), RawJob(
        source="indeed", title="Bilanzbuchhalter", company="Zahl AG", location="Bremen",
        url="https://de.indeed.com/viewjob?jk=o1", description=OFF)])
    hidden = by_title(conn, "Ingenieur programmierbare")
    assert hidden["status"] == "filtered" and hidden["filtered_reason"] == "hiçbir hedef alana uymuyor"
    fake = WordEmbedder()
    report = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    # 22 keyword matches, and 13 postings only the track rule had filtered (12 at a reception desk and the
    # hidden one); the bookkeeper breaks a rule of your own (title word) and is not even looked at
    assert (report.embedded, report.scored, report.waiting) == (35, 35, 0)
    assert (report.reference, report.background, report.promoted) == (22, 13, 1)
    assert conn.execute("SELECT COUNT(*) FROM embeddings WHERE kind = 'job'").fetchone()[0] == 35
    assert match_row(conn, by_title(conn, "Bilanzbuchhalter")["id"]) is None
    hidden = by_title(conn, "Ingenieur programmierbare")
    row = match_row(conn, hidden["id"])
    # the bar lies half way between what the keyword rules accept and what they turn away
    accepted = match_row(conn, by_title(conn, "FPGA-Entwickler 3")["id"])["semantic"]
    desk = match_row(conn, by_title(conn, "Empfangskraft 3")["id"])
    assert report.threshold == pytest.approx((accepted + desk["semantic"]) / 2, abs=1e-3)
    assert desk["semantic"] < report.threshold < row["semantic"] and desk["promoted"] == 0
    assert by_title(conn, "Empfangskraft 3")["status"] == "filtered"
    assert hidden["status"] == "new" and hidden["filtered_reason"] is None and hidden["track"] == "fpga"
    assert hidden["flags"]["semantic"] == {"promoted": True, "track": "fpga", "sim": round(row["semantic"], 3)}
    assert row["promoted"] == 1 and row["best_track"] == "fpga" and row["semantic"] >= report.threshold
    assert 0 < row["track_sim"] <= 1 and 0 < row["profile_sim"] <= 1
    assert any(e["kind"] == "semantic_promoted" for e in db.events_for(conn, hidden["id"]))
    from jobradar.processing.flags import flag_labels

    assert ("Anlamsal eşleşme", "info") in flag_labels(hidden["flags"])
    # a re-filter (settings changed) keeps the promotion; the evaluation queue now contains it
    refilter_all(conn, cfg, profile)
    assert by_title(conn, "Ingenieur programmierbare")["status"] == "new"
    assert db.pending_evaluation_count(conn, cfg.scoring.prescore_min) == 23
    assert hidden["id"] in [j["id"] for j in evaluation_queue(conn, cfg, limit=50)]
    # nothing changed: the second run asks the model for nothing and changes nothing
    asked = len(fake.calls)
    again = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert (again.embedded, again.scored, again.promoted, again.demoted) == (0, 0, 0, 0) and len(fake.calls) == asked
    assert match.status(conn, cfg)["scored"] == 35 and match.status(conn, cfg)["promoted"] == 1
    # the promoted posting still counts among those the keyword rules turn away: the bar has not moved
    assert again.threshold == report.threshold and (again.reference, again.background) == (22, 13)
    view = match.job_view(conn, cfg, hidden["id"])
    assert view["promoted"] is True and view["track_name"] == "FPGA / Embedded hardware"


def test_promotion_respects_your_own_rules_and_the_limit(cfg, profile):
    cfg.matching.promote_max_per_run = 2
    conn = seed(cfg, profile, fpga_jobs() + office_jobs() + [hidden_job(1), hidden_job(2), hidden_job(3), hidden_job(4)])
    # the fourth company lands on the blocklist after the scan: its posting is still stored as "track only"
    cfg.filters.company_blacklist = ["Himmel 4"]
    fake = WordEmbedder()
    first = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert first.promoted == 2
    second = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert second.promoted == 1 and second.embedded == 0 and second.threshold == first.threshold
    third = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert third.promoted == 0
    blocked = by_title(conn, "Ingenieur programmierbare Logik 4")
    assert blocked["status"] == "filtered" and "semantic" not in blocked["flags"]
    assert match_row(conn, blocked["id"])["promoted"] == 0
    assert conn.execute("SELECT COUNT(*) FROM job_match WHERE promoted = 1").fetchone()[0] == 3
    # promotion can be turned off on its own: scores stay, nothing new is let through
    cfg.matching.promote = False
    conn2 = seed(cfg, profile, [hidden_job(5)])
    assert match.run_matching(conn2, cfg, profile, fake, log=lambda m: None).promoted == 0


def test_without_enough_postings_on_either_side_there_is_no_bar(cfg, profile):
    # keyword matches, but hardly anything the keyword rules turn away: nothing to measure the bar on
    conn = seed(cfg, profile, fpga_jobs() + office_jobs(3) + [hidden_job()])
    fake = WordEmbedder()
    few = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert (few.threshold, few.reference, few.background, few.promoted) == (None, 22, 4, 0)
    assert by_title(conn, "Ingenieur programmierbare")["status"] == "filtered"
    # more of them arrive with the next scan: now the bar exists
    import_raws(conn, cfg, profile, office_jobs(12)[3:])
    more = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert more.threshold is not None and (more.reference, more.background, more.promoted) == (22, 13, 1)


def test_evaluated_postings_are_the_yardstick_right_after_matching_is_turned_on(cfg, profile, monkeypatch):
    conn = seed(cfg, profile, fpga_jobs() + office_jobs() + [hidden_job()])
    # an installation that has been in use: everything the keyword rules accepted is evaluated already
    conn.execute("UPDATE jobs SET llm_score = 3.0 WHERE status = 'new'")
    conn.commit()
    fake = WordEmbedder()
    cfg.matching.promote = False
    assert match.run_matching(conn, cfg, profile, fake, log=lambda m: None).embedded == 0    # nothing waits
    cfg.matching.promote = True
    # only a few of them are looked at: too few for a bar
    monkeypatch.setattr(match, "REFERENCE_SAMPLE", 5)
    few = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert (few.embedded, few.reference, few.background, few.threshold) == (18, 5, 13, None)
    monkeypatch.setattr(match, "REFERENCE_SAMPLE", 300)
    report = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert (report.embedded, report.reference, report.background, report.promoted) == (17, 22, 13, 1)
    assert by_title(conn, "Ingenieur programmierbare")["status"] == "new"


def test_when_both_sides_score_alike_nothing_is_promoted(cfg, profile):
    conn = seed(cfg, profile, fpga_jobs() + office_jobs() + [hidden_job()])
    cfg.matching.promote_max_per_run = 0
    match.run_matching(conn, cfg, profile, WordEmbedder(), log=lambda m: None)      # scores, no promotion
    cfg.matching.promote_max_per_run = 5
    model, qhash = match.current_keys(cfg, profile)
    bar, accepted, away = match.promotion_bar(conn, cfg, model, qhash)
    assert bar is not None and (accepted, away) == (22, 13)
    filtered = "job_id IN (SELECT id FROM jobs WHERE status = 'filtered')"
    # what the keyword rules turn away scores like what they accept: meaning cannot tell the two apart
    conn.execute("UPDATE job_match SET semantic = 0.3")
    assert match.promotion_bar(conn, cfg, model, qhash) == (None, 22, 13)
    # … or even higher
    conn.execute(f"UPDATE job_match SET semantic = 0.6 WHERE {filtered}")
    assert match.promotion_bar(conn, cfg, model, qhash) == (None, 22, 13)
    assert match.run_matching(conn, cfg, profile, WordEmbedder(), log=lambda m: None).promoted == 0
    # promote_bar says where between the two typical scores the bar lies
    conn.execute(f"UPDATE job_match SET semantic = 0.2 WHERE {filtered}")
    assert match.promotion_bar(conn, cfg, model, qhash)[0] == pytest.approx(0.25)
    cfg.matching.promote_bar = 0.2
    assert match.promotion_bar(conn, cfg, model, qhash)[0] == pytest.approx(0.22)
    cfg.matching.promote_bar = 1.0
    assert match.promotion_bar(conn, cfg, model, qhash)[0] == pytest.approx(0.3)


def test_a_posting_scored_down_by_a_requirement_is_not_promoted(cfg, profile):
    # close to the track in meaning, and only the track rule filtered it, but it asks for ten years of
    # experience: its quick score is low for a reason the embedding model knows nothing about
    demanding = hidden_job(7, description=HIDDEN + "\nMindestens 10 Jahre Berufserfahrung erforderlich.")
    conn = seed(cfg, profile, fpga_jobs() + office_jobs() + [hidden_job(1), demanding])
    job = by_title(conn, "Ingenieur programmierbare Logik 7")
    assert job["status"] == "filtered" and job["flags"]["years_required"] == 10
    assert match._penalty(job["prescore_detail"]) <= match.HEAVY_PENALTY
    assert match._penalty(json.dumps(job["prescore_detail"])) == match._penalty(job["prescore_detail"])
    assert match._penalty(None) == 0 and match._penalty("{broken") == 0 and match._penalty('{"penalties": [["x"]]}') == 0
    fake = WordEmbedder()
    report = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    # it has a score (the measurements use it), but it is neither a candidate nor part of the yardstick
    assert match_row(conn, job["id"])["semantic"] > report.threshold
    assert (report.promoted, report.background) == (1, 13)
    assert by_title(conn, "Ingenieur programmierbare Logik 7")["status"] == "filtered"
    promoted = by_title(conn, "Ingenieur programmierbare Logik 1")
    assert promoted["status"] == "new"
    # the full text of the promoted posting arrives later and asks for the same: the promotion is taken back
    from jobradar.pipeline import Processor

    promoted["description"] = demanding.description
    Processor(cfg, profile).refresh(promoted)
    assert promoted["status"] == "new"                       # still carried by its promotion
    db.update_job(conn, promoted)
    conn.commit()
    later = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert (later.embedded, later.demoted, later.promoted) == (1, 1, 0)
    assert by_title(conn, "Ingenieur programmierbare Logik 1")["status"] == "filtered"


def test_a_changed_posting_is_embedded_again_and_can_lose_its_promotion(cfg, profile):
    conn = seed(cfg, profile, fpga_jobs() + office_jobs() + [hidden_job()])
    fake = WordEmbedder()
    assert match.run_matching(conn, cfg, profile, fake, log=lambda m: None).promoted == 1
    hidden = by_title(conn, "Ingenieur programmierbare")
    # the full description arrives later and shows another job
    db.update_fields(conn, hidden["id"], description=OFFICE, title="Empfangskraft Zentrale")
    conn.commit()
    before = fake.documents()
    report = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert (report.embedded, report.scored, report.demoted, report.promoted) == (1, 1, 1, 0)
    assert fake.documents() - before == len(match.job_chunks("Empfangskraft Zentrale", OFFICE))
    job = db.get_job(conn, hidden["id"])
    assert job["status"] == "filtered" and "semantic" not in job["flags"]
    assert match_row(conn, job["id"])["promoted"] == 0
    assert any(e["kind"] == "semantic_demoted" for e in db.events_for(conn, job["id"]))


def test_a_promoted_posting_you_have_handled_keeps_its_place(cfg, profile):
    conn = seed(cfg, profile, fpga_jobs() + office_jobs() + [hidden_job()])
    fake = WordEmbedder()
    assert match.run_matching(conn, cfg, profile, fake, log=lambda m: None).promoted == 1
    hidden = by_title(conn, "Ingenieur programmierbare")
    db.set_status(conn, hidden["id"], "shortlisted")
    db.update_fields(conn, hidden["id"], description=OFFICE)
    conn.commit()
    report = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert report.demoted == 0 and db.get_job(conn, hidden["id"])["status"] == "shortlisted"


def test_other_tracks_or_another_model_mean_new_scores(cfg, profile):
    conn = seed(cfg, profile, fpga_jobs(4) + [hidden_job()])
    fake = WordEmbedder()
    first = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert first.embedded == 5 and first.threshold is None and first.reference == 4   # too few keyword matches
    documents, queries = fake.documents(), fake.queries()
    # one track is rewritten: its text is embedded again, no posting is, every posting is scored again
    cfg.tracks[0].north_star = "Accounting and bookkeeping of annual reports and invoices."
    second = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert (second.embedded, second.scored) == (0, 5)
    assert fake.documents() == documents and fake.queries() - queries == 1
    # a track is removed: its vectors go away
    cfg.tracks[2].enabled = False
    match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    refs = [r[0] for r in conn.execute("SELECT ref FROM embeddings WHERE kind = 'query'")]
    assert refs and not any(ref.startswith("track:sustainability") for ref in refs)
    # another model: its vectors are separate, the old ones are removed, everything is embedded again
    cfg.matching.model = "another/model"
    third = match.run_matching(conn, cfg, profile, fake, log=lambda m: None)
    assert (third.embedded, third.scored) == (5, 5)
    assert {r[0] for r in conn.execute("SELECT DISTINCT model FROM embeddings")} == {"fastembed:another/model"}
    assert {r[0] for r in conn.execute("SELECT DISTINCT model FROM job_match")} == {"fastembed:another/model"}


def test_a_fixed_bar_and_the_time_budget(cfg, profile):
    cfg.matching.promote_min_similarity = 0.05
    conn = seed(cfg, profile, fpga_jobs(30) + [hidden_job()])
    fake = WordEmbedder()
    # no time at all: one portion is still done, the rest waits for the next run
    report = match.run_matching(conn, cfg, profile, fake, log=lambda m: None, max_seconds=0)
    assert report.embedded == match.JOBS_PER_BATCH and report.waiting == 31 - match.JOBS_PER_BATCH
    steps = []
    rest = match.run_matching(conn, cfg, profile, fake, log=lambda m: None, progress=lambda *a: steps.append(a))
    assert rest.embedded == 31 - match.JOBS_PER_BATCH and rest.waiting == 0 and rest.promoted == 1
    assert rest.threshold == 0.05 and rest.reference == 0        # the bar was given, not measured
    assert steps[0][:2] == (0, 0) and steps[-1] == (rest.embedded, rest.embedded)


def test_evaluations_follow_the_fused_order(cfg, profile):
    cfg.matching.enabled = True
    conn = db.connect(cfg.db_path)
    now = "2026-11-01T00:00:00+00:00"
    for job_id, prescore in (("a", 90), ("b", 80), ("c", 70), ("low", 10)):
        db.insert_job(conn, {"id": job_id, "title": job_id, "status": "new", "prescore": prescore,
                             "first_seen": now, "last_seen": now})
    conn.commit()
    ids = lambda **kw: [j["id"] for j in evaluation_queue(conn, cfg, limit=kw.pop("limit", 10), **kw)]  # noqa: E731
    # no semantic score yet: the quick score alone decides, as without matching
    assert match.llm_queue(conn, cfg, limit=10) is None and ids() == ["a", "b", "c"]

    def score(job_id, semantic, promoted=0, model=None):
        conn.execute("INSERT OR REPLACE INTO job_match (job_id, model, query_hash, text_hash, semantic, track_sim, "
                     "promoted, updated_at) VALUES (?, ?, 'q', 't', ?, ?, ?, ?)",
                     (job_id, model or embed.model_key(cfg), semantic, semantic, promoted, now))
        conn.commit()

    score("a", 0.1), score("b", 0.9), score("c", 0.5)
    # a: first by keywords, last by meaning; b: second and first; c: third and second
    assert ids() == ["b", "a", "c"] and ids(limit=1) == ["b"]
    # a promoted posting joins the queue although its quick score is far below the minimum
    score("low", 0.95, promoted=1)
    assert ids() == ["b", "a", "low", "c"]
    # evaluated postings leave the queue unless everything is evaluated again
    db.update_fields(conn, "b", llm_score=4.2)
    conn.commit()
    assert "b" not in ids() and "b" in ids(force=True)
    # scores of another model say nothing about the current one
    for job_id in ("a", "b", "c", "low"):
        score(job_id, 0.5, model="fastembed:old")
    assert match.llm_queue(conn, cfg, limit=10) is None and ids() == ["a", "c"]
    cfg.matching.enabled = False
    assert ids() == ["a", "c"]


def test_a_promoted_posting_without_a_text_gets_its_description(cfg, profile):
    cfg.matching.promote_min_similarity = 0.05
    board = RawJob(source="greenhouse:Himmel", title="Ingenieur programmierbare Logik und Hardware für Sensor Systems",
                   company="Himmel AG", location="Bremen", url="https://job-boards.greenhouse.io/himmel/jobs/7",
                   needs_location_check=True, detail_ref="url:https://job-boards.greenhouse.io/himmel/jobs/7")
    conn = seed(cfg, profile, [board])
    job = by_title(conn, "Ingenieur programmierbare")
    assert job["status"] == "filtered" and job["prescore"] < cfg.scoring.prescore_min
    assert match.run_matching(conn, cfg, profile, WordEmbedder(), log=lambda m: None).promoted == 1
    page = ('<html><head><script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "title": board.title, "description": HIDDEN.replace("\n", "<br>"),
        "hiringOrganization": {"name": "Himmel AG"}}) + "</script></head><body></body></html>")
    client = make_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=page)))
    assert enrich_pending(conn, cfg, profile, client=client, log=lambda m: None, pause=0) == 1
    job = db.get_job(conn, job["id"])
    assert len(job["description"]) > 300 and job["status"] == "new" and job["flags"]["semantic"]["promoted"]


# ---------------------------------------------------------------------------
# API and the scan cycle
# ---------------------------------------------------------------------------


def wait(client, task):
    for _ in range(400):
        state = client.get(f"/api/v1/tasks/{task['id']}").json()
        if state["status"] != "running":
            return state
        time.sleep(0.01)
    raise AssertionError("task did not finish")


def test_matching_settings_test_and_run_through_the_api(cfg, profile, monkeypatch):
    conn = seed(cfg, profile, fpga_jobs() + office_jobs() + [hidden_job()])
    cfg.matching.enabled = False
    fake = WordEmbedder()
    monkeypatch.setattr(match, "get_embedder", lambda c: fake)
    monkeypatch.setattr(embed, "get_embedder", lambda c: fake)
    client = TestClient(create_app(cfg, llm_factory=lambda c: FakeLLM(), cycle_runner=lambda c: None))
    view = client.get("/api/v1/matching", headers={"X-JobRadar-Lang": "en"}).json()
    assert view["enabled"] is False and view["provider"] == "fastembed" and view["scored"] == 0
    assert view["model"] == "" and view["model_effective"] == embed.DEFAULT_MODELS["fastembed"]
    assert view["models"][0]["id"] == view["model_effective"] and "default" in view["models"][0]["note"]
    assert isinstance(view["installed"], bool) and view["providers"] == ["fastembed", "ollama", "openai"]
    assert client.post("/api/v1/matching/run").status_code == 409                 # off: nothing to run
    assert client.put("/api/v1/matching", json={"provider": "magic"}).status_code == 422
    assert client.put("/api/v1/matching", json={"promote_max_per_run": -3}).status_code == 422
    on = client.put("/api/v1/matching", json={"enabled": True, "promote_max_per_run": 3}).json()
    assert on["enabled"] is True and on["promote_max_per_run"] == 3 and cfg.matching.enabled is True
    from jobradar.config import load_config

    assert load_config(cfg.config_path).matching.enabled is True                   # kept in data/settings.json
    tested = wait(client, client.post("/api/v1/matching/test", headers={"X-JobRadar-Lang": "en"}).json())
    assert tested["status"] == "done" and tested["result"]["dim"] == 96
    assert tested["result"]["message"] == "The matching model works."
    done = wait(client, client.post("/api/v1/matching/run").json())
    assert done["status"] == "done" and done["result"]["embedded"] == 35 and done["result"]["promoted"] == 1
    after = client.get("/api/v1/matching").json()
    assert after["scored"] == 35 and after["promoted"] == 1 and after["last_run"] and after["threshold"] > 0
    assert (after["last_reference"], after["last_background"]) == (22, 13)
    assert (after["reference_needed"], after["background_needed"]) == (match.MIN_REFERENCE, match.MIN_BACKGROUND)
    hidden = by_title(conn, "Ingenieur programmierbare")
    detail = client.get(f"/api/v1/jobs/{hidden['id']}", headers={"X-JobRadar-Lang": "en"}).json()
    assert detail["match"]["promoted"] is True and detail["match"]["track"] == "fpga"
    assert {"label": "Semantic match", "kind": "info"} in detail["badges"] and detail["status"] == "new"
    assert client.get("/api/v1/summary").json()["pending_evaluation"] == 23
    # turned off: the posting goes back to what the keyword rules say, and its badge goes away
    off = client.put("/api/v1/matching", json={"enabled": False}).json()
    assert off["enabled"] is False and off["promoted"] == 0
    detail = client.get(f"/api/v1/jobs/{hidden['id']}").json()
    assert detail["status"] == "filtered" and detail["match"] is None
    assert not any(b["label"] in ("Anlamsal eşleşme", "Semantic match") for b in detail["badges"])
    # a model that cannot be loaded: the test reports why
    def broken(c):
        raise embed.EmbedError("model could not be downloaded")

    monkeypatch.setattr(embed, "get_embedder", broken)
    failed = wait(client, client.post("/api/v1/matching/test").json())
    assert failed["status"] == "error" and "could not be downloaded" in failed["message"]


class StaticSource(Source):
    name = "static"

    def __init__(self, jobs):
        self._jobs = jobs

    def fetch(self, ctx):
        return list(self._jobs)


def test_a_scan_matches_before_it_evaluates_and_survives_a_missing_model(cfg, profile, monkeypatch):
    from jobradar import progress as progress_mod

    cfg.matching.enabled = True
    cfg.scoring.llm_max_per_run = 30
    raws = fpga_jobs() + office_jobs() + [hidden_job()]
    monkeypatch.setattr("jobradar.pipeline.build_sources", lambda c, only=None: [StaticSource(raws)])
    llm = FakeLLM()
    monkeypatch.setattr("jobradar.scoring.llm.get_llm", lambda c: llm)
    fake = WordEmbedder()
    monkeypatch.setattr(match, "get_embedder", lambda c: fake)
    stages = []
    original = progress_mod.CycleProgress._write

    def capture(self, data):
        original(self, data)
        stages.append(data["stage"])

    monkeypatch.setattr(progress_mod.CycleProgress, "_write", capture)
    run_cycle(cfg, log=lambda m: None, notify=False)
    assert "match" in stages and stages.index("match") < stages.index("evaluate")
    conn = db.connect(cfg.db_path)
    hidden = by_title(conn, "Ingenieur programmierbare")
    assert hidden["status"] == "new" and hidden["llm_score"] is not None      # promoted, then evaluated
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE llm_score IS NOT NULL").fetchone()[0] == 23
    assert db.get_meta(conn, match.META_ERROR) == ""

    # the next scan cannot load the model: it says so, keeps the scores it has and still evaluates
    def broken(c):
        raise embed.EmbedError("Eşleştirme paketi (fastembed) kurulu değil.")

    monkeypatch.setattr(match, "get_embedder", broken)
    more = [RawJob(source="linkedin", title="FPGA Design Engineer Neu", company="Neu GmbH", location="Kiel",
                   url="https://www.linkedin.com/jobs/view/4100000990", description=DESC)]
    monkeypatch.setattr("jobradar.pipeline.build_sources", lambda c, only=None: [StaticSource(more)])
    logs = []
    run_cycle(cfg, log=logs.append, notify=False)
    assert any("Eşleştirme atlandı" in line for line in logs)
    assert "fastembed" in db.get_meta(conn, match.META_ERROR)
    assert by_title(conn, "FPGA Design Engineer Neu")["llm_score"] is not None
    assert db.get_meta(conn, "last_cycle")


def test_a_quick_scan_gives_matching_a_third_of_the_time(cfg, profile, monkeypatch):
    from jobradar import cli

    seen = []
    monkeypatch.setattr(match, "run_matching", lambda conn, cfg, profile, **kw: seen.append(kw["max_seconds"]))
    conn = db.connect(cfg.db_path)
    cli.matching_step(conn, cfg, profile, lambda m: None)                     # off: nothing runs
    cfg.matching.enabled = True
    cli.matching_step(conn, cfg, profile, lambda m: None)
    cli.matching_step(conn, cfg, profile, lambda m: None, quick=True)
    assert seen == [None, 60]                                                 # None = matching.max_seconds_per_run


# ---------------------------------------------------------------------------
# The real model (only where it may be downloaded: JOBRADAR_TEST_REAL_MODEL=1)
# ---------------------------------------------------------------------------

REAL = os.environ.get("JOBRADAR_TEST_REAL_MODEL", "")


@pytest.mark.skipif(not REAL, reason="downloads the embedding model; set JOBRADAR_TEST_REAL_MODEL=1")
def test_the_real_model_puts_related_postings_first(cfg, profile, tmp_path):
    cfg.matching.enabled = True
    cfg.matching.promote_min_similarity = 0.99      # only scores are looked at here
    if REAL not in ("1", "true", "yes"):
        cfg.matching.model = REAL                   # another model to try
    cfg.matching.cache_dir = os.environ.get("JOBRADAR_TEST_MODEL_DIR", str(tmp_path / "models"))
    related = [
        ("Entwicklungsingenieur programmierbare Logik", "Ihre Aufgaben\n• Entwurf und Verifikation digitaler "
         "Schaltungen für Flugrechner\n• Implementierung von Bildverarbeitung in programmierbarer Logik\nIhr Profil\n"
         "• Studium der Elektrotechnik\n• Erste Erfahrung mit Hardwarebeschreibungssprachen"),
        ("Graduate Engineer, Digital Hardware", "Your tasks\n- Design and verify digital logic for sensor payloads of "
         "unmanned aircraft\n- Bring up boards and debug with an oscilloscope\nYour profile\n- Degree in electrical "
         "engineering\n- Interest in hardware description languages"),
        ("Ingenieur Netzintegration Ladeinfrastruktur", "Ihre Aufgaben\n• Planung von Netzanschlüssen für Ladeparks\n"
         "• Lastflussberechnungen im Verteilnetz\nIhr Profil\n• Studium der Energietechnik"),
    ]
    unrelated = [
        ("Bilanzbuchhalter", "Ihre Aufgaben\n• Erstellung von Monats- und Jahresabschlüssen\n• Abstimmung der Konten\n"
         "Ihr Profil\n• Ausbildung im Rechnungswesen"),
        ("Pflegefachkraft Intensivstation", "Ihre Aufgaben\n• Pflege und Betreuung von Patienten\n• Dokumentation\n"
         "Ihr Profil\n• Abgeschlossene Ausbildung in der Pflege"),
        ("Sales Manager Fashion Retail", "Your tasks\n- Grow revenue with key accounts in fashion retail\n- Lead "
         "negotiations\nYour profile\n- Experience in sales"),
        ("Koch / Köchin", "Ihre Aufgaben\n• Zubereitung von Speisen\n• Einhaltung der Hygienevorschriften\nIhr Profil\n"
         "• Ausbildung als Koch"),
    ]
    conn = db.connect(cfg.db_path)
    now = "2026-11-01T00:00:00+00:00"
    for i, (title, text) in enumerate(related + unrelated):
        db.insert_job(conn, {"id": f"real{i}", "title": title, "company": "X", "description": text, "status": "new",
                             "prescore": 60, "first_seen": now, "last_seen": now})
    conn.commit()
    started = time.monotonic()
    report = match.run_matching(conn, cfg, profile, log=print, max_seconds=900)
    seconds = time.monotonic() - started
    scores = {r["job_id"]: r["semantic"] for r in conn.execute("SELECT job_id, semantic FROM job_match")}
    good = [scores[f"real{i}"] for i in range(len(related))]
    bad = [scores[f"real{i}"] for i in range(len(related), len(related) + len(unrelated))]
    print(f"\nmodel {report.model}: related {good}, unrelated {bad}, first run {seconds:.1f} s")
    assert report.embedded == len(related) + len(unrelated)
    assert min(good) > max(bad), (good, bad)
    tracks = {r["job_id"]: r["best_track"] for r in conn.execute("SELECT job_id, best_track FROM job_match")}
    assert tracks["real0"] == "fpga" and tracks["real1"] == "fpga" and tracks["real2"] == "energy"
    # speed of a warm model: 40 postings of four pieces each
    for i in range(40):
        db.insert_job(conn, {"id": f"speed{i}", "title": f"{related[i % 3][0]} {i}", "company": "X",
                             "description": related[i % 3][1] + f"\n• Aufgabe {i}", "status": "new", "prescore": 60,
                             "first_seen": now, "last_seen": now})
    conn.commit()
    started = time.monotonic()
    again = match.run_matching(conn, cfg, profile, log=print, max_seconds=900)
    seconds = time.monotonic() - started
    print(f"warm: {again.embedded} postings in {seconds:.1f} s ({again.embedded / max(seconds, 0.001):.1f} per second)")
    assert again.embedded == 40
