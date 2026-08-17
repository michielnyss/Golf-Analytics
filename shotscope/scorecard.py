#!/usr/bin/env python3
"""
scorecard.py
------------
Folds the club's printed card — par, stroke index and every set of tee markers —
into course_<id>.json as `card` (course level) and `card_tees` / `si` per hole,
then works out where each set of markers actually stands on the ground.

Why this exists
    tees.py recovers one tee per hole: the spot your watch logged when you teed
    off, which is the set you played (Yellow here). The club plays four. The
    other three are never in your shot data, and the scraped mapping cannot tell
    them apart either — a 128x128 lie raster puts white, yellow, blue and red
    markers in one blob of `t` cells.

    The card does know: it prints every hole from every tee. So anchor on the tee
    you played — a real GPS fix, metres accurate — and step the *difference* in
    card length along the line the teeing grounds sit on. Where that lands on a
    mapped teeing-ground centroid, take the centroid; it is a surveyed shape and
    a better answer than a step along a line.

    Stepping the difference (not the absolute length) is what makes this work on
    a dogleg: a card measures 3, 8 and 10 along the playing line, so their card
    length is tens of metres longer than the straight tee->green distance. The
    difference between two tees on the same hole is the same either way, because
    both share the playing line from the corner onwards.

Distances are the card's own — printed, not measured — so what the viewer shows
matches what the starter's sheet says. The straight-line measurement is kept
alongside as `to_green_m` / `to_pin_m` for the rings and the HUD.

This runs entirely on the already-downloaded JSON — no login, no network.
Run it after tees.py (it anchors on the played tee) and before satellite.py
(the back tee moves the page, so imagery has to cover the new one).

Usage:
    python scorecard.py                        # pilot course, patch + report
    python scorecard.py --course 20625
    python scorecard.py --report-only          # show the fit, write nothing
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pages import Frame, derive as derive_pages

HERE = Path(__file__).parent
PILOT_COURSE_ID = 20625

M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LNG = 111_320.0

SNAP_BOX = 12.0    # m — a mapped teeing ground this close to the stepped point wins
MIN_SEP = 12.0     # m — but not the ground the anchor itself stands on
CELL_R = 9.0       # m — otherwise vote with the tee cells within this radius
CELL_MAX = 10.0    # m — and never let that move the point further than this
AXIS_TOL = 0.80    # cos — reject a tee-box line more than ~37° off tee->green

# The card's length is the one number here that is not an estimate, and it is a
# distance *along* the tee line. So the raster may move a tee sideways onto the
# teeing ground it belongs on — markers sit off the centre line all the time —
# but it may not move it up or down that line by more than this, because that is
# the part the card already told us.
ALONG_MAX = 6.0    # m


# ── The printed cards ──────────────────────────────────────────────────────────
# One entry per course. `tees` are in card order, which is also longest first.
# `holes` rows are: hole, par, stroke index, then one length per tee set, metres.
CARDS: dict[int, dict] = {
    20625: {
        "name": "Flanders Nippon Golf & Business Club — Championship",
        "units": "m",
        # The number the card prints beside each colour, kept verbatim.
        "tees": [
            {"name": "White",  "code": 60},
            {"name": "Yellow", "code": 54},
            {"name": "Blue",   "code": 51},
            {"name": "Red",    "code": 48},
        ],
        "holes": [
            #
            (1,  4, 10, 355, 331, 304, 294),
            (2,  4, 18, 275, 262, 243, 238),
            (3,  4,  2, 393, 334, 296, 291),
            (4,  3, 16, 129, 123, 118, 113),
            (5,  4,  6, 324, 279, 261, 245),
            (6,  5,  8, 479, 438, 428, 420),
            (7,  3, 14, 149, 137, 125, 109),
            (8,  5,  4, 471, 450, 432, 420),
            (9,  4, 12, 346, 289, 282, 263),
            (10, 5,  9, 501, 473, 430, 405),
            (11, 4,  1, 372, 340, 315, 290),
            (12, 3, 17, 144, 135, 132, 127),
            (13, 4, 15, 332, 312, 301, 261),
            (14, 4,  7, 336, 309, 303, 268),
            (15, 4,  3, 398, 329, 283, 281),
            (16, 4,  5, 346, 300, 287, 268),
            (17, 3, 13, 194, 157, 148, 130),
            (18, 5, 11, 488, 468, 459, 427),
        ],
        # Printed subtotals — asserted against the rows so a typo cannot slip in.
        "totals": {
            "out": {"par": 36, "White": 2921, "Yellow": 2643, "Blue": 2489, "Red": 2393},
            "in":  {"par": 36, "White": 3111, "Yellow": 2823, "Blue": 2658, "Red": 2457},
            "all": {"par": 72, "White": 6032, "Yellow": 5466, "Blue": 5147, "Red": 4850},
        },
    },
}


def card_for(course_id: int) -> dict:
    card = CARDS.get(course_id)
    if card is None:
        raise SystemExit(
            f"No printed card on file for course {course_id}.\n"
            f"  Add one to CARDS in {Path(__file__).name} — hole, par, stroke index, "
            f"then one length per tee set."
        )
    return card


def rows_of(card: dict) -> dict[int, dict]:
    """Card rows keyed by hole number, with the lengths as {tee name: metres}."""
    names = [t["name"] for t in card["tees"]]
    out = {}
    for row in card["holes"]:
        num, par, si, *lens = row
        if len(lens) != len(names):
            raise SystemExit(f"hole {num}: {len(lens)} lengths for {len(names)} tee sets")
        out[num] = {"par": par, "si": si, "len": dict(zip(names, lens))}
    return out


def check_totals(card: dict, rows: dict[int, dict]) -> None:
    """The card prints OUT / IN / TOTAL; make the rows add up to them."""
    spans = {"out": range(1, 10), "in": range(10, 19), "all": range(1, 19)}
    for key, span in spans.items():
        want = card["totals"].get(key)
        if not want:
            continue
        got = {"par": sum(rows[n]["par"] for n in span)}
        for name in (t["name"] for t in card["tees"]):
            got[name] = sum(rows[n]["len"][name] for n in span)
        for k, v in want.items():
            if got[k] != v:
                raise SystemExit(f"card {key.upper()} {k}: rows add to {got[k]}, card says {v}")


# ── Geometry ───────────────────────────────────────────────────────────────────

def norm(v: tuple[float, float]) -> tuple[float, float]:
    n = math.hypot(*v) or 1.0
    return (v[0] / n, v[1] / n)


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def tee_cells(hole: dict) -> list[tuple[float, float]]:
    """Every grid cell the mapping calls `tee`, projected — same set tees.py uses."""
    b, n = hole["bounds"], hole["res"]
    cells = []
    for i, row in enumerate(hole["rows"]):
        lat = b["maxLat"] - (b["maxLat"] - b["minLat"]) * i / (n - 1)
        for j, code in enumerate(row):
            if code == "t":
                cells.append((lat, b["minLng"] + (b["maxLng"] - b["minLng"]) * j / (n - 1)))
    return cells


def tee_line(boxes: list[tuple[float, float]], weights: list[float],
             back: tuple[float, float]) -> tuple[tuple[float, float], str]:
    """Unit vector pointing away from the green, along the teeing grounds' own line.

    Tee boxes on a hole are laid out along the initial play direction, which is
    what a card's lengths step along. On a dogleg that is not the tee->green
    line, so prefer the boxes when there are at least two of them — and fall back
    to `back` (tee->green, reversed) when they disagree with it wildly, which
    means the blobs were not really one line of tees.
    """
    if len(boxes) < 2:
        return back, "tee->green"

    wsum = sum(weights) or 1.0
    cx = sum(p[0] * w for p, w in zip(boxes, weights)) / wsum
    cy = sum(p[1] * w for p, w in zip(boxes, weights)) / wsum

    # Weighted principal axis of the centroids: the line they best sit on.
    sxx = sum(w * (p[0] - cx) ** 2 for p, w in zip(boxes, weights))
    syy = sum(w * (p[1] - cy) ** 2 for p, w in zip(boxes, weights))
    sxy = sum(w * (p[0] - cx) * (p[1] - cy) for p, w in zip(boxes, weights))
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    u = (math.cos(theta), math.sin(theta))

    if u[0] * back[0] + u[1] * back[1] < 0:          # point it away from the green
        u = (-u[0], -u[1])
    if u[0] * back[0] + u[1] * back[1] < AXIS_TOL:
        return back, "tee->green"
    return u, "tee-boxes"


def refine(cand: tuple[float, float], cells: list[tuple[float, float]],
           u: tuple[float, float]) -> tuple[tuple[float, float], float]:
    """Nudge a stepped point sideways onto the mapped teeing ground next to it.

    Only the component across the tee line is taken: the component along it is
    the card's own length, which the raster has no business overruling.
    """
    near = [c for c in cells if dist(cand, c) <= CELL_R]
    if not near:
        return cand, 0.0
    cx = sum(p[0] for p in near) / len(near)
    cy = sum(p[1] for p in near) / len(near)
    dx, dy = cx - cand[0], cy - cand[1]
    along = dx * u[0] + dy * u[1]
    dx, dy = dx - along * u[0], dy - along * u[1]     # keep the lateral part only
    moved = math.hypot(dx, dy)
    if moved > CELL_MAX or moved < 0.05:
        return cand, 0.0
    return (cand[0] + dx, cand[1] + dy), moved


def place(hole: dict, row: dict, names: list[str], f: Frame) -> tuple[list[dict], dict]:
    """Position every tee set on one hole. Returns (card_tees, report row)."""
    green = hole.get("green_center")
    aim = hole.get("aim") or green
    gp = f.proj(green["lat"], green["lng"]) if green else (0.0, 0.0)
    ap = f.proj(aim["lat"], aim["lng"]) if aim else gp

    # Anchor: the tee you played, if the card knows that colour. Otherwise the
    # farthest mapped teeing ground, read as the back (longest) set on the card.
    played = {t["name"]: t for t in (hole.get("played_tees") or [])}
    anchor_name = next((n for n in names if n in played), None)
    if anchor_name:
        src = played[anchor_name]
        anchor = f.proj(src["lat"], src["lng"])
        anchor_src = "played"
    else:
        boxes = hole.get("tee_boxes") or []
        if not boxes:
            return [], {"hole": hole["num"], "anchor": None, "tees": []}
        anchor_name = names[0]
        src = boxes[0]
        anchor = f.proj(src["lat"], src["lng"])
        anchor_src = "mapped"

    d_anchor = row["len"][anchor_name]

    boxes = hole.get("tee_boxes") or []
    bp = [f.proj(b["lat"], b["lng"]) for b in boxes]
    u, axis_src = tee_line(bp, [float(b.get("cells", 1)) for b in boxes],
                           norm((anchor[0] - gp[0], anchor[1] - gp[1])))
    cells = [f.proj(*c) for c in tee_cells(hole)]

    # Step the card's difference along that line, from the tee you stood on.
    cand = {
        n: anchor if n == anchor_name
        else (anchor[0] + u[0] * (row["len"][n] - d_anchor),
              anchor[1] + u[1] * (row["len"][n] - d_anchor))
        for n in names
    }

    # A mapped teeing ground next to a stepped point beats the point: it is a
    # surveyed shape, not a step along a line. Conditions, in order: the hole has
    # to have more than one mapped ground at all (a hole mapped as a single blob
    # has one centroid covering every colour, so claiming it would collapse the
    # set onto one spot); it cannot be the ground the anchor is standing on; it
    # has to be close; and it may not disagree with the card along the tee line.
    def claim_ok(n: str, p: tuple[float, float]) -> bool:
        d = dist(cand[n], p)
        along = (p[0] - cand[n][0]) * u[0] + (p[1] - cand[n][1]) * u[1]
        return d <= SNAP_BOX and abs(along) <= ALONG_MAX and dist(anchor, p) >= MIN_SEP

    claims = sorted(
        (dist(cand[n], p), n, k)
        for n in names if n != anchor_name
        for k, p in enumerate(bp)
        if len(bp) > 1 and claim_ok(n, p)
    )
    taken_box: set[int] = set()
    snapped: dict[str, int] = {}
    for _, n, k in claims:
        if n not in snapped and k not in taken_box:
            snapped[n] = k
            taken_box.add(k)

    out, report_tees = [], []
    for n in names:
        p, moved = cand[n], 0.0
        if n == anchor_name:
            how = f"anchor/{anchor_src}"
        elif n in snapped:
            p, how = bp[snapped[n]], "mapped-box"
            moved = dist(cand[n], p)
        else:
            p, moved = refine(cand[n], cells, u)
            how = "tee-cells" if moved else "stepped"

        lat, lng = f.unproj(*p)
        entry = {
            "name": n,
            "lat": lat,
            "lng": lng,
            "card_m": row["len"][n],
            "delta_m": row["len"][n] - d_anchor,
            "source": how,
            "axis": axis_src,
            "snap_m": round(moved, 1),
            "played": n == anchor_name and anchor_src == "played",
            "to_green_m": round(dist(p, gp), 1),
            "to_pin_m": round(dist(p, ap), 1),
        }
        if entry["played"]:
            for k in ("fixes", "rounds", "gps_lat", "gps_lng"):
                if k in played[anchor_name]:
                    entry[k] = played[anchor_name][k]
        out.append(entry)
        report_tees.append(entry)

    # Longest first, so the back tee anchors the page corridor in pages.py and
    # the same option leads the list in the viewer.
    out.sort(key=lambda t: -t["card_m"])
    return out, {"hole": hole["num"], "anchor": anchor_name, "tees": report_tees}


# ── Patch ──────────────────────────────────────────────────────────────────────

def derive(course: dict) -> list[dict]:
    """Add `card`, `si` and `card_tees`. Returns one report row per hole."""
    card = card_for(course["courseID"])
    rows = rows_of(card)
    check_totals(card, rows)
    names = [t["name"] for t in card["tees"]]

    f = Frame(course["bounds"])
    report = []
    for h in course["holes"]:
        row = rows.get(h["num"])
        if row is None:
            continue
        if row["par"] != h["par"]:
            print(f"  ! hole {h['num']}: card says par {row['par']}, "
                  f"Shot Scope says par {h['par']} — keeping the card's")
        h["par"] = row["par"]
        h["si"] = row["si"]
        h["card_len"] = dict(row["len"])
        tees, rep = place(h, row, names, f)
        h["card_tees"] = tees
        report.append(rep)

    course["card"] = {
        "name": card.get("name", course["name"]),
        "units": card.get("units", "m"),
        "tees": [dict(t, total=sum(rows[n]["len"][t["name"]] for n in rows)) for t in card["tees"]],
        "totals": card["totals"],
        "par": sum(r["par"] for r in rows.values()),
    }
    return report


def print_report(report: list[dict], course: dict) -> None:
    card = course["card"]
    names = [t["name"] for t in card["tees"]]
    print(f"\n{card['name']}  —  {len(names)} tee sets placed from the printed card\n")
    print(f"  {'#':>2}  {'tee':<7} {'card':>5} {'delta':>6} {'straight':>9} {'gap':>6}  source")
    print("  " + "-" * 62)
    for rep in report:
        for t in rep["tees"]:
            # `gap` is card length minus the straight line: the dogleg, plus the
            # slack between the mapped green centre and where the card measures to.
            gap = t["card_m"] - t["to_green_m"]
            snap = f" +{t['snap_m']:.0f}m" if t["snap_m"] else ""
            print(f"  {rep['hole']:>2}  {t['name']:<7} {t['card_m']:>5} {t['delta_m']:>+6} "
                  f"{t['to_green_m']:>9.1f} {gap:>+6.1f}  {t['source']}{snap}")
        print("  " + "·" * 62)

    on_box = sum(1 for r in report for t in r["tees"] if t["source"] == "mapped-box")
    on_cells = sum(1 for r in report for t in r["tees"] if t["source"] == "tee-cells")
    stepped = sum(1 for r in report for t in r["tees"] if t["source"] == "stepped")
    anchors = sum(1 for r in report for t in r["tees"] if t["source"].startswith("anchor"))
    total = on_box + on_cells + stepped + anchors
    print(f"\n  {total} tees: {anchors} anchored on your tee shots, {on_box} on a mapped "
          f"teeing ground,\n  {on_cells} nudged onto tee cells, {stepped} stepped along the tee line.")
    print("\n  card     = the length the club prints for that tee")
    print("  delta    = how far behind/ahead of the tee you played it sits")
    print("  straight = mapped-green-centre distance from the placed tee (for the rings)")
    print("  gap      = card minus straight: the dogleg the card measures around\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fold the printed scorecard into a course JSON.")
    ap.add_argument("--course", type=int, default=PILOT_COURSE_ID)
    ap.add_argument("--report-only", action="store_true", help="print the fit, write nothing")
    args = ap.parse_args()

    src = HERE / f"course_{args.course}.json"
    if not src.exists():
        raise SystemExit(f"{src.name} not found — run:  python courses.py --course {args.course}")

    course = json.loads(src.read_text(encoding="utf-8"))
    report = derive(course)
    print_report(report, course)

    if args.report_only:
        print("  (--report-only: course JSON left untouched)")
        return

    # The back tee now sits behind the one you played, so the page that frames the
    # hole has to grow to hold it. Re-lay the pages rather than leave a stale one.
    derive_pages(course)

    src.write_text(json.dumps(course), encoding="utf-8")
    n = sum(len(h.get("card_tees", [])) for h in course["holes"])
    print(f"      ✓ {n} card tees + stroke indexes written to {src.name}, pages re-laid")
    print(f"\nNext:  python satellite.py --course {args.course}   (the pages moved)")
    print(f"       python build_viewer.py --course {args.course}")


if __name__ == "__main__":
    main()
