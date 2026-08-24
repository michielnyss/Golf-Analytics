# Golf Analytics

In-depth golf performance analysis based on shot data from the **Garmin Approach R10** launch monitor.

## Overview

This project analyses individual shot-level data exported from the Garmin R10 and compares it against a personal benchmark. It produces publication-quality visualisations and Excel reports covering distance, accuracy, ball flight, swing mechanics, and launch conditions.

## Project Structure

```
Golf-Analytics/
├── Golfstats.R                 # Main analysis script
├── data.xlsx                   # Input data (shot log + benchmark)
├── graphs/                     # Output PNG visualisations
├── tables/                     # Output Excel tables
└── shotscope/                  # Shot Scope on-course data + yardage book
```

### data.xlsx sheets

| Sheet | Description |
|-------|-------------|
| `Michiel` | My own raw shot-level data from the Garmin R10 (up to 300 rows), use as example |
| `Benchmark` | Reference performance values by club type |

**Key columns:** Club Type, Club Speed, Ball Speed, Launch Angle, Spin Rate, Spin Axis, Club Path, Club Face, Attack Angle, Apex Height, Carry Distance, Total Distance, Launch Direction, Carry Deviation, Backswing/Downswing Time.

## Analyses

| Function | What it shows |
|----------|---------------|
| `make_boxplot()` | Distance or accuracy distribution per club, with benchmark overlay |
| `pairwise_plot()` | Correlation matrix across selected metrics |
| `shot_shape_rose()` | Club Path vs Attack Angle scatter with quadrant labels |
| `launch_condition_triangle()` | Ball Speed / Launch Angle / Spin Rate vs optimal windows |
| `shot_birdview_facet()` | Bird's-eye Bézier trajectories coloured by shot shape |
| `shot_sideview_facet()` | Side-view trajectories with apex height and roll |
| `compare_to_benchmark()` | Delta (absolute / % / hybrid) vs benchmark per club |
| `plot_benchmark_heatmap()` | Normalised heatmap — white = on target, red = off target |
| `table_benchmark_comparison()` | Wide-format pivot table exported to Excel |

## Requirements

R ≥ 4.1 with the packages listed in `requirements.R`. Install them all with:

```r
source("requirements.R")
```

## Usage

1. Export your Garmin R10 session to Excel and paste shots into the `Michiel` sheet of `data.xlsx`.
2. Update the `Benchmark` sheet if needed.
3. Open and run `Golfstats.R` in RStudio or from the R console:

```r
source("Golfstats.R")
```

Outputs are written to `graphs/` (PNG) and `tables/` (XLSX).

---

# Distance and dispersion report (`distance_report.py`)

A 13-page PDF on what each club actually goes and how tightly, built from the same
`data.xlsx` sheet the R side uses and cross-checked against the Shot Scope round data.

```
python distance_report.py                      # -> distance_report.pdf
python distance_report.py --player Seppe --out seppe.pdf
```

Needs `pandas`, `numpy`, `scipy`, `statsmodels`, `scikit-learn`, `matplotlib` and
`openpyxl`.

## What is on each page

| Page | |
|------|--|
| 1 | The yardage card: median carry, 95% CI, the 80% window, spread, roll and total |
| 2 | Sample, exclusions and the estimator used for each quantity |
| 3 | Every shot per club - IQR, p10-p90 and the raw strikes behind them |
| 4 | Distribution shape: robust vs classical moments, Shapiro-Wilk, Q-Q plots |
| 5 | Bootstrap CIs on centre and spread, and how many shots each conclusion needs |
| 6 | Prediction windows and 80/90 tolerance intervals - the carry-over-hazard numbers |
| 7 | Gapping ladder: P(longer club wins) over every shot pair, per rung |
| 8 | Two-dimensional dispersion: 50%/90% covariance ellipses, directional bias tested |
| 9 | Whether offline spread scales with distance - the dispersion cone in degrees |
| 10 | Variance decomposition: speed vs strike quality, and session vs swing (ICC) |
| 11 | Distance control on the nominated-target lob wedge blocks - bias and precision |
| 12 | On-course check against 598 GPS-tracked strokes over 14 rounds |
| 13 | Ranked conclusions with their statistical warrant, and the measurement plan |

## Decisions the script makes, and why

- **One shot is dropped**, a sand wedge logged at 213.6 km/h of club speed - 52 km/h
  above the fastest driver swing in the file, so a radar fault rather than a mishit.
  Nothing else is removed; mishits stay in, because a yardage built on good swings only
  is a yardage that comes up short.
- **The lob wedge is split, not pooled.** Both its blocks were hit to a nominated carry
  (`Goal: carry 30` / `50` in the Note field), so they are two distance-control samples
  and are analysed as such on page 11, outside the gapping ladder.
