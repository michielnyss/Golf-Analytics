#!/usr/bin/env python3
"""
fetch.py
--------
Loads credentials from shotscope/.env, opens Chrome, auto-logs in to Shot Scope,
then pulls every round (per-shot GPS + club data) straight from their API.

Outputs (written next to this script):
    golf_shots.csv  +  golf_shots.json

Dependencies (install once):
    pip install selenium requests python-dotenv
Selenium 4.6+ manages ChromeDriver automatically — no manual download needed.
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ── Paths ──────────────────────────────────────────────────────────────────────

HERE = Path(__file__).parent          # shotscope/
ENV_FILE  = HERE / ".env"
OUT_BASE  = HERE / "golf_shots"       # → golf_shots.csv / golf_shots.json

# ── Constants ──────────────────────────────────────────────────────────────────

BASE_URL = "https://dashboard.shotscope.com"
API_URL  = f"{BASE_URL}/api/rounds/slim"

HEADERS_TEMPLATE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    BASE_URL + "/",
    "Accept":     "application/json, text/plain, */*",
}

AUTH_PATH_FRAGMENTS = ("/login", "/signin", "/account", "/auth", "/identity")

# ── Browser helpers ────────────────────────────────────────────────────────────

def _auto_login(driver, email: str, password: str) -> None:
    """Fill and submit the login form."""
    print("      Waiting for login form…")

    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
    )

    all_inputs = driver.find_elements(By.TAG_NAME, "input")

    email_field = next(
        (el for el in all_inputs
         if el.get_attribute("type") in ("email", "text", "username", None)
         and el.is_displayed()),
        None,
    )
    if not email_field:
        raise RuntimeError("Could not find a visible email/username input on the login page.")

    pw_field = next(
        (el for el in all_inputs if el.get_attribute("type") == "password"), None
    )

    email_field.clear()
    email_field.send_keys(email)
    pw_field.clear()
    pw_field.send_keys(password)

    buttons = driver.find_elements(By.TAG_NAME, "button")
    submit  = next(
        (b for b in buttons if b.get_attribute("type") == "submit" and b.is_displayed()),
        next((b for b in buttons if b.is_displayed()), None),
    )
    if not submit:
        raise RuntimeError("Could not find a submit button on the login page.")

    submit.click()
    print("      Form submitted — waiting for dashboard…")


def _wait_for_dashboard(driver, timeout: int = 120) -> None:
    """Block until the browser URL looks like the post-login dashboard."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        url     = driver.current_url.lower()
        on_base = BASE_URL.lower() in url
        on_auth = any(f in url for f in AUTH_PATH_FRAGMENTS)
        if on_base and not on_auth:
            time.sleep(0.5)
            return
        time.sleep(1)
    driver.quit()
    raise TimeoutError(f"Dashboard not reached within {timeout}s — check your credentials.")


# ── Step 1: Browser ────────────────────────────────────────────────────────────

def get_session_cookies(email: str | None, password: str | None) -> dict:
    """Launch Chrome, log in, return session cookies as {name: value}."""
    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])

    driver = webdriver.Chrome(options=opts)
    driver.get(BASE_URL)

    if email and password:
        print("\n[1/3] Auto-login: opening Shot Scope…")
        time.sleep(2)
        try:
            _auto_login(driver, email, password)
        except Exception as exc:
            print(f"      Auto-login failed ({exc}). Complete login manually in the browser.")
    else:
        print("\n[1/3] No credentials found — please log in manually in the browser.")
        print("      Waiting up to 2 minutes…")

    _wait_for_dashboard(driver)

    cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
    driver.quit()
    print("      ✓ Logged in. Browser closed.\n")
    return cookies


# ── Step 2: API ────────────────────────────────────────────────────────────────

