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

    The syllabus states periods per *specific competence* (repeated on every
    activity of that competence). Split a competence's periods evenly across its
    activities so the weekly total stays faithful to the syllabus."""
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


def _references(subject: str) -> str:
    meta = syllabus.get_subject_meta(subject)
    ed = meta.get("syllabus_edition", "2023 (Tanzania Institute of Education)")
    return f"{subject} Syllabus for Ordinary Secondary Education, {ed}"


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
    # derive periods/week from the syllabus's own totals over the real 2026 weeks
    ppw = max(1, round(total_periods / len(weeks)))
    refs = _references(subject)

    # Expand the syllabus into an ordered queue of period-slots, each tagged
    # with the activity it belongs to, then chunk the queue into weeks of `ppw`
    # periods. A multi-week topic naturally spans several week rows.
    slots: list[int] = []
    for i, p in enumerate(periods):
        slots.extend([i] * p)

    n_week_rows = min(len(weeks), max(1, -(-len(slots) // ppw)))  # ceil division
    entries: list[dict] = []
    for row in range(n_week_rows):
        chunk = slots[row * ppw:(row + 1) * ppw]
        if not chunk:
            break
        wk = weeks[row]
        # primary activity for the week = the one with the most periods in it
        primary_i = max(set(chunk), key=chunk.count)
        a = activities[primary_i]
        # which week (of how many) this activity is currently in, for display
        span = periods[primary_i]
        entries.append({
            "entry_id": f"s{wk['semester']}w{wk['week']}",
            "semester": wk["semester"],
            "week": wk["week"],
            "month": wk["month"],
            "start_date": wk["start_date"],
            "end_date": wk["end_date"],
            "main_competence": a.get("main_competence", ""),
            "specific_competence": a.get("specific_competence", ""),
            "learning_activity": a.get("learning_activity", ""),
            "activity_id": a.get("id", ""),
            "periods": len(chunk),
            "activity_total_periods": span,
            "teaching_learning_activities": a.get("suggested_methods", []),
            "assessment": a.get("assessment_criteria", ""),
            "resources": a.get("suggested_resources", []),
            "references": refs,
            "remarks": "",
        })

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
