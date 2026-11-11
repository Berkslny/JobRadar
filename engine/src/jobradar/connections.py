"""LinkedIn Connections.csv: 'do I know someone at this company?'
(career-ops linkedin-join idea). Pure local matching, no network."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from jobradar.processing.normalize import normalize_company


def parse_connections_csv(content: str) -> list[dict[str, str]]:
    lines = content.splitlines()
    start = 0
    for i, line in enumerate(lines[:50]):
        low = line.lower()
        if "first name" in low and "company" in low:
            start = i
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    out = []
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        company = row.get("company", "")
        if not company:
            continue
        out.append({
            "first_name": row.get("first name", ""),
            "last_name": row.get("last name", ""),
            "company": company,
            "company_norm": normalize_company(company),
            "position": row.get("position", ""),
            "url": row.get("url", ""),
            "connected_on": row.get("connected on", ""),
        })
    return out


def load_connections_file(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return parse_connections_csv(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return []
