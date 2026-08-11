#!/usr/bin/env python3
"""Generate the scheme of work for every ready subject/form, at both levels, and
write it to data/schemes/<slug>_<form>.json.

Schemes are derived deterministically from the syllabus data + the academic
calendar for that form's level — 2026 for Form I-IV, 2026/2027 for Form V-VI
(no API calls), so this just materialises them as committed, inspectable
artifacts. The app generates the same schemes on the fly; these files are the
data snapshot.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import scheme, syllabus  # noqa: E402

OUT = ROOT / "data" / "schemes"


def slug(subject: str) -> str:
    return subject.lower().replace(" ", "_").replace("ya_", "").replace("'", "")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    count = 0
    pairs = [(lvl["key"], s) for lvl in syllabus.list_levels()
             for s in syllabus.list_subjects(lvl["key"]) if s["status"] == "ready"]
    for level, s in pairs:
        subject = s["name"]
        # Form V-VI files never collide with Form I-IV ones: the form is in the
        # filename and no form name is shared between the levels.
        for form in syllabus.list_forms(subject, level):
            sch = scheme.build_scheme(subject, form)
            if not sch["entries"]:
                continue
            path = OUT / f"{slug(subject)}_{form.replace(' ', '_').lower()}.json"
            path.write_text(json.dumps(sch, indent=2, ensure_ascii=False), encoding="utf-8")
            count += 1
            print(f"  {path.name}: {len(sch['entries'])} weeks "
                  f"({sch['periods_per_week']} periods/week)")
    print(f"Wrote {count} scheme files to {OUT}")


if __name__ == "__main__":
    main()
