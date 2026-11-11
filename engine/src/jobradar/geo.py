"""Countries a search can target: ISO code -> the English name the job boards (JobSpy/Indeed) expect."""

from __future__ import annotations

COUNTRIES: list[tuple[str, str]] = [
    ("AR", "Argentina"), ("AU", "Australia"), ("AT", "Austria"), ("BH", "Bahrain"), ("BD", "Bangladesh"),
    ("BE", "Belgium"), ("BR", "Brazil"), ("BG", "Bulgaria"), ("CA", "Canada"), ("CL", "Chile"), ("CN", "China"),
    ("CO", "Colombia"), ("CR", "Costa Rica"), ("HR", "Croatia"), ("CY", "Cyprus"), ("CZ", "Czech Republic"),
    ("DK", "Denmark"), ("EC", "Ecuador"), ("EG", "Egypt"), ("EE", "Estonia"), ("FI", "Finland"), ("FR", "France"),
    ("DE", "Germany"), ("GR", "Greece"), ("HK", "Hong Kong"), ("HU", "Hungary"), ("IN", "India"),
    ("ID", "Indonesia"), ("IE", "Ireland"), ("IL", "Israel"), ("IT", "Italy"), ("JP", "Japan"), ("KW", "Kuwait"),
    ("LV", "Latvia"), ("LT", "Lithuania"), ("LU", "Luxembourg"), ("MY", "Malaysia"), ("MT", "Malta"),
    ("MX", "Mexico"), ("MA", "Morocco"), ("NL", "Netherlands"), ("NZ", "New Zealand"), ("NG", "Nigeria"),
    ("NO", "Norway"), ("OM", "Oman"), ("PK", "Pakistan"), ("PA", "Panama"), ("PE", "Peru"), ("PH", "Philippines"),
    ("PL", "Poland"), ("PT", "Portugal"), ("QA", "Qatar"), ("RO", "Romania"), ("SA", "Saudi Arabia"),
    ("SG", "Singapore"), ("SK", "Slovakia"), ("SI", "Slovenia"), ("ZA", "South Africa"), ("KR", "South Korea"),
    ("ES", "Spain"), ("SE", "Sweden"), ("CH", "Switzerland"), ("TW", "Taiwan"), ("TH", "Thailand"),
    ("TR", "Turkey"), ("UA", "Ukraine"), ("AE", "United Arab Emirates"), ("GB", "UK"), ("US", "USA"),
    ("UY", "Uruguay"), ("VE", "Venezuela"), ("VN", "Vietnam"),
]
_BY_CODE = dict(COUNTRIES)
_ALIASES = {"deutschland": "DE", "almanya": "DE", "türkiye": "TR", "turkiye": "TR", "united kingdom": "GB",
            "great britain": "GB", "england": "GB", "united states": "US", "us": "US", "america": "US",
            "österreich": "AT", "schweiz": "CH", "czechia": "CZ", "holland": "NL", "nederland": "NL"}
_BY_NAME = {name.lower(): code for code, name in COUNTRIES}


def country_name(code: str) -> str:
    """'DE' -> 'Germany'; unknown codes come back unchanged."""
    return _BY_CODE.get((code or "").strip().upper(), (code or "").strip())


def country_code(name: str) -> str:
    """'Germany', 'Deutschland' or 'de' -> 'DE'; '' when unknown."""
    key = (name or "").strip().lower()
    if key.upper() in _BY_CODE:
        return key.upper()
    return _BY_NAME.get(key) or _ALIASES.get(key, "")


def is_germany(country: str) -> bool:
    return country_code(country) == "DE"
