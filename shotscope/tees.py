#!/usr/bin/env python3
"""
tees.py
-------
Recovers the tee you actually played from the GPS fix on each hole's first shot
and folds it into course_<id>.json as `played_tees`.

Why this exists
    The tee boxes in the scraped mapping are centroids of the *whole* teeing
    ground, clustered out of a 128x128 lie raster. One raster blob can cover
    white, yellow and red markers at once, so the "back tee" the viewer shows
    can sit tens of metres from where you really teed off. Your watch, on the
    other hand, logged a fix at the exact spot — one per hole, per round.

    So: take shot 1 of every round, group the fixes by the tee colour recorded
    for that round, then nudge the result onto the mapped teeing ground (a GPS
    fix carries a few metres of error; the raster does not drift).

This runs entirely on the already-downloaded JSON — no login, no network.

Usage:
    python tees.py                        # pilot course, patch + report
    python tees.py --course 20561
    python tees.py --report-only          # show the deltas, write nothing
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
PILOT_COURSE_ID = 20625

M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LNG = 111_320.0

CLUSTER_R = 12.0   # m — tee cells this close to the fix vote on the final spot
SNAP_MAX = 25.0    # m — beyond this the raster is probably not the same tee


def meters_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat0 = math.radians((lat1 + lat2) / 2.0)
    dx = (lng2 - lng1) * M_PER_DEG_LNG * math.cos(lat0)
    dy = (lat2 - lat1) * M_PER_DEG_LAT
    return math.hypot(dx, dy)


def tee_cells(hole: dict) -> list[tuple[float, float]]:
    """Every grid cell the course mapping calls `tee`, as lat/lng."""
    b, n = hole["bounds"], hole["res"]
    cells = []
    for i, row in enumerate(hole["rows"]):
        lat = b["maxLat"] - (b["maxLat"] - b["minLat"]) * i / (n - 1)
        for j, code in enumerate(row):
            if code == "t":
                cells.append((lat, b["minLng"] + (b["maxLng"] - b["minLng"]) * j / (n - 1)))
    return cells


def refine(lat: float, lng: float, cells: list[tuple[float, float]]) -> tuple[float, float, str, float]:
    """Pull a GPS fix onto the mapped teeing ground. Returns (lat, lng, how, moved_m)."""
    if not cells:
        return lat, lng, "gps", 0.0

    near = [c for c in cells if meters_between(lat, lng, c[0], c[1]) <= CLUSTER_R]
    if near:
        clat = sum(c[0] for c in near) / len(near)
        clng = sum(c[1] for c in near) / len(near)
        return clat, clng, "tee-cluster", meters_between(lat, lng, clat, clng)

    best = min(cells, key=lambda c: meters_between(lat, lng, c[0], c[1]))
    d = meters_between(lat, lng, best[0], best[1])
    if d <= SNAP_MAX:
        return best[0], best[1], "nearest-cell", d
    return lat, lng, "gps", 0.0


def derive(course: dict) -> list[dict]:
    """Add `played_tees` to every hole. Returns one report row per hole/tee."""
    tee_name = {r["roundID"]: (r.get("tees") or "Played") for r in course.get("rounds", [])}
    report = []

    for h in course["holes"]:
        # `tee_boxes` measure to the green centre; `length_m` measures to the pin.
        # Carry both so nothing has to guess which reference it is looking at.
        green = h.get("green_center")
        aim = h.get("aim") or green
        cells = tee_cells(h)

        # One fix per round: the start of shot 1. Group rounds by tee colour.
        by_tee: dict[str, list[dict]] = defaultdict(list)
        for s in h.get("shots", []):
            if s.get("shot") != 1 or not s.get("startLat"):
                continue
            by_tee[tee_name.get(s.get("roundID"), "Played")].append(s)

        played = []
        for name, shots in sorted(by_tee.items()):
            raw_lat = sum(s["startLat"] for s in shots) / len(shots)
            raw_lng = sum(s["startLng"] for s in shots) / len(shots)
            lat, lng, how, moved = refine(raw_lat, raw_lng, cells)

            entry = {
                "name": name,
                "lat": lat,
                "lng": lng,
                "source": how,
                "fixes": len(shots),
                "gps_lat": raw_lat,
                "gps_lng": raw_lng,
                "snap_m": round(moved, 1),
                "rounds": [s.get("roundID") for s in shots],
                "lies": sorted({(s.get("lie") or "?") for s in shots}),
            }
            if green:
                entry["to_green_m"] = round(meters_between(lat, lng, green["lat"], green["lng"]), 1)
            if aim:
                entry["to_pin_m"] = round(meters_between(lat, lng, aim["lat"], aim["lng"]), 1)
            played.append(entry)

            # What the viewer used to show for this hole: the farthest mapped box.
            mapped = h["tee_boxes"][0] if h["tee_boxes"] else None
            nearest = min(
                h["tee_boxes"],
                key=lambda t: meters_between(lat, lng, t["lat"], t["lng"]),
                default=None,
            )
            report.append({
                "hole": h["num"],
                "par": h["par"],
                "tee": name,
                "source": how,
                "snap_m": round(moved, 1),
                "played_len": entry.get("to_green_m"),
                "mapped_len": mapped.get("to_green_m") if mapped else None,
                "off_mapped_m": round(
                    meters_between(lat, lng, mapped["lat"], mapped["lng"]), 1) if mapped else None,
                "off_nearest_m": round(
                    meters_between(lat, lng, nearest["lat"], nearest["lng"]), 1) if nearest else None,
                "nearest_idx": h["tee_boxes"].index(nearest) if nearest else None,
                "boxes": len(h["tee_boxes"]),
            })

        h["played_tees"] = played

    return report


def print_report(rows: list[dict], course: dict) -> None:
    print(f"\n{course['name']}  —  tee positions recovered from your tee shots\n")
    print(f"  {'#':>2}  {'par':>3}  {'tee':<8} {'played':>7} {'mapped':>7} {'delta':>6}  "
          f"{'moved':>6} {'off-box':>7}  source")
    print("  " + "-" * 74)
    for r in rows:
        delta = (r["played_len"] - r["mapped_len"]
                 if r["played_len"] is not None and r["mapped_len"] is not None else None)
        flag = "  <<" if delta is not None and abs(delta) >= 15 else ""
        print(f"  {r['hole']:>2}  {r['par']:>3}  {r['tee']:<8} "
              f"{r['played_len'] or 0:>7.1f} {r['mapped_len'] or 0:>7.1f} "
              f"{delta if delta is not None else 0:>+6.1f}  "
              f"{r['snap_m']:>6.1f} {r['off_mapped_m'] or 0:>7.1f}  {r['source']}{flag}")

    deltas = [r["played_len"] - r["mapped_len"] for r in rows
              if r["played_len"] is not None and r["mapped_len"] is not None]
    if deltas:
        print("  " + "-" * 74)
        print(f"  total played {sum(r['played_len'] for r in rows if r['played_len']):.0f} m   "
              f"vs mapped-back-tee {sum(r['mapped_len'] for r in rows if r['mapped_len']):.0f} m   "
              f"({sum(deltas):+.0f} m over {len(deltas)} holes)")
        print(f"  holes off by 15 m or more: "
              f"{sum(1 for d in deltas if abs(d) >= 15)}")
    print("\n  played  = green centre from your logged tee shot (same reference as `mapped`)")
    print("  mapped  = length from the farthest mapped tee box (what the viewer showed)")
    print("  moved   = how far the GPS fix was nudged onto the mapped teeing ground")
    print("  off-box = distance from your tee to that farthest mapped tee box\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Recover played tee positions from your tee shots.")
    ap.add_argument("--course", type=int, default=PILOT_COURSE_ID)
    ap.add_argument("--report-only", action="store_true", help="print the deltas, write nothing")
    args = ap.parse_args()

    src = HERE / f"course_{args.course}.json"
    if not src.exists():
        raise SystemExit(f"{src.name} not found — run:  python courses.py --course {args.course}")

    course = json.loads(src.read_text(encoding="utf-8"))
    rows = derive(course)
    print_report(rows, course)

    if args.report_only:
        print("  (--report-only: course JSON left untouched)")
        return

    # Each page is framed around the tee you played, so moving a tee moves the
    # page. Re-lay them here rather than leave a stale one on disk.
    from pages import derive as derive_pages
    derive_pages(course)

    src.write_text(json.dumps(course), encoding="utf-8")
    n = sum(len(h.get("played_tees", [])) for h in course["holes"])
    print(f"      ✓ {n} played tee(s) written to {src.name}, pages re-laid")
    print(f"\nNext:  python satellite.py --course {args.course}")


if __name__ == "__main__":
    main()