- **On-course lengths are separated by a two-component Gaussian mixture** per club, since
  the round data mixes full swings with layups and chips. The upper component is compared
  against the range total.
- **Any block hit to a nominated target should say so in the Note field.** That is the
  only thing that makes accuracy - as opposed to precision - measurable, and page 11 is
  the only page in the report that can currently do it.

---

# Shot Scope course mapping (`shotscope/`)

Where the R side covers launch-monitor shots, this side covers **on-course** play: every
round, every shot's GPS trace, and a reconstruction of the course itself.

## Pipeline

```
python courses.py        # scrape course mapping + your rounds  -> course_<id>.json
python tees.py           # recover the tees you played from your tee shots
python scorecard.py      # fold in the printed card: par, stroke index, every tee set
python pages.py          # lay out the card each hole is drawn on
python satellite.py      # bake aerial imagery into that JSON   (optional)
python build_app.py      # emit the app over every course        -> app/
python build_viewer.py   # or one course on its own              -> yardage_<id>.html
```

The order matters: the card's tee sets are anchored on the tee you played, pages are framed
around the farthest tee of the set, and imagery is fetched to cover the pages. `courses.py`
runs the tee and page steps itself, and both `tees.py` and `scorecard.py` re-lay the pages
after they move a tee — but if you re-run one stage by hand, re-run everything after it too.
Adding a card moves the back tee up to 70 m behind the one you played, which grows the page,
so re-run `satellite.py` after `scorecard.py` or the new corner comes out bare.

Credentials live in `shotscope/.env` (gitignored):

```
SHOTSCOPE_EMAIL=you@example.com
SHOTSCOPE_PASSWORD=...
```

## Building another course

Every script takes the same `--course <id>`, and each stage is independent — only
`courses.py` needs the network.

```
python courses.py --list                 # which courses your history covers
python courses.py --course 20561         # scrape it            (~5 min per course)
python satellite.py --course 20561       # imagery              (optional)
python build_viewer.py --course 20561    # -> yardage_20561.html
```

`courses.py --all-played` scrapes every course you have a round on in one pass;
`build_app.py` then folds every `course_*.json` sitting on disk into one app, and
`build_viewer.py --all` builds each as its own book instead. Both take `--list`. `courses.py` folds `tees.py` in
automatically, and `scorecard.py` too when a card for that course is on file, so a fresh
scrape already knows which tees you played and what the club prints — you only run those two
by hand to re-derive a course scraped before they existed, or after editing a card.

The pilot course ID is a module-level constant (`PILOT_COURSE_ID`) in each script if you
would rather change the default than pass the flag every time.

## Scripts

| Script | What it does |
|--------|--------------|
| `fetch.py` | Original round/shot export → `golf_shots.csv` / `.json` |
| `courses.py` | Reconstructs course mapping and folds in pins + shots |
| `tees.py` | Derives the tees you actually played from your tee-shot GPS fixes |
| `scorecard.py` | Holds the club's printed card and places every tee set on the ground |
| `pages.py` | Lays out each hole's fixed-ratio card, shared by the viewer and the imagery |
| `satellite.py` | Downloads aerial imagery, embeds it as data URIs |
| `build_app.py` | Builds the app over every scraped course — library, analysis, viewer |
| `build_viewer.py` | The same page for one course on its own |
| `viewer_template.html` | The front end (edit this, not the built file) |

## How the mapping works

Shot Scope exposes no polygon or GeoJSON endpoint, but its private API has a **lie
oracle**: `POST /api/CourseInfo/LieMulti` takes a `courseID`, a `holeID` and a list of
coordinates, and answers `tee` / `fairway` / `green` / `bunker` / `water` / `rough` for
each one. `courses.py` grid-samples each hole's bounding box (128×128 by default, ~295k
points across 18 holes, batched 4096 per request) and rebuilds the course as a raster.

Everything else is derived from that raster: green centres and depth, tee boxes clustered
by flood fill, bunker positions with carry distances, and hole length along the play axis.
Pin positions and shot traces come from `/api/rounds/slim`.

Verified against recorded play — the oracle's answer matched the stored `lie` on all six
shots of a test hole.

## Where the tees come from

The raster gives *teeing grounds*, not tee markers: one flood-filled blob routinely covers
white, yellow and red at once, and its centroid can sit 60 m from where you actually teed
off. So `tees.py` takes the GPS fix on shot 1 of every round, groups those fixes by the tee
colour Shot Scope recorded for the round, and nudges each one onto the nearest mapped tee
cells (a fix carries a few metres of error; the raster does not drift).

