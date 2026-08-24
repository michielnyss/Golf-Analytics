#!/usr/bin/env python3
"""
build_app.py
------------
Builds the multi-course app out of the same `viewer_template.html` the single
course book is built from: a searchable library of every course on disk, the
analysis dashboard, and the yardage viewer, in one page.

Two shapes come out of the same template, because a browser opened from disk
cannot fetch a sibling file and a web tool should not inline 2.5 MB per course:

    python build_app.py                 # app/  — index.html + data/*.json, served
    python build_app.py --serve         # …and serve it on localhost
    python build_app.py --standalone    # golfstats.html — one file, opens from disk

Served is the webtool shape: the page ships with a small manifest and pulls a
course's JSON when you pick it. Standalone bakes every course into the HTML,
the way `build_viewer.py` bakes one — no server, but the file grows with the
library.

The manifest carries the summary each library card shows (rounds, scoring,
putting, fairways, greens), so searching and browsing never waits on a 2.5 MB
download. The dashboard's own numbers are computed in the page from the course
JSON — this is only what you need before you have chosen a course.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# A Windows console defaults to cp1252, which cannot print a course name — let
# alone an arrow. Ask for UTF-8 and fall back to replacing what will not go.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
TEMPLATE = HERE / "viewer_template.html"
PLACEHOLDER = "/*__COURSE_DATA__*/null"

PUTTER = "Putter"


# ── Summary stats ─────────────────────────────────────────────────────────────
# Only what the library card and the search results need. The dashboard derives
# everything else in the page, from the course JSON it has loaded anyway.

def hole_rounds(course: dict):
    """Every (hole, round) the player actually played, shots in order."""
    for h in course["holes"]:
        by_round = defaultdict(list)
        for s in h["shots"]:
            by_round[s["roundID"]].append(s)
        for rid, shots in by_round.items():
            yield h, rid, sorted(shots, key=lambda s: s["shot"])


def hole_score(shots: list[dict]):
    """Strokes on the hole. Authoritative — a penalty makes it exceed len(shots)."""
    return next((s["score"] for s in shots if s.get("score") is not None), None)


def summarise(course: dict) -> dict:
    """The numbers a library card shows, per course and per round."""
    rounds = {r["roundID"]: r for r in course["rounds"]}
    acc = {rid: dict(holes=0, par=0, shots=0, putts=0, gir=0, gir_n=0, scr=0, scr_n=0,
                     fir_n=0)
           for rid in rounds}

    for h, rid, shots in hole_rounds(course):
        a = acc.get(rid)
        if a is None:                     # a round the scrape did not list
            continue
        sc = hole_score(shots)
        if sc is None:
            continue
        par = h["par"]
        a["holes"] += 1
        a["par"] += par
        a["shots"] += sc
        a["putts"] += sum(1 for s in shots if s["club"] == PUTTER)
        if par >= 4:
            a["fir_n"] += 1               # the holes a fairway can be hit on

        # Green in regulation: on the green with two strokes left for par. Derived
        # rather than read off the round, because it has to hold per hole too —
        # and it reproduces Shot Scope's own per-round figure exactly.
        reach = next((s["shot"] for s in shots if s.get("toLie") == "green"), None)
        a["gir_n"] += 1
        if reach is not None and reach <= par - 2:
            a["gir"] += 1
        else:
            # Scrambling: par or better after missing the green in regulation.
            a["scr_n"] += 1
            a["scr"] += 1 if sc <= par else 0

    # Fairways stay Shot Scope's own count. Its definition is not reproducible
    # from the exported fields (it drops tee shots ours keeps, and not only the
    # wedges), and the app should agree with the dashboard the data came from.
    # The percentage is hits/attempts, so the integer hit count comes back exact.
    per_round = []
    for rid, r in rounds.items():
        a = acc[rid]
        fir_n = a["fir_n"]
        per_round.append({
            "id": rid,
            "date": r["date"],
            "tees": r.get("tees"),
            "holes": a["holes"],
            "par": a["par"],
            "shots": a["shots"],
            "toPar": a["shots"] - a["par"],
            "putts": a["putts"],
            "gir": a["gir"], "girN": a["gir_n"],
            "scr": a["scr"], "scrN": a["scr_n"],
            "fir": round(r["fir"] * fir_n / 100) if r.get("fir") is not None else None,
            "firN": fir_n,
        })
    per_round.sort(key=lambda r: r["date"])

    played = [r for r in per_round if r["holes"]]
    tot = lambda k: sum(r[k] for r in played)
    rate = lambda k, n: round(100 * tot(k) / tot(n), 1) if tot(n) else None

    holes = tot("holes")
    return {
        "rounds": per_round,
        "stats": {
            # Not "rounds" — the entry already carries the round list under that
            # name, and the count is derivable from it.
            "roundCount": len(played),
            "holesPlayed": holes,
            "toPar": tot("shots") - tot("par"),
            # Per hole, because half these rounds are nine or fewer: a round
            # total would compare a front nine against a full eighteen.
            "toParPerHole": round((tot("shots") - tot("par")) / holes, 3) if holes else None,
            "puttsPerHole": round(tot("putts") / holes, 3) if holes else None,
            "fir": rate("fir", "firN"),
            "gir": rate("gir", "girN"),
            "scramble": rate("scr", "scrN"),
            "first": played[0]["date"] if played else None,
            "last": played[-1]["date"] if played else None,
            "best": min((r["toPar"] / r["holes"], r["date"]) for r in played)[1] if played else None,
        },
    }


def meta(course: dict, path: Path) -> dict:
    """One library entry: what the search matches on and the card shows."""
    s = summarise(course)
    card = course.get("card")
    played = sorted({t["name"] for h in course["holes"] for t in h.get("played_tees", [])})
    return {
        "id": course["courseID"],
        "name": course["name"],
        "file": path.name,
        "bytes": path.stat().st_size,
        "holes": len(course["holes"]),
        "par": sum(h["par"] for h in course["holes"]),
        "usingYards": course.get("usingYards", False),
        "player": course.get("player"),
        "hasCard": bool(card),
        "hasSat": bool(course.get("sat")) or any(h.get("sat") for h in course["holes"]),
        "tees": [t["name"] for t in card["tees"]] if card else played,
        "playedTees": played,
        "rounds": s["rounds"],
        **s["stats"],
    }


# ── Build ─────────────────────────────────────────────────────────────────────

def scraped() -> list[Path]:
    return sorted(HERE.glob("course_*.json"), key=lambda p: int(p.stem.split("_")[1]))


def load(paths: list[Path]) -> list[tuple[Path, dict]]:
    out = []
    for p in paths:
        out.append((p, json.loads(p.read_text(encoding="utf-8"))))
    return out


def strip_sat(course: dict) -> dict:
    """Drop the baked imagery — the analysis never draws it and it is the file."""
    lean = {k: v for k, v in course.items() if k != "sat"}
    lean["holes"] = [{k: v for k, v in h.items() if k != "sat"} for h in course["holes"]]
    return lean


def inject(payload: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit(f"Placeholder {PLACEHOLDER} missing from {TEMPLATE.name}")
    # `</script>` inside the payload would close the tag early; `<` is enough.
    blob = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")
    return template.replace(PLACEHOLDER, blob)


def build(out: Path, courses: list[tuple[Path, dict]], standalone: bool,
          sat: bool) -> Path:
    library = [meta(c, p) for p, c in courses]

    if standalone:
        page = out if out.suffix == ".html" else out / "golfstats.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(inject({
            "library": library,
            "courses": {str(c["courseID"]): (c if sat else strip_sat(c))
                        for _, c in courses},
        }), encoding="utf-8")
    else:
        out.mkdir(parents=True, exist_ok=True)
        data = out / "data"
        data.mkdir(exist_ok=True)
        for p, c in courses:
            if sat:
                shutil.copyfile(p, data / p.name)
            else:
                (data / p.name).write_text(
                    json.dumps(strip_sat(c), separators=(",", ":")), encoding="utf-8")
        (data / "index.json").write_text(json.dumps({
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "library": library,
        }, indent=1), encoding="utf-8")
        page = out / "index.html"
        page.write_text(inject({"library": library, "base": "data/"}), encoding="utf-8")

    for m in library:
        played = f"{m['holesPlayed']} holes over {m['roundCount']} rounds"
        print(f"  {m['id']:>6}  {m['name'][:44]:<44}  par {m['par']}  {played}")
    size = page.stat().st_size / 1e6
    print(f"\n  {len(library)} course{'s' if len(library) != 1 else ''} · "
          f"{page} ({size:.2f} MB){'' if sat else ' · imagery stripped'}")
    if not standalone:
        print(f"  serve it:  python -m http.server -d {out} 8000   →  "
              f"http://localhost:8000/")
    return page


def serve(root: Path, port: int) -> None:
    import functools
    import http.server
    import socketserver

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(root))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"\n  serving {root}  →  http://localhost:{port}/   (ctrl-c to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the multi-course app.")
    ap.add_argument("--out", type=Path, default=None,
                    help="output directory (served) or .html file (standalone)")
    ap.add_argument("--course", type=int, action="append",
                    help="limit the library to these course IDs (repeatable)")
    ap.add_argument("--standalone", action="store_true",
                    help="one self-contained HTML instead of a served directory")
    ap.add_argument("--no-sat", action="store_true",
                    help="leave the aerial imagery out — much smaller, map only loses satellite")
    ap.add_argument("--serve", type=int, nargs="?", const=8000, default=None,
                    metavar="PORT", help="serve the built directory (default port 8000)")
    ap.add_argument("--list", action="store_true", help="show which courses are on disk")
    args = ap.parse_args()

    paths = scraped()
    if not paths:
        raise SystemExit("No course_*.json on disk — run:  python courses.py --all-played")
    if args.course:
        want = set(args.course)
        paths = [p for p in paths if int(p.stem.split("_")[1]) in want]
        if not paths:
            raise SystemExit(f"None of {sorted(want)} scraped. On disk: "
                             + ", ".join(p.stem.split("_")[1] for p in scraped()))

    if args.list:
        for p, c in load(paths):
            print(f"  {c['courseID']:>6}  {c['name'][:50]:<50}  "
                  f"{len(c['rounds'])} rounds  {p.stat().st_size / 1e6:.1f} MB")
        return

    if args.serve is not None and args.standalone:
        raise SystemExit("--serve builds the served shape; drop --standalone")

    out = args.out or (HERE / "golfstats.html" if args.standalone else HERE / "app")
    page = build(out, load(paths), args.standalone, sat=not args.no_sat)

    if args.serve is not None:
        serve(page.parent, args.serve)


if __name__ == "__main__":
    main()