def fetch_all_rounds(cookies: dict, since: str = "2000-01-01T00:00:00.000Z") -> dict:
    """Call the slim-rounds endpoint and return the parsed JSON payload."""
    headers = {
        **HEADERS_TEMPLATE,
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
    }
    print("[2/3] Fetching rounds from API…")
    resp = requests.get(f"{API_URL}?modifiedSinceDate={since}", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Step 3: Parse ──────────────────────────────────────────────────────────────

def extract_shots(data: dict, round_index: int) -> list[dict]:
    """Flatten one round → hole → shot into a plain list, with round metadata prepended."""
    clubs    = data.get("clubs", [])
    id_key   = next((k for k in ("clubID", "id", "clubId") if clubs and k in clubs[0]), None)
    club_map = {c[id_key]: c for c in clubs} if id_key else {}

    r    = data["rounds"][round_index]
    meta = {
        "round_date":  str(r.get("startedDate") or r.get("roundDate") or r.get("date") or r.get("playedAt") or "")[:10],
        "course":      r.get("courseName") or r.get("course") or r.get("name") or "",
        "total_score": r.get("totalShots") or r.get("totalScore") or r.get("score") or r.get("strokes") or "",
    }

    shots = []
    for hole in r.get("holes", []):
        for s in hole.get("shots", []):
            club = club_map.get(s.get("clubID"), {})
            shots.append({
                **meta,
                "hole":        hole.get("holeNum") or hole.get("holeNumber"),
                "shot":        s.get("shotNumber"),
                "club":        club.get("name") or s.get("clubName") or s.get("club") or "Unknown",
                "club_short":  club.get("shortName") or s.get("clubShortName", ""),
                "start_lat":   s.get("startLat"),
                "start_lng":   s.get("startLng"),
                "end_lat":     s.get("endLat"),
                "end_lng":     s.get("endLng"),
                "distance_m":  s.get("distance"),
                "stroke_type": s.get("strokeType"),
                "lie":         s.get("lie"),
                "to_lie":      s.get("toLie"),
                "dist_to_pin": s.get("distanceToPin"),
            })
    return shots


def extract_all_shots(data: dict) -> list[dict]:
    """Extract and combine shots from every round."""
    return [shot for i in range(len(data["rounds"])) for shot in extract_shots(data, i)]


# ── Step 4: Save ───────────────────────────────────────────────────────────────

def save(shots: list[dict]) -> None:
    """Overwrite golf_shots.csv and golf_shots.json inside the shotscope/ folder."""
    with open(f"{OUT_BASE}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=shots[0].keys())
        writer.writeheader()
        writer.writerows(shots)

    with open(f"{OUT_BASE}.json", "w", encoding="utf-8") as f:
        json.dump(shots, f, indent=2)

    print(f"      ✓ {len(shots)} shots saved → {OUT_BASE}.csv  |  {OUT_BASE}.json")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv(ENV_FILE)
    email    = os.getenv("SHOTSCOPE_EMAIL")
    password = os.getenv("SHOTSCOPE_PASSWORD")

    cookies = get_session_cookies(email, password)

    data   = fetch_all_rounds(cookies)
    rounds = data.get("rounds", [])
    if not rounds:
        print("No rounds found in the API response.")
        return

    def _v(d, *keys, default="?"):
        for k in keys:
            v = d.get(k)
            if v not in (None, "", "N/A"):
                return v
        return default

    print(f"      Found {len(rounds)} round(s):\n")
    for i, r in enumerate(rounds):
        date   = str(_v(r, "startedDate", "roundDate", "date", "playedAt", "created"))[:10]
        course = _v(r, "courseName", "course", "name")
        score  = _v(r, "totalShots", "totalScore", "score", "strokes", "gross")
        print(f"  [{i}]  {date}   {str(course):<35}  Score: {score}")

    raw = input("\n  Round index to export, or 'all' (default 0 = most recent): ").strip().lower()

    if raw == "all":
        shots = extract_all_shots(data)
        print(f"\n[3/3] All {len(rounds)} rounds  |  {len(shots)} shots total\n")
    else:
        idx   = int(raw) if raw.isdigit() else 0
        shots = extract_shots(data, round_index=idx)
        r     = rounds[idx]
        print(f"\n[3/3] {_v(r, 'courseName', 'course', 'name')}  |  "
              f"{str(_v(r, 'startedDate', 'roundDate', 'date', 'playedAt'))[:10]}  |  "
              f"Score: {_v(r, 'totalShots', 'totalScore', 'score', 'strokes', 'gross')}  |  {len(shots)} shots\n")

    print(f"  {'Date':>10}  {'Hole':>4} {'Shot':>4}  {'Club':<20}  "
          f"{'Start Lat':>11}  {'Start Lng':>11}  {'Dist(m)':>8}")
    print("  " + "─" * 82)
    for s in shots:
        print(f"  {str(s['round_date']):>10}  "
              f"{str(s['hole'] or ''):>4} {str(s['shot'] or ''):>4}  "
              f"{str(s['club'] or ''):<20}  "
              f"{str(s['start_lat'] or ''):>11}  {str(s['start_lng'] or ''):>11}  "
              f"{str(s['distance_m'] or ''):>8}")

    print()
    save(shots)


if __name__ == "__main__":
    main()
