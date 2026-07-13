#!/usr/bin/env python3
"""Dump text from a TIE syllabus PDF so its competence matrix can be transcribed
into data/syllabus/<subject>.json.

Usage:
    python scripts/extract_pdf_text.py data/pdfs/biology_olevel_2023.pdf [start_page end_page]
"""

import sys

from pypdf import PdfReader


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    path = sys.argv[1]
    reader = PdfReader(path)
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    end = int(sys.argv[3]) if len(sys.argv) > 3 else len(reader.pages)
    for i in range(start - 1, min(end, len(reader.pages))):
        print(f"\n===== PAGE {i + 1} =====")
        print(reader.pages[i].extract_text() or "(no extractable text)")


if __name__ == "__main__":
    main()
