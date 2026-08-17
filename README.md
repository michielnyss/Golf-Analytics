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
python build_viewer.py   # emit a standalone page               -> yardage_<id>.html
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
`build_viewer.py --all` then rebuilds every `course_*.json` sitting on disk, and
`build_viewer.py --list` shows which those are. `courses.py` folds `tees.py` in
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
| `build_viewer.py` | Injects the JSON into `viewer_template.html` |
| `viewer_template.html` | The yardage-book front end (edit this, not the built file) |

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

## Viewer

`yardage_<id>.html` is fully self-contained (imagery included) and opens straight from disk.

- **Tees** — the header picks the set (White · Yellow · Blue · Red) once for the whole book:
  the scorecard, every hole page, the map marker and the printed ribbon all follow it. The
  set you played is preselected and tagged `played`.
- **Course view** — all 18 routings composited, with your shot traces and the card: par,
  stroke index, length off the chosen tee, your score, and the card's own OUT / IN / TOTAL.
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
