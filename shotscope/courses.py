#!/usr/bin/env python3
"""
courses.py
----------
Pulls everything Shot Scope knows about a golf course and writes it to JSON.

For each hole it grid-samples the private `CourseInfo/LieMulti` endpoint to
reconstruct the course mapping (tee / fairway / green / bunker / rough / water),
then folds in the pin positions and shots from every round you have played there.

Outputs (next to this script):
    course_<courseID>.json      full course model + your rounds on it
    courses_catalog.json        global course list (only with --catalog)

Usage:
    python courses.py                     # pilot: Flanders Nippon Championship
    python courses.py --course 20561      # a different course you have played
    python courses.py --all-played        # every course in your history
    python courses.py --list              # show which courses you have played
    python courses.py --catalog           # also dump the 42k global catalog
    python courses.py --res 96            # coarser/faster grid (default 128)

Dependencies:  pip install playwright python-dotenv  &&  playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from pages import derive as derive_pages
from scorecard import CARDS, derive as derive_card
from tees import derive as derive_played_tees

# ── Config ─────────────────────────────────────────────────────────────────────

HERE = Path(__file__).parent
ENV_FILE = HERE / ".env"

BASE_URL = "https://dashboard.shotscope.com"
ROUNDS_API = "/api/rounds/slim?modifiedSinceDate=2000-01-01T00:00:00.000Z"
CATALOG_API = "/api/v2/courses/availablecourses/completev5"
LIE_MULTI_API = "/api/CourseInfo/LieMulti"

PILOT_COURSE_ID = 20625          # Flanders Nippon Golf & Business Club Championship

GRID_RES = 128                   # samples per axis, per hole
CHUNK = 4096                     # points per LieMulti request (verified safe)
THROTTLE_S = 0.4                 # pause between requests — be a good citizen
MAX_RETRIES = 3

# Single-character codes used in the exported raster.
LIE_CODES = {
    "tee": "t",
    "fairway": "f",
    "green": "g",
    "bunker": "b",
    "rough": "r",
    "water": "w",
    "hazard": "w",
    "penalty": "w",
    "path": "p",
    "trees": "x",
    "tree": "x",
    "recovery": "x",
    "unknown": "r",
}
FALLBACK_CODE = "r"

# Metres per degree at mid-latitudes; good to ~0.1% over a golf course.
M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LNG = 111_320.0


# ── Geometry helpers ───────────────────────────────────────────────────────────

def meters_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Equirectangular distance in metres — exact enough at golf-course scale."""
    lat0 = math.radians((lat1 + lat2) / 2.0)
    dx = (lng2 - lng1) * M_PER_DEG_LNG * math.cos(lat0)
    dy = (lat2 - lat1) * M_PER_DEG_LAT
    return math.hypot(dx, dy)


def centroid(points: list[tuple[float, float]]) -> dict | None:
    """Mean lat/lng of a cluster of grid cells."""
    if not points:
        return None
    return {
        "lat": sum(p[0] for p in points) / len(points),
        "lng": sum(p[1] for p in points) / len(points),
    }


def cluster_cells(cells: list[tuple[int, int]], max_gap: int = 2) -> list[list[tuple[int, int]]]:
    """Flood-fill grid cells into connected blobs (used to split tee boxes / bunkers)."""
    remaining = set(cells)
    blobs: list[list[tuple[int, int]]] = []
    while remaining:
        seed = remaining.pop()
        blob, queue = [seed], [seed]
        while queue:
            ci, cj = queue.pop()
            for di in range(-max_gap, max_gap + 1):
                for dj in range(-max_gap, max_gap + 1):
                    nb = (ci + di, cj + dj)
                    if nb in remaining:
                        remaining.discard(nb)
                        blob.append(nb)
                        queue.append(nb)
        blobs.append(blob)
    return sorted(blobs, key=len, reverse=True)


# ── Browser session ────────────────────────────────────────────────────────────

