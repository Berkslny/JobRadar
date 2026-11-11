import json

import httpx

from jobradar.config import CompanySource
from jobradar.http import make_client
from jobradar.sources import arbeitsagentur, ats, freehire
from jobradar.sources.base import SourceContext
from jobradar.sources.jobspy_src import JobSpySource, row_to_raw


def client_for(handler):
    return make_client(transport=httpx.MockTransport(handler))


def test_arbeitsagentur_v6_parse_and_detail():
    data = {"ergebnisliste": [
        {"referenznummer": "10000-123/4-S", "stellenangebotsTitel": " FPGA Entwickler (m/w/d) ", "firma": " ACME ",
         "stellenlokationen": [{"adresse": {"ort": "Aachen", "land": "DEUTSCHLAND"}},
                               {"adresse": {"ort": "Wien", "land": "ÖSTERREICH"}}],
         "aktuelleVeroeffentlichungsdatum": "2026-11-05", "homeofficeprozent": 100},
        {"stellenangebotsTitel": "kein refnr"},
    ]}
    jobs = arbeitsagentur.parse_list(data, 1)
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "FPGA Entwickler (m/w/d)" and j.company == "ACME"
    assert j.location == "Aachen · Wien, Österreich"
    assert j.posted_at == "2026-11-05" and j.remote is True
    assert j.url.endswith("10000-123%252F4-S")
    assert j.detail_ref == "aa:10000-123/4-S"

    seen = {}

    def handler(request: httpx.Request):
        seen["key"] = request.headers.get("X-API-Key")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"stellenangebotsBeschreibung": "<p>VHDL &amp; Zynq</p>", "firma": "ACME GmbH"})

    d = arbeitsagentur.fetch_detail(client_for(handler), "10000-123/4-S")
    assert d["description"] == "VHDL & Zynq" and d["company"] == "ACME GmbH"
    assert seen["key"] == "jobboerse-jobsuche"
    assert seen["path"].endswith("MTAwMDAtMTIzLzQtUw==")


def test_arbeitsagentur_source_queries_and_partial_failure(cfg, profile):
    calls = []

    def handler(request: httpx.Request):
        calls.append(dict(request.url.params))
        if request.url.params.get("was") == "FPGA":
            return httpx.Response(500)
        return httpx.Response(200, json={"ergebnisliste": [
            {"referenznummer": f"R-{len(calls)}", "stellenangebotsTitel": "Elektroingenieur", "firma": "X"}]})

    ctx = SourceContext(config=cfg, profile=profile, client=client_for(handler), log=lambda m: None)
    jobs = arbeitsagentur.ArbeitsagenturSource().fetch(ctx)
    assert jobs and ctx.warnings  # FPGA query failed, others succeeded
    nationwide = [c for c in calls if c.get("was") == "FPGA Entwickler"]
    assert nationwide and "wo" not in nationwide[0]  # fpga track is nationwide
    local = [c for c in calls if c.get("was") == "Netzplanung"]
    assert local and local[0]["wo"] == "Hamburg" and local[0]["umkreis"] == "100"
    assert {c["angebotsart"] for c in calls} == {"1", "34"}


def test_freehire_parse():
    item = {"public_slug": "fpga-acme-1", "url": "https://boards.greenhouse.io/acme/jobs/1", "title": "FPGA Engineer",
            "company": "Acme", "location": "Munich", "description": "<p>VHDL</p>", "posted_at": "2026-11-01T00:00:00Z",
            "source": "greenhouse", "work_mode": "hybrid", "closed_at": None,
            "enrichment": {"employment_type": "full_time", "salary_min": 60000, "salary_max": 70000,
                           "salary_currency": "EUR", "salary_period": "year", "seniority": "junior"}}
    raw = freehire.parse_item(item)
    assert raw.title == "FPGA Engineer" and raw.description_html
    assert raw.employment_type == "fulltime" and raw.salary_min == 60000
    assert raw.extra["origin"] == "greenhouse"
    assert freehire.parse_item({**item, "closed_at": "2026-11-02"}) is None


