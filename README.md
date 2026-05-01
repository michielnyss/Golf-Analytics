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
└── tables/                     # Output Excel tables
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
