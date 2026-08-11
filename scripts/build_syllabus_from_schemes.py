#!/usr/bin/env python3
"""Replace a form's activities in data/syllabus/<subject>.json with the rows
parsed out of a real teacher-authored 2026 scheme of work.

Run scripts/ingest_scheme_docs.py first; this reads data/reference/parsed/*.json.

Unlike the rest of data/syllabus (transcribed from the official TIE syllabus
PDFs), these forms are sourced from schemes actually used in class, so they
carry topic-level detail and the teacher's real month/week pacing. Activities
therefore gain three extra fields, all optional and ignored by any form that
lacks them:

    periods           - periods for THIS activity (not shared across a competence)
    scheduled_month   - month the teacher placed it in
    scheduled_weeks   - week-of-month ordinals, e.g. [1, 2] for "1st & 2nd"

Usage:
    python scripts/build_syllabus_from_schemes.py [--dry-run]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARSED = ROOT / "data" / "reference" / "parsed"
SYLLABUS = ROOT / "data" / "syllabus"

# Which parsed document replaces which form, and the id prefix to number under.
TARGETS = {
    "biology_form_one_scheme_2026.json": ("biology", "Form One", "biol-one"),
    "biology_form_three_scheme_2026.json": ("biology", "Form Three", "biol-three"),
    "chemistry_form_two_scheme_2026.json": ("chemistry", "Form Two", "chem-two"),
    "chemistry_form_three_scheme_2026.json": ("chemistry", "Form Three", "chem-three"),
}

# Teaching methods named in the old topic-format documents, which write them as
# prose ("To guide students to discuss ...") rather than as a tagged list.
_METHOD_PATTERNS = [
    (r"discuss", "Group discussion"),
    (r"experiment|practical", "Experimentation"),
    (r"brainstorm", "Brainstorming"),
    (r"demonstrat", "Demonstration"),
    (r"field ?trip|visit", "Field trip"),
    (r"question and answer|q ?& ?a", "Question and answer"),
    (r"think-ink-pair", "Think-ink-pair-share"),
    (r"project", "Project work"),
    (r"inquiry", "Inquiry-based learning"),
    (r"gallery walk", "Gallery walk"),
    (r"jigsaw", "Jigsaw"),
    (r"simulat|video|animation|technological", "Technological-based learning"),
    (r"observ", "Observation"),
]


def _methods_from_prose(*texts: str) -> list[str]:
    blob = " ".join(t for t in texts if t).lower()
    found = [label for pattern, label in _METHOD_PATTERNS if re.search(pattern, blob)]
    return found or (["Group discussion"] if blob.strip() else [])


def _week_ordinals(label: str) -> list[int]:
    """'1st & 2nd' -> [1, 2];  '2 - 4th' -> [2, 3, 4];  '3' -> [3]."""
    nums = [int(n) for n in re.findall(r"\d{1,2}", label or "") if 1 <= int(n) <= 6]
    if not nums:
        return []
    if re.search(r"[-–]|to\b", label or "") and len(nums) >= 2:
        return list(range(min(nums), max(nums) + 1))
    return sorted(set(nums))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


# Teacher schemes interleave calendar rows among the teaching rows. Breaks and
# holidays are already modelled by app/calendars.py, so they are dropped;
# tests, exams and revision are real scheduled work and are kept, tagged so the
# app can tell them apart from topic teaching.
_CALENDAR_ROW = re.compile(r"\b(break|leave|holiday)", re.I)
_ASSESSMENT_ROW = re.compile(r"\b(test|exam|exams|examination|revision)", re.I)


def _row_kind(title: str) -> str:
    """'calendar' (drop), 'assessment' (keep, tagged) or 'topic'."""
    if _CALENDAR_ROW.search(title):
        return "calendar"
    if _ASSESSMENT_ROW.search(title):
        return "assessment"
    return "topic"


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        item = _clean(item)
        if item and item.lower() not in {s.lower() for s in seen}:
            seen.append(item)
    return seen


def convert_new(rows: list[dict], prefix: str) -> list[dict]:
    """Competence-format rows already speak the syllabus schema."""
    out = []
    for i, r in enumerate(rows, 1):
        out.append({
            "main_competence": _clean(r["main_competence"]),
            "specific_competence": _clean(r["specific_competence"]),
            "main_learning_activity": _clean(r.get("main_learning_activity", "")),
            "learning_activity": _clean(r["learning_activity"]),
            "suggested_methods": _dedupe(r.get("methods") or []),
            "assessment_criteria": _clean(r.get("assessment", "")),
            "suggested_resources": _dedupe(r.get("resources") or []),
            "periods_for_specific_competence": r.get("periods", 0),
            "periods": r.get("periods", 0),
            "scheduled_month": r.get("month", ""),
            "scheduled_weeks": _week_ordinals(r.get("week", "")),
            "id": f"{prefix}-{i}",
        })
    return out


def convert_old(rows: list[dict], prefix: str) -> list[dict]:
    """Topic-format rows: MAIN-TOPIC/SUB-TOPIC stand in for the competences,
    and the teaching/learning activity columns supply the methods."""
    out = []
    for i, r in enumerate(rows, 1):
        teaching = _clean(r.get("teaching_activities", ""))
        learning = _clean(r.get("learning_activities", ""))
        topic = _clean(r.get("main_topic", ""))
        if not (topic or r.get("sub_topic") or learning):
            continue  # spacer row in the source table
        # Only full-width notice rows are calendar/assessment events; a normal
        # teaching row keeps its topic even if the title mentions e.g. "test".
        kind = _row_kind(topic) if r.get("banner") else "topic"
        if kind == "calendar":
            continue
        out.append({
            "main_competence": topic,
            "specific_competence": _clean(r.get("sub_topic", "")),
            "kind": kind,
            "main_learning_activity": teaching,
            "learning_activity": learning or teaching,
            "suggested_methods": _methods_from_prose(teaching, learning),
            "assessment_criteria": _clean(r.get("assessment", "")),
            "suggested_resources": _dedupe(r.get("resources") or []),
            "periods_for_specific_competence": r.get("periods", 0),
            "periods": r.get("periods", 0),
            "scheduled_month": r.get("month", ""),
            "scheduled_weeks": _week_ordinals(r.get("week", "")),
            "id": f"{prefix}-{i}",
        })
    # ids must stay contiguous after dropping spacer rows
    for n, act in enumerate(out, 1):
        act["id"] = f"{prefix}-{n}"
    return out


def main() -> None:
    dry = "--dry-run" in sys.argv
    by_subject: dict[str, dict] = {}

    for name, (slug, form, prefix) in TARGETS.items():
        parsed_path = PARSED / name
        if not parsed_path.exists():
            print(f"  SKIP {name} (run ingest_scheme_docs.py first)")
            continue
        doc = json.loads(parsed_path.read_text(encoding="utf-8"))

        syl_path = SYLLABUS / f"{slug}.json"
        data = by_subject.setdefault(slug, json.loads(syl_path.read_text(encoding="utf-8")))

        convert = convert_new if doc["layout"] == "new" else convert_old
        activities = convert(doc["rows"], prefix)

        before = len(data["forms"].get(form, {}).get("activities", []))
        data["forms"][form] = {
            "activities": activities,
            "source": {
                "document": doc["source_document"],
                "layout": doc["layout"],
                "note": ("Replaces the TIE-syllabus transcription for this form; "
                         "sourced from a teacher-authored 2026 scheme of work."),
            },
        }
        print(f"  {slug} {form}: {before} -> {len(activities)} activities, "
              f"{sum(a['periods'] for a in activities)} periods "
              f"({doc['layout']} layout)")

    if dry:
        print("\n(dry run - nothing written)")
        return
    for slug, data in by_subject.items():
        path = SYLLABUS / f"{slug}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
