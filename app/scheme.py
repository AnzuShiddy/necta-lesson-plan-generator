"""Generate a 2026 scheme of work (azimio la kazi) for a subject + form.

A scheme distributes the syllabus's learning activities across the real 2026
teaching weeks. It is fully grounded in data we already have — the model is not
involved:

  * competences, activities, methods, assessment  -> from data/syllabus/*.json
  * periods per specific competence                -> `periods_for_specific_competence`
  * teaching weeks + dates                          -> app/calendar2026.py

Periods-per-week is *derived*, not guessed: total syllabus periods for the form
divided over the number of 2026 teaching weeks. Activities are packed into weeks
in syllabus order, each carrying its real week number, month and Mon-Fri dates.
"""

from __future__ import annotations

from functools import lru_cache

from . import calendar2026, syllabus

# Sensible floor so an activity with 0 stated periods still gets scheduled.
_MIN_PERIODS_PER_ACTIVITY = 1
# Guards against bad syllabus data (e.g. a mis-transcribed 17-digit period count)
# blowing up the schedule. No real specific competence exceeds these.
_MAX_GROUP_PERIODS = 120
_MAX_ACTIVITY_PERIODS = 60


def _activity_periods(activities: list[dict]) -> list[int]:
    """Periods for each activity.

    Forms ingested from a real teacher scheme state periods per *activity*
    (`periods`), which is authoritative -- use it directly.

    Otherwise the syllabus states periods per *specific competence* (repeated on
    every activity of that competence). Split a competence's periods evenly
    across its activities so the weekly total stays faithful to the syllabus."""
    if any(a.get("periods") for a in activities):
        return [min(max(int(a.get("periods") or 0), _MIN_PERIODS_PER_ACTIVITY),
                    _MAX_ACTIVITY_PERIODS) for a in activities]
    # group consecutive activities sharing a specific competence
    groups: list[list[int]] = []
    idx_by_group: list[list[int]] = []
    last_key = object()
    for i, a in enumerate(activities):
        key = (a.get("main_competence", ""), a.get("specific_competence", ""))
        if key != last_key:
            groups.append([])
            idx_by_group.append([])
            last_key = key
        idx_by_group[-1].append(i)

    periods = [0] * len(activities)
    for members in idx_by_group:
        raw = activities[members[0]].get("periods_for_specific_competence", 0) or 0
        total = min(max(int(raw), 0), _MAX_GROUP_PERIODS)  # clamp bad/huge data
        n = len(members)
        if total <= 0:
            for i in members:
                periods[i] = 2  # default small block when the syllabus omits periods
            continue
        base, extra = divmod(total, n)
        for j, i in enumerate(members):
            p = max(_MIN_PERIODS_PER_ACTIVITY, base + (1 if j < extra else 0))
            periods[i] = min(p, _MAX_ACTIVITY_PERIODS)
    return periods


# Schemes of work cite the approved TIE textbooks. Subjects taught in Kiswahili
# cite the Kiswahili editions (TET = Taasisi ya Elimu Tanzania).
_KISWAHILI_MEDIUM = {"Kiswahili", "Historia ya Tanzania na Maadili",
                     "Elimu ya Dini ya Kiislamu"}
_FORM_KISWAHILI = {
    "Form One": "Kidato cha Kwanza",
    "Form Two": "Kidato cha Pili",
    "Form Three": "Kidato cha Tatu",
    "Form Four": "Kidato cha Nne",
}


def _references(subject: str, form: str) -> str:
    """TIE book citation for the scheme's reference (rejea) column."""
    if subject in _KISWAHILI_MEDIUM:
        kidato = _FORM_KISWAHILI.get(form, form)
        return (f"TET, {subject} {kidato}: Kitabu cha Mwanafunzi na Kiongozi "
                "cha Mwalimu (Toleo la 2023), Taasisi ya Elimu Tanzania")
    return (f"TIE, {subject} for Secondary Schools {form}: Student's Book and "
            "Teacher's Guide (2023 Edition), Tanzania Institute of Education")


def _month_week_index(weeks: list[dict]) -> dict[tuple[str, int], int]:
    """Map (month, nth teaching week of that month) -> index into `weeks`.

    Teacher schemes cite weeks as "the 2nd week of March", while the calendar
    numbers weeks per semester, so the two have to be reconciled."""
    index: dict[tuple[str, int], int] = {}
    seen: dict[str, int] = {}
    for i, wk in enumerate(weeks):
        seen[wk["month"]] = seen.get(wk["month"], 0) + 1
        index[(wk["month"], seen[wk["month"]])] = i
    return index


