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


# Official TIE (2023 revised curriculum) lesson plan layout: portrait page,
# LESSON PLAN title, School/Teacher, Form/Subject, Time/Date lines, a
# Registered/Present students table, competence and activity lines, then the
# Teaching and Learning Process table and Remarks.
_LP_DOTS = "." * 30


def _lp_header_lines(doc: LessonPlanDocument) -> list[str]:
    r = doc.request
    time = r.time
    if r.period_number:
        time = f"Period {r.period_number}, {time}".strip(", ")
    if r.duration_minutes:
        time = f"{time} ({r.duration_minutes} minutes)".strip()
    return [
        f"Name of School: {r.school_name or _LP_DOTS}"
        f"        Teacher's Name: {r.teacher_name or _LP_DOTS}",
        f"Form: {f'{r.form} {r.stream}'.strip()}        Subject: {r.subject}",
        f"Time: {time or _LP_DOTS}        Date: {r.date or _LP_DOTS}",
    ]


def _lp_fields(doc: LessonPlanDocument) -> list[tuple[str, str]]:
    p = doc.plan
    fields = [
        ("Main Competence", p.main_competence),
        ("Specific Competence", p.specific_competence),
        ("Main Activity", doc.request.subtopic or p.lesson_title),
        ("Specific Activity", p.lesson_title),
    ]
    if doc.request.week_label:
        fields.append(("Scheme of Work Reference", doc.request.week_label))
    return fields


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def to_docx(doc: LessonPlanDocument) -> bytes:
    r = doc.request
    d = Document()
    style = d.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    title = d.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("LESSON PLAN")
    run.bold = True
    run.font.size = Pt(14)

    for line in _lp_header_lines(doc):
        d.add_paragraph(line)

    # Number of students: Registered vs Present (present left for the teacher)
    stable = d.add_table(rows=4, cols=6)
    stable.style = "Table Grid"
    stable.alignment = WD_TABLE_ALIGNMENT.CENTER
    top = stable.rows[0].cells
    top[0].merge(top[5]).paragraphs[0].add_run("Number of students").bold = True
    mid = stable.rows[1].cells
    mid[0].merge(mid[2]).paragraphs[0].add_run("Registered").bold = True
    mid[3].merge(mid[5]).paragraphs[0].add_run("Present").bold = True
    for c, label in zip(stable.rows[2].cells, ["Girls", "Boys", "Total"] * 2):
        c.paragraphs[0].add_run(label).bold = True
    for c, value in zip(stable.rows[3].cells,
                        [r.girls, r.boys, r.boys + r.girls, "", "", ""]):
        c.text = str(value)

    d.add_paragraph()

    def kv(label: str, value: str):
        p = d.add_paragraph()
        p.add_run(label + ": ").bold = True
        p.add_run(value)

    for label, value in _lp_fields(doc):
        kv(label, value)

    kv("Teaching and Learning Resources",
       "; ".join(doc.plan.teaching_learning_resources))
    kv("References", "; ".join(doc.plan.references))

    d.add_paragraph()
    p = d.add_paragraph()
    p.add_run("Teaching and Learning Process").bold = True

    table = d.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, label in zip(table.rows[0].cells,
                           ["Stages", "Time (Minutes)", "Teaching Activities",
                            "Learning Activities", "Assessment Criteria"]):
        cell.paragraphs[0].add_run(label).bold = True
    for st in doc.plan.stages:
        cells = table.add_row().cells
        cells[0].text = st.stage
        cells[1].text = str(st.duration_minutes)
        cells[2].text = st.teaching_activities
        cells[3].text = st.learning_activities
        cells[4].text = st.assessment

    d.add_paragraph()
    kv("Remarks", doc.plan.remarks)

    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def to_pdf(doc: LessonPlanDocument) -> bytes:
    r = doc.request
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title="Lesson Plan",
    )
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
    cell_b = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold",
                            textColor=colors.white)
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=16)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, leading=12)

    story = [Paragraph("LESSON PLAN", h1)]
    for line in _lp_header_lines(doc):
        story.append(Paragraph(line.replace("        ", "&nbsp;" * 8), small))
    story.append(Spacer(1, 6))

    # Number of students: Registered vs Present
    total = r.boys + r.girls
    sdata = [
        [Paragraph("<b>Number of students</b>", small), "", "", "", "", ""],
        [Paragraph("<b>Registered</b>", small), "", "", Paragraph("<b>Present</b>", small), "", ""],
        [Paragraph(f"<b>{h}</b>", small) for h in ["Girls", "Boys", "Total"] * 2],
        [Paragraph(str(v), small) for v in [r.girls, r.boys, total]] + ["", "", ""],
    ]
    stable = Table(sdata, colWidths=[2.2 * cm] * 6, hAlign="LEFT")
    stable.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("SPAN", (0, 0), (5, 0)),
        ("SPAN", (0, 1), (2, 1)),
        ("SPAN", (3, 1), (5, 1)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story += [stable, Spacer(1, 8)]

    def block(label, value):
        story.append(Paragraph(f"<b>{label}:</b> {value}", small))

    for label, value in _lp_fields(doc):
        block(label, value)
    block("Teaching and Learning Resources",
          "; ".join(doc.plan.teaching_learning_resources))
    block("References", "; ".join(doc.plan.references))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Teaching and Learning Process</b>", small))
    story.append(Spacer(1, 4))

    data = [[Paragraph(h, cell_b) for h in
             ["Stages", "Time (Minutes)", "Teaching Activities",
              "Learning Activities", "Assessment Criteria"]]]
    for st in doc.plan.stages:
        data.append([
            Paragraph(f"<b>{st.stage}</b>", cell),
            Paragraph(str(st.duration_minutes), cell),
            Paragraph(st.teaching_activities.replace("\n", "<br/>"), cell),
            Paragraph(st.learning_activities.replace("\n", "<br/>"), cell),
            Paragraph(st.assessment.replace("\n", "<br/>"), cell),
        ])
    table = Table(data, colWidths=[2.8 * cm, 1.7 * cm, 5.5 * cm, 5.5 * cm, 3.1 * cm],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f7a4d")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [table, Spacer(1, 8)]
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