class ShotScope:
    """A logged-in dashboard page; every fetch runs in-page so cookies just work."""

    def __init__(self, page):
        self.page = page

    @staticmethod
    def login(page, email: str, password: str) -> "ShotScope":
        print(f"[auth] opening {BASE_URL}")
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2_500)

        if re.search(r"/(login|signin|auth|account)", page.url, re.I):
            page.wait_for_selector("input[type='password']", timeout=30_000)
            page.locator("input[type='email'], input[type='text']").first.fill(email)
            page.locator("input[type='password']").first.fill(password)
            page.locator("button[type='submit']").first.click()
            for _ in range(90):
                page.wait_for_timeout(1_000)
                if not re.search(r"/(login|signin|auth|account)", page.url, re.I):
                    break
            else:
                raise TimeoutError("Login did not complete — check SHOTSCOPE_* in .env")

        page.wait_for_timeout(5_000)
        print(f"[auth] logged in -> {page.url}")
        return ShotScope(page)

    def get_json(self, path: str):
        return self.page.evaluate(
            """async (p) => {
                const r = await fetch(p, {credentials: 'include'});
                if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + p);
                return r.json();
            }""",
            path,
        )

    def lie_multi(self, course_id: int, hole_id: int, points: list[dict]) -> list[str]:
        """POST a batch of coordinates, get one lie string back per point."""
        raw = self.page.evaluate(
            """async ([url, body]) => {
                const r = await fetch(url, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body),
                });
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            }""",
            [LIE_MULTI_API, {"courseID": course_id, "holeID": hole_id, "shots": points}],
        )
        # The endpoint answers with a list-of-lists (one entry per input shot,
        # each holding the lies sampled along that shot). Ours are single points.
        flat: list[str] = []
        for item in raw:
            flat.extend(item) if isinstance(item, list) else flat.append(item)
        return flat


# ── Course reconstruction ──────────────────────────────────────────────────────

def sample_hole(ss: ShotScope, course_id: int, hole: dict, res: int) -> dict:
    """Grid-sample one hole's bounding box and return a raster of lie codes."""
    lat_hi, lat_lo = hole["maxLat"], hole["minLat"]
    lng_lo, lng_hi = hole["minLng"], hole["maxLng"]

    # Pad the bounding box slightly — Shot Scope's boxes hug the played corridor.
    pad_lat = (lat_hi - lat_lo) * 0.06
    pad_lng = (lng_hi - lng_lo) * 0.06
    lat_hi, lat_lo = lat_hi + pad_lat, lat_lo - pad_lat
    lng_lo, lng_hi = lng_lo - pad_lng, lng_hi + pad_lng

    # Row 0 is the northern edge, so the raster reads like a north-up map.
    points = [
        {
            "startLat": lat_hi - (lat_hi - lat_lo) * i / (res - 1),
            "startLng": lng_lo + (lng_hi - lng_lo) * j / (res - 1),
        }
        for i in range(res)
        for j in range(res)
    ]

    lies: list[str] = []
    for start in range(0, len(points), CHUNK):
        batch = points[start:start + CHUNK]
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                lies.extend(ss.lie_multi(course_id, hole["id"], batch))
                break
            except Exception as exc:
                if attempt == MAX_RETRIES:
                    raise
                wait = 2 ** attempt
                print(f"        retry {attempt}/{MAX_RETRIES} after {exc} (waiting {wait}s)")
                time.sleep(wait)
        time.sleep(THROTTLE_S)
        print(f"        sampled {min(start + CHUNK, len(points))}/{len(points)}", end="\r")

    if len(lies) != len(points):
        print(f"      ! expected {len(points)} lies, got {len(lies)} — padding with rough")
        lies += ["rough"] * (len(points) - len(lies))

    vocab = Counter(x.lower() for x in lies)
    codes = [LIE_CODES.get(x.lower(), FALLBACK_CODE) for x in lies]
    rows = ["".join(codes[i * res:(i + 1) * res]) for i in range(res)]

    def cell_latlng(i: int, j: int) -> tuple[float, float]:
        return (
            lat_hi - (lat_hi - lat_lo) * i / (res - 1),
            lng_lo + (lng_hi - lng_lo) * j / (res - 1),
        )

    def cells_of(code: str) -> list[tuple[int, int]]:
        return [(i, j) for i in range(res) for j in range(res) if rows[i][j] == code]

    green_cells = cells_of("g")
    tee_cells = cells_of("t")
    bunker_cells = cells_of("b")

    green_center = centroid([cell_latlng(i, j) for i, j in green_cells])

    # A hole can have several tee boxes; keep them separate, farthest one first.
    tee_boxes = []
    for blob in cluster_cells(tee_cells)[:6]:
        if len(blob) < 3:
            continue
        c = centroid([cell_latlng(i, j) for i, j in blob])
        if c and green_center:
            c["to_green_m"] = round(
                meters_between(c["lat"], c["lng"], green_center["lat"], green_center["lng"]), 1
            )
        c["cells"] = len(blob)
        tee_boxes.append(c)
    tee_boxes.sort(key=lambda t: t.get("to_green_m", 0), reverse=True)

    bunkers = []
    for blob in cluster_cells(bunker_cells):
        if len(blob) < 3:
            continue
        c = centroid([cell_latlng(i, j) for i, j in blob])
        c["cells"] = len(blob)
        if green_center:
            c["to_green_m"] = round(
                meters_between(c["lat"], c["lng"], green_center["lat"], green_center["lng"]), 1
            )
        bunkers.append(c)

    return {
        "res": res,
        "bounds": {"minLat": lat_lo, "maxLat": lat_hi, "minLng": lng_lo, "maxLng": lng_hi},
        "rows": rows,
        "vocab": dict(vocab),
        "green_center": green_center,
        "tee_boxes": tee_boxes,
        "bunkers": bunkers,
    }


