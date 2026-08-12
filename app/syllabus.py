"""Loads structured TIE syllabus data from data/syllabus/*.json.

One file per subject *per level*: `chemistry.json` is the Form I-IV syllabus and
`chemistry_advanced.json` the Form V-VI one. They are different documents with
different editions and period lengths, so they stay separate — but the form name
already implies the level, so callers keep passing a form and never a level.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from .calendars import (ADVANCED, LEVEL_LABELS, LEVEL_ORDER, NURSERY, ORDINARY,
                        PRIMARY, level_of)

SYLLABUS_DIR = Path(__file__).resolve().parent.parent / "data" / "syllabus"


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PDF_DIR = DATA_DIR / "pdfs"

# A subject taught at several levels (English, Kiswahili, Mathematics ...) has a
# separate TIE document per level. Every level but ordinary suffixes its files so
# the documents never collide; ordinary keeps the bare slug it was first written
# with.
LEVEL_SUFFIX = {ORDINARY: "", ADVANCED: "_advanced",
                PRIMARY: "_primary", NURSERY: "_nursery"}


def _slug(subject: str, level: str = ORDINARY) -> str:
    slug = re.sub(r"\bya\b", " ", subject.lower())
    slug = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", slug)).strip("_")
    return slug + LEVEL_SUFFIX.get(level, "")


@lru_cache(maxsize=1)
def _load_all() -> dict[tuple[str, str], dict]:
    """Every syllabus document, keyed by (subject, level)."""
    catalog: dict[tuple[str, str], dict] = {}
    for path in sorted(SYLLABUS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        forms = list(data.get("forms", {}))
        level = level_of(forms[0]) if forms else ORDINARY
        catalog[(data["subject"], level)] = data
    return catalog


def _document(subject: str, form: str) -> dict | None:
    return _load_all().get((subject, level_of(form)))


@lru_cache(maxsize=1)
def _registry() -> dict[str, list[str]]:
    """Advertised subjects per level, from data/registry.json."""
    reg = DATA_DIR / "registry.json"
    levels: dict[str, list[str]] = {key: [] for key in LEVEL_ORDER}
    if reg.exists():
        data = json.loads(reg.read_text(encoding="utf-8"))
        for key in LEVEL_ORDER:
            levels[key] = list(data.get("levels", {}).get(key, {}).get("subjects", []))
    for subject, level in _load_all():
        if subject not in levels.setdefault(level, []):
            levels[level].append(subject)
    return levels


def list_levels() -> list[dict]:
    return [{"key": key, "label": LEVEL_LABELS[key]} for key in LEVEL_ORDER]


def subject_status(subject: str, level: str = ORDINARY) -> str:
    """'ready' = has structured data; 'pdf' = PDF downloaded, awaiting ingestion;
    'pending' = needs the official TIE PDF URL."""
    if (subject, level) in _load_all():
        return "ready"
    if (PDF_DIR / f"{_slug(subject, level)}.pdf").exists():
        return "pdf"
    return "pending"


def list_subjects(level: str = ORDINARY) -> list[dict]:
    """All advertised subjects for one level with their data status, ready
    ones first."""
    out = [{"name": s, "status": subject_status(s, level)}
           for s in _registry().get(level, [])]
    order = {"ready": 0, "pdf": 1, "pending": 2}
    out.sort(key=lambda d: (order[d["status"]], d["name"]))
    return out


def list_forms(subject: str, level: str = ORDINARY) -> list[str]:
    data = _load_all().get((subject, level))
    return list(data["forms"].keys()) if data else []


def list_activities(subject: str, form: str) -> list[dict]:
    data = _document(subject, form)
    if not data or form not in data["forms"]:
        return []
    return data["forms"][form]["activities"]


def get_activity(subject: str, form: str, activity_id: str) -> dict | None:
    for act in list_activities(subject, form):
        if act["id"] == activity_id:
            return act
    return None


def get_form_source(subject: str, form: str) -> dict:
    """Provenance for one form, when it does not come from the TIE syllabus
    transcription. Forms rebuilt from a teacher-authored scheme of work record
    {document, layout, note}; every other form returns {}."""
    data = _document(subject, form) or {}
    return (data.get("forms", {}).get(form, {}) or {}).get("source", {})


def get_subject_meta(subject: str, form: str) -> dict:
    data = _document(subject, form) or {}
    return {
        "syllabus_edition": data.get("syllabus_edition", ""),
        "source_pdf": data.get("source_pdf", ""),
        "period_length_minutes": data.get("period_length_minutes", 40),
        "periods_per_week": data.get("periods_per_week", {}),
    }
