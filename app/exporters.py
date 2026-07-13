"""Render a LessonPlanDocument to .docx and .pdf byte buffers."""

import io

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .schema import LessonPlanDocument


def _header_pairs(doc: LessonPlanDocument) -> list[tuple[str, str]]:
    r = doc.request
    total = r.boys + r.girls
    pairs = [
        ("School", r.school_name or "…………………………"),
        ("Teacher's name", r.teacher_name or "…………………………"),
        ("Date", r.date or "……………"),
        ("Subject", r.subject),
        ("Class/Form", f"{r.form} {r.stream}".strip()),
        ("Period / Time", f"{r.period_number}  {r.time}".strip() or "……………"),
        ("Number of students", f"Boys: {r.boys}  Girls: {r.girls}  Total: {total}"),
        ("Duration", f"{r.duration_minutes} minutes"),
    ]
    if r.week_label:
        pairs.append(("Scheme of work", r.week_label))
    if r.subtopic:
        pairs.append(("Sub-topic", r.subtopic))
    return pairs


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def to_docx(doc: LessonPlanDocument) -> bytes:
    d = Document()
    style = d.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    title = d.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("LESSON PLAN")
    run.bold = True
    run.font.size = Pt(14)

    sub = d.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    srun = sub.add_run(doc.plan.lesson_title)
    srun.italic = True
    srun.font.size = Pt(11)

    # Header table (2 columns per row -> 4 cells)
    pairs = _header_pairs(doc)
    htable = d.add_table(rows=0, cols=4)
    htable.style = "Table Grid"
    for i in range(0, len(pairs), 2):
        row = htable.add_row().cells
        row[0].paragraphs[0].add_run(pairs[i][0] + ":").bold = True
        row[1].text = pairs[i][1]
        if i + 1 < len(pairs):
            row[2].paragraphs[0].add_run(pairs[i + 1][0] + ":").bold = True
            row[3].text = pairs[i + 1][1]

    d.add_paragraph()

    def kv(label: str, value: str):
        p = d.add_paragraph()
        p.add_run(label + ": ").bold = True
        p.add_run(value)

    kv("Main competence", doc.plan.main_competence)
    kv("Specific competence", doc.plan.specific_competence)

    p = d.add_paragraph()
    p.add_run("Specific objectives:").bold = True
    for obj in doc.plan.specific_objectives:
        d.add_paragraph(obj, style="List Bullet")

    p = d.add_paragraph()
    p.add_run("Teaching and learning resources:").bold = True
    for res in doc.plan.teaching_learning_resources:
        d.add_paragraph(res, style="List Bullet")

    p = d.add_paragraph()
    p.add_run("References:").bold = True
    for ref in doc.plan.references:
        d.add_paragraph(ref, style="List Bullet")

    d.add_paragraph()
    p = d.add_paragraph()
    p.add_run("LESSON DEVELOPMENT").bold = True

    # Stages table
    table = d.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    for cell, label in zip(
        hdr,
        ["Stage / Time", "Teaching activities", "Learning activities", "Assessment", ""],
    ):
        run = cell.paragraphs[0].add_run(label)
        run.bold = True
    # Merge last two header cells (assessment spans)
    hdr[3].merge(hdr[4])

    for st in doc.plan.stages:
        cells = table.add_row().cells
        cells[0].text = f"{st.stage}\n({st.duration_minutes} min)"
        cells[1].text = st.teaching_activities
        cells[2].text = st.learning_activities
        cells[3].merge(cells[4])
        cells[3].text = st.assessment

    d.add_paragraph()
    kv("Evaluation", doc.plan.evaluation)
    kv("Remarks", doc.plan.remarks)

    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def to_pdf(doc: LessonPlanDocument) -> bytes:
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title="Lesson Plan",
    )
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
    cell_b = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=16)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, leading=12)

    story = [Paragraph("LESSON PLAN", h1), Paragraph(doc.plan.lesson_title, styles["Italic"]), Spacer(1, 8)]

    # Header grid
    pairs = _header_pairs(doc)
    rows = []
    for i in range(0, len(pairs), 2):
        left = [Paragraph(f"<b>{pairs[i][0]}:</b> {pairs[i][1]}", small)]
        right = [Paragraph(f"<b>{pairs[i+1][0]}:</b> {pairs[i+1][1]}", small)] if i + 1 < len(pairs) else [""]
        rows.append([left[0], right[0]])
    htable = Table(rows, colWidths=[13.5 * cm, 13.5 * cm])
    htable.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [htable, Spacer(1, 8)]

    def block(label, value):
        story.append(Paragraph(f"<b>{label}:</b> {value}", small))

    block("Main competence", doc.plan.main_competence)
    block("Specific competence", doc.plan.specific_competence)
    story.append(Paragraph("<b>Specific objectives:</b>", small))
    for obj in doc.plan.specific_objectives:
        story.append(Paragraph("• " + obj, small))
    story.append(Paragraph(
        "<b>Resources:</b> " + "; ".join(doc.plan.teaching_learning_resources), small))
    story.append(Paragraph("<b>References:</b> " + "; ".join(doc.plan.references), small))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>LESSON DEVELOPMENT</b>", small))
    story.append(Spacer(1, 4))

    data = [[
        Paragraph("<b>Stage / Time</b>", cell_b),
        Paragraph("<b>Teaching activities</b>", cell_b),
        Paragraph("<b>Learning activities</b>", cell_b),
        Paragraph("<b>Assessment</b>", cell_b),
    ]]
    for st in doc.plan.stages:
        data.append([
            Paragraph(f"<b>{st.stage}</b><br/>({st.duration_minutes} min)", cell),
            Paragraph(st.teaching_activities.replace("\n", "<br/>"), cell),
            Paragraph(st.learning_activities.replace("\n", "<br/>"), cell),
            Paragraph(st.assessment.replace("\n", "<br/>"), cell),
        ])
    table = Table(data, colWidths=[4 * cm, 8.5 * cm, 8.5 * cm, 6 * cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f7a4d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [table, Spacer(1, 8)]
    block("Evaluation", doc.plan.evaluation)
    block("Remarks", doc.plan.remarks)

    pdf.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Scheme of work exporters (the scheme is itself a document teachers submit)
# ---------------------------------------------------------------------------

# Official TIE (2023 revised curriculum) scheme-of-work layout: landscape page,
# SCHEME OF WORK title, School/Teacher/Subject/Year/Term header lines, then a
# 12-column table, one table per term.
_SCHEME_COLS = [
    ("Main Competence", 2.6),
    ("Specific Competences", 2.8),
    ("Learning Activities", 3.4),
    ("Specific Activities", 2.0),
    ("Month", 1.4),
    ("Week", 0.9),
    ("Number of Periods", 1.0),
    ("Teaching and Learning Methods", 4.1),
    ("Teaching and Learning Resources", 2.6),
    ("Assessment Tools", 2.4),
    ("References", 2.8),
    ("Remarks", 1.4),
]
_TERM_NAMES = {1: "TERM I", 2: "TERM II"}
_DOTS = "." * 44


def _scheme_row(e: dict) -> list[str]:
    # Specific Activities is the teacher's own breakdown of the learning
    # activity; pre-fill only the multi-week split so the teacher completes it.
    specific = ""
    if e.get("topic_weeks", 1) > 1:
        specific = f"Part {e['topic_week']} of {e['topic_weeks']} of the learning activity"
    return [
        e.get("main_competence", ""),
        e.get("specific_competence", ""),
        e.get("learning_activity", ""),
        specific,
        e["month"],
        str(e["week"]),
        str(e["periods"]),
        "; ".join(e.get("teaching_learning_activities", [])),
        ", ".join(e.get("resources", [])),
        e.get("assessment", ""),
        e.get("references", ""),
        e.get("remarks", ""),
    ]


def _scheme_terms(sch: dict) -> list[tuple[str, list[dict]]]:
    terms: list[tuple[str, list[dict]]] = []
    for sem in (1, 2):
        entries = [e for e in sch["entries"] if e["semester"] == sem]
        if entries:
            terms.append((_TERM_NAMES[sem], entries))
    return terms


def scheme_to_docx(sch: dict) -> bytes:
    d = Document()
    sec = d.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    sec.left_margin = sec.right_margin = Cm(1)
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(7)

    title = d.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("SCHEME OF WORK")
    run.bold = True
    run.font.size = Pt(14)
    for line in (
        f"Name of School: {_DOTS}        Teacher's Name: {_DOTS}",
        f"Subject: {sch['subject']}        Form: {sch['form']}",
        f"Year: {sch['year']}        Periods per week: {sch['periods_per_week']}",
    ):
        p = d.add_paragraph()
        p.add_run(line).font.size = Pt(10)

    for term_name, entries in _scheme_terms(sch):
        hp = d.add_paragraph()
        hr = hp.add_run(term_name)
        hr.bold = True
        hr.font.size = Pt(11)
        table = d.add_table(rows=1, cols=len(_SCHEME_COLS))
        table.style = "Table Grid"
        table.autofit = False
        for c, (label, width) in zip(table.rows[0].cells, _SCHEME_COLS):
            c.width = Cm(width)
            c.paragraphs[0].add_run(label).bold = True
        for e in entries:
            cells = table.add_row().cells
            for c, (_, width), text in zip(cells, _SCHEME_COLS, _scheme_row(e)):
                c.width = Cm(width)
                c.text = text

    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def scheme_to_pdf(sch: dict) -> bytes:
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1 * cm,
                            rightMargin=1 * cm, topMargin=1 * cm, bottomMargin=1 * cm,
                            title="Scheme of Work")
    styles = getSampleStyleSheet()
    head = ParagraphStyle("shead", parent=styles["Normal"], fontSize=10, leading=14)
    cell = ParagraphStyle("scell", parent=styles["Normal"], fontSize=6.5, leading=7.5)
    cell_b = ParagraphStyle("scellb", parent=cell, fontName="Helvetica-Bold",
                            textColor=colors.white)
    gap = "&nbsp;" * 8
    story = [
        Paragraph("SCHEME OF WORK", styles["Title"]),
        Paragraph(f"Name of School: {_DOTS}{gap}Teacher's Name: {_DOTS}", head),
        Paragraph(f"Subject: {sch['subject']}{gap}Form: {sch['form']}", head),
        Paragraph(f"Year: {sch['year']}{gap}Periods per week: {sch['periods_per_week']}", head),
        Spacer(1, 6),
    ]
    for term_name, entries in _scheme_terms(sch):
        story.append(Paragraph(term_name, styles["Heading3"]))
        data = [[Paragraph(label, cell_b) for label, _ in _SCHEME_COLS]]
        for e in entries:
            data.append([Paragraph(text, cell) for text in _scheme_row(e)])
        table = Table(data, colWidths=[w * cm for _, w in _SCHEME_COLS], repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f7a4d")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(table)
        story.append(Spacer(1, 10))
    pdf.build(story)
    return buf.getvalue()
