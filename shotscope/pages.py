#!/usr/bin/env python3
"""
pages.py
--------
Works out the page each hole is drawn on and writes it into course_<id>.json as
`page` (+ `page_bounds`), so the viewer and the imagery fetcher agree on exactly
what a hole page covers.

Why this exists
    The viewer prints every hole on a card of one fixed shape, rotated so the
    tee is at the bottom and the green at the top. That card is bigger than the
    hole's own bounding box — and rotated relative to it — so imagery fetched
    for the bounding box leaves the corners of the card bare. Deciding the page
    here means `satellite.py` can fetch imagery that covers it and the viewer
    can draw the page without recomputing anything.

    The geometry has to match the viewer exactly, so this replicates its
    projection (equirectangular about the course centre) and its constants. If
    you change PAGE_AR or the corridor here, change it in viewer_template.html
    too — they are annotated on both sides.

This runs entirely on the already-downloaded JSON — no login, no network.
Run it after tees.py (the page frames the tee you played) and before
satellite.py (which needs the page to know what to fetch).

Usage:
    python pages.py                       # pilot course
    python pages.py --course 20561
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
PILOT_COURSE_ID = 20625

M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LNG = 111_320.0

# ── Must match viewer_template.html ────────────────────────────────────────────
PAGE_AR = 0.62          # width / height of every hole page
PAGE_PAD = 18           # m of air around the hole content
CORRIDOR_HALF = 85      # m either side of the tee->green line that counts as this hole
CORRIDOR_END = 45       # m behind the tee / past the green that still counts


class Frame:
    """The viewer's projection: metres east/south of the course centre."""

    def __init__(self, bounds: dict):
        self.lat0 = (bounds["minLat"] + bounds["maxLat"]) / 2
        self.lng0 = (bounds["minLng"] + bounds["maxLng"]) / 2
        self.cosl = math.cos(math.radians(self.lat0))

    def proj(self, lat: float, lng: float) -> tuple[float, float]:
        return ((lng - self.lng0) * M_PER_DEG_LNG * self.cosl,
                -(lat - self.lat0) * M_PER_DEG_LAT)

    def unproj(self, x: float, y: float) -> tuple[float, float]:
        return (self.lat0 - y / M_PER_DEG_LAT,
                self.lng0 + x / (M_PER_DEG_LNG * self.cosl))


