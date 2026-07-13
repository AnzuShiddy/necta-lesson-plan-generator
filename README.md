# Tanzania Lesson Plan Generator (NECTA / TIE 2023)

An AI-assisted web app that produces competence-based lesson plans for Tanzanian
secondary education, grounded in the **Tanzania Institute of Education (TIE) 2023
revised curriculum**. Teachers pick a subject, form, and a real syllabus learning
activity; the AI (Google Gemini) expands it into a full classroom-ready plan that they can preview
and download as **Word (.docx)** or **PDF**.

![Screenshot: choosing a Biology Form One activity and the generated competence-based lesson plan](docs/screenshot.png)

## Getting started

**Prerequisites:** Python 3.10+ and a free Google Gemini API key.

```bash
# 1. Clone
git clone https://github.com/AnzuShiddy/necta-lesson-plan-generator.git
cd necta-lesson-plan-generator

# 2. Get a free Gemini key at https://aistudio.google.com/apikey, then:
export GEMINI_API_KEY=your-key-here

# 3. Install dependencies and start the app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

Open **http://localhost:8000**, pick a subject → form → learning activity, fill in
the lesson header, and click **Generate lesson plan**. Preview it in the browser,
then download it as **Word (.docx)** or **PDF**.

> The 14 subjects with syllabus data (see below) work out of the box. Without a
> `GEMINI_API_KEY` the browsing UI still loads and exports work, but **Generate**
> returns an error asking you to set the key. On Google's free tier, per-model
> daily request limits are small — if generation is rate-limited, wait and retry
> or set a different model via `LESSONPLAN_MODEL` (see *Model* below).

## Why it's grounded, not invented

The curriculum content is stored as structured data in `data/syllabus/*.json`,
extracted from the official TIE syllabus PDFs. Each learning activity carries its
real **main competence**, **specific competence**, suggested methods, assessment
criteria, and resources. The model is instructed to copy the competence statements
verbatim and build the lesson only from the selected activity, so the plans cite
the actual syllabus rather than the model's general (and possibly outdated)
knowledge.

## Subject coverage

The app advertises all 18 subjects (`data/registry.json`). Each shows a status:

- **ready** — has structured syllabus data and can generate plans now.
  Currently **14 subjects, 769 learning activities** across Forms I–IV: Biology,
  Chemistry, Physics, Mathematics, Geography, History, Computer Science,
  Kiswahili, English Language, Literature in English, Business Studies,
  Bible Knowledge, Historia ya Tanzania na Maadili, Elimu ya Dini ya Kiislamu.
  (Literature is a Form III–IV subject, so its data covers only those two
  forms — that is correct, not a gap.) All were transcribed verbatim from the
  official TIE PDFs via `scripts/ingest_syllabus.py`.
- **pending** — no usable 2023 PDF found. Currently 4: **Arabic** (TIE's own
  publications-page link 404s — broken on their server), **Civics** (not
  published standalone in 2023; its content was folded into *Historia ya
  Tanzania na Maadili*, which is covered), **French** and **Chinese** (no 2023
  `sw-*` document posted yet). See `data/sources.json` → `unavailable` for notes.

Non-ready subjects appear in the dropdown (disabled) so teachers see what's coming.

## Populating subjects (ingestion)

`scripts/ingest_syllabus.py` turns a downloaded TIE PDF into structured JSON,
**grounded in the real document**: it extracts the PDF text, slices it per Form,
and asks the model to *transcribe* (not invent) each learning-activity row of the
syllabus matrix into the schema. Because the model only ever sees the real
syllabus text and is told to copy verbatim, the output is a faithful
transcription.

```bash
export GEMINI_API_KEY=...
python scripts/ingest_syllabus.py Chemistry     # one subject
python scripts/ingest_syllabus.py --all         # every downloaded PDF
```

After ingestion the new `data/syllabus/<subject>.json` makes that subject "ready"
in the UI automatically. Always spot-check the generated JSON against the PDF —
the Form-splitter is best-effort and a few subjects (e.g. Physics, Islamic
Education) have PDF-extraction quirks that may drop or thin a Form section.

To add a subject that's still **pending**: find its `tie.go.tz/uploads/documents/sw-...`
PDF URL, add it to `data/sources.json`, run the download step, then ingest.

## Run

```bash
export GEMINI_API_KEY=...   # free key: https://aistudio.google.com/apikey
./run.sh                                  # http://localhost:8000
```

Or manually:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

Without a key, the browsing/preview UI still loads and exports work, but
**Generate** returns a 502 telling you to set `GEMINI_API_KEY`.

## Lesson development formats

- **Classic** — Introduction → New Knowledge → Reinforcement → Reflection → Consolidation
- **TIE 2023** — Introduction → Competence Development → Design → Realisation

## Architecture

| File | Role |
|------|------|
| `app/syllabus.py` | Loads structured TIE syllabus JSON |
| `app/llm.py` | Single point where the app calls the LLM (Google Gemini)
| `app/generator.py` | Builds the grounded prompt and calls `llm.structured()` |
| `app/exporters.py` | Renders the plan to `.docx` (python-docx) and `.pdf` (reportlab) |
| `app/main.py` | FastAPI endpoints + serves the single-page UI |
| `app/static/index.html` | Teacher-facing form and live preview |
| `data/syllabus/*.json` | Structured curriculum data (ground truth) |
| `scripts/` | Helpers for extracting more syllabi from TIE PDFs |

## Model

Uses **Google Gemini** (default `gemini-flash-lite-latest`, free tier) with
structured outputs so the response always matches the lesson-plan schema. The
provider lives in one file, `app/llm.py` — change the model via the
`LESSONPLAN_MODEL` environment variable (e.g. a stronger model on a paid tier for
higher-quality plans), or swap providers there without touching the rest of the
app.

## Extending the syllabus

1. Download the subject PDF from tie.go.tz into `data/pdfs/`.
2. Extract the competence matrix (Table 3–6) — `scripts/extract_pdf_text.py`
   dumps the text; transcribe each row into the JSON shape in `biology.json`.
3. Drop the new JSON in `data/syllabus/`. It appears in the UI automatically.
