"""Demo workspace: fictional postings + offline heuristic 'LLM'.
All companies and people below are invented."""

from __future__ import annotations

import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import yaml

from jobradar import db
from jobradar.config import AppConfig, load_config
from jobradar.i18n import t
from jobradar.models import RawJob
from jobradar.pipeline import evaluate_pending, import_raws
from jobradar.profile import load_profile
from jobradar.scoring.fake import FakeLLM

TEMPLATES = Path(__file__).parent / "templates"

DEMO_PROFILE = {
    "name": "Deniz Beispiel",
    "headline": "Embedded Systems Engineer · M.Sc. candidate",
    "email": "deniz@example.com",
    "phone": "+49 160 0000000",
    "city": "Hamburg",
    "german_level": "B1",
    "citizenships": [],
    "summary_facts": [{"id": "GEN-1", "text": "Electrical engineer combining FPGA development with energy-system analysis."}],
    "experience": [
        {"id": "THES", "kind": "thesis", "organization": "Institut für Energiesysteme (Demo)", "title": "Master's Thesis",
         "location": "Hamburg", "start": "2026-04", "end": "present", "facts": [
             {"id": "THES-1", "text": "Built a MILP optimisation model for the charging schedules of an electric bus depot.",
              "skills": ["MILP", "Optimization", "E-Mobility"]},
             {"id": "THES-2", "text": "Compared open energy-demand datasets and documented their quality.",
              "skills": ["Data Analysis"]}]},
        {"id": "FPGA", "kind": "work", "organization": "Sensorik Demo GmbH", "title": "FPGA Engineer", "location": "Dresden",
         "start": "2022-03", "end": "2024-06", "facts": [
             {"id": "FPGA-1", "text": "Developed FPGA designs in VHDL and Verilog for UAV camera payloads and inspection systems.",
              "skills": ["FPGA", "VHDL", "Verilog", "UAV"]},
             {"id": "FPGA-2", "text": "Implemented image-processing pipelines on Zynq SoC platforms using PYNQ.",
              "skills": ["Zynq", "PYNQ", "Computer Vision"]}]},
        {"id": "MV", "kind": "internship", "organization": "Schaltanlagen Demo GmbH", "title": "Intern Medium Voltage",
         "location": "Leipzig", "start": "2020-07", "end": "2020-09", "facts": [
             {"id": "MV-1", "text": "Supported testing and documentation of medium-voltage switchgear.",
              "skills": ["Medium Voltage", "Switchgear"]}]},
    ],
    "education": [
        {"id": "MSC", "kind": "education", "organization": "Technische Hochschule (Demo)", "title": "M.Sc. Electrical Engineering",
         "location": "Hamburg", "start": "2024-10", "end": "2026-09", "facts": []},
        {"id": "BSC", "kind": "education", "organization": "Universität (Demo)", "title": "B.Sc. Electrical Engineering",
         "location": "Dresden", "start": "2017-10", "end": "2021-09", "facts": []},
    ],
    "skills": {"hardware": ["FPGA", "VHDL", "Verilog", "Zynq", "PYNQ", "UAV", "Computer Vision"],
               "energy": ["MILP", "Optimization", "E-Mobility", "Medium Voltage", "Switchgear", "Data Analysis"]},
    "languages": [{"name": "Nederlands", "level": "Native"}, {"name": "English", "level": "C1"},
                  {"name": "Deutsch", "level": "B1"}],
}


