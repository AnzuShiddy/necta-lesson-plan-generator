"""Official MoEST 2026 academic calendar for Tanzanian secondary schools, and
the ordered list of teaching weeks it produces.

Source: MoEST Semester Calendar for Pre-Primary, Primary and Secondary Schools
(Forms I-IV), academic year 2026.
  Semester 1: 13 Jan 2026 - 05 Jun 2026;  mid-term break 27 Mar - 08 Apr 2026
  Semester 2: 06 Jul 2026 - 04 Dec 2026;  mid-term break 04 Sep - 14 Sep 2026

A "teaching week" is a Monday-Friday week that overlaps a semester and is not
inside a mid-term break. Weeks are numbered per semester.
"""

from __future__ import annotations

from datetime import date, timedelta

YEAR = 2026

SEMESTERS = [
    {
        "semester": 1,
        "start": date(2026, 1, 13),
        "end": date(2026, 6, 5),
        "break_start": date(2026, 3, 27),
        "break_end": date(2026, 4, 8),
    },
    {
        "semester": 2,
        "start": date(2026, 7, 6),
        "end": date(2026, 12, 4),
        "break_start": date(2026, 9, 4),
        "break_end": date(2026, 9, 14),
    },
]

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def teaching_weeks() -> list[dict]:
    """Ordered teaching weeks across the 2026 school year.

    Each week: {semester, week (per-semester #), month, start_date, end_date}
    where start/end are the Mon/Fri of that school week (ISO strings)."""
    weeks: list[dict] = []
    for sem in SEMESTERS:
        wk = 0
        monday = _monday_of(sem["start"])
        while monday <= sem["end"]:
            friday = monday + timedelta(days=4)
            overlaps_break = not (friday < sem["break_start"] or monday > sem["break_end"])
            overlaps_term = not (friday < sem["start"] or monday > sem["end"])
            if overlaps_term and not overlaps_break:
                wk += 1
                weeks.append({
                    "semester": sem["semester"],
                    "week": wk,
                    "month": MONTHS[monday.month],
                    "start_date": monday.isoformat(),
                    "end_date": friday.isoformat(),
                })
            monday += timedelta(days=7)
    return weeks


def total_teaching_weeks() -> int:
    return len(teaching_weeks())
