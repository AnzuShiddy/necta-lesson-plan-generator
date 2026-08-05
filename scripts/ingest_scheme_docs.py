#!/usr/bin/env python3
"""Parse teacher-authored 2026 schemes of work into normalised rows.

Two source layouts are handled:

  * "new" (TIE competence-based, .pdf) -- Main competence | Specific competence |
    Main learning activities | Specific learning activities | Month | Week |
    No. of periods | Teaching and learning methods | ... resources |
    Assessment tools | Reference(s) | Remarks
  * "old" (topic-based, .docx) -- COMPETENCE | OBJECTIVES | MONTH | WEEK |
    MAIN-TOPIC | SUB-TOPIC | PERIOD | TEACHING ACTIVITIES | LEARNING ACTIVITIES |
    T/L RESOURCES | REFERENCE | ASSESSMENT | REMARKS

The PDFs are scanned-layout tables whose column *positions* shift from page to
page (pdfplumber reports 17-32 columns depending on the page) and whose Month /
Week / period headers are rendered rotated, so cells are classified by content
rather than by index.

Usage:
    python scripts/ingest_scheme_docs.py            # parse all known documents
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"
OUT = REF / "parsed"

MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
          "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]

# Documents to ingest: file -> (subject, form, layout)
DOCUMENTS = {
    "biology_form_one_scheme_2026.pdf": ("Biology", "Form One", "new"),
    "chemistry_form_two_scheme_2026.pdf": ("Chemistry", "Form Two", "new"),
    "biology_form_three_scheme_2026.docx": ("Biology", "Form Three", "old"),
    "chemistry_form_three_scheme_2026.docx": ("Chemistry", "Form Three", "old"),
}


def _clean(text: str) -> str:
    """Collapse whitespace; drop the soft hyphens PDF wrapping leaves behind."""
    text = (text or "").replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_heading(text: str) -> str:
    """Undo the two artefacts the .docx headings pick up.

    Topic cells are sometimes typeset letter-by-letter ("E X C R E T I O N"),
    which would otherwise read as a different topic from "EXCRETION". Headings
    also carry wrapping hyphens ("CLASSIFICATI-ON", "REPRODU- CTION"); those are
    rejoined, but only when the hyphen is followed by whitespace or by a short
    tail, so a genuine compound like "NON-METALS" survives.
    """
    text = _clean(text)
    if not text:
        return text
    # letter-spaced: every token is a single character, so rebuild the word
    tokens = text.split()
    if len(tokens) > 2 and all(len(t) == 1 for t in tokens):
        text = "".join(tokens)
    text = re.sub(r"([A-Za-z])-\s+([A-Za-z])", r"\1\2", text)
    text = re.sub(r"([A-Za-z])-([A-Za-z]{1,3})\b", r"\1\2", text)
    return _clean(text)


def _demangle_month(cell: str) -> str | None:
    """Rotated header cells arrive as 'YRAUNAJ' or 'H C R A M' or 'J A N U A R Y'."""
    squashed = re.sub(r"[^A-Z]", "", cell.upper())
    if not squashed:
        return None
    for m in MONTHS:
        if squashed in (m, m[::-1]):
            return m.title()
    # a month name embedded in a longer cell
    for m in MONTHS:
        if m in squashed or m[::-1] in squashed:
            return m.title()
    return None


_WEEK_RE = re.compile(r"^\s*\d{1,2}\s*(st|nd|rd|th)?\b")


def _is_week(cell: str) -> bool:
    """'2 - 4th', '1st & 2nd', '3rd', '4' -- but not a bare period count and not
    the leading '1.0' of a long competence string."""
    c = cell.strip()
    if len(c) > 20 or not _WEEK_RE.match(c):
        return False
    return bool(re.search(r"(st|nd|rd|th)|[-&,]|to\b", c, re.I))


# Header cells arrive fragmented across their own table rows ("Main", "and",
# "learning", "resources"); they carry no scheme content.
_HEADER_WORDS = {"main", "specific", "competence", "competencies", "activities",
                 "activity", "and", "learning", "teaching", "methods",
                 "resources", "assessment", "tools", "reference", "references",
                 "reference(s)", "remarks", "month", "week", "number", "periods",
                 "of", "no.", "no", "rema", "rks", "assess", "ment"}


def _is_header_fragment(cells: list[str]) -> bool:
    words = [c.lower().strip() for c in cells if c.strip()]
    if not words:
        return True
    return all(w in _HEADER_WORDS or len(w) <= 2 for w in words)


def _is_periods(cell: str) -> bool:
    c = cell.strip()
    return bool(re.fullmatch(r"\d{1,2}", c)) and int(c) <= 60


_CODE_RE = re.compile(r"^\d\.\d\b")
_MAIN_CODE_RE = re.compile(r"^\d\.0\b")
_SUBACT_RE = re.compile(r"^\([a-z]\)")


def _split_list(cell: str) -> list[str]:
    """Resource / method cells pack several items with no delimiter discipline."""
    parts = re.split(r"[,;/]|\s{2,}", cell)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 1]


def parse_new(rows: list[dict]) -> list[dict]:
    """Classify each cell of a competence-format row by its content."""
    out: list[dict] = []
    for row in rows:
        cells = [_clean(c) for c in row["cells"]]
        if not any(cells):
            continue
        # skip repeated per-page header rows and their wrapped fragments
        joined = " ".join(cells).lower()
        if "main competence" in joined and "specific competence" in joined:
            continue
        if _is_header_fragment(cells):
            continue

        rec: dict = {"page": row["page"], "month": "", "week": "", "periods": 0,
                     "main_competence": "", "specific_competence": "",
                     "main_learning_activity": "", "learning_activity": "",
                     "methods": [], "resources": [], "assessment": "",
                     "references": "", "remarks": ""}
        codes: list[str] = []
        subacts: list[str] = []
        prose: list[str] = []

        for c in cells:
            if not c:
                continue
            month = _demangle_month(c)
            if month and len(re.sub(r"[^A-Z]", "", c.upper())) <= 12:
                rec["month"] = month
                continue
            if not rec["week"] and _is_week(c):
                rec["week"] = c
                continue
            if not rec["periods"] and _is_periods(c):
                rec["periods"] = int(c)
                continue
            # Structural markers first: competence strings themselves read
            # "1.1 Demonstrate mastery ...", which would otherwise be captured
            # by the teaching-method keywords below.
            if _SUBACT_RE.match(c):
                subacts.append(c)
                continue
            if _CODE_RE.match(c):
                codes.append(c)
                continue
            if c.upper().startswith("TIE") or "TANZANIA INSTITUTE" in c.upper():
                if len(c) > len(rec["references"]):
                    rec["references"] = c
                continue
            if re.search(r"quiz|question|test|assignm|homewo|oral|portfolio", c, re.I) \
                    and len(c) < 160:
                if len(c) > len(rec["assessment"]):
                    rec["assessment"] = c
                continue
            if re.search(r"think-ink-pair|brainstorm|discussion|jigsaw|gallery walk|"
                         r"technological based|inquiry|demonstrat|project|"
                         r"experimentation|field trip", c, re.I) and len(c) < 200:
                rec["methods"] = _split_list(c)
                continue
            prose.append(c)

        # competence codes: x.0 is the main competence, x.y the specific one
        mains = [c for c in codes if _MAIN_CODE_RE.match(c)]
        specifics = [c for c in codes if not _MAIN_CODE_RE.match(c)]
        if mains:
            rec["main_competence"] = max(mains, key=len)
        if specifics:
            rec["specific_competence"] = max(specifics, key=len)
        elif len(mains) > 1:
            rec["specific_competence"] = sorted(mains, key=len)[-2]
        if subacts:
            rec["main_learning_activity"] = max(subacts, key=len)
        # Specific learning activities are written as instructions ("To explain
        # ...", "Students to discuss ..."); everything else left over is a
        # teaching/learning resource list.
        acts = [p for p in prose if re.match(r"^(to|students? to)\b", p, re.I)]
        rest = [p for p in prose if p not in acts]
        if acts:
            rec["learning_activity"] = max(acts, key=len)
        elif rest:
            # no instruction-shaped cell: fall back to the longest prose
            rest.sort(key=len, reverse=True)
            rec["learning_activity"] = rest.pop(0)
        for p in rest:
            rec["resources"].extend(_split_list(p))

        substantive = (rec["main_competence"] or rec["specific_competence"]
                       or rec["main_learning_activity"] or rec["learning_activity"])
        if substantive and (rec["month"] or rec["periods"]):
            out.append(rec)

    # Competence cells are vertically merged in the source table, so a run of
    # rows under one competence only states it on the first row. Carry the last
    # seen value forward.
    # A cell clipped to just its code ("1.0") carries no meaning either, so
    # treat it the same as an empty one.
    _fill_down(out, "main_competence", bare=r"\d\.\d\.?")
    _fill_down(out, "specific_competence", bare=r"\d\.\d\.?")
    _fill_down(out, "month")
    return out


def _is_banner(topic: str, sub_topic: str, learning: str) -> bool:
    """True for a full-width notice row ("MIDTERM BREAK ...", "TERMINAL
    EXAMINATIONS"), which repeats its text across every column.

    These interrupt a topic without ending it: the rows after a mid-term break
    continue the topic that was running before it. They must therefore be kept
    out of the main-topic fill-down, or they would be inherited by the real
    teaching rows that follow and wrongly discard them."""
    if not topic:
        return False
    key = topic[:15].upper()
    return sub_topic.upper().startswith(key) or learning.upper().startswith(key)


def _fill_down(rows: list[dict], field: str, bare: str | None = None,
               skip: str | None = None) -> None:
    """Carry the last meaningful value of a vertically merged column forward.

    Rows above the column's first stated value are filled from it instead --
    a merged cell whose text sits on its last line reads that way."""
    def meaningful(rec: dict) -> str:
        value = (rec.get(field) or "").strip()
        return "" if (bare and re.fullmatch(bare, value)) else value

    targets = [r for r in rows if not (skip and r.get(skip))]

    last = ""
    for rec in targets:
        value = meaningful(rec)
        if value:
            last = value
        elif last:
            rec[field] = last

    first = next((meaningful(r) for r in targets if meaningful(r)), "")
    for rec in targets:
        if not meaningful(rec) and first:
            rec[field] = first
        else:
            break


OLD_COLUMNS = ["competence", "objectives", "month", "week", "main_topic",
               "sub_topic", "periods", "teaching_activities",
               "learning_activities", "resources", "references",
               "assessment", "remarks"]


def parse_old(rows: list[list[str]]) -> list[dict]:
    """The .docx tables are a clean fixed 13-column grid."""
    out: list[dict] = []
    for cells in rows:
        cells = [_clean(c) for c in cells]
        if not any(cells):
            continue
        if cells[0].upper().startswith("COMPETENCE"):
            continue  # header
        rec = dict(zip(OLD_COLUMNS, cells))
        month = _demangle_month(rec.get("month", "")) or ""
        periods = rec.get("periods", "").strip()
        topic = _normalize_heading(rec.get("main_topic", ""))
        sub_topic = _normalize_heading(rec.get("sub_topic", ""))
        out.append({
            "banner": _is_banner(topic, sub_topic,
                                 _clean(rec.get("learning_activities", ""))),
            "month": month,
            "week": rec.get("week", ""),
            "periods": int(periods) if periods.isdigit() else 0,
            "main_topic": topic,
            "sub_topic": sub_topic,
            "competence": rec.get("competence", ""),
            "objectives": rec.get("objectives", ""),
            "teaching_activities": rec.get("teaching_activities", ""),
            "learning_activities": rec.get("learning_activities", ""),
            "resources": _split_list(rec.get("resources", "")),
            "assessment": rec.get("assessment", ""),
            "references": rec.get("references", ""),
            "remarks": rec.get("remarks", ""),
        })
    # Month and main topic are merged across the rows they span; notice rows
    # sit outside that structure.
    _fill_down(out, "month")
    _fill_down(out, "main_topic", skip="banner")
    return out


def read_docx(path: Path) -> list[list[str]]:
    from docx import Document
    doc = Document(str(path))
    rows: list[list[str]] = []
    for table in doc.tables:
        for row in table.rows:
            rows.append([c.text for c in row.cells])
    return rows


def read_pdf(path: Path) -> list[dict]:
    import pdfplumber
    rows: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            for table in page.extract_tables():
                for row in table:
                    cells = [(c or "") for c in row]
                    if any(c.strip() for c in cells):
                        rows.append({"page": i + 1, "cells": cells})
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (subject, form, layout) in DOCUMENTS.items():
        path = REF / name
        if not path.exists():
            print(f"  SKIP {name} (not found)")
            continue
        if layout == "new":
            rows = parse_new(read_pdf(path))
        else:
            rows = parse_old(read_docx(path))
        doc = {"subject": subject, "form": form, "layout": layout,
               "source_document": name, "row_count": len(rows), "rows": rows}
        dest = OUT / (path.stem + ".json")
        dest.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {dest.name}: {len(rows)} rows ({subject} {form}, {layout} layout)")


if __name__ == "__main__":
    main()