On the pilot course that moved every fix less than 5 m — but moved nine of eighteen holes by
15 m or more against the back-tee reading, and the round total from 5584 m to 5205 m. Run
`python tees.py --report-only` for the per-hole table.

Without a card the viewer lists the played tee first and measures everything — hole length,
scorecard, rings, the HUD — from it, with the mapped centroids selectable as `Mapped 1..n`.

## Where the other tees come from

Your shot data knows one tee per hole: the set you played. The club plays four, and the
raster cannot tell them apart. `scorecard.py` closes that gap from the printed card.

The card's own numbers are the only exact input, so they are used as such: anchor on the tee
you played — a GPS fix, metres accurate — and step the **difference** in card length along
the line the teeing grounds sit on (fitted through the mapped tee blobs by weighted PCA,
falling back to tee→green when they are not really one line). Differences rather than
absolute lengths is what makes it work on a dogleg, where a card measures around the corner
and reads tens of metres longer than the straight tee→green distance: both tees share the
playing line from the corner on, so the difference between them is the same either way.

Where a stepped point lands on a mapped teeing ground, that surveyed centroid is taken
instead — but only if it does not contradict the card *along* the tee line by more than 6 m.
The raster may move a tee sideways (markers sit off the centre line all the time); it may not
move it up or down the hole, because that is the part the card already told us. On the pilot
course, of 72 tees: 18 anchored on tee shots, 12 landed on a mapped teeing ground, 35 were
nudged sideways onto tee cells, 7 stand where the card put them.

The sanity check is in `python scorecard.py --report-only`: the `gap` column (card minus
straight-line) should be near-constant down a hole, since the dogleg it measures around is a
property of the hole, not of the tee. It is within 3 m on fourteen of eighteen holes; the
rest are the doglegs (3, 8, 10, 11), where a forward tee genuinely cuts less corner.

Lengths shown anywhere in the viewer are the card's, not the mapping's — that is what the
starter's sheet says and what the marker plate reads. The straight-line distance to the green
centre rides along beside it, because that is what the rings are drawn to.

Stroke index comes off the same card and shows up in the header chip, the scorecard column
and the printed ribbon. To add a course, put its card in `CARDS` in `scorecard.py`: hole,
par, stroke index, then one length per tee set. The printed OUT / IN / TOTAL go in beside it
and are asserted against the rows, so a mistyped hole fails loudly instead of quietly.

## The app

`build_app.py` folds every course on disk into one page: a searchable library, an
analysis tab per course, and the yardage viewer. It builds in two shapes, from the
same `viewer_template.html`.

```
python build_app.py                  # app/  — index.html + data/*.json
python build_app.py --serve          # …and serve it on localhost:8000
python build_app.py --standalone     # golfstats.html — one file, opens from disk
python build_app.py --no-sat         # drop the aerials: 5.2 MB -> 0.9 MB
```

**Served** is the web-tool shape. The page ships with a manifest — the numbers every
library card shows — and pulls a course's mapping only when you pick it, so a library
of forty courses still opens instantly. It needs a server: a page opened from `file://`
is not allowed to read its sibling `data/` folder, and says so if you try.

**Standalone** bakes every course into the HTML, the way a yardage book bakes one. No
server, but the file grows with the library (5.2 MB for two courses with imagery).

### Library

Every scraped course, with its rounds, scoring per 18, putting, greens, the tee sets it
knows and a trace of how you have scored there over time. Type to filter on name, ID,
tee or player; enter opens the top hit. `/` reopens it from anywhere, and the course
name in the header is the way back.

### Analysis

Scoped by the round picker at the top — all rounds, or one — and computed from the same
shot data the map draws, so the two cannot disagree.

| | |
|--|--|
| **Headline** | to par per 18, rounds, putts per hole, fairways, greens in regulation, scrambling |
| **How you score** | share of holes by score, centred on par, split out by par 3 / 4 / 5 |
| **Round by round** | to par, putts, greens or fairways across every round — per hole, so a nine sits beside an eighteen honestly |
| **Which holes cost you** | average strokes over par per hole, by hole or ranked hardest |
| **Every hole, every round** | the whole score matrix, one row per round |
| **What each club goes** | the middle half of every strike with the median marked — what a club *does*, not what it should |
| **Where the ball ends up** | every shot from each lie, by the lie it found |
| **Putting** | holes by number of putts |

Every chart has a **Table** toggle showing the same numbers, and hover gives the detail.

Fairways come off Shot Scope's own count rather than being re-derived — its definition
is not reproducible from the exported fields — so the figure matches the dashboard the
data came from. Everything else is derived here.

### Links

