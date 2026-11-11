from datetime import date, timedelta

import pytest

from jobradar.processing.normalize import canonical_url, clean_title, normalize_company, normalize_title
from jobradar.textutil import KeywordSet, detect_language, html_to_text, parse_date, parse_relative_posted


def test_html_to_text_handles_escaped_greenhouse_html():
    raw = "&lt;p&gt;Your tasks&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Write VHDL&lt;/li&gt;&lt;li&gt;Test boards&lt;/li&gt;&lt;/ul&gt;"
    text = html_to_text(raw)
    assert "Your tasks" in text
    assert "• Write VHDL" in text and "• Test boards" in text
    assert "<" not in text


def test_detect_language():
    assert detect_language("Wir suchen Sie für unser Team und bieten Ihnen spannende Aufgaben mit Erfahrung") == "de"
    assert detect_language("We are looking for you to join our team and you will work with the best") == "en"
    assert detect_language("FPGA") == ""


def test_keywords_match_german_compounds_and_short_words():
    ks = KeywordSet(["Hardwareentwickl", "FPGA", "=Fahrer", "C++"])
    assert ks.find("Hardwareentwickler (m/w/d) für Radar") == ["Hardwareentwickl"]
    assert ks.find("FPGA-Entwickler") == ["FPGA"]
    assert ks.find("FPGAs") == []
    assert ks.find("Entwickler Fahrerassistenzsysteme") == []
    assert ks.find("LKW-Fahrer gesucht") == ["Fahrer"]
    assert ks.find("C++ und Python") == ["C++"]


@pytest.mark.parametrize("value,expected", [
    ("2026-11-05T10:00:00Z", "2026-11-05"),
    ("05.11.2026", "2026-11-05"),
    (1762300800000, "2025-11-05"),
    ("nan", None),
    (None, None),
])
def test_parse_date(value, expected):
    assert parse_date(value) == expected


def test_parse_relative_posted():
    ref = date(2026, 11, 8)
    assert parse_relative_posted("Posted 3 Days Ago", ref) == "2026-11-05"
    assert parse_relative_posted("Posted Today", ref) == "2026-11-08"
    assert parse_relative_posted("vor 2 Tagen", ref) == "2026-11-06"
    assert parse_relative_posted("Gestern ausgeschrieben", ref) == "2026-11-07"
    assert parse_relative_posted("Posted 30+ Days Ago", ref) == (ref - timedelta(days=30)).isoformat()


@pytest.mark.parametrize("title", [
    "FPGA-Entwickler (m/w/d)", "FPGA-Entwickler (w/m/d)", "FPGA-Entwickler (m/f/d)", "FPGA-Entwickler (all genders)",
    "FPGA-Entwickler [m|w|d]", "FPGA-Entwickler ( m / w / d )", "FPGA-Entwickler*in", "FPGA-Entwickler:in",
    "FPGA-Entwickler (gn)", "FPGA-Entwickler m/w/d",
])
def test_gender_markers_removed(title):
    assert normalize_title(title) == "fpga entwickler"


def test_clean_title_keeps_meaning():
    assert clean_title("Junior FPGA Engineer (all genders) – Radar") == "Junior FPGA Engineer – Radar"
    assert clean_title("Werkstudent (m/w/d) Embedded Hardware") == "Werkstudent Embedded Hardware"


def test_normalize_company():
    assert normalize_company("Rheinmetall AG") == "rheinmetall"
    assert normalize_company("Nordlicht Defence Systems GmbH") == normalize_company("Nordlicht Defence Systems")
    assert normalize_company("Siemens Energy Global GmbH & Co. KG") == "siemens energy global"
    assert normalize_company("RENK Group AG") == "renk"
    assert normalize_company("Müller Elektronik") == "mueller elektronik"


def test_canonical_url_linkedin_variants():
    a = canonical_url("https://www.linkedin.com/jobs/view/4100000001/?refId=abc&trackingId=xyz")
    b = canonical_url("https://de.linkedin.com/comm/jobs/view/4100000001?alertAction=view")
    c = canonical_url("https://www.linkedin.com/jobs/search/?currentJobId=4100000001&keywords=fpga")
    d = canonical_url("https://www.linkedin.com/jobs/view/fpga-engineer-at-acme-4100000001")
    assert a[1] == b[1] == c[1] == d[1] == "linkedin:4100000001"
    assert a[0] == "https://www.linkedin.com/jobs/view/4100000001"


def test_canonical_url_indeed_stepstone_aa_and_generic():
    assert canonical_url("https://de.indeed.com/rc/clk?jk=AbC123&from=vj")[1] == "indeed:abc123"
    s = canonical_url("https://www.stepstone.de/stellenangebote--FPGA-Entwickler-Muenchen-Firma--12345678-inline.html?rltr=1")
    assert s[1] == "stepstone:12345678"
    aa = canonical_url("https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-123%252F4-S")
    assert aa[1] == "aa:10000-123/4-S"
    assert aa[0].endswith("10000-123%252F4-S")
    g1 = canonical_url("https://jobs.example.com/job/42?utm_source=x&gh_jid=42")
    g2 = canonical_url("https://jobs.example.com/job/42/?gh_jid=42&utm_medium=y")
    assert g1[1] == g2[1]
    assert "utm_" not in g1[0]
    assert canonical_url("https://jobs.ashbyhq.com/acme/123/application")[1] == "jobs.ashbyhq.com/acme/123"
