# Tanzania Lesson Plan Generator (NECTA / TIE 2023)

An AI-assisted web app that produces competence-based lesson plans for Tanzanian
secondary education, grounded in the **Tanzania Institute of Education (TIE) 2023
revised curriculum**. It follows the real teaching workflow: the syllabus is laid
out as a **2026 scheme of work** (weeks and dates on the official school calendar),
the teacher picks a week, and the AI (Google Gemini) expands that week's sub-topic
into a full classroom-ready lesson plan — previewable and downloadable as
**Word (.docx)** or **PDF**. The scheme of work itself is also exportable.

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

## Scheme of work → lesson plan

In Tanzanian practice a lesson plan is drawn from the **scheme of work (azimio la
kazi)** — the syllabus distributed across the year's teaching weeks. The app builds
that scheme **deterministically and grounded**, with no AI and no scraping:

- **competences, activities, methods, assessment** come from the syllabus data;
- **periods per topic** come from the syllabus's own `periods_for_specific_competence`;
- **weeks and dates** come from the official MoEST **2026** calendar
  (`app/calendar2026.py` — Sem 1: 13 Jan–5 Jun, break 27 Mar–8 Apr; Sem 2:
  6 Jul–4 Dec, break 4 Sep–14 Sep; 37 teaching weeks).

Periods-per-week is *derived* (total syllabus periods ÷ 2026 teaching weeks), not
guessed, and multi-week topics span consecutive weeks. The generated schemes are
materialised in `data/schemes/*.json` (via `scripts/build_schemes.py`) and are also
exportable to Word/PDF. Then the lesson plan flows from a chosen week, inheriting
its week number, dates and sub-topic.

> Third-party 2026 scheme files (wazaelimu, elimuchap, …) are paywalled or gated,
> and are themselves just the syllabus on the calendar — so generating gives the
> same result, complete for all subjects and consistent with the plans.

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

The PDFs themselves are gitignored, so fetch them first — `data/sources.json`
holds the official TIE URLs:

```bash
python scripts/download_syllabus_pdfs.py --all   # or: ... Geography History
```

```bash
export GEMINI_API_KEY=...
python scripts/ingest_syllabus.py Chemistry     # one subject
python scripts/ingest_syllabus.py --all         # every downloaded PDF
```

Every subject already has a JSON file, so re-ingesting needs `--force`. Forms
built from a teacher scheme of work are preserved either way.

### Ingesting without a local API key

`.github/workflows/ingest-syllabus.yml` runs the same pipeline on GitHub
Actions using the `GEMINI_API_KEY` repository secret, and opens a pull request
with the regenerated data. Trigger it from **Actions → Ingest TIE syllabus →
Run workflow**, picking a subject. It is `workflow_dispatch` only — ingestion
is model-based and must never fire on push.

Requires **Settings → Actions → General → Workflow permissions → "Allow GitHub
Actions to create and approve pull requests"**, otherwise the PR step fails.

After ingestion the new `data/syllabus/<subject>.json` makes that subject "ready"
in the UI automatically. Always spot-check the generated JSON against the PDF —
the Form-splitter is best-effort and a few subjects (e.g. Physics, Islamic
Education) have PDF-extraction quirks that may drop or thin a Form section.

To add a subject that's still **pending**: find its `tie.go.tz/uploads/documents/sw-...`
PDF URL, add it to `data/sources.json`, run the download step, then ingest.

### Ingesting a real teacher scheme of work

A few forms are built from schemes actually used in class rather than from the
TIE syllabus transcription, which gives them topic-level detail and the
teacher's own month/week pacing. Drop the source document in `data/reference/`
(the documents stay local — as does the parsed text of any third-party one, since
that text *is* the document; the rebuilt output is committed either way), then:

```bash
python scripts/ingest_scheme_docs.py          # documents  -> data/reference/parsed/
python scripts/build_syllabus_from_schemes.py # parsed     -> data/syllabus/
python scripts/build_schemes.py               # syllabus   -> data/schemes/
```

Both source layouts are handled: the TIE competence-based layout, and the older
topic-based one (`MAIN-TOPIC` / `SUB-TOPIC`). No model call is involved — parsing
is deterministic. Activities from these forms carry three extra fields
(`periods`, `scheduled_month`, `scheduled_weeks`); `app/scheme.py` honours that
pacing instead of spreading periods evenly, and any form without them keeps the
original even-distribution behaviour. Currently applied to Biology Form One and
Three, and Chemistry Form Two and Three.

Re-ingesting a subject with `ingest_syllabus.py` **will not** overwrite a form
that was built this way — forms carrying a `source` block are kept as they are.

### Calendar milestones

Every teacher-authored scheme carries test and examination rows beside the
teaching rows, always in the same places. `calendar2026.milestones()` derives
them from the semester dates rather than hard-coding them:

| Milestone | When |
|---|---|
| `MIDTERM TEST` | last teaching week before each mid-term break |
| `TERMINAL EXAMINATIONS` | last teaching week of semester 1 |
| `REVISION` | second-to-last teaching week of semester 2 |
| `ANNUAL EXAMINATIONS` | last teaching week of semester 2 |

Schemes get these automatically, tagged `kind: "assessment"` and carrying zero
teaching periods so they never inflate the period totals. A form whose source
document already supplies its own milestone rows keeps those instead, at the
weeks the teacher chose.

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
| `app/calendar2026.py` | Official MoEST 2026 term dates → ordered teaching weeks |
| `app/scheme.py` | Builds the 2026 scheme of work from syllabus + calendar |
| `app/llm.py` | Single point where the app calls the LLM (Google Gemini) |
| `app/generator.py` | Builds the grounded prompt (from a scheme week) and calls `llm.structured()` |
| `app/exporters.py` | Renders lesson plans and schemes to `.docx` / `.pdf` |
| `app/main.py` | FastAPI endpoints + serves the single-page UI |
| `app/static/index.html` | Teacher-facing scheme table + lesson preview |
| `data/syllabus/*.json` | Structured curriculum data (ground truth) |
| `data/schemes/*.json` | Generated 2026 schemes of work (via `scripts/build_schemes.py`) |
| `scripts/` | PDF ingestion + scheme generation helpers |

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
