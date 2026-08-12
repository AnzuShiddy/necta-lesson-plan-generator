#!/usr/bin/env python3
"""Write an English rendering of the Kiswahili pre-primary and primary syllabuses.

TIE publishes those two levels in Kiswahili only. English-medium schools teach
that identical curriculum in English, so the app offers a medium of instruction
— but a scheme of work is built deterministically, with no model call, and must
stay that way. So the translation happens ONCE, here, and is stored beside the
source as `data/syllabus/<slug>.en.json`. At request time the app just picks the
file matching the chosen medium.

The Kiswahili file is never modified: it remains the verbatim transcription of
the published syllabus, and the `.en.json` beside it is plainly a translation.

Rows are matched back by their activity `id`, so a row the model drops or
renames keeps its original Kiswahili text rather than disappearing.

Usage:
    python scripts/translate_syllabus.py --all --level primary
    python scripts/translate_syllabus.py "Sayansi / Science" --level primary
    python scripts/translate_syllabus.py --all --level nursery --force
Requires GEMINI_API_KEY.
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import llm  # noqa: E402
from app.syllabus import SYLLABUS_DIR, TRANSLATION_SUFFIX, _slug  # noqa: E402

# Fields that carry syllabus prose and therefore need rendering. Everything else
# (id, period counts) is structural and copied across untouched.
TEXT_FIELDS = ("main_competence", "specific_competence", "learning_activity",
               "assessment_criteria")
LIST_FIELDS = ("suggested_methods", "suggested_resources")

SYSTEM = """You translate official Tanzania Institute of Education (TIE) syllabus \
content from Kiswahili into English for use in an English-medium Tanzanian school.

Translate faithfully and completely. Keep the meaning, the register and the level of \
detail exactly; this is a curriculum document, not prose to improve. Preserve every \
numbering and lettering marker exactly as given ("1.0", "5.1", "(a)", "(b)"). Keep \
each list the same length and in the same order. Keep the `id` of every row EXACTLY \
as supplied — it is how the translation is matched back to the original.

Use the standard English terms of the Tanzanian curriculum: umahiri mkuu = main \
competence, umahiri mahususi = specific competence, shughuli za ujifunzaji = learning \
activities, vigezo vya upimaji = assessment criteria, zana = resources.

If a passage is already in English, copy it through unchanged. Never add, drop, \
merge or reorder rows, and never invent content that is not in the source.

Some language syllabuses are bilingual: the row carries Arabic or Chinese script \
alongside the Kiswahili. EVERY field you return must still be English. Render the \
meaning in English and drop the duplicated foreign-script copy, except where a word \
is itself the thing being taught (a Kiswahili word a pupil must learn, an Arabic \
letter, a Chinese character) — keep those, in their own script, inside the English \
sentence. Returning Kiswahili is a failure, even if the source row was Kiswahili."""


class TranslatedActivity(BaseModel):
    id: str = Field(description="Copied EXACTLY from the input row")
    main_competence: str
    specific_competence: str
    learning_activity: str
    suggested_methods: list[str]
    assessment_criteria: str
    suggested_resources: list[str]


class Translated(BaseModel):
    activities: list[TranslatedActivity]


def translate_form(subject: str, form: str, activities: list[dict]) -> list[dict]:
    """Return `activities` with their prose fields rendered in English."""
    payload = [{"id": a.get("id", "")} | {f: a.get(f, "") for f in TEXT_FIELDS}
               | {f: a.get(f, []) for f in LIST_FIELDS} for a in activities]
    parsed = llm.structured(
        system=SYSTEM,
        user=(f"Subject: {subject}\nForm: {form}\n\nTranslate these "
              f"{len(payload)} syllabus rows into English:\n"
              + json.dumps(payload, ensure_ascii=False, indent=1)),
        schema=Translated,
    )
    if parsed is None:
        print("    ! model returned nothing — keeping Kiswahili", file=sys.stderr)
        return activities

    by_id = {t.id: t for t in parsed.activities}
    out, missed = [], 0
    for a in activities:
        t = by_id.get(a.get("id", ""))
        if t is None:
            missed += 1
            out.append(dict(a))          # untranslated beats missing
            continue
        row = dict(a)
        for f in TEXT_FIELDS:
            row[f] = getattr(t, f)
        for f in LIST_FIELDS:
            row[f] = getattr(t, f)
        out.append(row)
    if missed:
        print(f"    ! {missed}/{len(activities)} row(s) came back unmatched and "
              f"stay in Kiswahili", file=sys.stderr)
    return out


def translate(subject: str, level: str, force: bool = False) -> None:
    src = SYLLABUS_DIR / f"{_slug(subject, level)}.json"
    if not src.exists():
        print(f"  ! no syllabus for {subject} at {src}", file=sys.stderr)
        return
    dest = src.with_name(src.stem + TRANSLATION_SUFFIX)
    if dest.exists() and not force:
        print(f"= {subject}: already translated (use --force to redo)")
        return

    data = json.loads(src.read_text(encoding="utf-8"))
    print(f"→ {subject} ({level}): translating …")
    forms_out = {}
    for form, fd in data["forms"].items():
        acts = fd.get("activities", [])
        print(f"  · {form}: {len(acts)} rows → {llm.MODEL}")
        forms_out[form] = dict(fd, activities=translate_form(subject, form, acts))

    doc = dict(data)
    doc["forms"] = forms_out
    doc["language"] = "en"
    doc["translation_of"] = src.name
    doc["translation_note"] = (
        "English rendering of the Kiswahili TIE syllabus, for English-medium "
        "schools. Not TIE's own wording — see translation_of for the verbatim "
        "source.")
    dest.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    n = sum(len(f["activities"]) for f in forms_out.values())
    print(f"  ✓ wrote {dest.name} ({n} rows)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("subject", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--level", default="primary", choices=["primary", "nursery"],
                    help="Only these two levels are published in Kiswahili")
    args = ap.parse_args()

    if not llm.has_credentials():
        sys.exit("No Gemini credentials found. export GEMINI_API_KEY=...")

    suffix = {"primary": "_primary", "nursery": "_nursery"}[args.level]
    if args.all:
        done = failed = 0
        for path in sorted(SYLLABUS_DIR.glob(f"*{suffix}.json")):
            if path.name.endswith(TRANSLATION_SUFFIX):
                continue
            subject = json.loads(path.read_text(encoding="utf-8"))["subject"]
            try:
                translate(subject, args.level, args.force)
                done += 1
            except llm.QuotaExceeded as e:
                print(f"  ! {subject}: daily quota hit — stopping.\n    {str(e)[:120]}",
                      file=sys.stderr)
                failed += 1
                break
            except Exception as e:
                print(f"  ! {subject}: failed ({type(e).__name__}: {str(e)[:120]})",
                      file=sys.stderr)
                failed += 1
        print(f"\nDone: {done}  Failed: {failed}")
    elif args.subject:
        translate(args.subject, args.level, args.force)


if __name__ == "__main__":
    main()
