"""Shared data shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STATUSES = [
    "new", "shortlisted", "tailored", "approved", "applied", "interview",
    "offer", "rejected", "skipped", "closed", "filtered",
]
ACTIVE_STATUSES = ["new", "shortlisted", "tailored", "approved", "applied", "interview"]
PIPELINE_COLUMNS = ["shortlisted", "tailored", "approved", "applied", "interview", "offer"]

STATUS_LABELS_TR = {
    "new": "Yeni",
    "shortlisted": "Kısa liste",
    "tailored": "Belgeler hazır",
    "approved": "Onaylandı",
    "applied": "Başvuruldu",
    "interview": "Mülakat",
    "offer": "Teklif",
    "rejected": "Ret",
    "skipped": "Geçildi",
    "closed": "Kapandı",
    "filtered": "Elendi",
}


@dataclass
class RawJob:
    """A posting exactly as one source delivered it (before processing)."""

    source: str
    title: str
    company: str = ""
    location: str = ""
    url: str = ""
    apply_url: str = ""
    external_id: str = ""
    description: str = ""
    description_html: bool = False
    posted_at: str | None = None
    employment_type: str = ""
    remote: bool | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    salary_period: str = ""
    needs_location_check: bool = False
    detail_ref: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
