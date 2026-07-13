"""Generates a competence-based lesson plan with Claude, grounded in a real
TIE syllabus learning activity.

The syllabus content (main competence, specific competence, learning activity,
suggested methods, assessment criteria, resources) is passed in as ground truth.
Claude expands it into a full, classroom-ready lesson plan. It is instructed to
copy the competence statements verbatim so the plan cites the real syllabus.
"""

from . import llm, scheme, syllabus
from .schema import GeneratedLessonPlan, LessonPlanRequest

SYSTEM_PROMPT = """You are an experienced Tanzanian secondary school teacher and \
curriculum expert who prepares lesson plans that comply with the Tanzania Institute \
of Education (TIE) 2023 competence-based curriculum and NECTA expectations.

You will be given ONE learning activity taken directly from the official TIE syllabus, \
together with its main competence, specific competence, suggested teaching/learning \
methods, assessment criteria and suggested resources. Your job is to expand it into a \
single classroom-ready lesson plan.

Rules you must follow:
- Copy the `main_competence` and `specific_competence` text EXACTLY as supplied. Do not \
reword them.
- Base the lesson strictly on the supplied learning activity. Do not introduce content \
from other topics or invent syllabus references.
- Write specific objectives in measurable ABCD form ("By the end of the lesson, each \
student should be able to ..."), starting with observable verbs (state, describe, \
demonstrate, classify, investigate). Keep them achievable within the given lesson time.
- Favour student-centred, activity-based methods (group discussion, brainstorming, \
jigsaw, field visit, experimentation, project, ICT-based learning) drawn from the \
suggested methods.
- Prefer locally available and improvised teaching/learning resources suitable for a \
Tanzanian school.
- Assessment must reflect the supplied assessment criteria.
- The stages you produce must sum (in duration_minutes) to the total lesson duration \
supplied by the teacher.
- Write in clear, professional English suitable for a teacher's file and for inspection."""

STAGE_GUIDES = {
    "classic": (
        "Use these five stages in order: Introduction, New Knowledge (Presentation of "
        "new knowledge), Reinforcement, Reflection, Consolidation. This is the standard "
        "competence-based lesson development format used in Tanzanian secondary schools."
    ),
    "tie2023": (
        "Use these four stages in order: Introduction, Competence Development, "
        "Design, Realisation. This follows the TIE 2023 competence-based lesson "
        "development stages."
    ),
}


def build_user_prompt(req: LessonPlanRequest, entry: dict) -> str:
    meta = syllabus.get_subject_meta(req.subject)
    periods = req.duration_minutes / max(meta["period_length_minutes"], 1)
    stage_guide = STAGE_GUIDES.get(req.plan_format, STAGE_GUIDES["classic"])
    methods = entry.get("teaching_learning_activities", [])
    resources = entry.get("resources", [])
    span_note = ""
    if entry.get("topic_weeks", 1) > 1:
        span_note = (f"\nThis topic runs across {entry['topic_weeks']} weeks in the scheme "
                     f"of work; this lesson is for WEEK {entry['topic_week']} of "
                     f"{entry['topic_weeks']}. Cover the portion appropriate to this week, "
                     f"not the entire topic.")
    return f"""Prepare a lesson plan for one scheduled lesson, taken from the 2026 scheme \
of work below. The scheme entry is derived from the official TIE syllabus.

SUBJECT: {req.subject}
SYLLABUS: {meta['syllabus_edition']}
FORM: {req.form}
SCHEME OF WORK SLOT: Semester {entry['semester']}, Week {entry['week']} \
({entry['month']}, {entry['start_date']} to {entry['end_date']})
LESSON DURATION: {req.duration_minutes} minutes (~{periods:.0f} period(s) of \
{meta['period_length_minutes']} minutes)
CLASS SIZE: {req.boys} boys, {req.girls} girls

MAIN COMPETENCE (copy verbatim):
{entry['main_competence']}

SPECIFIC COMPETENCE (copy verbatim):
{entry['specific_competence']}

LEARNING ACTIVITY / SUB-TOPIC (the focus of this lesson):
{entry['learning_activity']}{span_note}

SUGGESTED TEACHING AND LEARNING METHODS:
{chr(10).join('- ' + m for m in methods) if methods else '- (use suitable student-centred methods)'}

ASSESSMENT CRITERIA:
{entry.get('assessment', '')}

SUGGESTED RESOURCES:
{', '.join(resources) if resources else '(use locally available materials)'}

LESSON DEVELOPMENT FORMAT:
{stage_guide}

TEACHER'S EXTRA NOTES: {req.extra_notes or '(none)'}

For the references field, cite the {req.subject} Syllabus for Ordinary Secondary \
Education ({meta['syllabus_edition']}) and leave space for the approved textbook and page.

Produce the complete lesson plan now."""


def generate(req: LessonPlanRequest) -> GeneratedLessonPlan:
    entry = scheme.get_entry(req.subject, req.form, req.entry_id)
    if entry is None:
        raise ValueError(
            f"Unknown scheme week {req.entry_id!r} for {req.subject} {req.form}"
        )

    plan = llm.structured(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(req, entry),
        schema=GeneratedLessonPlan,
    )
    if plan is None:
        raise RuntimeError("Model did not return a valid lesson plan")
    return plan