`#20625` opens a course, `#20625/analysis` its analysis, `#20625/book=A6,White` a
printed book off the White tees — so any view is one URL.

## Viewer

`yardage_<id>.html` is one course in the same page, fully self-contained (imagery
included) and opening straight from disk onto that course.

- **Tees** — the header picks the set (White · Yellow · Blue · Red) once for the whole book:
  the scorecard, every hole page, the map marker and the printed ribbon all follow it. The
  set you played is preselected and tagged `played`.
- **Course view** — all 18 routings composited, with your shot traces and the card: par,
  stroke index, length off the chosen tee, your score, and the card's own OUT / IN / TOTAL.
  Where you have played a course more than once, the score column is your average over
  every round (the hole page adds your best), and the rounds / fairways / greens above it
  are the course's, not one round's. The Analysis tab is where they come apart by round.
- **Hole view** — rotated so the tee is at the bottom and the green at the top, and framed
  on a fixed-ratio page so every hole prints at the same shape however long it is.
- **Focus** — only the non-playable ground is dimmed. The hole is sliced across the play
  axis and each slice is lit from the outermost mapped feature on one side to the outermost
  on the other, so the rough between tee, fairway and green stays lit; slices with nothing
  mapped (the carry off the tee) are bridged from their neighbours. A 22 m buffer of rough
  is kept lit all round, with a 10 m feather at the edge. Toggle with the button or `f`;
  `PLAY_BUFFER`, `PLAY_MAX_HALF` and `FEATHER_M` in `viewer_template.html` set the metres.
- **Distance rings** — amber from the tee (100/150/200/250) and cyan from the pin
  (25/50/75/100/125/150/175/200), in whichever unit is selected.
- **Zoom** — scroll or pinch to zoom about the cursor, drag to pan, `+` / `−` / `0`, or the
  control top-right. Changing hole or view resets to the fitted page.
- Hover for live distances, click to drop a measuring point, `←`/`→` to change hole, `Esc`
  for the course view. Metres/yards and light/dark both toggle.

## Yardage book (print)

**Create yardage book** in the header (or `b`) turns the viewer into a printable book: one
hole card per page, the map with its focus and rings, and a ribbon naming the hole — number,
par, stroke index, the card length off the tee you picked (headed by that tee's name, so a
printed book says which markers it was made for), and green depth. Preview is the paper, so
`Print / Save PDF` gives you a PDF at the size shown and nothing else.

The cards are drawn by the viewer's own renderer at 300 dpi, so **the book shows whatever
the viewer is showing**. That is where you personalise it: set focus, tee rings, green rings,
shots, pins, satellite, the tee and the units the way you want them on paper, then open the
book. The bar itself only owns what is specific to paper:

| Control | |
|---------|--|
| Page | A6 · A5 · A4 · Letter · Pocket (4×6″) |
| Per sheet | 1 hole, or 2 side by side — 2-up turns the paper landscape and adds a cut line |
| Margin | mm; defaults to something sane per page size |
| Print light | Forces the light palette regardless of the screen theme — leave it on for paper |
| Greyscale | For a mono printer |
| Ribbon on top | Moves the ribbon above the map |

Everything is laid out in millimetres rather than percentages, so the preview and the page
agree and a card can never spill onto a second sheet. A6 is the pocket-book default: 18
pages at 105×148 mm, ~2.7 MB.

`#book` in the URL boots straight into it, which also makes the export scriptable:

```
chrome --headless --print-to-pdf=book.pdf --no-pdf-header-footer \
       --virtual-time-budget=180000 "yardage_20625.html#book"
```

Options come off the same fragment, comma-separated — `#book=A4,2` for 2-up A4,
`#book=Pocket,grey,top`. A tee name is an option too, so one book per tee is one command
each: `#book=A6,White`.

## Notes

- The tile cache in `shotscope/.tilecache/` makes repeat imagery runs free; delete it to refetch.
- `satellite.py` defaults to Esri World Imagery (no API key). Google Static Maps works via
  `--provider google --key <KEY>` but needs a billing-enabled project.
- A hole page is rotated relative to north and covers about **2.8× the area** of the scraped
  hole box, so `satellite.py` fetches the page's lat/lng box and records it as `sat_bounds`.
  Esri's zoom steps are discrete, so the default `--hole-px 1100` lands on z17 (~0.75 m/px)
  for most holes; `--hole-px 1700` buys z18 at roughly four times the file size.
- This is an undocumented private API used against your own account. Keep the request
  volume near what the dashboard itself would make — `courses.py` throttles and retries
  for that reason. Grid-sampling the full 42k-course catalogue would be a different thing
  entirely, and is not what these scripts are for.