def page_for(hole: dict, f: Frame) -> tuple[dict, dict]:
    """Return (page, page_bounds) for one hole."""
    tees = hole.get("tee_boxes") or []
    green = hole.get("green_center")

    # Play axis: mapped back tee -> green. Rotating by this points it up-screen.
    t_back = f.proj(tees[0]["lat"], tees[0]["lng"]) if tees else (0.0, 0.0)
    g = f.proj(green["lat"], green["lng"]) if green else t_back
    rot = -math.pi / 2 - math.atan2(g[1] - t_back[1], g[0] - t_back[0])
    c, s = math.cos(rot), math.sin(rot)

    def rotate(p): return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)
    def unrotate(r): return (r[0] * c + r[1] * s, -r[0] * s + r[1] * c)

    # Tees you can select, back tee first — same order as the viewer builds them,
    # so the corridor anchored on opts[0] is the same corridor on both sides.
    opts = [(t["lat"], t["lng"]) for t in (hole.get("card_tees") or [])]
    opts += [(t["lat"], t["lng"]) for t in (hole.get("played_tees") or [])]
    opts += [(t["lat"], t["lng"]) for t in tees]

    # Corridor: the band around the tee->green line that counts as this hole.
    corr = None
    if opts and green:
        t_r, g_r = rotate(f.proj(*opts[0])), rotate(g)
        corr = (t_r, g_r,
                min(t_r[1], g_r[1]) - CORRIDOR_END,
                max(t_r[1], g_r[1]) + CORRIDOR_END)

    def in_corridor(rx: float, ry: float) -> bool:
        if corr is None:
            return True
        t_r, g_r, lo, hi = corr
        if ry < lo or ry > hi:
            return False
        d = g_r[1] - t_r[1]
        u = 0.0 if d == 0 else max(0.0, min(1.0, (ry - t_r[1]) / d))
        return abs(rx - (t_r[0] + u * (g_r[0] - t_r[0]))) <= CORRIDOR_HALF

    x0 = y0 = math.inf
    x1 = y1 = -math.inf

    def grow(r):
        nonlocal x0, x1, y0, y1
        x0, x1 = min(x0, r[0]), max(x1, r[0])
        y0, y1 = min(y0, r[1]), max(y1, r[1])

    def add(lat, lng):
        grow(rotate(f.proj(lat, lng)))

    # Mapped hole content: every cell the mapping calls something but rough.
    b, n = hole["bounds"], hole["res"]
    for i, row in enumerate(hole["rows"]):
        lat = b["maxLat"] - (b["maxLat"] - b["minLat"]) * i / (n - 1)
        for j, code in enumerate(row):
            if code == "r":
                continue
            r = rotate(f.proj(lat, b["minLng"] + (b["maxLng"] - b["minLng"]) * j / (n - 1)))
            if in_corridor(*r):
                grow(r)

    # …plus anything the viewer draws that could sit outside it.
    for lat, lng in opts:
        add(lat, lng)
    for p in hole.get("pins") or []:
        add(p["lat"], p["lng"])
    for key in ("green_center", "aim"):
        if hole.get(key):
            add(hole[key]["lat"], hole[key]["lng"])
    for sh in hole.get("shots") or []:
        if sh.get("startLat"):
            add(sh["startLat"], sh["startLng"])
        if sh.get("endLat"):
            add(sh["endLat"], sh["endLng"])

    if not math.isfinite(x0):
        x0, x1, y0, y1 = -50.0, 50.0, -50.0, 50.0

    x0 -= PAGE_PAD; x1 += PAGE_PAD
    y0 -= PAGE_PAD; y1 += PAGE_PAD

    # Grow the deficient side to the fixed ratio — never crop, or a dogleg goes.
    w, h = x1 - x0, y1 - y0
    if w / h < PAGE_AR:
        air = (h * PAGE_AR - w) / 2
        x0 -= air; x1 += air
    else:
        air = (w / PAGE_AR - h) / 2
        y0 -= air; y1 += air

    page = {"rot": rot, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "w": x1 - x0, "h": y1 - y0}

    # The page is rotated, so its lat/lng box is the box around its four corners.
    corners = [f.unproj(*unrotate(r))
               for r in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    lats = [p[0] for p in corners]
    lngs = [p[1] for p in corners]
    bounds = {"minLat": min(lats), "maxLat": max(lats),
              "minLng": min(lngs), "maxLng": max(lngs)}
    return page, bounds


def derive(course: dict) -> list[dict]:
    """Add `page` and `page_bounds` to every hole. Returns one report row per hole."""
    f = Frame(course["bounds"])
    rows = []
    for h in course["holes"]:
        page, bounds = page_for(h, f)
        h["page"] = page
        h["page_bounds"] = bounds

        hb = h["bounds"]
        rows.append({
            "hole": h["num"],
            "page_w": page["w"],
            "page_h": page["h"],
            "rot_deg": math.degrees(page["rot"]) % 360,
            # How much more ground the page covers than the scraped hole box —
            # this is the imagery that used to be missing from the card corners.
            "extra": ((bounds["maxLat"] - bounds["minLat"]) * (bounds["maxLng"] - bounds["minLng"]))
                     / max(1e-12, (hb["maxLat"] - hb["minLat"]) * (hb["maxLng"] - hb["minLng"])),
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute each hole's page rectangle.")
    ap.add_argument("--course", type=int, default=PILOT_COURSE_ID)
    ap.add_argument("--report-only", action="store_true", help="print the pages, write nothing")
    args = ap.parse_args()

    src = HERE / f"course_{args.course}.json"
    if not src.exists():
        raise SystemExit(f"{src.name} not found — run:  python courses.py --course {args.course}")

    course = json.loads(src.read_text(encoding="utf-8"))
    rows = derive(course)

    print(f"\n{course['name']}  —  hole pages ({PAGE_AR} ratio)\n")
    print(f"  {'#':>2}  {'page w':>7} {'page h':>7}  {'rot':>6}   imagery vs hole box")
    print("  " + "-" * 52)
    for r in rows:
        print(f"  {r['hole']:>2}  {r['page_w']:>6.0f}m {r['page_h']:>6.0f}m  "
              f"{r['rot_deg']:>5.0f}°   ×{r['extra']:.2f}")
    print("  " + "-" * 52)
    print(f"  imagery area needed, on average: ×{sum(r['extra'] for r in rows) / len(rows):.2f}\n")

    if args.report_only:
        print("  (--report-only: course JSON left untouched)")
        return

    src.write_text(json.dumps(course), encoding="utf-8")
    print(f"      ✓ {len(rows)} pages written to {src.name}")
    print(f"\nNext:  python satellite.py --course {args.course}")


if __name__ == "__main__":
    main()
