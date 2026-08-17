#!/usr/bin/env python3
"""
satellite.py
------------
Downloads aerial imagery for a scraped course and bakes it into the course JSON
as data URIs, so the viewer stays a single self-contained file that works offline.

Imagery is fetched per hole — covering the whole page the viewer prints the hole
on, not just the scraped bounding box, so the rotated card has no bare corners —
plus one course-wide frame for the overview map.

Run `pages.py` first so the pages exist; without them this falls back to each
hole's bounding box and the card corners will be empty.

Providers
    esri    (default) ArcGIS World Imagery — no API key, high resolution.
            Attribution: Esri, Maxar, Earthstar Geographics, and the GIS User Community.
    google  Google Maps Static API — needs --key with a billing-enabled project.

Usage:
    python satellite.py                                  # pilot course, Esri
    python satellite.py --course 20561
    python satellite.py --provider google --key AIza...
    python satellite.py --zoom 19 --quality 72

Dependencies:  pip install pillow requests
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from PIL import Image

HERE = Path(__file__).parent
CACHE = HERE / ".tilecache"
PILOT_COURSE_ID = 20625

TILE = 256
ESRI_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}")
GOOGLE_URL = "https://maps.googleapis.com/maps/api/staticmap"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) golfstats/1.0"}

MAX_ZOOM = 19          # Esri World Imagery tops out here in most of Europe
TARGET_PX = 1100       # longest edge of a hole image before downscaling
COURSE_PX = 1800       # longest edge of the course overview image


# ── Web-mercator helpers ───────────────────────────────────────────────────────

def latlng_to_px(lat: float, lng: float, z: int) -> tuple[float, float]:
    """Global pixel coordinates at zoom z (256 px tiles)."""
    n = 2 ** z
    x = (lng + 180.0) / 360.0 * n
    r = math.radians(lat)
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n
    return x * TILE, y * TILE


def pick_zoom(bounds: dict, target_px: int) -> int:
    """Largest zoom whose image stays under target_px on its longest edge."""
    for z in range(MAX_ZOOM, 10, -1):
        x0, y0 = latlng_to_px(bounds["maxLat"], bounds["minLng"], z)
        x1, y1 = latlng_to_px(bounds["minLat"], bounds["maxLng"], z)
        if max(x1 - x0, y1 - y0) <= target_px:
            return z
    return 15


# ── Tile fetching ──────────────────────────────────────────────────────────────

_session = requests.Session()
_session.headers.update(UA)


def fetch_tile(z: int, x: int, y: int) -> Image.Image | None:
    """One tile, memoised on disk so re-runs cost nothing."""
    path = CACHE / f"{z}_{x}_{y}.jpg"
    if path.exists():
        try:
            return Image.open(path).convert("RGB")
        except Exception:
            path.unlink(missing_ok=True)

    url = ESRI_URL.format(z=z, x=x, y=y)
    for attempt in range(1, 4):
        try:
            r = _session.get(url, timeout=20)
            if r.status_code == 200 and len(r.content) > 500:
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(r.content)
                return Image.open(io.BytesIO(r.content)).convert("RGB")
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(0.6 * attempt)
    return None


def mosaic_esri(bounds: dict, target_px: int) -> Image.Image | None:
    """Stitch the tiles covering `bounds`, then crop to it exactly."""
    z = pick_zoom(bounds, target_px)
    x0, y0 = latlng_to_px(bounds["maxLat"], bounds["minLng"], z)
    x1, y1 = latlng_to_px(bounds["minLat"], bounds["maxLng"], z)

    tx0, ty0 = int(x0 // TILE), int(y0 // TILE)
    tx1, ty1 = int(x1 // TILE), int(y1 // TILE)
    cols, rows = tx1 - tx0 + 1, ty1 - ty0 + 1

    canvas = Image.new("RGB", (cols * TILE, rows * TILE), (46, 74, 42))
    jobs = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]

    got = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for (tx, ty), img in zip(jobs, pool.map(lambda t: fetch_tile(z, t[0], t[1]), jobs)):
            if img is not None:
                canvas.paste(img, ((tx - tx0) * TILE, (ty - ty0) * TILE))
                got += 1
    if got == 0:
        return None

    # Crop to the exact bbox. The viewer stretches this linearly onto an
    # equirectangular rect; over a single hole the mercator error is sub-metre.
    return canvas.crop((
        int(round(x0 - tx0 * TILE)), int(round(y0 - ty0 * TILE)),
        int(round(x1 - tx0 * TILE)), int(round(y1 - ty0 * TILE)),
    ))


def mosaic_google(bounds: dict, target_px: int, key: str) -> Image.Image | None:
    """Google Static Maps caps at 640x640 per request (1280 with scale=2)."""
    z = pick_zoom(bounds, min(target_px, 1280))
    clat = (bounds["minLat"] + bounds["maxLat"]) / 2
    clng = (bounds["minLng"] + bounds["maxLng"]) / 2
    r = _session.get(GOOGLE_URL, timeout=25, params={
        "center": f"{clat},{clng}", "zoom": z, "size": "640x640", "scale": 2,
        "maptype": "satellite", "format": "jpg", "key": key,
    })
    if r.status_code != 200:
        print(f"      google error {r.status_code}: {r.text[:160]}")
        return None
    return Image.open(io.BytesIO(r.content)).convert("RGB")


# ── Encoding ───────────────────────────────────────────────────────────────────

def to_data_uri(img: Image.Image, longest: int, quality: int) -> str:
    w, h = img.size
    if max(w, h) > longest:
        s = longest / max(w, h)
        img = img.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Bake aerial imagery into a course JSON.")
    ap.add_argument("--course", type=int, default=PILOT_COURSE_ID)
    ap.add_argument("--provider", choices=["esri", "google"], default="esri")
    ap.add_argument("--key", default=None, help="Google Static Maps API key")
    ap.add_argument("--quality", type=int, default=72, help="JPEG quality (default 72)")
    ap.add_argument("--hole-px", type=int, default=TARGET_PX)
    ap.add_argument("--course-px", type=int, default=COURSE_PX)
    args = ap.parse_args()

    if args.provider == "google" and not args.key:
        raise SystemExit("--provider google needs --key (a billing-enabled Static Maps key)")

    src = HERE / f"course_{args.course}.json"
    if not src.exists():
        raise SystemExit(f"{src.name} not found — run:  python courses.py --course {args.course}")

    course = json.loads(src.read_text(encoding="utf-8"))
    grab = (lambda b, px: mosaic_google(b, px, args.key)) if args.provider == "google" else mosaic_esri

    print(f"[sat] {course['name']}  via {args.provider}")

    print("[sat] course overview…")
    img = grab(course["bounds"], args.course_px)
    if img:
        course["sat"] = to_data_uri(img, args.course_px, args.quality)
        print(f"      ✓ {img.size[0]}x{img.size[1]} -> {len(course['sat']) / 1e6:.2f} MB b64")
    else:
        print("      ! overview unavailable")

    if not any(h.get("page_bounds") for h in course["holes"]):
        print("      ! no page_bounds — run `python pages.py` first, or the hole")
        print("        pages will have uncovered corners. Falling back to hole boxes.")

    ok = 0
    for h in course["holes"]:
        # The page is what the viewer draws, so it is what we fetch. Recording
        # the box back onto the hole means the viewer never has to guess where
        # the image belongs.
        box = h.get("page_bounds") or h["bounds"]
        img = grab(box, args.hole_px)
        if img:
            h["sat"] = to_data_uri(img, args.hole_px, args.quality)
            h["sat_bounds"] = box
            ok += 1
            print(f"  hole {h['num']:>2}  {img.size[0]}x{img.size[1]}  "
                  f"{len(h['sat']) / 1e6:.2f} MB b64")
        else:
            h.pop("sat_bounds", None)
            print(f"  hole {h['num']:>2}  ! no imagery")

    course["satProvider"] = args.provider
    course["satCredit"] = ("Esri, Maxar, Earthstar Geographics, and the GIS User Community"
                           if args.provider == "esri" else "Google")

    src.write_text(json.dumps(course), encoding="utf-8")
    print(f"\n      ✓ {ok}/{len(course['holes'])} holes imaged")
    print(f"      ✓ {src.name} now {src.stat().st_size / 1e6:.1f} MB")
    print("\nNext:  python build_viewer.py")


if __name__ == "__main__":
    main()