def test_greenhouse_lever_ashby_parsers():
    gh = ats.parse_greenhouse({"jobs": [{"id": 7, "title": "Hardware Engineer", "location": {"name": "Munich"},
                                         "absolute_url": "https://job-boards.greenhouse.io/helsing/jobs/7",
                                         "content": "&lt;p&gt;VHDL&lt;/p&gt;", "updated_at": "2026-11-01T10:00:00Z"}]},
                               "Helsing")
    assert gh[0].location == "Munich" and gh[0].needs_location_check and gh[0].description_html
    lv = ats.parse_lever([{"id": "u1", "text": "FPGA Dev", "hostedUrl": "https://jobs.lever.co/x/u1",
                           "categories": {"location": "Berlin", "commitment": "Full-time"}, "createdAt": 1762000000000,
                           "descriptionPlain": "About", "lists": [{"text": "Tasks", "content": "<li>VHDL</li>"}],
                           "workplaceType": "remote"}], "X")
    assert "VHDL" in lv[0].description and lv[0].remote is True and lv[0].employment_type == "Full-time"
    ab = ats.parse_ashby({"jobs": [{"id": "a", "title": "EW Engineer", "location": "Munich", "isListed": True,
                                    "secondaryLocations": [{"location": "Berlin"}], "jobUrl": "https://jobs.ashbyhq.com/s/a",
                                    "descriptionPlain": "radar", "publishedAt": "2026-11-02T00:00:00Z",
                                    "compensation": {"compensationTierSummary": "€60K – €75K"}},
                                   {"id": "b", "title": "hidden", "isListed": False, "jobUrl": "x"}]}, "S")
    assert len(ab) == 1 and ab[0].location == "Munich · Berlin" and ab[0].extra["salary_text"] == "€60K – €75K"


def test_personio_xml_and_listing():
    xml = """<?xml version="1.0" encoding="UTF-8"?><workzag-jobs>
    <position><id>123</id><office>Gilching</office><additionalOffices><office>München</office></additionalOffices>
    <name>FPGA Engineer (m/w/d)</name><schedule>full-time</schedule><createdAt>2026-11-01T08:00:00+00:00</createdAt>
    <jobDescriptions><jobDescription><name>Aufgaben</name><value><![CDATA[<ul><li>VHDL</li></ul>]]></value></jobDescription>
    </jobDescriptions></position></workzag-jobs>"""
    jobs = ats.parse_personio_xml(xml, "QS", "qs.jobs.personio.de")
    assert jobs[0].url == "https://qs.jobs.personio.de/job/123"
    assert jobs[0].location == "Gilching · München" and "• VHDL" in jobs[0].description
    payload = json.dumps([1, '{"id":"555","name":"Embedded Engineer","main_office":"Berlin","additional_offices":[],'
                             '"created_at":"2026-10-30","available_languages":["de","en"],"current_locale":"de"}'])
    html = f"<script>self.__next_f.push({payload})</script>"
    listing = ats.parse_personio_listing(html, "QS", "qs.jobs.personio.de")
    assert listing[0].title == "Embedded Engineer" and listing[0].detail_ref.startswith("url:")


def test_personio_falls_back_to_listing_on_404():
    payload = json.dumps([1, '{"id":"9","name":"HW","main_office":"Berlin","available_languages":["de"]}'])

    def handler(request):
        if request.url.path == "/xml":
            return httpx.Response(404)
        return httpx.Response(200, text=f"<script>self.__next_f.push({payload})</script>")

    jobs = ats.fetch_personio(client_for(handler), CompanySource(name="QS", ats="personio", slug="qs"))
    assert [j.title for j in jobs] == ["HW"]