def _paced_week_rows(activities: list[dict], periods: list[int],
                     weeks: list[dict]) -> dict[int, list[tuple[int, int]]]:
    """Place each activity in the week its source document actually names.

    A document's "week 4 of January" is read as the 4th *teaching* week of
    January. Schools open on 13 January 2026, so January has only three teaching
    weeks and that ordinal has nowhere to land; an out-of-range ordinal clamps
    to the month's last teaching week, which keeps the document's ordering and
    clustering intact (clamping to the first week would reorder the term).

    An activity spanning several weeks has its periods split across them. An
    activity whose month is unknown keeps syllabus order after the previously
    placed one."""
    index = _month_week_index(weeks)
    month_weeks: dict[str, list[int]] = {}
    for i, wk in enumerate(weeks):
        month_weeks.setdefault(wk["month"], []).append(i)

    rows: dict[int, list[tuple[int, int]]] = {}
    last = 0
    for ai, act in enumerate(activities):
        month = act.get("scheduled_month") or ""
        in_month = month_weeks.get(month, [])
        targets = []
        for o in act.get("scheduled_weeks") or []:
            if (month, o) in index:
                targets.append(index[(month, o)])
            elif in_month:
                targets.append(in_month[-1])
        targets = sorted(set(targets))
        if not targets:
            targets = in_month[:1]
        if not targets:
            targets = [min(last, len(weeks) - 1)]
        base, extra = divmod(periods[ai], len(targets))
        for k, wi in enumerate(targets):
            share = base + (1 if k < extra else 0)
            if share > 0:
                rows.setdefault(wi, []).append((ai, share))
        last = max(targets)
    return rows


def _even_week_rows(periods: list[int],
                    weeks: list[dict]) -> dict[int, list[tuple[int, int]]]:
    """Spread every activity's periods as evenly as possible over ALL 2026
    teaching weeks (per-week load varies by at most one period), so nothing is
    cut by rounding."""
    slots: list[int] = []
    for i, p in enumerate(periods):
        slots.extend([i] * p)

    rows: dict[int, list[tuple[int, int]]] = {}
    base, extra = divmod(len(slots), len(weeks))
    pos = 0
    for row in range(len(weeks)):
        size = base + (1 if row < extra else 0)
        chunk = slots[pos:pos + size]
        pos += size
        order: list[int] = []
        share: dict[int, int] = {}
        for i in chunk:
            if i not in share:
                order.append(i)
                share[i] = 0
            share[i] += 1
        if order:
            rows[row] = [(i, share[i]) for i in order]
    return rows


@lru_cache(maxsize=64)
def build_scheme(subject: str, form: str) -> dict:
    """Return a scheme-of-work dict for one subject + form for 2026."""
    activities = syllabus.list_activities(subject, form)
    weeks = calendar2026.teaching_weeks()
    if not activities or not weeks:
        return {"subject": subject, "form": form, "year": calendar2026.YEAR,
                "periods_per_week": 0, "entries": []}

    periods = _activity_periods(activities)
    total_periods = sum(periods)
    refs = _references(subject, form)

    # Forms sourced from a real teacher scheme carry the month and week the
    # teacher actually taught each activity; honour that placement rather than
    # inventing an even spread. A week teaching several activities gets one row
    # per activity, each keeping its own competences, methods and assessment.
    paced = any(a.get("scheduled_month") for a in activities)
    if paced:
        week_rows = _paced_week_rows(activities, periods, weeks)
    else:
        week_rows = _even_week_rows(periods, weeks)

    entries: list[dict] = []
    for row in sorted(week_rows):
        wk = weeks[row]
        for k, (i, share) in enumerate(week_rows[row]):
            a = activities[i]
            entries.append({
                "entry_id": f"s{wk['semester']}w{wk['week']}" + (f"-{k + 1}" if k else ""),
                "semester": wk["semester"],
                "week": wk["week"],
                "month": wk["month"],
                "start_date": wk["start_date"],
                "end_date": wk["end_date"],
                "main_competence": a.get("main_competence", ""),
                "specific_competence": a.get("specific_competence", ""),
                "learning_activity": a.get("learning_activity", ""),
                "activity_id": a.get("id", ""),
                "periods": share,
                "activity_total_periods": periods[i],
                "teaching_learning_activities": a.get("suggested_methods", []),
                "assessment": a.get("assessment_criteria", ""),
                "resources": a.get("suggested_resources", []),
                "references": refs,
                "remarks": "",
            })

    # periods/week over the weeks actually taught (a paced scheme leaves exam and
    # revision weeks empty, so averaging over all 37 would understate the load)
    taught_weeks = len(week_rows) or len(weeks)
    ppw = max(1, round(total_periods / taught_weeks))

    # annotate "week X of Y" for topics that span several weeks
    from collections import Counter
    totals = Counter(e["activity_id"] for e in entries)
    seen: dict[str, int] = {}
    for e in entries:
        aid = e["activity_id"]
        seen[aid] = seen.get(aid, 0) + 1
        e["topic_week"] = seen[aid]
        e["topic_weeks"] = totals[aid]

    return {
        "subject": subject,
        "form": form,
        "year": calendar2026.YEAR,
        "periods_per_week": ppw,
        "total_periods": total_periods,
        "teaching_weeks": len(weeks),
        "entries": entries,
    }


def get_entry(subject: str, form: str, entry_id: str) -> dict | None:
    """Look up a scheme week by its entry_id (e.g. 's1w4')."""
    for e in build_scheme(subject, form)["entries"]:
        if e["entry_id"] == entry_id:
            return e
    return None
