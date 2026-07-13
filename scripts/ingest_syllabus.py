#!/usr/bin/env python3
"""Turn an official TIE syllabus PDF into the app's structured JSON, grounded
in the real document.

Pipeline per subject:
  1. Extract the PDF text with pypdf (the ground truth).
  2. For each Form (I-IV), send the relevant text to Claude with a strict
     structured-output schema and ask it to TRANSCRIBE — not invent — every
     learning activity row of the detailed-contents matrix.
  3. Write data/syllabus/<subject>.json in the shape app/syllabus.py expects.

Because the model only ever sees the real syllabus text and is told to copy
verbatim, the result is a faithful transcription, not generated content.

Usage:
    python scripts/ingest_syllabus.py Chemistry
    python scripts/ingest_syllabus.py --all
Requires GEMINI_API_KEY (free key at https://aistudio.google.com/apikey).
"""

import argparse
import json
import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import llm  # noqa: E402  (shared provider wrapper)

PDF_DIR = ROOT / "data" / "pdfs"
OUT_DIR = ROOT / "data" / "syllabus"
SOURCES = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))

FORMS = ["Form One", "Form Two", "Form Three", "Form Four"]


def slug(subject: str) -> str:
    return subject.lower().replace(" ", "_").replace("ya_", "").replace("'", "")


# --- structured-output schema the model must fill (one Form at a time) --------

class Activity(BaseModel):
    main_competence: str = Field(description="Main competence, copied verbatim from the syllabus")
    specific_competence: str = Field(description="Specific competence, copied verbatim")
    learning_activity: str = Field(description="The learning activity text, copied verbatim")
    suggested_methods: list[str] = Field(description="Suggested teaching and learning methods, copied verbatim")
    assessment_criteria: str = Field(description="Assessment criteria, copied verbatim")
    suggested_resources: list[str] = Field(description="Suggested resources, copied verbatim")
    periods_for_specific_competence: int = Field(default=0, description="Number of periods if stated, else 0")


class FormContents(BaseModel):
    activities: list[Activity]


SYSTEM = """You transcribe official Tanzania Institute of Education (TIE) syllabus \
content into structured data. You are given the raw extracted text of ONE form's \
detailed-contents matrix (columns: main competence, specific competence, learning \
activities, suggested teaching and learning methods, assessment criteria, suggested \
resources, number of periods).

Your ONLY job is faithful transcription. Copy every field VERBATIM from the supplied \
text. Do NOT invent, summarise, rephrase, translate, or add activities that are not in \
the text. Produce one entry per learning activity row. If a value is missing in the \
text, use an empty string or empty list. Never fabricate syllabus content."""


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def split_by_form(full_text: str) -> dict[str, str]:
    """Slice the syllabus text into the four Form sections.

    The real section headings are 'Detailed Contents for Form <ROMAN>' followed
    by the matrix header ('Main competences ...'); the first four occurrences of
    the same phrase are table-of-contents entries (followed by dot leaders). We
    take the LAST occurrence of each form's heading, which is always the real
    section start. Falls back to the last bare 'Form <ROMAN>' heading if the
    'Detailed Contents' phrasing is absent (some subjects word it differently)."""
    # Each form can be headed in English (roman or spelled-out) or Swahili.
    # `rn` is a regex alternation of every way a form's numeral is written in
    # the PDFs, including OCR/typo variants: Form IV is sometimes "1V" (digit-1
    # + V), Form III sometimes "1II", etc.
    aliases = {
        "Form One":   {"rn": "I",            "word": "One",   "sw": "I"},
        "Form Two":   {"rn": "II",           "word": "Two",   "sw": "II"},
        "Form Three": {"rn": "(?:III|1II)",  "word": "Three", "sw": "III"},
        "Form Four":  {"rn": "(?:IV|1V)",    "word": "Four",  "sw": "IV"},
    }
    idx: dict[str, int] = {}
    for name, a in aliases.items():
        pats = [
            # "Detailed Content(s)" — the 's' and inner spacing vary by PDF.
            rf"Detailed\s+Contents?\s+for\s+Form\s*{a['rn']}\b",
            rf"Detailed\s+Contents?\s+for\s+Form\s*{a['word']}\b",
            # Swahili-medium syllabi: "Maudhui ya Kidato cha I" (Contents of
            # Form I) is the section heading — specific enough to avoid the
            # "Kidato cha I – IV" running footer that plain "Kidato cha I" hits.
            rf"Maudhui ya Kidato cha\s*{a['sw']}\b",
            rf"Kidato cha\s*{a['sw']}\b",
            # Bare heading before the matrix, tolerating a page number in between
            # e.g. "Form III\n38\nMain competences".
            rf"\bForm\s*{a['rn']}\s*\n?\s*\d*\s*Main\b",
        ]
        pos = -1
        for pat in pats:
            hits = list(re.finditer(pat, full_text, re.IGNORECASE))
            if hits:
                pos = hits[-1].start()
                break
        idx[name] = pos
    ordered = sorted((n for n in FORMS if idx[n] >= 0), key=lambda n: idx[n])
    out: dict[str, str] = {}
    for i, name in enumerate(ordered):
        start = idx[name]
        end = idx[ordered[i + 1]] if i + 1 < len(ordered) else len(full_text)
        out[name] = full_text[start:end]
    return out