def test_smartrecruiters_recruitee_workday_softgarden_rheinmetall():
    sr = ats.parse_smartrecruiters({"content": [{"id": "1", "name": "HW Eng", "releasedDate": "2026-11-01T00:00:00Z",
                                                 "location": {"city": "Ulm", "country": "de", "remote": False},
                                                 "typeOfEmployment": {"label": "Full-time"}}]}, "Acme", "acme")
    assert sr[0].url == "https://jobs.smartrecruiters.com/acme/1" and sr[0].detail_ref == "sr:acme:1"
    rc = ats.parse_recruitee({"offers": [{"id": 3, "title": "PCB Designer", "careers_url": "https://x.recruitee.com/o/pcb",
                                          "locations": [{"name": "Köln"}, {"name": "Remote in Germany"}],
                                          "description": "<p>Altium</p>", "requirements": "<p>B2</p>",
                                          "published_at": "2026-11-01 10:00:00 UTC"}]}, "X")
    assert rc[0].location == "Köln · Remote in Germany" and rc[0].posted_at == "2026-11-01"
    host, tenant, site = ats.workday_parts("https://acme.wd3.myworkdayjobs.com/en-US/External_Careers")
    assert (host, tenant, site) == ("acme.wd3.myworkdayjobs.com", "acme", "External_Careers")
    wd = ats.parse_workday({"jobPostings": [{"title": "FPGA Engineer", "externalPath": "/job/Munich/FPGA_R1",
                                             "locationsText": "Munich", "postedOn": "Posted Today",
                                             "bulletFields": ["R1"]}]}, "Acme", host, tenant, site)
    assert wd[0].url == "https://acme.wd3.myworkdayjobs.com/External_Careers/job/Munich/FPGA_R1"
    assert wd[0].detail_ref.startswith("wd:acme.wd3.myworkdayjobs.com|acme|External_Careers|/job/")
    sg_html = ('<div class="matchElement" id="job_id_42"><a href="/job/42/FPGA?l=de">FPGA <b>Engineer</b></a>'
               '<span class="location-view-item">Augsburg</span><div class="matchValue date">11/05/2026</div></div>')
    sg = ats.parse_softgarden(sg_html, "RENK", "https://renk-group.softgarden.io/de/widgets/jobs")
    assert sg[0].title == "FPGA Engineer" and sg[0].url.startswith("https://renk-group.softgarden.io/job/42")
    assert sg[0].posted_at == "2026-11-05"
    rh_html = ('<div class="flex gap-0.5 group"><a href="/en/job/FPGA_Engineer/77"><div class="md:text-xl font-bold">'
               'FPGA Engineer (m/f/d)</div></a><div class="flex flex-wrap mr-6">Rheinmetall Electronics | Bremen</div></div>')
    rh = ats.parse_rheinmetall(rh_html, "https://www.rheinmetall.com", "Rheinmetall")
    assert rh[0].title == "FPGA Engineer (m/f/d)" and rh[0].location == "Bremen"
    assert rh[0].url == "https://www.rheinmetall.com/en/job/FPGA_Engineer/77"


def test_detect_ats():
    html = ('<a href="https://job-boards.greenhouse.io/helsing/jobs/1">x</a>'
            '<iframe src="https://quantum-systems.jobs.personio.de/"></iframe>'
            '<a href="https://acme.wd3.myworkdayjobs.com/en-US/External">y</a>')
    found = ats.detect_ats(html)
    kinds = {f["ats"]: f for f in found}
    assert kinds["greenhouse"]["slug"] == "helsing"
    assert kinds["personio"]["slug"] == "quantum-systems"
    assert kinds["workday"]["url"].startswith("https://acme.wd3.myworkdayjobs.com")


def test_jobspy_adapter_handles_nan_and_signature(cfg, profile):
    nan = float("nan")
    raw = row_to_raw({"site": "linkedin", "title": "FPGA Engineer", "company": "Acme", "location": nan,
                      "job_url": "https://www.linkedin.com/jobs/view/123456789", "job_url_direct": nan,
                      "date_posted": "2026-11-05", "is_remote": nan, "min_amount": nan, "description": nan,
                      "job_type": "fulltime", "interval": nan})
    assert raw.location == "" and raw.remote is None and raw.salary_min is None and raw.posted_at == "2026-11-05"

    captured = []

    class FakeDF:
        attrs = {"errors": {"glassdoor": "429 blocked"}}

        def to_dict(self, orient):
            return [{"site": "indeed", "title": "FPGA Dev", "company": "B", "job_url": "https://de.indeed.com/viewjob?jk=ab12"}]

    def scrape_jobs(site_name, search_term, location, results_wanted, hours_old, country_indeed,
                    description_format, verbose, distance=50, linkedin_fetch_description=False):
        captured.append(locals())
        return FakeDF()

    cfg.sources.jobspy.max_queries = 2
    ctx = SourceContext(config=cfg, profile=profile, client=None, log=lambda m: None)
    jobs = JobSpySource(scrape_fn=scrape_jobs).fetch(ctx)
    assert len(jobs) == 2 and jobs[0].source == "indeed"
    assert "linkedin_fetch_description" in captured[0] and "fetch_description" not in captured[0]
    assert captured[0]["location"] == "Germany"  # first query belongs to the nationwide FPGA track
    assert any("glassdoor" in w for w in ctx.warnings)


