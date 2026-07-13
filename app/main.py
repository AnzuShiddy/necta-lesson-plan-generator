"""FastAPI app: NECTA/TIE competence-based lesson plan generator."""

import base64

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import exporters, generator, llm, scheme, syllabus
from .schema import GeneratedLessonPlan, LessonPlanDocument, LessonPlanRequest

app = FastAPI(title="Tanzania Lesson Plan Generator", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/subjects")
def api_subjects():
    # Each entry: {"name": ..., "status": "ready"|"pdf"|"pending"}
    return {"subjects": syllabus.list_subjects()}


@app.get("/api/forms")
def api_forms(subject: str):
    return {"forms": syllabus.list_forms(subject)}


@app.get("/api/scheme")
def api_scheme(subject: str, form: str):
    """The 2026 scheme of work for a subject + form (weeks driving lesson plans)."""
    return scheme.build_scheme(subject, form)


def _week_label(entry: dict) -> str:
    return (f"Semester {entry['semester']}, Week {entry['week']} "
            f"({entry['month']} {entry['start_date']} to {entry['end_date']})")


@app.post("/api/generate")
def api_generate(req: LessonPlanRequest):
    if not llm.has_credentials():
        raise HTTPException(
            status_code=503,
            detail="No GEMINI_API_KEY set on the server. Get a free key at "
                   "https://aistudio.google.com/apikey and restart the app.",
        )
    entry = scheme.get_entry(req.subject, req.form, req.entry_id)
    if entry is None:
        raise HTTPException(status_code=400,
                            detail=f"Unknown scheme week {req.entry_id!r}")
    # stamp the scheme context onto the request so exports carry week + sub-topic
    req.week_label = _week_label(entry)
    req.subtopic = entry["learning_activity"]
    try:
        plan = generator.generate(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # surface model/credential errors to the UI
        raise HTTPException(status_code=502, detail=f"Generation failed: {e}")
    return {"request": req.model_dump(), "plan": plan.model_dump()}


def _rebuild_doc(payload: dict) -> LessonPlanDocument:
    return LessonPlanDocument(
        request=LessonPlanRequest(**payload["request"]),
        plan=GeneratedLessonPlan(**payload["plan"]),
    )


@app.post("/api/export/docx")
def api_export_docx(payload: dict):
    doc = _rebuild_doc(payload)
    data = exporters.to_docx(doc)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="lesson_plan.docx"'},
    )


@app.post("/api/export/pdf")
def api_export_pdf(payload: dict):
    doc = _rebuild_doc(payload)
    data = exporters.to_pdf(doc)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="lesson_plan.pdf"'},
    )


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@app.get("/api/scheme/export/docx")
def api_scheme_docx(subject: str, form: str):
    sch = scheme.build_scheme(subject, form)
    fn = f"scheme_{subject}_{form}".replace(" ", "_")
    return Response(exporters.scheme_to_docx(sch), media_type=DOCX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{fn}.docx"'})


@app.get("/api/scheme/export/pdf")
def api_scheme_pdf(subject: str, form: str):
    sch = scheme.build_scheme(subject, form)
    fn = f"scheme_{subject}_{form}".replace(" ", "_")
    return Response(exporters.scheme_to_pdf(sch), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fn}.pdf"'})
