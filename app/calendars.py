"""Academic calendars for Tanzanian secondary schools, and the ordered teaching
weeks each one produces.

Two calendars, because the two levels do not share a school year:

  * Ordinary level (Form I-IV) runs January to December within one calendar
    year. Source: MoEST Semester Calendar for Pre-Primary, Primary and
    Secondary Schools, academic year 2026.
      Semester 1: 13 Jan 2026 - 05 Jun 2026;  mid-term break 27 Mar - 08 Apr
      Semester 2: 06 Jul 2026 - 04 Dec 2026;  mid-term break 04 Sep - 14 Sep

  * Advanced level (Form V-VI) runs July to June and therefore spans two
    calendar years - the 2026/2027 year. Form V students selected in 2026
    reported from 4 July 2026 with studies beginning 6 July 2026, and Form VI
    sits the NECTA ACSEE examinations in May.

A "teaching week" is a Monday-Friday week that overlaps a semester and is not
inside a mid-term break. Weeks are numbered per semester.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

ORDINARY_FORMS = ("Form One", "Form Two", "Form Three", "Form Four")
ADVANCED_FORMS = ("Form Five", "Form Six")

ORDINARY = "ordinary"
ADVANCED = "advanced"


def level_of(form: str) -> str:
    """Which level a form belongs to. The form name implies the level, so
    nothing else in the app has to carry it around."""
    return ADVANCED if form in ADVANCED_FORMS else ORDINARY


@dataclass(frozen=True)
class Calendar:
    key: str
    year_label: str                 # printed on the scheme of work
    semesters: tuple[dict, ...]
    # True when part of the calendar is inferred rather than taken from the
    # official almanac. Surfaced through the API so the UI can say so instead
    # of presenting inferred dates as fact.
    provisional: bool = False
    provisional_note: str = ""

    def teaching_weeks(self) -> list[dict]:
        """Ordered teaching weeks across the school year.

        Each week: {semester, week (per-semester #), month, start_date,
        end_date} where start/end are the Mon/Fri of that school week."""
        weeks: list[dict] = []
        for sem in self.semesters:
            wk = 0
            monday = _monday_of(sem["start"])
            while monday <= sem["end"]:
                friday = monday + timedelta(days=4)
                in_break = not (friday < sem["break_start"]
                                or monday > sem["break_end"])
                in_term = not (friday < sem["start"] or monday > sem["end"])
                if in_term and not in_break:
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

    def milestones(self) -> list[dict]:
        """School-calendar assessment events, pinned to real teaching weeks.

        Every teacher-authored scheme of work carries these rows alongside the
        teaching ones, in the same places: a test in the last week before each
        mid-term break, terminal examinations closing the first semester, and
        revision then annual examinations closing the year. The dates come from
        `semesters`, so nothing here is guesswork - only the naming follows the
        source documents.

        Returns [{index, label}] where index points into teaching_weeks()."""
        weeks = self.teaching_weeks()
        by_semester: dict[int, list[int]] = {}
        for i, wk in enumerate(weeks):
            by_semester.setdefault(wk["semester"], []).append(i)

        events: list[dict] = []
        for sem in self.semesters:
            indices = by_semester.get(sem["semester"], [])
            if not indices:
                continue
            before_break = [i for i in indices
                            if weeks[i]["end_date"] < sem["break_start"].isoformat()]
            if before_break:
                events.append({"index": before_break[-1], "label": "MIDTERM TEST"})
            if sem["semester"] == self.semesters[-1]["semester"]:
                if len(indices) >= 2:
                    events.append({"index": indices[-2], "label": "REVISION"})
                events.append({"index": indices[-1], "label": "ANNUAL EXAMINATIONS"})
            else:
                events.append({"index": indices[-1], "label": "TERMINAL EXAMINATIONS"})
        return sorted(events, key=lambda e: e["index"])


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


ORDINARY_2026 = Calendar(
    key=ORDINARY,
    year_label="2026",
    semesters=(
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
    ),
)

# ---------------------------------------------------------------------------
# Advanced level 2026/2027
#
# Semester 1 is real: it is the same Jul-Dec 2026 block as the ordinary-level
# calendar above, and Form V reporting (4 Jul 2026) with studies from 6 Jul 2026
# falls exactly on it.
#
# Semester 2 runs into 2027, and the official MoEST almanac for that year is not
# in hand. The dates below mirror the 2026 January-June shape and stop before
# the ACSEE examinations in May. They are INFERRED, not official - `provisional`
# is True so the app says so rather than presenting them as fact. Replace this
# block with the published 2026/2027 almanac and drop the flag.
# ---------------------------------------------------------------------------
ADVANCED_2026_27 = Calendar(
    key=ADVANCED,
    year_label="2026/2027",
    semesters=(
        {
            "semester": 1,
            "start": date(2026, 7, 6),
            "end": date(2026, 12, 4),
            "break_start": date(2026, 9, 4),
            "break_end": date(2026, 9, 14),
        },
        {
            "semester": 2,
            "start": date(2027, 1, 12),
            "end": date(2027, 5, 7),
            "break_start": date(2027, 3, 26),
            "break_end": date(2027, 4, 7),
        },
    ),
    provisional=True,
    provisional_note=(
        "Semester 1 (Jul-Dec 2026) follows the official MoEST 2026 calendar. "
        "Semester 2 (Jan-May 2027) is inferred from the 2026 pattern and ends "
        "before the ACSEE examinations - replace it with the published "
        "2026/2027 almanac before relying on those dates."
    ),
)

CALENDARS = {ORDINARY: ORDINARY_2026, ADVANCED: ADVANCED_2026_27}


def for_form(form: str) -> Calendar:
    return CALENDARS[level_of(form)]
