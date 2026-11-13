"""Builds a workspace of made-up postings for looking at the app (probe branch only).

    python seed.py <workspace folder>

Starts from the engine's own sample workspace (made-up profile, ten postings) and adds about seventy
more: postings the keyword rules accept, postings they score low, postings only the track rule filters
(some related to the profile, some not) and postings a hard rule removes. Then it lets the offline
stand-in evaluate a part of them and records verdicts, so every part of the measurement card has data.
All companies are invented.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from jobradar import db
from jobradar.config import load_config
from jobradar.demo import build_demo
from jobradar.models import RawJob
from jobradar.pipeline import evaluate_pending, import_raws
from jobradar.profile import load_profile
from jobradar.scoring.fake import FakeLLM

try:
    from jobradar.scoring import bench      # 1.1 and later: your own verdicts and the measurements
except ImportError:
    bench = None


def days(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def de(about: str, tasks: list[str], profile: list[str], offer: str = "Flexible Arbeitszeiten, 30 Tage Urlaub.") -> str:
    return ("Über uns\n" + about + "\n\nIhre Aufgaben\n" + "\n".join("• " + t for t in tasks)
            + "\n\nIhr Profil\n" + "\n".join("• " + p for p in profile) + "\n\nWir bieten\n" + offer)


def en(about: str, tasks: list[str], profile: list[str], offer: str = "Hybrid work and 30 days of holiday.") -> str:
    return ("About us\n" + about + "\n\nYour tasks\n" + "\n".join("• " + t for t in tasks)
            + "\n\nYour profile\n" + "\n".join("• " + p for p in profile) + "\n\nWhat we offer\n" + offer)


FPGA_TASKS_DE = ["Entwicklung von FPGA-Designs in VHDL für Bildverarbeitung und Sensorik",
                 "Integration auf Xilinx Zynq SoC Plattformen mit Vivado",
                 "Verifikation mit Simulation und Tests im Labor",
                 "Inbetriebnahme von Leiterplatten gemeinsam mit dem Hardware-Team"]
FPGA_PROFILE_DE = ["Studium der Elektrotechnik oder vergleichbar", "Erfahrung mit VHDL oder Verilog",
                   "Kenntnisse in Bildverarbeitung oder UAV-Systemen von Vorteil", "Gute Englischkenntnisse"]
FPGA_TASKS_EN = ["Design and verify FPGA logic in VHDL and Verilog for camera and radar payloads",
                 "Bring up Zynq based boards and write test benches",
                 "Implement image-processing pipelines with AXI interfaces",
                 "Work closely with the embedded software and systems teams"]
FPGA_PROFILE_EN = ["Degree in electrical engineering", "First experience with FPGA development (VHDL or Verilog)",
                   "Interest in UAV, computer vision or signal processing", "Fluent English, German is a plus"]
ENERGY_TASKS_DE = ["Netzplanung und Netzberechnung in der Mittelspannung", "Analyse von Lastprofilen und Tarifen",
                   "Integration von Ladeinfrastruktur, Photovoltaik und Speichern in das Verteilnetz",
                   "Optimierung von Ladeplänen mit MILP-Modellen"]
ENERGY_PROFILE_DE = ["Studium Elektrotechnik oder Energietechnik", "Erste Erfahrung mit Mittelspannung und Schaltanlagen",
                     "Kenntnisse in Optimierung und Python", "Deutsch B1, Englisch fließend"]
ENERGY_TASKS_EN = ["Analyse charging load profiles and tariff effects for fleets",
                   "Build optimisation models (MILP) for charging schedules and bidirectional charging",
                   "Plan medium-voltage grid connections for charging hubs",
                   "Work with grid operators on flexibility"]
ENERGY_PROFILE_EN = ["Degree in electrical engineering or energy systems", "Experience with optimisation models and Python",
                     "Knowledge of medium voltage and switchgear is a plus", "Fluent English, German B1"]
SUST_TASKS_DE = ["Erstellung von Ökobilanzen (LCA) nach ISO 14040", "CO2-Bilanzierung und CSRD-Berichterstattung",
                 "Aufbau eines Energiemanagements nach ISO 50001", "Auswertung von Energie- und Verbrauchsdaten"]
SUST_PROFILE_DE = ["Studium im Bereich Nachhaltigkeit, Umwelt- oder Ingenieurwesen", "Erfahrung mit openLCA oder SimaPro",
                   "Sicherer Umgang mit Daten", "Gute Deutsch- und Englischkenntnisse"]

POSTINGS: list[dict] = []


def add(kind: str, want: int, title: str, company: str, city: str, text: str, age: int = 3, source: str = "indeed"):
    POSTINGS.append({"kind": kind, "want": want, "title": title, "company": company, "city": city, "text": text,
                     "age": age, "source": source})


# --- accepted by the keyword rules: FPGA and embedded hardware (looked for in all of Germany) ---------------
for i, (title, company, city, lang, want) in enumerate([
    ("FPGA Engineer (m/f/d) Image Processing", "Aeris Vision GmbH", "Bremen", "en", 2),
    ("Embedded Hardware Engineer (m/w/d) Avionik", "Hanse Avionik GmbH", "Hamburg", "de", 2),
    ("Junior FPGA Developer – Radar Signal Processing", "Polaris Radar Systems GmbH", "Ulm", "en", 2),
    ("Werkstudent (m/w/d) FPGA Verifikation", "Elbe Sensor Labs GmbH", "Hamburg", "de", 2),
    ("VHDL Entwickler (m/w/d) Flugsysteme", "Nordflug Systemtechnik GmbH", "Friedrichshafen", "de", 2),
    ("Digital Design Engineer (FPGA/ASIC)", "Tessera Microsystems GmbH", "Dresden", "en", 2),
    ("Electronics Engineer UAV Payloads (m/f/d)", "Kestrel Unmanned GmbH", "München", "en", 2),
    ("Hardwareentwickler (m/w/d) Sensorik", "Wattenmeer Messtechnik GmbH", "Kiel", "de", 1),
    ("Ingenieur Signalverarbeitung (m/w/d) Sonar", "Tiefsee Akustik GmbH", "Bremen", "de", 1),
    ("Computer Vision Engineer (m/f/d) Embedded", "Lumen Robotics GmbH", "Berlin", "en", 1),
    ("Hardware Engineer PCB Design (m/f/d)", "Brightline Devices GmbH", "Stuttgart", "en", 1),
    ("Drone Systems Engineer (m/f/d)", "Albatros Aerial GmbH", "Lübeck", "en", 1),
]):
    body = (de("%s entwickelt Elektronik für Luftfahrt und Sensorik." % company, FPGA_TASKS_DE, FPGA_PROFILE_DE)
            if lang == "de" else
            en("%s builds electronics for aerospace and sensing." % company, FPGA_TASKS_EN, FPGA_PROFILE_EN))
    add("accepted", want, title, company, city, body, age=1 + i % 9)

# keyword match in the title, but the work is something else
add("accepted", 0, "Embedded Software Engineer (m/w/d) Infotainment", "Autohaus Digital GmbH", "Wolfsburg",
    de("Autohaus Digital entwickelt Infotainment-Software für Fahrzeuge.",
       ["Entwicklung von C++ Anwendungen unter Linux und Android", "Pflege von Bluetooth- und Media-Stacks",
        "Fehleranalyse im Fahrzeug", "Abstimmung mit Zulieferern"],
       ["Studium Informatik oder vergleichbar", "Sehr gute C++ Kenntnisse", "Erfahrung mit Android Automotive",
        "Gute Deutschkenntnisse"]), age=5)
add("accepted", 0, "Embedded Linux Developer (m/f/d) Payment Terminals", "Kassenwerk GmbH", "Hannover",
    en("Kassenwerk builds payment terminals for retail.",
       ["Maintain our Yocto based Linux distribution", "Write device drivers and update mechanisms",
        "Harden the system for payment certification", "Support production testing"],
       ["Degree in computer science", "Strong C and shell skills", "Experience with Yocto and secure boot",
        "Fluent English"]), age=6)
add("accepted", 0, "Radar Operator Trainer (m/w/d)", "Küstenwache Dienstleistungen GmbH", "Cuxhaven",
    de("Wir schulen Personal für die Seeraumüberwachung.",
       ["Durchführung von Schulungen an Radaranlagen", "Erstellung von Schulungsunterlagen",
        "Betreuung der Teilnehmer", "Reisetätigkeit an Küstenstandorte"],
       ["Abgeschlossene Ausbildung, Erfahrung in der Seefahrt", "Freude am Unterrichten",
        "Sehr gute Deutschkenntnisse", "Führerschein Klasse B"]), age=4)

# --- accepted: energy and sustainability (looked for around Hamburg) --------------------------------------
for i, (title, company, city, lang, want) in enumerate([
    ("Elektroingenieur (m/w/d) Netzplanung Mittelspannung", "Elbnetz GmbH", "Hamburg", "de", 2),
    ("E-Mobility Engineer Charging Infrastructure (m/f/d)", "Ladehafen GmbH", "Hamburg", "en", 2),
    ("Energy Analyst (m/f/d) Flexibility Markets", "Tidewatt Energy GmbH", "Hamburg", "en", 2),
    ("Ingenieur Elektrotechnik (m/w/d) Schaltanlagen", "Hansa Schaltanlagen GmbH", "Bremen", "de", 1),
    ("Projektingenieur Photovoltaik (m/w/d)", "Sonnendeich Solar GmbH", "Kiel", "de", 1),
    ("Werkstudent (m/w/d) Energiewirtschaft", "Stromkontor Nord GmbH", "Hamburg", "de", 1),
    ("Smart Grid Engineer (m/f/d)", "Gridshore GmbH", "Lüneburg", "en", 2),
    ("Battery Systems Engineer (m/f/d)", "Speicherwerk Nord GmbH", "Hamburg", "en", 1),
]):
    body = (de("%s plant und betreibt Energieinfrastruktur im Norden." % company, ENERGY_TASKS_DE, ENERGY_PROFILE_DE)
            if lang == "de" else
            en("%s operates energy infrastructure in northern Germany." % company, ENERGY_TASKS_EN, ENERGY_PROFILE_EN))
    add("accepted", want, title, company, city, body, age=2 + i % 7, source="stepstone")

for i, (title, company, city, want) in enumerate([
    ("Sustainability Manager (m/w/d) Industrie", "GrünWerk Beratung GmbH", "Hamburg", 1),
    ("ESG Analyst (m/w/d)", "Hanse Invest Nachhaltigkeit GmbH", "Hamburg", 0),
    ("Energiemanager (m/w/d) ISO 50001", "Norddeutsche Papierwerke GmbH", "Lübeck", 1),
    ("LCA Engineer (m/w/d) Ökobilanz", "Kreislauf Technik GmbH", "Bremen", 1),
]):
    add("accepted", want, title, company, city,
        de("%s begleitet Unternehmen bei der Dekarbonisierung." % company, SUST_TASKS_DE, SUST_PROFILE_DE),
        age=3 + i, source="stepstone")

# --- accepted by the track rule, but a low quick score (language, years of experience) --------------------
for i, (title, company, city, want) in enumerate([
    ("Elektroingenieur (m/w/d) Netzbetrieb Leitstelle", "Stadtwerke Elbmarsch GmbH", "Hamburg", 0),
    ("Energiewirtschaft Referent (m/w/d) Regulierung", "Netzverband Nord e.V.", "Hamburg", 0),
    ("Ingenieur Elektrotechnik (m/w/d) Gutachten", "Prüfkontor Nord GmbH", "Bremen", 0),
    ("Energy Trader (m/f/d) Intraday", "Kontor Energiehandel GmbH", "Hamburg", 0),
    ("Hardware Engineer (m/w/d) Bahntechnik Zulassung", "Schienenwerk Signaltechnik GmbH", "Braunschweig", 1),
    ("Elektrotechnik Planer (m/w/d) Gebäudetechnik", "Planwerk TGA GmbH", "Hamburg", 0),
    ("Nachhaltigkeit Referent (m/w/d) Berichterstattung", "Hafenlogistik Holding AG", "Hamburg", 1),
    ("Radar Systemingenieur (m/w/d) Zulassung", "Seezeichen Technik GmbH", "Bremerhaven", 1),
]):
    add("low", want, title, company, city,
        de("%s sucht Verstärkung." % company,
           ["Erstellung von Gutachten und Stellungnahmen", "Abstimmung mit Behörden und Kunden",
            "Führung von Verhandlungen", "Dokumentation nach geltenden Normen"],
           ["Mindestens 6 Jahre Berufserfahrung", "Verhandlungssichere Deutschkenntnisse (C2)",
            "Abgeschlossenes Studium", "Bereitschaft zu Dienstreisen"]), age=30 + i, source="arbeitsagentur")

# --- only the track rule filters these: related to the profile, but worded without the keywords ----------
LOGIC_TASKS_DE = ["Entwurf rekonfigurierbarer Logikbausteine in einer Hardwarebeschreibungssprache",
                  "Umsetzung von Kamera-Datenpfaden mit hohen Bildraten",
                  "Timing-Analyse und Fehlersuche an Prototypen im Labor",
                  "Zusammenarbeit mit dem Team der Flugsteuerung für ferngesteuerte Fluggeräte"]
LOGIC_PROFILE_DE = ["Studium der Elektro- und Informationstechnik", "Erfahrung mit programmierbarer Logik und Schaltungssimulation",
                    "Interesse an Kameratechnik und Fluggeräten", "Gute Englischkenntnisse"]
LOGIC_TASKS_EN = ["Design reconfigurable logic in a hardware description language",
                  "Implement high-frame-rate camera data paths and their test benches",
                  "Timing closure and lab debugging on prototype boards",
                  "Work with the flight-control team on remotely piloted aircraft"]
LOGIC_PROFILE_EN = ["Degree in electrical engineering", "First experience with programmable logic and circuit simulation",
                    "Interest in cameras and aircraft", "Fluent English, German is a plus"]
DEPOT_TASKS_DE = ["Auswertung der Lastgänge elektrischer Lkw-Flotten", "Mathematische Modelle für Ladepläne im Depot",
                  "Planung der Anschlüsse an das 20-kV-Netz", "Abstimmung mit dem örtlichen Versorger zur Rückspeisung aus Fahrzeugen"]
DEPOT_PROFILE_DE = ["Studium der Elektro- und Informationstechnik", "Erfahrung mit ganzzahliger Programmierung und Python",
                    "Verständnis von Stromlieferverträgen", "Deutsch B1, Englisch fließend"]
ECO_TASKS_DE = ["Bewertung der Umweltwirkung unserer Geräte über den gesamten Lebensweg",
                "Aufbau einer Datenbank für Materialien und Emissionen", "Vorschläge für reparierbare und sparsame Produkte",
                "Zuarbeit für den jährlichen Bericht an die Geschäftsführung"]
ECO_PROFILE_DE = ["Studium im Ingenieurwesen oder in den Umweltwissenschaften", "Erfahrung mit Produktbilanzen",
                  "Sicherer Umgang mit Daten", "Gute Deutsch- und Englischkenntnisse"]
add("hidden", 2, "Entwicklungsingenieur Programmierbare Logik (m/w/d)", "Nordkap Mikrosysteme GmbH", "Hamburg",
    de("Nordkap Mikrosysteme entwickelt Kamerasysteme für Fluggeräte.", LOGIC_TASKS_DE, LOGIC_PROFILE_DE), age=2)
add("hidden", 2, "RTL Design Engineer (m/f/d) Video Pipelines", "Heliograph Imaging GmbH", "Jena",
    en("Heliograph Imaging builds cameras for aircraft.", LOGIC_TASKS_EN, LOGIC_PROFILE_EN), age=1)
add("hidden", 2, "Junior Engineer Programmable Logic Devices", "Corvus Flight Systems GmbH", "Bremen",
    en("Corvus Flight Systems develops payloads for remotely piloted aircraft.", LOGIC_TASKS_EN, LOGIC_PROFILE_EN), age=4)
add("hidden", 1, "Logic Design Engineer (m/f/d) High-Speed Interfaces", "Photonwerk GmbH", "Aachen",
    en("Photonwerk builds measurement devices.", LOGIC_TASKS_EN, LOGIC_PROFILE_EN), age=6)
add("hidden", 2, "Ingenieur (m/w/d) Ladepark-Planung für Lkw-Flotten", "Hafenstrom GmbH", "Hamburg",
    de("Hafenstrom betreibt Ladeparks für Lkw-Flotten.", DEPOT_TASKS_DE, DEPOT_PROFILE_DE), age=3, source="stepstone")
add("hidden", 1, "Analyst (m/w/d) Lastgänge und Stromverträge", "Deichstrom Analytics GmbH", "Hamburg",
    de("Deichstrom Analytics berät Flottenbetreiber.", DEPOT_TASKS_DE, DEPOT_PROFILE_DE), age=5, source="stepstone")
add("hidden", 1, "Ingenieur (m/w/d) Produktbilanzen und Ökodesign", "Küstenwerk Geräte GmbH", "Lübeck",
    de("Küstenwerk Geräte baut Haushaltsgeräte.", ECO_TASKS_DE, ECO_PROFILE_DE), age=7, source="stepstone")
add("hidden", 1, "Systemingenieur (m/w/d) ferngesteuerte Fluggeräte", "Nordwind Flugtechnik GmbH", "Rostock",
    de("Nordwind Flugtechnik entwickelt Flugsteuerungen.", LOGIC_TASKS_DE, LOGIC_PROFILE_DE), age=8)

# --- only the track rule filters these, and rightly so -----------------------------------------------------
for i, (title, company, city, tasks, profile) in enumerate([
    ("Marketing Manager (m/w/d) Social Media", "Küstenkind Mode GmbH", "Hamburg",
     ["Planung von Kampagnen auf Instagram und TikTok", "Betreuung von Influencern", "Auswertung der Reichweite",
      "Abstimmung mit dem Einkauf"],
     ["Studium Marketing oder Kommunikation", "Erfahrung im Social Media Marketing", "Kreativität", "Sehr gutes Deutsch"]),
    ("Accountant (m/f/d) Accounts Payable", "Harbour Trading GmbH", "Hamburg",
     ["Process incoming invoices", "Prepare month-end closing", "Reconcile accounts", "Support audits"],
     ["Commercial training or degree in finance", "Experience with SAP FI", "Careful way of working", "Fluent English"]),
    ("Koch (m/w/d) Betriebsrestaurant", "Hafenküche GmbH", "Hamburg",
     ["Zubereitung von Speisen", "Planung der Speisekarte", "Einhaltung der Hygienevorschriften", "Warenbestellung"],
     ["Abgeschlossene Ausbildung als Koch", "Erfahrung in der Gemeinschaftsverpflegung", "Teamfähigkeit", "Deutschkenntnisse"]),
    ("Frontend Developer React (m/f/d)", "Shopwelle GmbH", "Hamburg",
     ["Build web shops with React and TypeScript", "Improve page speed", "Write unit tests", "Work with designers"],
     ["Experience with React", "Good eye for design", "Knowledge of web accessibility", "Fluent English"]),
    ("HR Business Partner (m/w/d)", "Alsterhaus Personal GmbH", "Hamburg",
     ["Beratung der Führungskräfte", "Begleitung von Einstellungen", "Arbeitsrechtliche Fragen", "Personalentwicklung"],
     ["Studium mit Schwerpunkt Personal", "Mehrjährige Erfahrung", "Kenntnisse im Arbeitsrecht", "Sehr gutes Deutsch"]),
    ("UX Designer (m/f/d) Mobile Banking", "Elbbank Digital GmbH", "Hamburg",
     ["Design flows for our banking app", "Run user tests", "Maintain the design system", "Work with product owners"],
     ["Portfolio of mobile designs", "Experience with Figma", "User research skills", "Fluent English and German"]),
    ("Projektleiter Hochbau (m/w/d)", "Speicherstadt Bau GmbH", "Hamburg",
     ["Leitung von Bauprojekten", "Kosten- und Terminkontrolle", "Führung der Nachunternehmer", "Abnahmen"],
     ["Studium Bauingenieurwesen", "Erfahrung in der Bauleitung", "Kenntnisse der VOB", "Führerschein"]),
    ("Zahnmedizinische Fachangestellte (m/w/d)", "Zahnarztpraxis am Fleet", "Hamburg",
     ["Assistenz bei Behandlungen", "Terminvergabe", "Abrechnung", "Hygiene"],
     ["Abgeschlossene Ausbildung", "Freundliches Auftreten", "Zuverlässigkeit", "Deutschkenntnisse"]),
    ("Data Engineer (m/f/d) E-Commerce", "Paketfuchs GmbH", "Hamburg",
     ["Build data pipelines with Spark", "Model the data warehouse", "Monitor data quality", "Support analysts"],
     ["Experience with SQL and Python", "Knowledge of cloud platforms", "Degree in computer science", "Fluent English"]),
    ("Physiotherapeut (m/w/d)", "Praxis Elbgesund", "Hamburg",
     ["Behandlung von Patienten", "Erstellung von Therapieplänen", "Dokumentation", "Hausbesuche"],
     ["Abgeschlossene Ausbildung", "Fortbildung in manueller Therapie", "Einfühlungsvermögen", "Deutschkenntnisse"]),
]):
    add("unrelated", 0, title, company, city,
        de("%s sucht Verstärkung." % company, tasks, profile) if "(m/w/d)" in title
        else en("%s is hiring." % company, tasks, profile), age=2 + i)

# --- removed by a rule the user set (never brought back) ---------------------------------------------------
add("hard", 0, "Senior FPGA Architect (m/w/d)", "Aeris Vision GmbH", "Bremen",
    de("Aeris Vision entwickelt Kamerasysteme.", FPGA_TASKS_DE, FPGA_PROFILE_DE), age=3)
add("hard", 0, "Vertriebsingenieur (m/w/d) FPGA Module", "Chipkontor Vertrieb GmbH", "Hamburg",
    de("Chipkontor vertreibt FPGA Module.", FPGA_TASKS_DE, FPGA_PROFILE_DE), age=2)
add("hard", 0, "Servicetechniker (m/w/d) Ladeinfrastruktur", "Ladehafen GmbH", "Hamburg",
    de("Ladehafen betreibt Ladeparks.", ENERGY_TASKS_DE, ENERGY_PROFILE_DE), age=2)
add("hard", 0, "Sales Manager Energy Storage (m/f/d)", "Speicherwerk Nord GmbH", "Hamburg",
    en("Speicherwerk Nord sells battery storage.", ENERGY_TASKS_EN, ENERGY_PROFILE_EN), age=4)

# Which postings get an explicit verdict (the rest stay for the "Judge jobs" sheet). Counted per kind.
JUDGED = {"accepted": 20, "low": 6, "hidden": 5, "unrelated": 6}
LABEL = {2: "good", 1: "maybe", 0: "bad"}


def main(folder: str) -> None:
    workspace = Path(folder).expanduser()
    build_demo(workspace, log=print)
    cfg = load_config(workspace / "jobradar.yaml")
    profile = load_profile(cfg.profile_path)
    conn = db.connect(cfg.db_path)
    raws = [RawJob(source=p["source"], title=p["title"], company=p["company"], location=p["city"],
                   url="https://jobs.example/%d" % i, description=p["text"], posted_at=days(p["age"]))
            for i, p in enumerate(POSTINGS)]
    counts = import_raws(conn, cfg, profile, raws, "seed")
    print("seed: found %d, new %d, merged %d, filtered %d" % (counts.found, counts.new, counts.merged, counts.filtered))
    # the stand-in evaluates the best twelve; the rest wait in the queue
    evaluate_pending(conn, cfg, profile, FakeLLM(), limit=12, log=lambda m: None)

    by_url = {r["url"]: dict(r) for r in conn.execute("SELECT id, url, status, prescore, llm_score, filtered_reason FROM jobs")}
    judged = dict.fromkeys(JUDGED, 0)
    for i, p in enumerate(POSTINGS):
        row = by_url.get("https://jobs.example/%d" % i)
        if row is None:
            print("merged away:", p["title"])
            continue
        p["row"] = row
        if bench is not None and p["kind"] in JUDGED and judged[p["kind"]] < JUDGED[p["kind"]]:
            bench.set_label(conn, row["id"], LABEL[p["want"]], "")
            judged[p["kind"]] += 1
    # what the user did with a posting counts as a verdict too
    waiting = [p["row"]["id"] for p in POSTINGS if p.get("row") and p["kind"] == "accepted"
               and p["row"]["status"] == "new"][-4:]
    for job_id, status in zip(waiting, ["shortlisted", "shortlisted", "skipped", "skipped"]):
        db.set_status(conn, job_id, status, "seed")
    conn.commit()

    if bench is not None:
        report = bench.report(conn, cfg, profile)
        print("labels:", report["labels"])
        for g in report["gate"]["groups"]:
            print("group %-15s total %3d judged %2d wanted %s" % (g["id"], g["postings"], g["judged"], g["wanted"]))
        print("rankings on", report["rankings"]["n"], "postings; estimated missed:", report["gate"]["estimated_missed"])
    else:
        print("an engine without verdicts: postings only")
    for kind in ("accepted", "low", "hidden", "unrelated", "hard"):
        rows = [p["row"] for p in POSTINGS if p["kind"] == kind and p.get("row")]
        print("%-9s %2d postings · status %s · quick score %s" % (
            kind, len(rows), sorted({r["status"] for r in rows}),
            "%.0f to %.0f" % (min(r["prescore"] for r in rows), max(r["prescore"] for r in rows)) if rows else "-"))
    for p in POSTINGS:
        if p.get("row") and p["kind"] in ("low", "hidden", "hard", "unrelated"):
            print("  %-9s %-58s %-9s %5.1f  %s" % (p["kind"], p["title"][:58], p["row"]["status"], p["row"]["prescore"],
                                                 p["row"]["filtered_reason"] or ""))
    conn.close()


if __name__ == "__main__":
    main(sys.argv[1])
