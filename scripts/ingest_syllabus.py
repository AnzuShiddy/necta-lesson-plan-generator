#!/usr/bin/env python3
"""Turn an official TIE syllabus PDF into the app's structured JSON, grounded
in the real document.

Pipeline per subject:
  1. Extract the PDF text with pypdf (the ground truth).
  2. For each Form of the chosen level (I-IV, or V-VI with --level advanced),
     send the relevant text to Claude with a strict
     structured-output schema and ask it to TRANSCRIBE — not invent — every
     learning activity row of the detailed-contents matrix.
  3. Write data/syllabus/<subject>.json in the shape app/syllabus.py expects.

Because the model only ever sees the real syllabus text and is told to copy
verbatim, the result is a faithful transcription, not generated content.

Usage:
    python scripts/ingest_syllabus.py Chemistry
    python scripts/ingest_syllabus.py --all
    python scripts/ingest_syllabus.py Biology --level advanced   # Form V-VI
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

# Each level's forms, and how that level's syllabus PDFs head a form section.
# `rn` is a regex alternation of every way a form's numeral is written in the
# PDFs, including OCR/typo variants: Form IV is sometimes "1V" (digit-1 + V),
# Form III sometimes "1II", Form VI sometimes "V1".
LEVELS = {
    "ordinary": {
        "forms": ["Form One", "Form Two", "Form Three", "Form Four"],
        "label": "Ordinary Secondary Education (Form I-IV)",
        "aliases": {
            "Form One":   {"rn": "I",           "word": "One",   "sw": "I"},
            "Form Two":   {"rn": "II",          "word": "Two",   "sw": "II"},
            "Form Three": {"rn": "(?:III|1II)", "word": "Three", "sw": "III"},
            "Form Four":  {"rn": "(?:IV|1V)",   "word": "Four",  "sw": "IV"},
        },
    },
    "advanced": {
        "forms": ["Form Five", "Form Six"],
        "label": "Advanced Secondary Education (Form V-VI)",
        "anchor_running_head": True,
        # `fr`: the French-medium syllabus (Français langue étrangère) heads its
        # sections "Ve Année" / "VIe Année" over "Tableau N: Les Contenus ...".
        "aliases": {
            "Form Five": {"rn": "V",          "word": "Five", "sw": "V",  "fr": "Ve"},
            "Form Six":  {"rn": "(?:VI|V1)",  "word": "Six",  "sw": "VI", "fr": "VIe"},
        },
    },
}


def slug(subject: str, level: str = "ordinary") -> str:
    s = subject.lower().replace(" ", "_").replace("ya_", "").replace("'", "")
    return s + "_advanced" if level == "advanced" else s


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


# A contents-page line runs "... for Form VI ....... 46" — dot leaders, then a
# page number. Real section headings are followed by the matrix instead.
_CONTENTS_LEADER = re.compile(r"^[\s.]{0,6}\.{4,}")


def _is_contents_entry(text: str, end: int) -> bool:
    return bool(_CONTENTS_LEADER.match(text[end:end + 40]))


def split_by_form(full_text: str, level: str = "ordinary") -> dict[str, str]:
    """Slice the syllabus text into its Form sections.

    The real section headings are 'Detailed Contents for Form <ROMAN>' followed
    by the matrix header ('Main competences ...'); the same phrase also appears
    on the contents page, where it is followed by dot leaders. Those are dropped
    (`_is_contents_entry`) so a form whose real heading is worded differently
    falls through to the next pattern instead of anchoring on its contents-page
    line — the Form V-VI Computer Science syllabus lists 'Detailed content for
    Form VI' on the contents page but heads the section itself 'Detailed
    contents for Form Six'. Of what survives we take the LAST occurrence, and
    fall back to a bare 'Form <ROMAN>' heading for subjects that word it
    differently again."""
    # Each form can be headed in English (roman or spelled-out) or Swahili.
    aliases = LEVELS[level]["aliases"]
    forms = LEVELS[level]["forms"]
    idx: dict[str, int] = {}
    for name, a in aliases.items():
        pats = []
        if LEVELS[level].get("anchor_running_head"):
            # The running head ("Form VI" alone on a line) directly above the
            # matrix caption ("Table 4: Detailed Contents for ..."). Tried first
            # because it survives a mislabelled caption: TIE captioned the Form
            # VI table of the A-level Literature in English syllabus "Detailed
            # Contents for Form V", so the caption alone points both forms at
            # the same table. The caption lookahead keeps this off the identical
            # running head that repeats on every later page of the section.
            #
            # Only the advanced level uses it. It shifts an ordinary-level
            # section start by a few characters (onto the heading line rather
            # than the caption), and those four-form splits are already
            # validated against all 14 ingested subjects — no reason to perturb
            # them for a fault none of them has.
            pats.append(rf"(?m)^[ \t]*Form\s*{a['rn']}[ \t]*$"
                        rf"(?=\n[^\n]{{0,90}}(?:Table\s*\d|Detailed\s+Contents?))")
        if a.get("fr"):
            pats += [
                rf"(?m)^[ \t]*{a['fr']}\s*Ann[ée]e[ \t]*$"
                rf"(?=\n[^\n]{{0,90}}(?:Tableau\s*\d|Les\s+Contenus))",
                rf"Les\s+Contenus[^\n]{{0,80}}pour\s+la\s+{a['fr']}\s*Ann[ée]e",
            ]
        pats += [
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
            hits = [h for h in re.finditer(pat, full_text, re.IGNORECASE)
                    if not _is_contents_entry(full_text, h.end())]
            if hits:
                pos = hits[-1].start()
                break
        idx[name] = pos
    ordered = sorted((n for n in forms if idx[n] >= 0), key=lambda n: idx[n])
    out: dict[str, str] = {}
    for i, name in enumerate(ordered):
        start = idx[name]
        end = idx[ordered[i + 1]] if i + 1 < len(ordered) else len(full_text)
        out[name] = full_text[start:end]
    return out


def carry_merged_competences(activities: list[dict]) -> int:
    """Fill competence cells the syllabus merges across several activity rows.

    In the TIE matrix a main competence cell spans every specific competence and
    activity row beneath it, so only the first of those rows repeats the text. A
    row that reaches us without one belongs to the last stated competence — this
    copies it down rather than leaving the lesson plan's Main Competence blank.

    Only fills what is genuinely inherited: a row before any stated competence
    has nothing above it to inherit and is left empty rather than guessed at.
    Returns the number of cells filled."""
    filled = 0
    last: dict[str, str] = {}
    for a in activities:
        for field in ("main_competence", "specific_competence"):
            if a.get(field):
                last[field] = a[field]
            elif last.get(field):
                a[field] = last[field]
                filled += 1
    return filled


def ingest(subject: str, level: str = "ordinary") -> None:
    pdf = PDF_DIR / f"{slug(subject, level)}.pdf"
    if not pdf.exists():
        print(f"  ! no PDF for {subject} at {pdf}", file=sys.stderr)
        return
    print(f"→ {subject} ({level}): extracting text …")
    full = extract_text(pdf)
    sections = split_by_form(full, level)
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
        carried = carry_merged_competences(acts)
        if carried:
            print(f"    · carried {carried} merged competence cell(s) down")
        blank = sum(1 for a in acts if not a.get("main_competence"))
        if blank:
            print(f"    ! {blank}/{len(acts)} rows still have no main competence — "
                  f"the PDF text extraction dropped those cells", file=sys.stderr)
        forms_out[form] = {"activities": acts}

    out = OUT_DIR / f"{slug(subject, level)}.json"

    # Forms rebuilt from a teacher-authored scheme of work (they carry a
    # "source" block) are richer than anything this transcription produces and
    # are NOT regenerated here — re-ingesting a subject must not silently
    # discard them. See scripts/build_syllabus_from_schemes.py.
    if out.exists():
        existing = json.loads(out.read_text(encoding="utf-8")).get("forms", {})
        for form, data in existing.items():
            if data.get("source"):
                forms_out[form] = data
                print(f"  · {form}: kept teacher-scheme version "
                      f"({len(data.get('activities', []))} activities, not re-ingested)")

    doc = {
        "subject": subject,
        "level": LEVELS[level]["label"],
        "syllabus_edition": "2023 (Tanzania Institute of Education)",
        "source_pdf": SOURCES["levels"][level]["subjects"].get(subject, ""),
        "period_length_minutes": 40,
        "forms": forms_out,
    }
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ wrote {out} ({counter} activities)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("subject", nargs="?", help="Subject name (e.g. Chemistry)")
    ap.add_argument("--all", action="store_true", help="Ingest every downloaded PDF")
    ap.add_argument("--force", action="store_true",
                    help="Re-ingest even subjects that already have a JSON file")
    ap.add_argument("--level", default="ordinary", choices=list(LEVELS),
                    help="ordinary = Form I-IV (default), advanced = Form V-VI")
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
        for subj in SOURCES["levels"][args.level]["subjects"]:
            if not (PDF_DIR / f"{slug(subj, args.level)}.pdf").exists():
                continue
            if not args.force and (OUT_DIR / f"{slug(subj, args.level)}.json").exists():
                print(f"= {subj}: already ingested (use --force to redo)")
                skipped.append(subj)
                continue
            try:
                ingest(subj, args.level)
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
        ingest(args.subject, args.level)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
