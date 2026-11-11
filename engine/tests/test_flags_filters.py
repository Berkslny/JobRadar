import pytest

from jobradar.processing.filters import FilterEngine, location_in_germany
from jobradar.processing.flags import (
    citizenship_ok, detect_agency, detect_clearance, detect_employment_type, detect_german, detect_remote,
    detect_salary, detect_seniority, detect_tariff, detect_years_required,
)
from jobradar.profile import Profile


@pytest.mark.parametrize("text,level,optional", [
    ("Sehr gute Deutsch- und Englischkenntnisse", "C1", False),
    ("Gute Deutschkenntnisse in Wort und Schrift", "B2", False),
    ("Verhandlungssichere Deutschkenntnisse", "C1", False),
    ("Deutsch fließend in Wort und Schrift", "C1", False),
    ("Deutschkenntnisse auf C1-Niveau", "C1", False),
    ("Englisch C1, Deutsch B1", "B1", False),
    ("Deutsch als Muttersprache", "C2", False),
    ("Fluent English; German is a plus", None, True),
    ("Business fluent German and English", "C1", False),
    ("Fluency in German and English", "C1", False),
    ("Deutschkenntnisse sind von Vorteil", None, True),
    ("Standort in ganz Deutschland gut erreichbar", None, False),
    ("Good command of German (B2)", "B2", False),
])
def test_german_level(text, level, optional):
    r = detect_german(text)
    assert r["german_level"] == level
    assert r["german_optional"] == optional


def test_clearance_and_citizenship():
    assert detect_clearance("Bereitschaft zur Sicherheitsüberprüfung Ü2 nach SÜG")["clearance"] == "Ü2"
    assert detect_clearance("Sicherheitsüberprüfung erforderlich")["clearance"] == "yes"
    assert detect_clearance("deutsche Staatsangehörigkeit erforderlich")["citizenship"] == "DE"
    assert detect_clearance("Staatsangehörigkeit eines NATO-Mitgliedstaates")["citizenship"] == "NATO"
    assert detect_clearance("EU citizenship required")["citizenship"] == "EU"
    assert detect_clearance("Wir entwickeln Software für Banken")["clearance"] is None
    p = Profile(name="x", citizenships=["TR"])
    assert citizenship_ok("NATO", p) is True
    assert citizenship_ok("EU", p) is False
    assert citizenship_ok("DE", Profile(name="y")) is None


@pytest.mark.parametrize("title,body,raw,expected", [
    ("Werkstudent (m/w/d) Embedded", "", "", "werkstudent"),
    ("Working Student Hardware", "", "", "werkstudent"),
    ("Masterarbeit: FPGA-basierte Bildverarbeitung", "", "", "thesis"),
    ("Praktikum Elektrotechnik", "", "", "internship"),
    ("Trainee Engineering", "", "", "trainee"),
    ("FPGA Engineer", "", "fulltime", "fulltime"),
    ("FPGA Engineer", "Vollzeit, unbefristet", "", "fulltime"),
    ("FPGA Engineer", "", "", ""),
])
def test_employment_type(title, body, raw, expected):
    assert detect_employment_type(title, body, raw) == expected


@pytest.mark.parametrize("title,expected", [
    ("Senior FPGA Engineer", "senior"),
    ("Teamleiter Hardware", "lead"),
    ("Head of Electronics", "lead"),
    ("Leiterplattendesigner (m/w/d)", "mid"),
    ("Junior Hardware Engineer", "junior"),
    ("Sustainability Manager", "mid"),
    ("Absolvent Elektrotechnik", "junior"),
])
def test_seniority(title, expected):
    assert detect_seniority(title, "") == expected


def test_years_required():
    assert detect_years_required("Mindestens 3 Jahre Berufserfahrung in der FPGA-Entwicklung") == 3
    assert detect_years_required("5+ years of professional experience with VHDL") == 5
    assert detect_years_required("3-5 Jahre einschlägige Berufserfahrung") == 3
    assert detect_years_required("Erste Erfahrung mit VHDL") is None


def test_salary_and_tariff():
    s = detect_salary("Wir bieten 60.000 - 70.000 € brutto im Jahr")
    assert s["min"] == 60000 and s["max"] == 70000 and s["period"] == "year"
    s = detect_salary("Salary: €55k–€65k per year")
    assert s["min"] == 55000 and s["max"] == 65000
    s = detect_salary("Vergütung: 4.200 € brutto monatlich")
    assert s["min"] == 4200 and s["period"] == "month"
    assert detect_salary("Unser Team besteht aus 120 Personen") is None
    assert detect_tariff("Vergütung nach TV-L E13") == "TV-L E13"
    assert detect_tariff("Bezahlung nach Entgeltgruppe 12 TVöD Bund") == "TVöD Bund E12"
    assert detect_tariff("Vergütung nach Tarifvertrag IG Metall") == "IG Metall"
    assert detect_tariff("Vergütung nach Tarifvertrag") == "Tarifvertrag"
    assert detect_tariff("in the era of AI") is None


def test_agency_and_remote():
    assert detect_agency("Hays AG", "")
    assert detect_agency("Muster GmbH", "Für unseren Kunden, ein führendes Unternehmen, suchen wir")
    assert not detect_agency("Rheinmetall AG", "Wir entwickeln Systeme")
    assert detect_remote("Engineer (Remote)", "", "", None) == "remote"
    assert detect_remote("Engineer", "Remote", "", None) == "remote"
    assert detect_remote("Engineer", "Köln", "2 Tage Homeoffice pro Woche", None) == "hybrid"
    assert detect_remote("Engineer", "Köln", "Die Arbeit erfolgt vor Ort", None) == "onsite"


@pytest.mark.parametrize("loc,expected", [
    ("München, Bayern, Deutschland", True),
    ("Berlin", True),
    ("Remote, Germany", True),
    ("Remote - EU", True),
    ("London, United Kingdom", False),
    ("Remote - US", False),
    ("Remote", True),
    ("", None),
    ("Aachen, DE", True),
    ("Paris, France · Munich, Germany", True),
])
def test_location_in_germany(loc, expected):
    assert location_in_germany(loc) is expected


def test_filter_engine_rules(cfg, profile):
    fe = FilterEngine(cfg, profile)
    base = {"title": "FPGA Engineer", "company_norm": "acme", "description": "", "flags": {}, "location": "Berlin"}
    assert fe.reasons(base) == []
    assert any("istenmeyen" in r for r in fe.reasons({**base, "title": "Vertriebsingenieur FPGA"}))
    assert any("kıdem" in r for r in fe.reasons({**base, "flags": {"seniority": "senior"}}))
    assert any("çalışma türü" in r for r in fe.reasons({**base, "flags": {"employment_type": "thesis"}}))
    assert any("dışı konum" in r for r in fe.reasons({**base, "location": "London, UK", "needs_location_check": True}))
    # Off-target title from a company board with no description is dropped ...
    assert any("hedef" in r for r in fe.reasons({**base, "title": "Office Manager", "needs_location_check": True}))
    # ... but a search hit without a description is kept for enrichment.
    assert fe.reasons({**base, "title": "Office Manager"}) == []


def test_umlaut_free_city_names():
    assert location_in_germany("Rheinmetall IT Solutions | Dusseldorf, Unterluss") is True
    assert location_in_germany("Munchen") is True and location_in_germany("Koln") is True