def collect_play(data: dict, course_id: int) -> tuple[dict, list[dict]]:
    """Gather pins and shots per hole number across every round on this course."""
    clubs = data.get("clubs", [])
    id_key = next((k for k in ("clubID", "id", "clubId") if clubs and k in clubs[0]), None)
    club_map = {c[id_key]: c for c in clubs} if id_key else {}

    per_hole: dict[int, dict] = {}
    rounds_meta: list[dict] = []

    for r in data.get("rounds", []):
        if r.get("courseID") != course_id and r.get("secondCourseID") != course_id:
            continue

        rounds_meta.append({
            "roundID": r.get("roundID"),
            "date": str(r.get("startedDate", ""))[:10],
            "tees": r.get("tees"),
            "totalShots": r.get("totalShots"),
            "totalPar": r.get("totalPar"),
            "score": r.get("roundScore"),
            "putts": r.get("putts"),
            "fir": r.get("fairwaysInRegulation"),
            "gir": r.get("greensInRegulation"),
        })

        for hole in r.get("holes", []):
            num = hole.get("holeNum")
            if num is None:
                continue
            slot = per_hole.setdefault(num, {"pins": [], "shots": []})

            pin = hole.get("pin") or {}
            if pin.get("lat"):
                slot["pins"].append({
                    "lat": pin["lat"],
                    "lng": pin["lng"],
                    "date": str(pin.get("dateTime", ""))[:10],
                    "roundID": r.get("roundID"),
                })

            for s in hole.get("shots", []):
                if s.get("startLat") in (None, 0):
                    continue
                club = club_map.get(s.get("clubID"), {})
                slot["shots"].append({
                    "roundID": r.get("roundID"),
                    "date": str(r.get("startedDate", ""))[:10],
                    "shot": s.get("shotNumber"),
                    "club": club.get("name") or s.get("clubName") or "Unknown",
                    "club_short": club.get("shortName") or "",
                    "startLat": s.get("startLat"),
                    "startLng": s.get("startLng"),
                    "endLat": s.get("endLat"),
                    "endLng": s.get("endLng"),
                    "distance_m": s.get("distance"),
                    "lie": s.get("lie"),
                    "toLie": s.get("toLie"),
                    "strokeType": s.get("strokeType"),
                    "distanceToPin": s.get("distanceToPin"),
                    "score": hole.get("score"),
                })

    return per_hole, rounds_meta


