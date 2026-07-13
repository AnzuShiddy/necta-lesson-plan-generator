"""Loads structured TIE syllabus data from data/syllabus/*.json."""

import json
from functools import lru_cache
from pathlib import Path

SYLLABUS_DIR = Path(__file__).resolve().parent.parent / "data" / "syllabus"


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PDF_DIR = DATA_DIR / "pdfs"


def _slug(subject: str) -> str:
    return subject.lower().replace(" ", "_").replace("ya_", "").replace("'", "")


@lru_cache(maxsize=1)
def _load_all() -> dict:
    catalog: dict[str, dict] = {}
    for path in sorted(SYLLABUS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        catalog[data["subject"]] = data
    return catalog


@lru_cache(maxsize=1)
def _registry() -> list[str]:
    reg = DATA_DIR / "registry.json"
    if reg.exists():
        return json.loads(reg.read_text(encoding="utf-8")).get("subjects", [])
    return list(_load_all().keys())


def subject_status(subject: str) -> str:
    """'ready' = has structured data; 'pdf' = PDF downloaded, awaiting ingestion;
    'pending' = needs the official TIE PDF URL."""
    if subject in _load_all():
        return "ready"
    if (PDF_DIR / f"{_slug(subject)}.pdf").exists():
        return "pdf"
    return "pending"


def list_subjects() -> list[dict]:
    """All advertised subjects with their data status, ready ones first."""
    out = [{"name": s, "status": subject_status(s)} for s in _registry()]
    # include any data-backed subject not explicitly in the registry
    for s in _load_all():
        if s not in _registry():
            out.append({"name": s, "status": "ready"})
    order = {"ready": 0, "pdf": 1, "pending": 2}
    out.sort(key=lambda d: (order[d["status"]], d["name"]))
    return out


def list_forms(subject: str) -> list[str]:
    data = _load_all().get(subject)
    return list(data["forms"].keys()) if data else []


def list_activities(subject: str, form: str) -> list[dict]:
    data = _load_all().get(subject)
    if not data or form not in data["forms"]:
        return []
    return data["forms"][form]["activities"]


def get_activity(subject: str, form: str, activity_id: str) -> dict | None:
    for act in list_activities(subject, form):
        if act["id"] == activity_id:
            return act
    return None


def get_subject_meta(subject: str) -> dict:
    data = _load_all().get(subject, {})
    return {
        "syllabus_edition": data.get("syllabus_edition", ""),
        "source_pdf": data.get("source_pdf", ""),
        "period_length_minutes": data.get("period_length_minutes", 40),
        "periods_per_week": data.get("periods_per_week", {}),
    }