def ingest(subject: str) -> None:
    pdf = PDF_DIR / f"{slug(subject)}.pdf"
    if not pdf.exists():
        print(f"  ! no PDF for {subject} at {pdf}", file=sys.stderr)
        return
    print(f"→ {subject}: extracting text …")
    full = extract_text(pdf)
    sections = split_by_form(full)
    if not sections:
        print(f"  ! could not locate Form sections in {subject}", file=sys.stderr)
        return

    forms_out: dict[str, dict] = {}
    counter = 0
    for form, text in sections.items():
        text = text[:60000]  # keep the request bounded
        print(f"  · {form}: {len(text)} chars → {llm.MODEL}")
        parsed = llm.structured(
            system=SYSTEM,
            user=f"Subject: {subject}\nForm: {form}\n\nDetailed contents text:\n{text}",
            schema=FormContents,
        )
        if parsed is None:
            print("    ! model returned no activities", file=sys.stderr)
            continue
        acts = []
        for a in parsed.activities:
            counter += 1
            d = a.model_dump()
            d["id"] = f"{slug(subject)[:4]}-{form.split()[1].lower()}-{counter}"
            acts.append(d)
        forms_out[form] = {"activities": acts}

    doc = {
        "subject": subject,
        "level": "Ordinary Secondary Education (Form I-IV)",
        "syllabus_edition": "2023 (Tanzania Institute of Education)",
        "source_pdf": SOURCES["subjects"].get(subject, ""),
        "period_length_minutes": 40,
        "forms": forms_out,
    }
    out = OUT_DIR / f"{slug(subject)}.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ wrote {out} ({counter} activities)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("subject", nargs="?", help="Subject name (e.g. Chemistry)")
    ap.add_argument("--all", action="store_true", help="Ingest every downloaded PDF")
    ap.add_argument("--force", action="store_true",
                    help="Re-ingest even subjects that already have a JSON file")
    args = ap.parse_args()

    if not llm.has_credentials():
        sys.exit(
            "No Gemini credentials found. Ingestion calls the Gemini API.\n"
            "Get a free key at https://aistudio.google.com/apikey, then:\n"
            "  export GEMINI_API_KEY=...\n"
            "and re-run:  python scripts/ingest_syllabus.py --all"
        )

    if args.all:
        done, skipped, failed = [], [], []
        for subj in SOURCES["subjects"]:
            if not (PDF_DIR / f"{slug(subj)}.pdf").exists():
                continue
            if not args.force and (OUT_DIR / f"{slug(subj)}.json").exists():
                print(f"= {subj}: already ingested (use --force to redo)")
                skipped.append(subj)
                continue
            try:
                ingest(subj)
                done.append(subj)
            except llm.QuotaExceeded as e:
                print(f"  ! {subj}: daily quota hit — stopping. Re-run later to "
                      f"resume the rest.\n    {str(e)[:120]}", file=sys.stderr)
                failed.append(subj)
                break  # further calls will also 429 today
            except Exception as e:  # keep the batch going
                print(f"  ! {subj}: failed ({type(e).__name__}: {str(e)[:120]})",
                      file=sys.stderr)
                failed.append(subj)
        print(f"\nDone: {len(done)}  Skipped: {len(skipped)}  Failed: {len(failed)}")
        if done:
            print("  ingested:", ", ".join(done))
        if failed:
            print("  failed:  ", ", ".join(failed))
    elif args.subject:
        ingest(args.subject)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
