#!/usr/bin/env python3
"""
build_viewer.py
---------------
Injects a scraped course JSON into viewer_template.html and writes a single
self-contained page you can open straight from disk.

Usage:
    python build_viewer.py                    # pilot course, metric
    python build_viewer.py --course 20561
    python build_viewer.py --all              # every course_*.json on disk
    python build_viewer.py --out yardage.html
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATE = HERE / "viewer_template.html"
PLACEHOLDER = "/*__COURSE_DATA__*/null"
PILOT_COURSE_ID = 20625


def scraped() -> list[int]:
    """Course IDs already pulled to disk, ready to build without any network."""
    return sorted(int(p.stem.split("_")[1]) for p in HERE.glob("course_*.json"))


def build(course_id: int, out: Path | None = None) -> Path:
    src = HERE / f"course_{course_id}.json"
    if not src.exists():
        have = scraped()
        raise SystemExit(
            f"{src.name} not found — run:  python courses.py --course {course_id}\n"
            + (f"  already scraped: {', '.join(map(str, have))}\n" if have else "")
            + "  to see which courses you have played:  python courses.py --list"
        )

    course = json.loads(src.read_text(encoding="utf-8"))
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit(f"Placeholder {PLACEHOLDER} missing from {TEMPLATE.name}")

    # `</script>` inside the payload would close the tag early; `<` is enough to break it.
    payload = json.dumps(course, separators=(",", ":")).replace("<", "\\u003c")
    html = template.replace(PLACEHOLDER, payload)

    out = out or HERE / f"yardage_{course_id}.html"
    out.write_text(html, encoding="utf-8")

    sat = sum(1 for h in course["holes"] if h.get("sat"))
    played = {t["name"] for h in course["holes"] for t in h.get("played_tees", [])}
    card = course.get("card")
    if card:
        unit = card.get("units", "m")
        tees = ", ".join(f"{t['name']} {t['total']}{unit}" for t in card["tees"])
    else:
        tees = ", ".join(sorted(played)) + " (played only — run python scorecard.py)" \
            if played else "mapped only — run python tees.py"
    print(f"  course   {course['name']}")
    print(f"  holes    {len(course['holes'])}  ({sat} with satellite imagery)")
    print(f"  shots    {sum(len(h['shots']) for h in course['holes'])}")
    print(f"  tees     {tees}")
    if card:
        si = sum(1 for h in course["holes"] if h.get("si") is not None)
        print(f"  card     par {card['par']} · stroke index on {si}/{len(course['holes'])} holes")
    print(f"  output   {out}  ({out.stat().st_size / 1e6:.2f} MB)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the standalone yardage-book page.")
    ap.add_argument("--course", type=int, default=PILOT_COURSE_ID)
    ap.add_argument("--all", action="store_true", help="build every course_*.json on disk")
    ap.add_argument("--list", action="store_true", help="show which courses are ready to build")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if args.list:
        for cid in scraped():
            name = json.loads((HERE / f"course_{cid}.json").read_text(encoding="utf-8"))["name"]
            print(f"  {cid:>6}  {name}")
        return

    if args.all:
        for cid in scraped():
            build(cid)
            print()
        return

    build(args.course, args.out)


if __name__ == "__main__":
    main()
