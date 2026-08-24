#!/usr/bin/env python3
"""
build_viewer.py
---------------
Builds one course's standalone yardage book — the single-course shape of the
app in `build_app.py`, which is where the page itself now lives.

The page is the same one either way; a book is just the app with a library of
one, so it opens straight onto that course and `#book` still prints from it.
For the searchable multi-course tool, use `build_app.py`.

Usage:
    python build_viewer.py                    # pilot course
    python build_viewer.py --course 20561
    python build_viewer.py --all              # every course_*.json on disk
    python build_viewer.py --out yardage.html
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_app import HERE, build, load, scraped

PILOT_COURSE_ID = 20625


def build_one(course_id: int, out: Path | None = None) -> Path:
    src = HERE / f"course_{course_id}.json"
    if not src.exists():
        have = [p.stem.split("_")[1] for p in scraped()]
        raise SystemExit(
            f"{src.name} not found — run:  python courses.py --course {course_id}\n"
            + (f"  already scraped: {', '.join(have)}\n" if have else "")
            + "  to see which courses you have played:  python courses.py --list"
        )
    return build(out or HERE / f"yardage_{course_id}.html",
                 load([src]), standalone=True, sat=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build one course's standalone yardage book.")
    ap.add_argument("--course", type=int, default=PILOT_COURSE_ID)
    ap.add_argument("--all", action="store_true", help="build every course_*.json on disk")
    ap.add_argument("--list", action="store_true", help="show which courses are ready to build")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if args.list:
        for p in scraped():
            name = json.loads(p.read_text(encoding="utf-8"))["name"]
            print(f"  {p.stem.split('_')[1]:>6}  {name}")
        return

    if args.all:
        for p in scraped():
            build_one(int(p.stem.split("_")[1]))
            print()
        return

    build_one(args.course, args.out)


if __name__ == "__main__":
    main()
