import httpx

from jobradar.http import make_client
from jobradar.liveness import check_url
from jobradar.sources.importers import (
    fetch_url_details, parse_alert_email, parse_jsonld_jobposting, parse_linkedin_guest, raw_from_url,
)

JSONLD_PAGE = """<html><head><title>x</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebPage"},
{"@type":"JobPosting","title":"Embedded Engineer (m/w/d)","hiringOrganization":{"@type":"Organization","name":"Muster GmbH"},
"jobLocation":{"@type":"Place","address":{"addressLocality":"Köln","addressCountry":"DE"}},
"datePosted":"2026-11-03","employmentType":["FULL_TIME"],"description":"<p>Wir suchen <b>VHDL</b> Erfahrung.</p>",
"baseSalary":{"@type":"MonetaryAmount","currency":"EUR","value":{"@type":"QuantitativeValue","minValue":55000,"maxValue":65000,"unitText":"YEAR"}}}]}
</script></head><body>...</body></html>"""

LINKEDIN_LIVE = """<section class="core-rail"><div class="top-card-layout">
<h1 class="top-card-layout__title">FPGA Engineer</h1>
<h4><span class="topcard__flavor"><a class="topcard__org-name-link" href="#">Acme GmbH</a></span>
<span class="topcard__flavor topcard__flavor--bullet">Munich, Bavaria, Germany</span></h4>
<span class="posted-time-ago__text">2 days ago</span></div>
<div class="show-more-less-html__markup"><p>Design <strong>VHDL</strong> for radar.</p></div>
<ul><li class="description__job-criteria-item"><h3 class="description__job-criteria-subheader">Seniority level</h3>
<span class="description__job-criteria-text">Entry level</span></li></ul></section>"""

LINKEDIN_CLOSED = """<div class="top-card-layout"><h1 class="top-card-layout__title">Old Job</h1>
<span class="topcard__flavor">Acme</span><figure class="closed-job"><figcaption>No longer accepting applications</figcaption>
</figure></div>"""


def test_jsonld_jobposting():
    d = parse_jsonld_jobposting(JSONLD_PAGE)
    assert d["title"] == "Embedded Engineer (m/w/d)" and d["company"] == "Muster GmbH"
    assert d["location"] == "Köln" and d["posted_at"] == "2026-11-03"
    assert "VHDL" in d["description"] and d["salary"]["min"] == 55000
    assert d["employment_type"] == "FULL_TIME"


def test_linkedin_guest_parsing():
    d = parse_linkedin_guest(LINKEDIN_LIVE)
    assert d["title"] == "FPGA Engineer" and d["company"] == "Acme GmbH"
    assert d["location"].startswith("Munich") and "VHDL" in d["description"]
    assert d["seniority"] == "Entry level" and d["closed"] is False and d["posted_at"]
    assert parse_linkedin_guest(LINKEDIN_CLOSED)["closed"] is True


def test_fetch_url_details_routes_by_site():
    def handler(request: httpx.Request):
        if "jobs-guest" in request.url.path:
            assert request.url.path.endswith("/4100000001")
            return httpx.Response(200, text=LINKEDIN_LIVE)
        return httpx.Response(200, text=JSONLD_PAGE)

    client = make_client(transport=httpx.MockTransport(handler))
    li = fetch_url_details(client, "https://de.linkedin.com/comm/jobs/view/4100000001?trk=x")
    assert li["company"] == "Acme GmbH"
    raw = raw_from_url(client, "https://www.stepstone.de/stellenangebote--Embedded-Koeln-Muster--12345678-inline.html")
    assert raw.source == "manual:stepstone" and raw.title.startswith("Embedded") and raw.salary_max == 65000


ALERT_EML = """From: LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>
Subject: 3 neue Jobs für FPGA
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/4100000011/?trackingId=a">FPGA Engineer (m/w/d)</a>
<p>Acme GmbH · München</p></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4100000012/?trackingId=b">Hardware Developer</a></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4100000011/?trackingId=c">Jetzt bewerben</a></td></tr>
<tr><td><a href="https://www.linkedin.com/settings">Einstellungen</a></td></tr></table>"""

STEPSTONE_TEXT = """Ihre neuen Jobs bei StepStone

Elektroingenieur Netzplanung (m/w/d)
Rheinwerk Netze GmbH, Köln
https://www.stepstone.de/stellenangebote--Elektroingenieur-Netzplanung-Koeln-Rheinwerk--87654321-inline.html?utm_source=alert

Job ansehen
https://www.stepstone.de/stellenangebote--Sustainability-Analyst-Bonn-Gruen--87654322-inline.html
"""


def test_alert_email_html_eml():
    raws = parse_alert_email(ALERT_EML.encode("utf-8"))
    assert [r.url for r in raws] == ["https://www.linkedin.com/jobs/view/4100000011",
                                     "https://www.linkedin.com/jobs/view/4100000012"]
    assert raws[0].title == "FPGA Engineer (m/w/d)" and raws[0].company == "Acme GmbH"
    assert raws[0].location == "München" and raws[0].source == "alert:linkedin"


def test_alert_email_plain_text_and_slug_titles():
    raws = parse_alert_email(STEPSTONE_TEXT)
    assert len(raws) == 2
    assert raws[0].title == "Elektroingenieur Netzplanung (m/w/d)"
    assert raws[0].company == "Rheinwerk Netze GmbH" and raws[0].location == "Köln"
    assert raws[1].title == "Sustainability Analyst Bonn Gruen"  # URL slug when the card has no title line
    assert all(r.source == "alert:stepstone" for r in raws)


def test_liveness_is_conservative():
    def handler(request: httpx.Request):
        p = request.url.path
        if p == "/gone":
            return httpx.Response(404)
        if p == "/closed":
            return httpx.Response(200, text="<p>Diese Stelle ist leider nicht mehr verfügbar.</p>")
        if p == "/forbidden":
            return httpx.Response(403)
        if "jobs-guest" in p:
            return httpx.Response(200, text=LINKEDIN_CLOSED)
        return httpx.Response(200, text="<h1>FPGA Engineer</h1>")

    c = make_client(transport=httpx.MockTransport(handler))
    assert check_url(c, "https://x.example/gone")[0] == "closed"
    assert check_url(c, "https://x.example/closed")[0] == "closed"
    assert check_url(c, "https://x.example/forbidden")[0] == "uncertain"
    assert check_url(c, "https://x.example/open")[0] == "live"
    assert check_url(c, "https://www.linkedin.com/jobs/view/4100000099")[0] == "closed"
