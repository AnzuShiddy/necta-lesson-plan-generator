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
    "nursery": {
        "forms": ["Awali"],
        "label": "Pre-primary Education (Awali)",
        # One document for the whole level: there are no per-form sections to
        # find, so the matrix is taken whole and split by subject afterwards.
        # 30 pages of front matter precede it, so start at the matrix heading.
        "single_section": True,
        "matrix_start": r"Maudhui ya Muhtasari wa Elimu ya Awali",
        "aliases": {"Awali": {"rn": "Awali", "word": "Awali", "sw": "Awali"}},
    },
    "primary": {
        "forms": [f"Grade {n}" for n in range(1, 7)],
        "label": "Primary Education (Grade 1-6)",
        "anchor_running_head": True,
        "unit_en": "Standard",
        # "Darasa la IV" but also plain "Darasa IV" — TIE drops the "la" in
        # places (Historia ya Tanzania na Maadili heads Grade 4 that way).
        "unit_sw": r"Darasa(?:\s+la)?",
        # Primary syllabuses are written in Kiswahili and head each grade
        # "Maudhui ya Darasa la III"; the English-medium ones say "Standard III".
        # A bare "Darasa la I" matches running prose ("Darasa la I-VI, Tanzania
        # Bara"), so primary drops that fallback and relies on the real headings.
        "strict_headings": True,
        "aliases": {
            "Grade 1": {"rn": "I",           "word": "One",   "sw": "I"},
            "Grade 2": {"rn": "II",          "word": "Two",   "sw": "II"},
            # Swahili headings carry the same OCR variants as the English ones
            # (Darasa la 1V for IV), so the numerals allow both spellings.
            "Grade 3": {"rn": "(?:III|1II)", "word": "Three", "sw": "(?:III|1II)", "fr": "IIIe"},
            "Grade 4": {"rn": "(?:IV|1V)",   "word": "Four",  "sw": "(?:IV|1V)",  "fr": "IVe"},
            "Grade 5": {"rn": "V",           "word": "Five",  "sw": "V",          "fr": "Ve"},
            "Grade 6": {"rn": "(?:VI|V1)",   "word": "Six",   "sw": "(?:VI|V1)",  "fr": "VIe"},
        },
    },
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


SUFFIX = {"ordinary": "", "advanced": "_advanced",
          "primary": "_primary", "nursery": "_nursery"}