def _days(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def demo_jobs() -> list[RawJob]:
    fpga_de = """Über uns
Nordlicht Defence Systems entwickelt Sensorsysteme für Luftfahrt und Verteidigung.

Ihre Aufgaben
• Entwicklung von FPGA-Designs in VHDL für Bildverarbeitungsketten
• Integration auf Xilinx Zynq SoC Plattformen
• Verifikation mit Simulation und Labortests
• Zusammenarbeit mit Software- und Systemteams

Ihr Profil
• Abgeschlossenes Studium der Elektrotechnik oder vergleichbar
• Erfahrung mit VHDL oder Verilog
• Kenntnisse in Bildverarbeitung und UAV-Systemen von Vorteil
• Sehr gute Deutsch- und Englischkenntnisse
• Bereitschaft zur Sicherheitsüberprüfung Ü2

Wir bieten
Mobiles Arbeiten nach Absprache, Vergütung nach Tarifvertrag IG Metall."""
    radar_en = """Skyward Sensorik builds radar sensors for unmanned aircraft.

What you will do
• Implement signal-processing blocks on FPGAs in VHDL
• Bring up Zynq-based boards in the lab
• Work with our radar algorithm team

What you bring
• Degree in electrical engineering
• First experience with FPGA development (VHDL/Verilog)
• Interest in UAV and radar systems
• Fluent English; German is a plus

We offer a salary of 58.000 - 66.000 € per year and hybrid work."""
    ws_de = """Werkstudent (m/w/d) Embedded Hardware
• Unterstützung bei Schaltplanentwurf und Inbetriebnahme von Leiterplatten
• Programmierung von Testskripten
• Gute Deutschkenntnisse
• 15-20 Stunden pro Woche, Standort Hamburg"""
    grid_de = """Nordwerk Netze plant das Verteilnetz der Zukunft.
Ihre Aufgaben
• Netzplanung in der Mittelspannung
• Netzberechnungen mit PowerFactory
• Integration von Ladeinfrastruktur und PV-Anlagen
Ihr Profil
• Studium Elektrotechnik / Energietechnik
• Erste Erfahrung mit Mittelspannung und Schaltanlagen
• Verhandlungssichere Deutschkenntnisse"""
    emob_en = """VoltPark Mobility operates fast-charging hubs across Germany.
Your tasks
• Analyse charging load profiles and tariff effects
• Build optimisation models (MILP) for charging schedules
• Work with grid operators on flexibility and bidirectional charging
Your profile
• Degree in electrical engineering or energy systems
• Experience with optimisation models and Python
• Fluent English, German B2 or higher
Salary: 55.000 - 65.000 € p.a., hybrid (2 days office in Lübeck)."""
    lca = """GrünKreis Consulting supports industrial clients with decarbonisation.
Aufgaben
• Erstellung von Ökobilanzen (LCA) nach ISO 14040/44
• CO2-Bilanzierung und CSRD-Berichterstattung
Profil
• Studium im Bereich Nachhaltigkeit, Umwelt- oder Ingenieurwesen
• Erfahrung mit openLCA oder SimaPro
• Gute Deutsch- und Englischkenntnisse"""
    return [
        RawJob(source="linkedin", title="FPGA-Entwickler (m/w/d) Bildverarbeitung", company="Nordlicht Defence Systems GmbH",
               location="München, Bayern, Deutschland", url="https://www.linkedin.com/jobs/view/4100000001",
               description=fpga_de, posted_at=_days(2)),
        RawJob(source="arbeitsagentur", title="FPGA Entwickler (w/m/d) Bildverarbeitung", company="Nordlicht Defence Systems",
               location="München", url="https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1000000001-S",
               posted_at=_days(3), detail_ref="aa:10000-1000000001-S"),
        RawJob(source="greenhouse:Skyward Sensorik", title="Junior FPGA Engineer (all genders) – Radar",
               company="Skyward Sensorik GmbH", location="Ulm, Germany",
               url="https://job-boards.greenhouse.io/skyward/jobs/1001", description=radar_en, posted_at=_days(1),
               needs_location_check=True),
        RawJob(source="indeed", title="Werkstudent (m/w/d) Embedded Hardware", company="Hanse Antriebstechnik GmbH",
               location="Hamburg", url="https://de.indeed.com/viewjob?jk=demo0001", description=ws_de, posted_at=_days(4)),
        RawJob(source="arbeitsagentur", title="Elektroingenieur (m/w/d) Netzplanung Mittelspannung",
               company="Nordwerk Netze GmbH", location="Bremen", url="https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1000000002-S",
               description=grid_de, posted_at=_days(6)),
        RawJob(source="freehire", title="E-Mobility Engineer – Charging Infrastructure (m/f/d)",
               company="VoltPark Mobility GmbH", location="Lübeck, Germany", url="https://careers.voltpark.example/jobs/77",
               description=emob_en, posted_at=_days(2), needs_location_check=True, extra={"origin": "personio"}),
        RawJob(source="stepstone", title="Sustainability Analyst LCA (w/m/d)", company="GrünKreis Consulting GmbH",
               location="Kiel", url="https://www.stepstone.de/stellenangebote--Sustainability-Analyst-Kiel-GruenKreis--90000001-inline.html",
               description=lca, posted_at=_days(8)),
        RawJob(source="linkedin", title="Senior FPGA Architect (m/w/d)", company="Nordlicht Defence Systems GmbH",
               location="München", url="https://www.linkedin.com/jobs/view/4100000002", description=fpga_de, posted_at=_days(5)),
        RawJob(source="indeed", title="Vertriebsingenieur (m/w/d) Energietechnik", company="Kabel & Co KG",
               location="Essen", url="https://de.indeed.com/viewjob?jk=demo0002", description="Vertrieb von Kabeln.",
               posted_at=_days(3)),
        RawJob(source="greenhouse:Helix Robotics", title="Hardware Engineer (m/f/d)", company="Helix Robotics Ltd",
               location="London, United Kingdom", url="https://job-boards.greenhouse.io/helix/jobs/2002",
               description="Embedded hardware for robots.", posted_at=_days(2), needs_location_check=True),
    ]


def build_demo(directory: Path, log=print, keep: tuple[str, ...] = ()) -> AppConfig:
    directory = directory.expanduser().resolve()
    if directory.exists():
        # empty the folder but keep the folder itself: it may be the working directory of this process
        for child in directory.iterdir():
            if child.name in keep:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    (directory / "data" / "inbox").mkdir(parents=True)
    cfg_data = yaml.safe_load((TEMPLATES / "demo.yaml").read_text(encoding="utf-8"))
    cfg_data["sources"]["jobspy"]["enabled"] = False
    cfg_data["sources"]["arbeitsagentur"]["enabled"] = False
    cfg_data["sources"]["freehire"]["enabled"] = False
    cfg_data["sources"]["companies"] = []
    cfg_data["llm"]["provider"] = "none"
    # inside the Mac app its own PDF helper is used; on the command line a browser
    cfg_data["tailor"]["pdf_engine"] = "helper" if os.environ.get("JOBRADAR_PDF_HELPER") else "chrome"
    cfg_data["notify"]["dashboard_url"] = "http://127.0.0.1:8788"
    (directory / "jobradar.yaml").write_text(yaml.safe_dump(cfg_data, allow_unicode=True, sort_keys=False),
                                             encoding="utf-8")
    (directory / "data" / "profile.yaml").write_text(yaml.safe_dump(DEMO_PROFILE, allow_unicode=True, sort_keys=False),
                                                     encoding="utf-8")
    cfg = load_config(directory / "jobradar.yaml")
    profile = load_profile(cfg.profile_path)
    conn = db.connect(cfg.db_path)
    try:
        counts = import_raws(conn, cfg, profile, demo_jobs(), "demo")
        log(f"Demo: {counts.found} ilan, {counts.new} kayıt, {counts.merged} birleşti, {counts.filtered} elendi")
        llm = FakeLLM()
        evaluate_pending(conn, cfg, profile, llm, log=lambda m: None)
        best = conn.execute("SELECT id FROM jobs WHERE llm_score IS NOT NULL ORDER BY llm_score DESC LIMIT 1").fetchone()
        if best:
            from jobradar.tailor.generate import tailor_job

            tailor_job(cfg, profile, conn, best["id"], llm)
        other = conn.execute(
            "SELECT id FROM jobs WHERE status = 'new' AND llm_score IS NOT NULL ORDER BY llm_score DESC LIMIT 1 OFFSET 1"
        ).fetchone()
        if other:
            db.set_status(conn, other["id"], "applied", "demo")
            old = (date.today() - timedelta(days=12)).isoformat() + "T09:00:00+00:00"
            db.update_fields(conn, other["id"], applied_at=old, status_changed_at=old)
        conn.commit()
    finally:
        conn.close()
    log(f"Demo klasörü: {directory}")
    return cfg


DEMO_MARKER = ".jobradar-demo"


def ensure_demo(directory: Path, log=print) -> AppConfig:
    """The sample-data workspace of `serve --demo`: built on first use, reused afterwards.

    A folder that holds anything else is never touched (building a demo empties its folder)."""
    directory = directory.expanduser().resolve()
    marker = directory / DEMO_MARKER
    note = "JobRadar sample data. This folder is rebuilt by the app; do not keep your own files here.\n"
    if marker.exists() and (directory / "jobradar.yaml").exists() \
            and marker.read_text(encoding="utf-8").startswith("ready"):
        return load_config(directory / "jobradar.yaml")
    if directory.exists() and not marker.exists() and any(directory.iterdir()):
        raise ValueError(t("Bu klasör örnek veri klasörü değil, dokunulmadı: {path}", path=directory))
    directory.mkdir(parents=True, exist_ok=True)
    marker.write_text("building\n" + note, encoding="utf-8")   # ours from now on: a failed build can be repeated
    cfg = build_demo(directory, log=log, keep=(DEMO_MARKER,))
    marker.write_text("ready\n" + note, encoding="utf-8")
    return cfg