def test_arbeitsagentur_live_v6_shape():
    # Field names as returned by the live v6 API (values are made up).
    item = {"stellenangebotsart": "ARBEIT", "stellenangebotsTitel": "Entwicklungsingenieur Elektronik / Hardware (m/w/d)",
            "arbeitszeitVollzeit": True, "datumErsteVeroeffentlichung": "2026-10-25",
            "aenderungsdatum": "2026-10-27T12:49:30.474", "firma": "Beispiel AG", "hauptberuf": "Ingenieur/in - Elektronik",
            "referenznummer": "15939-BB-1-S", "entfernung": 64, "homeofficemoeglich": False,
            "stellenlokationen": [{"adresse": {"land": "DEUTSCHLAND", "ort": "Neuss", "plz": "41460",
                                               "region": "NORDRHEIN_WESTFALEN"}, "breite": 51.2, "laenge": 6.69}],
            "verguetungsangabe": "KEINE_ANGABEN", "vertragsdauer": "UNBEFRISTET"}
    j = arbeitsagentur.parse_list({"ergebnisliste": [item], "maxErgebnisse": 1}, 1)[0]
    assert j.posted_at == "2026-10-25" and j.employment_type == "fulltime" and j.location == "Neuss"
    assert j.extra["distance_km"] == 64 and j.extra["beruf"].startswith("Ingenieur")

    def handler(request):
        return httpx.Response(200, json={"stellenangebotsBeschreibung": "WOFÜR WIR SIE SUCHEN\n * Hardware",
                                         "istArbeitnehmerUeberlassung": True, "allianzpartnerUrl": "https://x.example/1",
                                         "verguetungsangabe": "KEINE_ANGABEN"})

    d = arbeitsagentur.fetch_detail(client_for(handler), "15939-BB-1-S")
    assert d["agency"] is True and d["apply_url"] == "https://x.example/1" and "Hardware" in d["description"]


def test_freehire_agency_and_stale_hints():
    raw = freehire.parse_item({"public_slug": "s", "url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/1-S?utm_source=freehire.me",
                               "title": "FPGA", "company": "persona service AG & Co.KG", "location": "", "cities": ["Geretsried"],
                               "enrichment": {"company_type": "outstaff"}, "reality": {"class": "fresh", "fake_freshness": True}})
    assert raw.extra["agency"] and raw.extra["stale"] and raw.location == "Geretsried"


def test_jobspy_glassdoor_location_and_linkedin_backoff(cfg, profile):
    calls, sleeps, logs = [], [], []

    class DF:
        def __init__(self, errors, rows=()):
            self.attrs = {"errors": errors}
            self.rows = list(rows)

        def to_dict(self, orient):
            return self.rows

    def scrape_jobs(site_name, search_term, location, results_wanted, hours_old, country_indeed,
                    description_format, verbose=1, distance=50, fetch_description=False):
        calls.append((tuple(site_name), location, verbose))
        if "linkedin" in site_name:
            return DF({"linkedin": "response status code 429 (blocked: use a proxy)"})
        return DF({}, [{"site": "indeed", "title": "FPGA", "company": "X", "job_url": f"https://de.indeed.com/viewjob?jk={len(calls)}"}])

    cfg.sources.jobspy.sites = ["linkedin", "indeed", "glassdoor"]
    cfg.sources.jobspy.max_queries = 4
    cfg.sources.jobspy.pause_seconds = 0
    ctx = SourceContext(config=cfg, profile=profile, client=None, log=logs.append)
    JobSpySource(scrape_fn=scrape_jobs, sleep=sleeps.append).fetch(ctx)
    gd = [c for c in calls if c[0] == ("glassdoor",)]
    assert gd and all("," not in c[1] for c in gd)  # bare place name for Glassdoor
    assert all(c[2] is None for c in calls)  # JobSpy's own logging left alone
    li = [c for c in calls if "linkedin" in c[0]]
    assert len(li) == 2  # dropped after two 429s
    assert sleeps == [60]
    assert any("LinkedIn" in m for m in logs)