def slug(subject: str, level: str = "ordinary") -> str:
    s = re.sub(r"\bya\b", " ", subject.lower())
    # subject names carry slashes and commas ("Sayansi / Science"); keep the
    # filename plain ASCII words.
    s = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s)).strip("_")
    return s + SUFFIX.get(level, "")


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
    cfg = LEVELS[level]
    forms = cfg["forms"]
    if cfg.get("single_section"):
        # Pre-primary is one document for one "form"; there is nothing to slice
        # beyond skipping the front matter.
        start = 0
        if cfg.get("matrix_start"):
            hits = list(re.finditer(cfg["matrix_start"], full_text, re.IGNORECASE))
            hits = [h for h in hits if not _is_contents_entry(full_text, h.end())]
            if hits:
                start = hits[-1].start()
        return {forms[0]: full_text[start:]}
    # Each form can be headed in English (roman or spelled-out) or Swahili.
    # Secondary calls a year "Form"/"Kidato cha", primary "Standard"/"Darasa la".
    unit_en = cfg.get("unit_en", "Form")
    unit_sw = cfg.get("unit_sw", "Kidato cha")
    aliases = cfg["aliases"]
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
            pats.append(rf"(?m)^[ \t]*{unit_en}\s*{a['rn']}[ \t]*$"
                        rf"(?=\n[^\n]{{0,90}}"
                        rf"(?:Table\s*\d|Jedwali|Detailed\s+Contents?|Maudhui))")
        if a.get("fr"):
            pats += [
                rf"(?m)^[ \t]*{a['fr']}\s*Ann[ée]e[ \t]*$"
                rf"(?=\n[^\n]{{0,90}}(?:Tableau\s*\d|Les\s+Contenus))",
                rf"Les\s+Contenus[^\n]{{0,80}}pour\s+la\s+{a['fr']}\s*Ann[ée]e",
            ]
        pats += [
            # "Detailed Content(s)" — the 's' and inner spacing vary by PDF.
            rf"Detailed\s+Contents?\s+for\s+{unit_en}\s*{a['rn']}\b",
            rf"Detailed\s+Contents?\s+for\s+{unit_en}\s*{a['word']}\b",
            # Swahili-medium syllabi: "Maudhui ya Kidato cha I" / "Maudhui ya
            # Darasa la III" is the section heading — specific enough to avoid
            # the "Kidato cha I - IV" running footer that the bare form hits.
            # "Maudhui ya|kwa [Muhtasari] Darasa la III" — TIE varies the
            # preposition and sometimes slips a word in before the unit.
            rf"Maudhui\s+(?:ya|kwa)\s+(?:\w+\s+)?{unit_sw}\s*{a['sw']}\b",
            *([] if cfg.get("strict_headings")
              else [rf"{unit_sw}\s*{a['sw']}\b"]),
            # Bare heading before the matrix, tolerating a page number in between
            # e.g. "Form III\n38\nMain competences".
            rf"\b{unit_en}\s*{a['rn']}\s*\n?\s*\d*\s*(?:Main|Umahiri)\b",
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


# ---------------------------------------------------------------------------
# Combined documents
#
# Pre-primary and Grade 1-2 are not published one PDF per subject: a single
# document carries the whole band, organised by main competence rather than by
# subject. Each numbered main competence IS a subject, so an activity is filed
# under the subject its competence number names. The maps below are read
# straight off each document's own competence table, cited beside them, so the
# split stays grounded in the source rather than in the model's judgement.
# ---------------------------------------------------------------------------
COMBINED_DOCS = {
    # Muhtasari wa Elimu ya Msingi Darasa la I na la II (2023), Jedwali Na. 1.
    "grade_1_2": {
        "level": "primary",
        "subjects": {
            1: "Kusoma / Reading",              # 1.0 Kusoma
            2: "Kuandika / Writing",            # 2.0 Kuandika
            3: "English",                       # 3.0 Demonstrate mastery of basic
                                                #     English language skills
            4: "Kuhesabu / Arithmetic",         # 4.0 Kuhesabu
            5: "Utamaduni, Sanaa na Michezo",   # 5.0 Kuthamini utamaduni, sanaa
                                                #     na michezo
            6: "Afya na Mazingira",             # 6.0 Kutunza afya na mazingira
        },
        # Subjects a school timetables under one name that the syllabus states
        # as several competences. This document has no Kiswahili competence —
        # it says Kiswahili is the *language of instruction* at Standard I-II
        # ("kwa kutumia Kiswahili kama lugha ya kufundishia") and its literacy
        # work is Kusoma and Kuandika. Schools still timetable that period as
        # Kiswahili, so it is offered under that name too, carrying exactly
        # those two competences' rows and nothing else.
        "aggregates": {"Kiswahili": (1, 2)},
    },
    # Mtaala na Muhtasari wa Elimu ya Awali (2023), Jedwali Na. 1.2.
    "awali": {
        "level": "nursery",
        "subjects": {
            1: "Creative Arts and Sports",       # 1.0 Kumudu stadi za kisanii,
                                                 #     ubunifu na michezo
            2: "Naipenda Nchi Yangu Tanzania",   # 2.0 Kuthamini utamaduni ... na
                                                 #     tunu za taifa
            3: "Early Literacy Skills",          # 3.0 Kumudu stadi za awali za
                                                 #     lugha ya mawasiliano
            4: "Early Life Skills",              # 4.0 Kuhusiana
            5: "Health and Environment",         # 5.0 Kutunza afya na mazingira
            6: "Arithmetic, Science and ICT",    # 6.0 Kutumia stadi za awali za
                                                 #     kihisabati, sayansi na TEHAMA
        },
    },
}

# A pre-primary session is 20 minutes (Mtaala wa Elimu ya Awali, Jedwali Na.
# 1.5); everything else runs on 40-minute periods.
PERIOD_MINUTES = {"nursery": 20}

# "1.0 Kusoma", "1. Kusoma" and plain "6 Kutumia stadi ..." all occur — the
# decimal part survives transcription inconsistently.
_LEADING_NUMBER = re.compile(r"^\s*(\d+)\s*(?:[.．]\s*\d*)?\s+\S")


def competence_number(activity: dict) -> int | None:
    """The main competence's number, which names the subject in a combined
    document. TIE numbers them "1.0 Kusoma", and the transcription keeps the
    number, so it can be read straight back off."""
    m = _LEADING_NUMBER.match(activity.get("main_competence", "") or "")
    return int(m.group(1)) if m else None


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


def _form_key(form: str) -> str:
    """Short id fragment for a form: "Form One" -> one, "Grade 3" -> 3,
    "Awali" -> awali."""
    parts = form.split()
    return (parts[1] if len(parts) > 1 else parts[0]).lower()


def transcribe(label: str, sections: dict[str, str], id_prefix: str) -> dict[str, list[dict]]:
    """Send each form's matrix text to the model and return its activity rows."""
    out: dict[str, list[dict]] = {}
    counter = 0
    for form, text in sections.items():
        text = text[:60000]  # keep the request bounded
        print(f"  · {form}: {len(text)} chars → {llm.MODEL}")
        parsed = llm.structured(
            system=SYSTEM,
            user=f"Subject: {label}\nForm: {form}\n\nDetailed contents text:\n{text}",
            schema=FormContents,
        )
        if parsed is None:
            print("    ! model returned no activities", file=sys.stderr)
            continue
        acts = []
        for a in parsed.activities:
            counter += 1
            d = a.model_dump()
            d["id"] = f"{id_prefix}-{_form_key(form)}-{counter}"
            acts.append(d)
        carried = carry_merged_competences(acts)
        if carried:
            print(f"    · carried {carried} merged competence cell(s) down")
        blank = sum(1 for a in acts if not a.get("main_competence"))
        if blank:
            print(f"    ! {blank}/{len(acts)} rows still have no main competence — "
                  f"the PDF text extraction dropped those cells", file=sys.stderr)
        out[form] = acts
    return out


def ingest_combined(doc_key: str) -> None:
    """Ingest a document that holds a whole band's subjects, filing each
    activity under the subject its main competence number names."""
    cfg = COMBINED_DOCS[doc_key]
    level = cfg["level"]
    pdf = PDF_DIR / f"{slug(doc_key, level)}.pdf"
    if not pdf.exists():
        print(f"  ! no PDF for {doc_key} at {pdf}", file=sys.stderr)
        return
    print(f"→ {doc_key} ({level}, combined): extracting text …")
    sections = split_by_form(extract_text(pdf), level)
    if not sections:
        print(f"  ! could not locate sections in {doc_key}", file=sys.stderr)
        return
    per_form = transcribe(doc_key, sections, doc_key[:4])

    by_subject: dict[str, dict[str, list[dict]]] = {}
    unmapped: list[str] = []
    for form, acts in per_form.items():
        for a in acts:
            subject = cfg["subjects"].get(competence_number(a))
            if subject is None:
                unmapped.append((a.get("main_competence") or "")[:60])
                continue
            by_subject.setdefault(subject, {}).setdefault(form, []).append(a)
    if unmapped:
        print(f"    ! {len(unmapped)} row(s) had no recognisable competence number "
              f"and were not filed: {unmapped[:3]}", file=sys.stderr)

    # Subjects a school names once but the syllabus states as several
    # competences. The rows are the same ones already filed above, re-presented
    # under the timetable's name — nothing is duplicated in the source.
    for name, numbers in cfg.get("aggregates", {}).items():
        for form, acts in per_form.items():
            rows = [a for a in acts if competence_number(a) in numbers]
            if rows:
                by_subject.setdefault(name, {})[form] = rows

    url = SOURCES["levels"][level].get("combined", {}).get(doc_key, "")
    for subject, forms in sorted(by_subject.items()):
        out = OUT_DIR / f"{slug(subject, level)}.json"
        forms_out = {f: {"activities": a} for f, a in forms.items()}
        # A subject can be split across documents — Kiswahili is Grade 1-2 here
        # and Grade 3-6 in its own syllabus — so keep the forms this document
        # does not cover, exactly as ingest() does.
        if out.exists():
            for form, data in json.loads(out.read_text(encoding="utf-8")).get("forms", {}).items():
                if form not in forms_out:
                    forms_out[form] = data
                    print(f"  · {subject} {form}: kept other document version "
                          f"({len(data.get('activities', []))} activities)")
        order = LEVELS[level]["forms"]
        forms_out = {f: forms_out[f] for f in
                     sorted(forms_out, key=lambda x: order.index(x) if x in order else 99)}
        doc = {
            "subject": subject,
            "level": LEVELS[level]["label"],
            "syllabus_edition": "2023 (Tanzania Institute of Education)",
            "source_pdf": url,
            "period_length_minutes": PERIOD_MINUTES.get(level, 40),
            "forms": forms_out,
        }
        out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        n = sum(len(f["activities"]) for f in forms_out.values())
        print(f"  ✓ {subject}: {n} activities across {len(forms_out)} form(s) → {out.name}")


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

    forms_out = {f: {"activities": a} for f, a in
                 transcribe(subject, sections, slug(subject)[:4]).items()}

    out = OUT_DIR / f"{slug(subject, level)}.json"

    # Keep every form this document does not itself cover:
    #  * forms rebuilt from a teacher-authored scheme of work carry a "source"
    #    block and are richer than anything this transcription produces
    #    (see scripts/build_syllabus_from_schemes.py);
    #  * a subject can also be split across two TIE documents — English is in
    #    both the combined Grade 1-2 syllabus and its own Grade 3-6 one, and
    #    ingesting either must not wipe the other's grades.
    if out.exists():
        existing = json.loads(out.read_text(encoding="utf-8")).get("forms", {})
        for form, data in existing.items():
            if form in forms_out:
                continue
            forms_out[form] = data
            why = "teacher-scheme" if data.get("source") else "other document"
            print(f"  · {form}: kept {why} version "
                  f"({len(data.get('activities', []))} activities, not re-ingested)")
        forms_out = {f: forms_out[f] for f in
                     sorted(forms_out, key=lambda x: LEVELS[level]["forms"].index(x)
                            if x in LEVELS[level]["forms"] else 99)}

    doc = {
        "subject": subject,
        "level": LEVELS[level]["label"],
        "syllabus_edition": "2023 (Tanzania Institute of Education)",
        "source_pdf": SOURCES["levels"][level]["subjects"].get(subject, ""),
        "period_length_minutes": PERIOD_MINUTES.get(level, 40),
        "forms": forms_out,
    }
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    total = sum(len(f["activities"]) for f in forms_out.values())
    print(f"  ✓ wrote {out} ({total} activities)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("subject", nargs="?", help="Subject name (e.g. Chemistry)")
    ap.add_argument("--all", action="store_true", help="Ingest every downloaded PDF")
    ap.add_argument("--force", action="store_true",
                    help="Re-ingest even subjects that already have a JSON file")
    ap.add_argument("--level", default="ordinary", choices=list(LEVELS),
                    help="nursery = Awali, primary = Grade 1-6, "
                         "ordinary = Form I-IV (default), advanced = Form V-VI")
    ap.add_argument("--combined", choices=list(COMBINED_DOCS),
                    help="Ingest one multi-subject document (pre-primary, Grade 1-2)")
    args = ap.parse_args()

    if not llm.has_credentials():
        sys.exit(
            "No Gemini credentials found. Ingestion calls the Gemini API.\n"
            "Get a free key at https://aistudio.google.com/apikey, then:\n"
            "  export GEMINI_API_KEY=...\n"
            "and re-run:  python scripts/ingest_syllabus.py --all"
        )

    combined_here = [k for k, c in COMBINED_DOCS.items() if c["level"] == args.level]

    if args.combined:
        ingest_combined(args.combined)
        return

    if args.all:
        done, skipped, failed = [], [], []
        # Combined documents first: they define subjects the per-subject loop
        # never sees.
        for key in combined_here:
            already = all((OUT_DIR / f"{slug(s, args.level)}.json").exists()
                          for s in COMBINED_DOCS[key]["subjects"].values())
            if already and not args.force:
                print(f"= {key}: already ingested (use --force to redo)")
                skipped.append(key)
                continue
            try:
                ingest_combined(key)
                done.append(key)
            except Exception as e:
                print(f"  ! {key}: failed ({type(e).__name__}: {str(e)[:120]})",
                      file=sys.stderr)
                failed.append(key)
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
