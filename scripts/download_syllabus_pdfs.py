#!/usr/bin/env python3
"""Download the official TIE syllabus PDFs listed in data/sources.json.

The PDFs are gitignored (they are large and belong to TIE, not this repo), so a
fresh clone -- or a CI runner -- has to fetch them before ingestion can run.

Usage:
    python scripts/download_syllabus_pdfs.py --all
    python scripts/download_syllabus_pdfs.py Geography History
    python scripts/download_syllabus_pdfs.py --all --force   # re-download
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))
PDF_DIR = ROOT / "data" / "pdfs"

# tie.go.tz rejects the default urllib agent.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; lesson-planner/1.0)"}
TIMEOUT = 120


def slug(subject: str) -> str:
    return subject.lower().replace(" ", "_").replace("ya_", "").replace("'", "")


def download(subject: str, url: str, force: bool) -> str:
    dest = PDF_DIR / f"{slug(subject)}.pdf"
    if dest.exists() and not force:
        return f"= {subject}: already present ({dest.stat().st_size:,} bytes)"

    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as err:
        return f"! {subject}: download failed — {err}"

    # A TIE 404 returns an HTML error page with a 200-ish body; refuse to write
    # something that is not actually a PDF.
    if not body.startswith(b"%PDF"):
        return f"! {subject}: not a PDF (got {body[:16]!r}), skipped"

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return f"✓ {subject}: {len(body):,} bytes → {dest.relative_to(ROOT)}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("subjects", nargs="*", help="Subject names (default: --all)")
    ap.add_argument("--all", action="store_true", help="Download every listed subject")
    ap.add_argument("--force", action="store_true", help="Re-download existing files")
    args = ap.parse_args()

    catalog = SOURCES["subjects"]
    wanted = list(catalog) if (args.all or not args.subjects) else args.subjects

    unknown = [s for s in wanted if s not in catalog]
    if unknown:
        sys.exit(f"Unknown subject(s): {', '.join(unknown)}\n"
                 f"Available: {', '.join(catalog)}")

    failures = 0
    for subject in wanted:
        line = download(subject, catalog[subject], args.force)
        print(f"  {line}")
        failures += line.startswith("!")

    print(f"\n{len(wanted) - failures}/{len(wanted)} available in {PDF_DIR.relative_to(ROOT)}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