def build_course(ss: ShotScope, data: dict, course_id: int, res: int) -> dict:
    """Assemble the complete model for one course."""
    info = next((c for c in data.get("courseInfos", []) if c.get("id") == course_id), None)
    if info is None:
        raise SystemExit(
            f"Course {course_id} is not in your history — "
            f"available: {[c['id'] for c in data.get('courseInfos', [])]}"
        )

    name = next(
        (r.get("courseName") for r in data.get("rounds", []) if r.get("courseID") == course_id),
        f"Course {course_id}",
    )
    per_hole, rounds_meta = collect_play(data, course_id)

    print(f"\n[course] {name}  (id {course_id}, {info.get('holes')} holes)")
    print(f"[course] {len(rounds_meta)} round(s) played here")
    print(f"[course] grid {res}x{res} = {res * res:,} samples per hole\n")

    holes = []
    details = info.get("holeDetails", [])
    for n, hole in enumerate(details, 1):
        print(f"  hole {hole['num']:>2} (par {hole['par']})  id={hole['id']}   [{n}/{len(details)}]")
        grid = sample_hole(ss, course_id, hole, res)
        play = per_hole.get(hole["num"], {"pins": [], "shots": []})

        # Prefer the real pin as the aim point; fall back to the mapped green centre.
        pins = play["pins"]
        pin_center = centroid([(p["lat"], p["lng"]) for p in pins]) if pins else None
        aim = pin_center or grid["green_center"]

        tee = grid["tee_boxes"][0] if grid["tee_boxes"] else None
        length = None
        if tee and aim:
            length = round(meters_between(tee["lat"], tee["lng"], aim["lat"], aim["lng"]), 1)

        v = grid["vocab"]
        print(f"        {dict(sorted(v.items(), key=lambda kv: -kv[1]))}")
        print(f"        length ~{length} m   tees={len(grid['tee_boxes'])}  "
              f"bunkers={len(grid['bunkers'])}  pins={len(pins)}  shots={len(play['shots'])}")

        holes.append({
            "num": hole["num"],
            "holeID": hole["id"],
            "par": hole["par"],
            "length_m": length,
            **grid,
            "pins": pins,
            "pin_center": pin_center,
            "aim": aim,
            "shots": play["shots"],
        })

    all_lat = [h["bounds"]["minLat"] for h in holes] + [h["bounds"]["maxLat"] for h in holes]
    all_lng = [h["bounds"]["minLng"] for h in holes] + [h["bounds"]["maxLng"] for h in holes]

    out = {
        "courseID": course_id,
        "name": name,
        "holes_count": info.get("holes"),
        "usingYards": data.get("usingYards", False),
        "player": data.get("name"),
        "handicap": data.get("handicapDecimal", data.get("handicap")),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "bounds": {
            "minLat": min(all_lat), "maxLat": max(all_lat),
            "minLng": min(all_lng), "maxLng": max(all_lng),
        },
        "rounds": rounds_meta,
        "holes": holes,
    }

    # The mapped tee blobs are whole teeing grounds; your tee shots say which
    # markers you actually played off. Fold those in while we have the shots,
    # then the club's card if one is on file — it anchors its tee sets on the tee
    # you played — and lay out the pages last: they frame the farthest tee, so
    # order matters.
    derive_played_tees(out)
    if course_id in CARDS:
        print(f"[card] printed scorecard on file — placing "
              f"{len(CARDS[course_id]['tees'])} tee sets")
        derive_card(out)
    derive_pages(out)
    return out


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape Shot Scope course mapping data.")
    ap.add_argument("--course", type=int, default=PILOT_COURSE_ID, help="courseID to pull")
    ap.add_argument("--all-played", action="store_true", help="pull every course you have played")
    ap.add_argument("--list", action="store_true", help="list your played courses and exit")
    ap.add_argument("--catalog", action="store_true", help="also dump the global course catalog")
    ap.add_argument("--res", type=int, default=GRID_RES, help=f"grid resolution (default {GRID_RES})")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    args = ap.parse_args()

    load_dotenv(ENV_FILE)
    email, password = os.getenv("SHOTSCOPE_EMAIL"), os.getenv("SHOTSCOPE_PASSWORD")
    if not (email and password):
        raise SystemExit("Set SHOTSCOPE_EMAIL and SHOTSCOPE_PASSWORD in shotscope/.env")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_context(viewport={"width": 1600, "height": 1000}).new_page()
        ss = ShotScope.login(page, email, password)

        print("[data] fetching rounds + course info…")
        data = ss.get_json(ROUNDS_API)
        infos = data.get("courseInfos", [])
        names = {
            r.get("courseID"): r.get("courseName")
            for r in data.get("rounds", []) if r.get("courseID")
        }

        if args.list:
            print("\nCourses in your history:")
            for c in infos:
                print(f"  {c['id']:>6}  {c.get('holes'):>2} holes   {names.get(c['id'], '?')}")
            browser.close()
            return

        if args.catalog:
            print("[data] fetching global course catalog (~15 MB)…")
            catalog = ss.get_json(CATALOG_API)
            out = HERE / "courses_catalog.json"
            out.write_text(json.dumps(catalog), encoding="utf-8")
            print(f"      ✓ {len(catalog):,} courses -> {out.name}")

        targets = [c["id"] for c in infos] if args.all_played else [args.course]
        for cid in targets:
            course = build_course(ss, data, cid, args.res)
            out = HERE / f"course_{cid}.json"
            out.write_text(json.dumps(course), encoding="utf-8")
            size_mb = out.stat().st_size / 1e6
            print(f"\n      ✓ {course['name']} -> {out.name} ({size_mb:.1f} MB)\n")

        browser.close()

    print("Done. Next:  python build_viewer.py")


if __name__ == "__main__":
    main()
