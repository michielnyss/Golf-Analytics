#!/usr/bin/env python3
"""
Distance and dispersion report - Garmin Approach R10 launch-monitor data.

Reads  : data.xlsx (sheet "Michiel"), shotscope/golf_shots.csv
Writes : distance_report.pdf

    python distance_report.py [--player Michiel] [--out distance_report.pdf]
"""
from __future__ import annotations

import argparse
import textwrap
import warnings

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, FancyBboxPatch, Polygon, Rectangle
from matplotlib.ticker import MaxNLocator
from scipy import stats
import statsmodels.api as sm
import statsmodels.formula.api as smf
from sklearn.mixture import GaussianMixture

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------- palette ---
# Light-surface instance of the reference data-viz palette. The categorical
# slots used here (blue / orange / aqua) validate on all pairs: worst CVD
# dE 9.2, worst normal-vision dE 24.0. Status colours below 3:1 against this
# surface always travel with a glyph and a word, never colour alone.
SURFACE, PLANE = "#fcfcfb", "#f4f4f1"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
BLUE_100, BLUE_250, BLUE_550 = "#cde2fb", "#86b6ef", "#1c5cab"
GOOD, WARNING, SERIOUS, CRITICAL = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"

mpl.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 8.5,
    "axes.facecolor": SURFACE,
    "figure.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK2,
    "axes.labelsize": 7.6,
    "axes.linewidth": 0.7,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelsize": 7.0,
    "ytick.labelsize": 7.0,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "grid.linestyle": "-",
    "legend.frameon": False,
    "legend.fontsize": 7.2,
    "pdf.fonttype": 42,
})

A4 = (8.27, 11.69)
PW_PT, PH_PT = 8.27 * 72, 11.69 * 72
L, R = 0.075, 0.955
COL = R - L
RNG = np.random.default_rng(20260422)
BOOT = 20000

CLUB_ORDER = ["Driver", "5 Wood", "5 Iron", "6 Iron", "7 Iron", "8 Iron",
              "9 Iron", "Pitching Wedge", "Gap Wedge", "Sand Wedge"]
SHORT = {"Driver": "Dr", "5 Wood": "5W", "5 Iron": "5i", "6 Iron": "6i",
         "7 Iron": "7i", "8 Iron": "8i", "9 Iron": "9i",
         "Pitching Wedge": "PW", "Gap Wedge": "GW", "Sand Wedge": "SW",
         "Lob Wedge": "LW"}


# ================================================== typography & chrome ====
def _chars(size, frac):
    """Characters that fit in `frac` of the page width at `size` pt."""
    return max(8, int(frac * PW_PT / (0.495 * size)))


def wrap_lines(text, size, frac):
    n = _chars(size, frac)
    out = []
    for block in str(text).split("\n"):
        out.extend(textwrap.wrap(block, n) or [""])
    return out


def lead(size, ls=1.5):
    return size * ls / PH_PT


def para(fig, x, y, text, size=7.8, color=INK2, frac=COL, ls=1.5,
         weight="normal"):
    """Draw wrapped text from the top-left; return the y below the block."""
    lines = wrap_lines(text, size, frac)
    lh = lead(size, ls)
    for i, ln in enumerate(lines):
        fig.text(x, y - i * lh, ln, fontsize=size, color=color, va="top",
                 weight=weight)
    return y - len(lines) * lh


def heading(fig, x, y, text, size=11, color=INK):
    fig.text(x, y, text, fontsize=size, color=color, weight="bold", va="top")
    return y - lead(size, 1.9)


def rule(fig, y, x0=L, x1=R, color=GRID, lw=0.8):
    fig.add_artist(Line2D([x0, x1], [y, y], transform=fig.transFigure,
                          color=color, lw=lw, zorder=1))


def header(fig, kicker, title, sub=None):
    fig.text(L, 0.963, kicker.upper(), color=S1, fontsize=7.4, weight="bold")
    fig.text(L, 0.949, title, color=INK, fontsize=16.5, weight="bold", va="top")
    y = 0.920
    if sub:
        y = para(fig, L, y, sub, size=8.6, color=INK2, frac=COL, ls=1.45)
    rule(fig, y - 0.012)
    return y - 0.030


def footer(fig, n, total, note=""):
    rule(fig, 0.042)
    if note:
        para(fig, L, 0.032, note, size=6.7, color=MUTED, frac=0.80, ls=1.4)
    fig.text(R, 0.032, f"{n} / {total}", color=MUTED, fontsize=6.7,
             va="top", ha="right")


def style(ax, xgrid=False, ygrid=True):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.grid(ygrid, axis="y", zorder=0)
    ax.grid(xgrid, axis="x", zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(length=2.5, width=0.6)
    return ax


def tile(fig, x, y, w, h, value, label, note=None, color=INK, vsize=20):
    fig.add_artist(FancyBboxPatch(
        (x, y), w, h, transform=fig.transFigure, zorder=0,
        boxstyle="round,pad=0,rounding_size=0.008", fc=PLANE, ec=GRID, lw=0.8))
    fig.text(x + 0.013, y + h - 0.013, label.upper(), fontsize=6.4,
             color=MUTED, weight="bold", va="top")
    fig.text(x + 0.013, y + h - 0.031, value, fontsize=vsize, color=color,
             weight="bold", va="top")
    if note:
        fig.text(x + 0.013, y + 0.011, note, fontsize=6.7, color=INK2,
                 va="bottom", linespacing=1.35)


def C(label, dx, align="l", w=None):
    return dict(label=label, dx=dx, al=align, w=w)


_HA = {"l": "left", "r": "right", "c": "center"}


def draw_table(fig, x, y, cols, rows, size=7.2, head=6.4, zebra=True,
               width=None, pad=0.0062, ls=1.38):
    """Flow-laid table. Cells are str or (str, colour, weight); a column with
    `w` set wraps to that fraction of page width and grows the row."""
    width = COL if width is None else width
    lh = lead(size, ls)
    for c in cols:
        fig.text(x + c["dx"], y, c["label"], fontsize=head, color=MUTED,
                 weight="bold", ha=_HA[c["al"]], va="baseline")
    rule(fig, y - 0.0055, x - 0.004, x + width, AXIS, 0.7)
    yy = y - 0.0055
    for i, row in enumerate(rows):
        prepared, nlines = [], 1
        for c, cell in zip(cols, row):
            txt, col, wt = (cell if isinstance(cell, tuple)
                            else (cell, INK if c["al"] == "l" else INK2, "normal"))
            lines = wrap_lines(txt, size, c["w"]) if c["w"] else [str(txt)]
            nlines = max(nlines, len(lines))
            prepared.append((c, lines, col, wt))
        rowh = nlines * lh + pad
        if zebra and i % 2 == 1:
            fig.add_artist(Rectangle((x - 0.008, yy - rowh), width + 0.014, rowh,
                                     transform=fig.transFigure, fc=PLANE,
                                     ec="none", zorder=0))
        base = yy - pad * 0.55 - lh * 0.72
        for c, lines, col, wt in prepared:
            for j, ln in enumerate(lines):
                fig.text(x + c["dx"], base - j * lh, ln, fontsize=size,
                         color=col, weight=wt, ha=_HA[c["al"]], va="baseline")
        yy -= rowh
    return yy - 0.004


def bullets(fig, x, y, items, hsize=8.7, bsize=7.8, frac=None, gap=0.012):
    """items: (headline, colour, body). Dot + bold headline + wrapped body."""
    frac = COL - 0.016 if frac is None else frac
    for headline, col, body in items:
        fig.text(x, y - 0.0018, "●", color=col, fontsize=8, va="top")
        fig.text(x + 0.016, y, headline, color=INK, fontsize=hsize,
                 weight="bold", va="top")
        y = para(fig, x + 0.016, y - lead(hsize, 1.75), body, size=bsize,
                 color=INK2, frac=frac) - gap
    return y


def numbered(fig, x, y, items, hsize=9.5, bsize=7.8, gap=0.014):
    """items: (n, headline, colour, body)."""
    for num, headline, col, body in items:
        fig.add_artist(FancyBboxPatch(
            (x, y - 0.0195), 0.020, 0.0195, transform=fig.transFigure, zorder=2,
            boxstyle="round,pad=0,rounding_size=0.004", fc=col, ec="none"))
        fig.text(x + 0.010, y - 0.0104, num, color="#ffffff", fontsize=8.2,
                 weight="bold", ha="center", va="center")
        fig.text(x + 0.030, y, headline, color=INK, fontsize=hsize,
                 weight="bold", va="top")
        y = para(fig, x + 0.030, y - lead(hsize, 1.7), body, size=bsize,
                 color=INK2, frac=COL - 0.030) - gap
    return y


# ================================================================= data ====
def load(player):
    raw = pd.read_excel("data.xlsx", player)
    raw["dt"] = pd.to_datetime(raw["Date"].str[:17], format="%m/%d/%y %H:%M:%S",
                               errors="coerce")
    raw["session"] = raw["dt"].dt.date
    artefact = raw[raw["Club Speed [km/h]"] >= 200]
    df = raw[raw["Club Speed [km/h]"] < 200].copy()
    df["intent"] = np.where(
        df["Club Type"] == "Lob Wedge",
        np.where(df["Note"].astype(str).str.contains("30"), "LW30", "LW50"),
        "full")
    return raw, df, df[df.intent == "full"].copy(), artefact


def hodges_lehmann(x):
    x = np.asarray(x, float)
    w = (x[:, None] + x[None, :]) / 2
    return float(np.median(w[np.triu_indices_from(w)]))


def tolerance_k(n, p=0.80, g=0.90):
    """Two-sided normal tolerance factor: content p at confidence g (Howe)."""
    z = stats.norm.ppf((1 + p) / 2)
    return float(np.sqrt(((n - 1) * (1 + 1 / n) * z ** 2)
                         / stats.chi2.ppf(1 - g, n - 1)))


def carry(full, c):
    return full.loc[full["Club Type"] == c, "Carry Distance [m]"].values


def lateral(full, c):
    return full.loc[full["Club Type"] == c, "Carry Deviation Distance [m]"].values


def club_table(full):
    rows = []
    for c in CLUB_ORDER:
        x, y = carry(full, c), lateral(full, c)
        n = len(x)
        bs = x[RNG.integers(0, n, (BOOT, n))]
        med_ci = np.percentile(np.median(bs, 1), [2.5, 97.5])
        sd_ci = np.percentile(bs.std(1, ddof=1), [2.5, 97.5])
        g = full[full["Club Type"] == c]
        cov = np.cov(np.vstack([y, x]))
        k = tolerance_k(n)
        rows.append(dict(
            club=c, n=n, avg=x.mean(), med=float(np.median(x)),
            hl=hodges_lehmann(x), tr10=stats.trim_mean(x, 0.1),
            sd=x.std(ddof=1),
            madsd=stats.median_abs_deviation(x, scale="normal"),
            iqr=float(np.subtract(*np.percentile(x, [75, 25]))),
            cv=100 * x.std(ddof=1) / x.mean(),
            skw=stats.skew(x, bias=False), krt=stats.kurtosis(x, bias=False),
            sw_p=stats.shapiro(x).pvalue,
            med_lo=med_ci[0], med_hi=med_ci[1],
            sd_lo=sd_ci[0], sd_hi=sd_ci[1],
            p05=np.percentile(x, 5), p10=np.percentile(x, 10),
            p25=np.percentile(x, 25), p75=np.percentile(x, 75),
            p90=np.percentile(x, 90), lo=x.min(), hi=x.max(), k=k,
            ti_lo=x.mean() - k * x.std(ddof=1),
            ti_hi=x.mean() + k * x.std(ddof=1),
            lat_mean=y.mean(), lat_sd=y.std(ddof=1), lat_med=float(np.median(y)),
            lat_p=stats.wilcoxon(y).pvalue if len(y) > 5 else np.nan,
            rho=float(np.corrcoef(y, x)[0, 1]),
            ell90=float(np.pi * 4.605 * np.sqrt(np.linalg.det(cov)) / 10000),
            ang_sd=g["Carry Deviation Angle [deg]"].std(ddof=1),
            roll=float((g["Total Distance [m]"] - g["Carry Distance [m]"]).median()),
            total=float(g["Total Distance [m]"].median()),
            sessions=g["session"].nunique()))
    return pd.DataFrame(rows).set_index("club").loc[CLUB_ORDER]


def gap_verdict(g):
    """One rule, used by the ladder chart and the ladder table alike."""
    if g.gap < 0:
        return CRITICAL, "x", "inverted - longer club is shorter"
    if g.pi < 0.70:
        return CRITICAL, "x", "not separated - one club of range"
    if g.pi < 0.80:
        return WARNING, "!", "marginal - shorter wins 1 in 4"
    if g.gap > 20:
        return WARNING, "!", "separated, but step is oversized"
    return GOOD, "+", "clean rung"


def gap_table(full):
    rows = []
    for a, b in zip(CLUB_ORDER[:-1], CLUB_ORDER[1:]):
        xa, xb = carry(full, a), carry(full, b)
        ba = xa[RNG.integers(0, len(xa), (BOOT, len(xa)))]
        bb = xb[RNG.integers(0, len(xb), (BOOT, len(xb)))]
        ci = np.percentile(np.median(ba, 1) - np.median(bb, 1), [2.5, 97.5])
        sp = np.sqrt(((len(xa) - 1) * xa.var(ddof=1)
                      + (len(xb) - 1) * xb.var(ddof=1))
                     / (len(xa) + len(xb) - 2))
        rows.append(dict(
            a=a, b=b, gap=float(np.median(xa) - np.median(xb)),
            lo=ci[0], hi=ci[1],
            pi=float((xa[:, None] > xb[None, :]).mean()),
            d=(xa.mean() - xb.mean()) / sp,
            p=stats.mannwhitneyu(xa, xb, alternative="two-sided").pvalue))
    return pd.DataFrame(rows)


def variance_components(full):
    out = {}
    for c in CLUB_ORDER:
        g = full[full["Club Type"] == c].rename(
            columns={"Carry Distance [m]": "carry"})
        ns = g["session"].nunique()
        if ns < 2:
            out[c] = (np.nan, g["carry"].std(ddof=1), np.nan, ns)
            continue
        try:
            m = smf.mixedlm("carry ~ 1", g, groups=g["session"]).fit(reml=True)
            vb, vw = max(float(m.cov_re.iloc[0, 0]), 0.0), float(m.scale)
            out[c] = (np.sqrt(vb), np.sqrt(vw), vb / (vb + vw), ns)
        except Exception:
            out[c] = (np.nan, g["carry"].std(ddof=1), np.nan, ns)
    return out


def strike_r2(full):
    out = {}
    for c in CLUB_ORDER:
        g = full[full["Club Type"] == c]
        if len(g) < 10:
            continue
        y = g["Carry Distance [m]"]
        out[c] = (
            sm.OLS(y, sm.add_constant(g[["Ball Speed [km/h]"]])).fit().rsquared,
            sm.OLS(y, sm.add_constant(g[["Ball Speed [km/h]",
                                         "Launch Angle [deg]",
                                         "Spin Rate [rpm]"]])).fit().rsquared)
    return out


def oncourse():
    d = pd.read_csv("shotscope/golf_shots.csv")
    d = d[(d.stroke_type == "Hit") & (d.club != "Putter")]
    rows = []
    for c, g in d.groupby("club"):
        x = g["distance_m"].values.reshape(-1, 1)
        if len(x) < 20:
            continue
        gm = GaussianMixture(2, random_state=0, n_init=10).fit(x)
        mu, w = gm.means_.ravel(), gm.weights_
        sd = np.sqrt(gm.covariances_.ravel())
        top = int(np.argmax(mu))
        rows.append(dict(club=c, n=len(x), mu_full=mu[top], sd_full=sd[top],
                         w_full=w[top], mu_part=mu[1 - top],
                         n_full=int((gm.predict(x) == top).sum())))
    return d, pd.DataFrame(rows).set_index("club")


def flagcv(cv):
    if cv <= 6:
        return "+", GOOD
    if cv <= 12:
        return "!", WARNING
    return "x", CRITICAL


# ================================================================ pages ====
TOTAL = 13


def p01_cover(fig, D):
    t, lw = D["t"], D["lw"]
    fig.text(L, 0.947,
             "GARMIN APPROACH R10  ·  LAUNCH-MONITOR SESSIONS  ·  APRIL 2026",
             color=S1, fontsize=7.6, weight="bold")
    fig.text(L, 0.928, "Carry distance,", color=INK, fontsize=30,
             weight="bold", va="top")
    fig.text(L, 0.888, "dispersion and gapping", color=INK, fontsize=30,
             weight="bold", va="top")
    para(fig, L, 0.845,
         f"A statistical profile of {D['player']}'s bag from {D['n_used']} logged "
         f"strikes across {len(D['sessions'])} range sessions, cross-checked "
         f"against {D['n_course']} GPS-tracked strokes (putts excluded) from "
         f"{D['n_rounds']} rounds of play.", size=9.6, color=INK2, ls=1.55)
    rule(fig, 0.808)

    w, h, gp = 0.208, 0.086, 0.0227
    y = 0.700
    nine, five = t.loc["9 Iron"], t.loc["5 Iron"]
    tile(fig, L, y, w, h, f"{nine.cv:.1f}%", "tightest club (n > 20)",
         f"9 iron  ·  s = {nine.sd:.1f} m\non {int(nine.n)} strikes", S1)
    tile(fig, L + w + gp, y, w, h, f"{five.cv:.1f}%", "loosest club",
         f"5 iron  ·  s = {five.sd:.1f} m\nspans {five.lo:.0f}-{five.hi:.0f} m",
         CRITICAL)
    tile(fig, L + 2 * (w + gp), y, w, h, f"{D['cone']:.1f}°", "dispersion cone",
         "angular SD of the\ncarry line, whole bag", INK)
    tile(fig, L + 3 * (w + gp), y, w, h, f"+{t.loc['7 Iron'].lat_mean:.0f} m",
         "mid-iron push", "7 iron mean offline\np < 0.001, n = 31", SERIOUS)

    y = heading(fig, L, 0.666, "The bag, as measured", 13)
    y = para(fig, L, y + 0.004,
             "Carry is the number to club off; the 80% window is where four shots in five actually finished. "
             "Roll and total are medians on range turf in cool April air, and will run further on a firm "
             "summer fairway - see page 12 for the on-course check.", size=7.8, frac=0.86)

    cols = [C("CLUB", 0.0), C("N", 0.130, "r"), C("CARRY", 0.215, "r"),
            C("95% CI ON CARRY", 0.350, "r"), C("80% CARRY WINDOW", 0.528, "r"),
            C("SPREAD s", 0.625, "r"), C("CV", 0.700, "r"),
            C("ROLL", 0.775, "r"), C("TOTAL", 0.855, "r")]
    rows = []
    for c in CLUB_ORDER:
        r = t.loc[c]
        mk, col = flagcv(r.cv)
        rows.append([(c, INK, "bold"), f"{int(r.n)}", (f"{r.med:.0f} m", INK, "bold"),
                     f"{r.med_lo:.0f} - {r.med_hi:.0f}",
                     (f"{r.p10:.0f} - {r.p90:.0f} m", INK, "normal"),
                     f"{r.sd:.1f}", (f"{mk} {r.cv:.1f}%", col, "bold"),
                     f"+{r.roll:.0f}", f"{r.total:.0f}"])
    rows.append([("Lob Wedge", INK, "bold"), f"{lw['n30']} + {lw['n50']}",
                 (f"{lw['m30']:.0f} / {lw['m50']:.0f} m", INK, "bold"),
                 ("partial shots", MUTED, "normal"),
                 ("to 30 m / 50 m targets", MUTED, "normal"),
                 f"{lw['s30']:.1f} / {lw['s50']:.1f}",
                 (f"! {lw['cv30']:.0f} / {lw['cv50']:.0f}%", WARNING, "bold"),
                 "—", "—"])
    y = draw_table(fig, L, y - 0.012, cols, rows, size=7.6, ls=1.55)

    y = heading(fig, L, y - 0.024, "What the numbers say", 13)
    bullets(fig, L, y + 0.002, [
        ("The 5 iron is not a 5 iron.", CRITICAL,
         f"Its median carry ({t.loc['5 Iron'].med:.0f} m) is "
         f"{t.loc['6 Iron'].med - t.loc['5 Iron'].med:.0f} m SHORTER than the 6 iron's, "
         f"and its spread (s = {t.loc['5 Iron'].sd:.1f} m) is three times the 6 iron's. "
         "It is the only inverted rung in the bag."),
        ("Two rungs of the ladder are broken, and four more are marginal.", WARNING,
         "5i/6i and 8i/9i overlap so far that the longer club wins under 65% of shot pairs; Dr/5W, 5W/5i, "
         "6i/7i and 7i/8i all sit in the 0.75-0.78 band. Effective gapping is seven clubs wide, not ten."),
        ("Direction is a bigger leak than distance.", SERIOUS,
         f"Offline spread scales at {D['cone']:.1f}° of carry - "
         f"±{t.loc['Driver'].lat_sd:.0f} m with the driver, before any bias at all. "
         "The 7 and 9 irons carry a significant push on top of that."),
        ("Day-to-day drift is small; strike quality is everything.", GOOD,
         "Between-session variance is under 5% of the total for five of seven repeated clubs, and clubhead "
         "speed explains under half of the carry spread in the scoring irons."),
    ], hsize=8.8, bsize=7.9, gap=0.014)

    footer(fig, 1, TOTAL,
           "Carry, roll and total are Garmin's flight-model outputs from measured ball speed and launch, with "
           "spin estimated on 78% of strikes. CV = s / mean. One radar artefact excluded; see page 2.")


def p02_method(fig, D):
    y = header(fig, "Page 2", "Data, exclusions and method",
               f"Every number in this report comes from {D['n_used']} usable strikes logged over six range "
               "sessions between 11 and 19 April 2026. This page states what was kept, what was dropped, and "
               "which estimator is used where - so any figure can be reproduced or contested.")

    y = heading(fig, L, y, "The sample", 11.5)
    cols = [C("SESSION", 0.0), C("SHOTS", 0.155, "r"), C("CLUBS", 0.225, "r"),
            C("AIR DENSITY", 0.345, "r"), C("TEMP", 0.415, "r"),
            C("RH", 0.465, "r"), C("SESSION NOTE", 0.505, "l", 0.375)]
    rows = []
    for s, g in D["df"].groupby("session"):
        rows.append([s.strftime("%a %d %b %Y"), f"{len(g)}",
                     f"{g['Club Type'].nunique()}",
                     f"{g['Air Density [g/L]'].mean():.3f} g/L",
                     f"{g['Temperature [deg C]'].mean():.1f} °C",
                     f"{g['Relative Humidity [%]'].mean():.0f}%",
                     (str(g["Note"].dropna().iloc[0]) if g["Note"].notna().any()
                      else "—")])
    y = draw_table(fig, L, y, cols, rows, size=7.3)

    a = D["artefact"]
    y = heading(fig, L, y - 0.016, "Exclusions and stratification", 11.5)
    y = bullets(fig, L, y + 0.002, [
        ("1 shot removed - radar artefact", CRITICAL,
         f"A “Sand Wedge” logged at {a['Club Speed [km/h]'].iloc[0]:.1f} km/h of club speed and "
         f"{a['Ball Speed [km/h]'].iloc[0]:.1f} km/h of ball speed, carrying "
         f"{a['Carry Distance [m]'].iloc[0]:.0f} m. That club speed is "
         f"{a['Club Speed [km/h]'].iloc[0] - D['max_cs']:.0f} km/h above the fastest driver swing in the "
         "file, so it is a sensor fault rather than a mishit. It is the only shot removed."),
        ("21 lob-wedge shots split out, not pooled", WARNING,
         "Both LW blocks were hit to a nominated target (“Goal: carry 30”, “Goal: carry 50”). "
         "They are two distance-control samples with different means by design; pooling them would "
         "manufacture a bimodal “distribution” that describes nothing. They are analysed on page 11 "
         "and excluded from the gapping ladder."),
        ("0 mishits removed - deliberately", GOOD,
         "The thinned 8 iron (63.9 m carry off a normal 167 km/h ball speed at a 4.3° launch), the "
         "chunked 5 iron (smash 1.00) and the skied driver (7 680 rpm) all stay in. They are strikes you will "
         "repeat on the course, and a yardage built on your good swings only is a yardage that is short when "
         "it matters. Where they distort a moment, the robust twin is reported beside it."),
    ], hsize=8.6, bsize=7.7, gap=0.008)

    y = heading(fig, L, y - 0.014, "Estimators used, and why", 11.5)
    cols = [C("QUANTITY", 0.0, "l", 0.155), C("ESTIMATOR", 0.175, "l", 0.305),
            C("RATIONALE", 0.500, "l", 0.380)]
    rows = [
        ["Typical carry", "Median; H-L and a 10% trimmed mean alongside",
         "Carry is left-skewed: a mishit loses 40 m, a flush one gains 8."],
        ["Spread", "SD and MAD-based SD (1.4826 × MAD)",
         "SD far above MAD-SD means the tail is wide, not the body."],
        ["Uncertainty", "Non-parametric bootstrap, 20 000 resamples",
         "No distributional assumption, and honest at n = 8."],
        ["Planning window", "Empirical p10-p90 and an 80/90 tolerance interval",
         "It covers 80% of future shots with 90% confidence."],
        ["Club separation", "P(A > B) over all shot pairs, plus Mann-Whitney U",
         "“How often does the longer club win” is the real question."],
        ["Two-way dispersion", "50% and 90% covariance ellipses (chi-square, 2 df)",
         "Carry and offline error are correlated in the wedges."],
        ["Day-to-day drift", "Random-intercept model on session (REML), with ICC",
         "Separates “the club changed” from “that swing was poor”."],
        ["On-course distance", "Two-component Gaussian mixture on GPS shot length",
         "Course data mixes full swings with layups and chips."],
    ]
    y = draw_table(fig, L, y, cols, rows, size=7.4)

    y = heading(fig, L, y - 0.016,
                "Three caveats worth carrying through the report", 11.5)
    y = para(fig, L, y + 0.002,
             "•  Carry is modelled, not measured.  The R10 measures ball speed and launch, then flies the "
             "ball through a model. Spin was estimated rather than measured on 165 of 211 strikes, so part of "
             "the carry spread here is the model's sensitivity to that estimate rather than ball flight. "
             "Treat it as an upper bound on true dispersion.", size=7.7)
    y = para(fig, L, y - 0.007,
             "•  n is small for half the bag.  Five clubs have fewer than 18 strikes. A spread estimated "
             "from 8 shots has a 95% interval running from 0.66× to 2.04× the number you computed - a "
             "threefold range. Page 5 shows which conclusions survive that and which do not.", size=7.7)
    para(fig, L, y - 0.007,
         "•  Range air was cool and dense.  Session air density ran 1.19-1.23 g/L at 13-21 °C. Warm "
         "summer air is nearer 1.16 g/L, worth roughly +2% of carry - part of the on-course gap on page 12, "
         "and not separable there from turf roll.", size=7.7)

    footer(fig, 2, TOTAL,
           "Source: data.xlsx, sheet “Michiel”, rows 1-212, and shotscope/golf_shots.csv. "
           "Analysis: distance_report.py.")


def p03_distributions(fig, D):
    t, full = D["t"], D["full"]
    header(fig, "Page 3", "Where every shot finished",
           "One row per club, ordered by median carry. The heavy bar is the interquartile range, the thin "
           "whisker the 10th to 90th percentile, and every logged strike is drawn behind it. The width of a "
           "row is the club's honest yardage - not the number stamped on its sole.")

    ax = fig.add_axes([0.145, 0.352, R - 0.145, 0.512])
    style(ax, xgrid=True, ygrid=False)
    order = t.sort_values("med").index.tolist()
    for i, c in enumerate(order):
        r = t.loc[c]
        x = carry(full, c)
        ax.scatter(x, i + RNG.normal(0, 0.085, len(x)), s=9, color=S1,
                   alpha=0.30, lw=0, zorder=3)
        ax.plot([r.p10, r.p90], [i, i], color=BLUE_550, lw=1.4, zorder=4,
                solid_capstyle="butt")
        ax.plot([r.p25, r.p75], [i, i], color=BLUE_550, lw=6.5, zorder=5,
                solid_capstyle="butt")
        ax.scatter([r.med], [i], s=46, color=SURFACE, zorder=6, lw=0)
        ax.scatter([r.med], [i], s=22, color=INK, zorder=7, lw=0)
        ax.text(r.p90 + 3, i, f"{r.med:.0f} m", fontsize=7.6, color=INK,
                weight="bold", va="center")
        ax.text(229, i, f"n = {int(r.n)}", fontsize=6.9, color=MUTED,
                va="center", ha="right")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order, fontsize=8.2, color=INK)
    ax.set_xlabel("Carry distance (m)")
    ax.set_xlim(55, 231)
    ax.set_ylim(-0.75, len(order) - 0.25)

    y = heading(fig, L, 0.312, "Reading the rows", 11.5)
    bullets(fig, L, y + 0.002, [
        ("The 5 iron row is four times as wide as the 6 iron row, and sits to the left of it.", CRITICAL,
         "Two clusters are visible inside it - the 11 April session (median 109 m) and the 16 April session "
         "(median 148 m). Page 10 tests whether that is a day effect or a strike effect."),
        ("The 8 iron's left whisker reaches 63.9 m while its box is only 11 m wide.", WARNING,
         "That single thinned strike doubles the club's SD. It is why this report carries a robust spread "
         "beside the classical one everywhere, rather than choosing between them."),
        ("The 9 iron and pitching wedge rows are narrower than the gaps around them.", GOOD,
         "Those two clubs are trustworthy to the metre. Nothing else in the bag is, and much of what follows "
         "is an account of why."),
        ("Wherever two boxes share ground on the x axis, the clubs are interchangeable.", SERIOUS,
         "Between the 5 and 6 irons, and between the 8 and 9 irons, the overlap is most of the box. That is "
         "the gapping problem, quantified on page 7."),
    ], hsize=8.4, bsize=7.8, gap=0.011)

    footer(fig, 3, TOTAL,
           "Lob wedge omitted: both its blocks were partial shots to a nominated target, and appear on page 11 "
           "instead. Vertical jitter is cosmetic and carries no information.")


def p04_shape(fig, D):
    t, full = D["t"], D["full"]
    nfail = int((t.sw_p < 0.05).sum())
    word = {1: "One", 2: "Two", 3: "Three"}.get(nfail, str(nfail))
    y = header(fig, "Page 4", "The shape of each distribution",
               f"Whether a club's carry is normal decides which interval you may quote. {word} of the ten "
               "clubs fails the test, and it fails through the left tail - which is exactly the tail that "
               "matters when the question is whether a shot will carry.")

    cols = [C("CLUB", 0.0), C("N", 0.125, "r"), C("MEAN", 0.185, "r"),
            C("MEDIAN", 0.25, "r"), C("H-L", 0.31, "r"), C("TRIM 10%", 0.38, "r"),
            C("s", 0.435, "r"), C("MAD-s", 0.50, "r"), C("s / MAD-s", 0.585, "r"),
            C("SKEW", 0.65, "r"), C("EX. KURT", 0.725, "r"),
            C("SHAPIRO-WILK p", 0.825, "r"), C("NORMAL?", 0.822, "l")]
    rows = []
    for c in CLUB_ORDER:
        r = t.loc[c]
        ratio = r.sd / r.madsd
        ok = r.sw_p >= 0.05
        rows.append([
            (c, INK, "bold"), f"{int(r.n)}", f"{r.avg:.1f}",
            (f"{r.med:.1f}", INK, "bold"), f"{r.hl:.1f}", f"{r.tr10:.1f}",
            f"{r.sd:.1f}", f"{r.madsd:.1f}",
            (f"{ratio:.2f}", CRITICAL if ratio > 1.25 else INK2,
             "bold" if ratio > 1.25 else "normal"),
            (f"{r.skw:+.2f}", CRITICAL if abs(r.skw) > 1 else INK2, "normal"),
            (f"{r.krt:+.2f}", CRITICAL if r.krt > 2 else INK2, "normal"),
            f"{r.sw_p:.4f}" if r.sw_p >= 0.0001 else "<0.0001",
            (("+  yes" if ok else "x  no"), GOOD if ok else CRITICAL, "bold")])
    y = draw_table(fig, L, y, cols, rows, size=7.3)

    y = heading(fig, L, y - 0.024, "Normal quantile plots", 11)
    para(fig, L, y + 0.002,
         "Clubs with at least 13 strikes. Points on the line are normal; a hook down at the left is a mishit "
         "tail.", size=7.6)

    panels = [c for c in CLUB_ORDER if t.loc[c].n >= 13]
    pw, ph, gx, gy = 0.1983, 0.113, 0.0293, 0.050
    y0 = y - 0.032 - ph
    for i, c in enumerate(panels[:8]):
        rr, cc = divmod(i, 4)
        ax = fig.add_axes([L + cc * (pw + gx), y0 - rr * (ph + gy), pw, ph])
        style(ax)
        x = carry(full, c)
        (osm, osr), (slope, inter, _) = stats.probplot(x, dist="norm")
        ax.plot(osm, slope * osm + inter, color=AXIS, lw=1.0, zorder=2)
        ax.scatter(osm, osr, s=10, color=S1, lw=0, alpha=0.85, zorder=3)
        p = t.loc[c].sw_p
        ax.set_title(f"{c}   n = {len(x)}", fontsize=7.8, color=INK,
                     weight="bold", loc="left", pad=3)
        ax.text(0.97, 0.06, f"W p = {p:.3f}" if p >= 0.001 else "W p < 0.001",
                transform=ax.transAxes, ha="right", fontsize=6.6,
                color=CRITICAL if p < 0.05 else MUTED, weight="bold")
        if rr == 1:
            ax.set_xlabel("theoretical quantile", fontsize=6.6, labelpad=1)
        if cc == 0:
            ax.set_ylabel("carry (m)", fontsize=6.6, labelpad=1)

    y = heading(fig, L, y0 - (ph + gy) - 0.030, "What the departures mean", 11)
    y = para(fig, L, y + 0.002,
             "The 8 iron fails hardest, and it fails on one shot: skew −2.22 with excess kurtosis +9.62 "
             "is the signature of a single extreme point, not of a wide body. Its s/MAD-s ratio of 1.30 says "
             "the same thing from the other side - drop the tail and it is a ±11 m club, keep it and it "
             "is a ±14 m club. Both are true and they answer different questions: use the robust number "
             "to judge your striking, the classical one to decide whether to take on a carry.", size=7.8)
    para(fig, L, y - 0.008,
         "The driver's mild left skew (−0.53) is the ordinary shape of a full-swing distribution and does "
         "not fail the test. The 5 iron's flat kurtosis (−1.04) is not a heavy tail either - it is the "
         "signature of two sessions sitting at different means, which page 10 confirms.", size=7.8)

    footer(fig, 4, TOTAL,
           "Shapiro-Wilk at α = 0.05 with no multiplicity correction; across ten tests, expect roughly "
           "one false rejection every two reports of this size. H-L is the Hodges-Lehmann pseudomedian.")


def p05_uncertainty(fig, D):
    t = D["t"]
    y = header(fig, "Page 5", "How much of this is real",
               "Every number on page 3 is an estimate from a handful of swings. These are their 95% bootstrap "
               "intervals. Where an interval is wide, the club has not been measured - it has been glimpsed.")

    order = t.sort_values("med").index.tolist()
    ax = fig.add_axes([L + 0.030, y - 0.278, 0.375, 0.250])
    style(ax, xgrid=True, ygrid=False)
    for i, c in enumerate(order):
        r = t.loc[c]
        ax.plot([r.med_lo, r.med_hi], [i, i], color=S1, lw=1.6, zorder=3,
                solid_capstyle="round")
        ax.scatter([r.med], [i], s=34, color=SURFACE, lw=0, zorder=4)
        ax.scatter([r.med], [i], s=17, color=BLUE_550, lw=0, zorder=5)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([SHORT[c] for c in order], fontsize=7.6, color=INK)
    ax.set_xlabel("Median carry, 95% bootstrap CI (m)")
    ax.set_title("Where the club's centre is", fontsize=9.5, color=INK,
                 weight="bold", loc="left", pad=6)
    ax.set_ylim(-0.7, len(order) - 0.3)

    ax2 = fig.add_axes([L + 0.505, y - 0.278, 0.375, 0.250])
    style(ax2, xgrid=True, ygrid=False)
    for i, c in enumerate(order):
        r = t.loc[c]
        ax2.plot([r.sd_lo, r.sd_hi], [i, i], color=S2, lw=1.6, zorder=3,
                 solid_capstyle="round")
        ax2.scatter([r.sd], [i], s=34, color=SURFACE, lw=0, zorder=4)
        ax2.scatter([r.sd], [i], s=17, color=S2, lw=0, zorder=5)
        ax2.text(r.sd_hi + 0.9, i, f"{r.sd:.1f}", fontsize=6.8, color=INK2,
                 va="center")
    ax2.set_yticks(range(len(order)))
    ax2.set_yticklabels([SHORT[c] for c in order], fontsize=7.6, color=INK)
    ax2.set_xlabel("Carry SD, 95% bootstrap CI (m)")
    ax2.set_title("How wide the club is", fontsize=9.5, color=INK,
                  weight="bold", loc="left", pad=6)
    ax2.set_ylim(-0.7, len(order) - 0.3)
    ax2.set_xlim(0, 37)

    y = heading(fig, L, y - 0.322,
                "The centre is well pinned; the spread is not", 11)
    y = para(fig, L, y + 0.002,
             "Median carry is known to within ±3 m on the well-sampled clubs (7i, 9i, PW) and to "
             "±20 m on the 5 iron. But the SD intervals on the right overlap almost universally: on this "
             "data you cannot claim the 6 iron is a tighter club than the 8 iron, only that the 5 iron is "
             "looser than everything. Spread needs far more shots than centre does - the table below is why.",
             size=7.8)

    y = heading(fig, L, y - 0.020, "What a sample of n buys you", 11)
    cols = [C("SHOTS n", 0.0), C("CLUBS AT THIS n", 0.145),
            C("95% CI FOR σ, AS A MULTIPLE OF THE OBSERVED s", 0.555, "r"),
            C("WIDTH", 0.615, "r"), C("VERDICT", 0.645)]
    rows = []
    for n in (6, 8, 13, 17, 26, 31, 35, 50, 75, 100):
        lo = np.sqrt((n - 1) / stats.chi2.ppf(0.975, n - 1))
        hi = np.sqrt((n - 1) / stats.chi2.ppf(0.025, n - 1))
        clubs = ", ".join(SHORT[c] for c in CLUB_ORDER if int(t.loc[c].n) == n)
        ratio = hi / lo
        if ratio > 2.5:
            v, col, mk = "spread essentially unmeasured", CRITICAL, "x"
        elif ratio > 1.9:
            v, col, mk = "spread indicative only", CRITICAL, "x"
        elif ratio > 1.55:
            v, col, mk = "spread usable for ranking clubs", WARNING, "!"
        else:
            v, col, mk = "spread usable as a planning number", GOOD, "+"
        rows.append([(f"n = {n}", INK, "bold"),
                     (clubs if clubs else "—", INK2, "normal"),
                     f"{lo:.2f}×  to  {hi:.2f}×", f"{ratio:.1f}×",
                     (f"{mk}  {v}", col, "bold")])
    y = draw_table(fig, L, y, cols, rows, size=7.4)

    y = heading(fig, L, y - 0.024, "The practical consequence", 11)
    para(fig, L, y + 0.002,
         "To state a club's dispersion to within ±20% - tight enough to track whether practice is working "
         "- you need roughly 50 strikes of that club, gathered across at least three sessions so the day "
         "effect sits inside the estimate rather than confounded with it. Only the 8 iron (35) and 7 iron (31) "
         "come close. A hundred-ball session spread over ten clubs measures nothing about any of them; the "
         "same hundred balls over two clubs measures both properly. If you take one number from this page: "
         "rotate a two-club block rather than a ten-club buffet, and five sessions will give you publishable "
         "dispersion on the whole bag.", size=7.8)

    footer(fig, 5, TOTAL,
           "The two panels are different quantities on different scales and are deliberately drawn as two "
           "charts rather than one with two axes. The CI for σ assumes normality; on the club that fails "
           "page 4's test the true interval is wider still.")


def p06_intervals(fig, D):
    t = D["t"]
    y = header(fig, "Page 6", "The number to club off",
               "A median is what a club does on average; it is not what to aim with. These are prediction "
               "windows - the observed middle 80% of shots, and the interval that covers 80% of future shots "
               "with 90% confidence given how little data stands behind it.")

    order = t.sort_values("med").index.tolist()
    ax = fig.add_axes([0.145, y - 0.340, R - 0.145, 0.296])
    style(ax, xgrid=True, ygrid=False)
    for i, c in enumerate(order):
        r = t.loc[c]
        ax.plot([r.ti_lo, r.ti_hi], [i + 0.18, i + 0.18], color=S2, lw=3.4,
                solid_capstyle="butt", zorder=3)
        ax.plot([r.p10, r.p90], [i - 0.18, i - 0.18], color=S1, lw=3.4,
                solid_capstyle="butt", zorder=3)
        ax.scatter([r.med], [i], s=30, color=SURFACE, lw=0, zorder=5)
        ax.scatter([r.med], [i], s=15, color=INK, lw=0, zorder=6)
        ax.text(247, i, f"{r.ti_hi - r.ti_lo:.0f} m wide", fontsize=6.9,
                color=INK2, va="center", ha="right")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order, fontsize=8, color=INK)
    ax.set_xlabel("Carry distance (m)")
    ax.set_xlim(60, 248)
    ax.set_ylim(-0.8, len(order) - 0.2)
    ax.legend(handles=[
        Line2D([], [], color=S1, lw=3.4, label="Observed middle 80% (p10-p90)"),
        Line2D([], [], color=S2, lw=3.4,
               label="80/90 tolerance interval - covers 80% of future shots"),
        Line2D([], [], color=INK, lw=0, marker="o", ms=4, label="Median")],
        loc="lower left", bbox_to_anchor=(0.0, 1.005), ncol=3, handlelength=1.6,
        borderpad=0.1)

    y = heading(fig, L, y - 0.374,
                "The two intervals disagree, and the gap is the sample size", 11)
    y = para(fig, L, y + 0.002,
             "For the 7 iron (n = 31) the tolerance interval is 29 m wide against an observed 24 m - a modest "
             "premium for uncertainty. For the 5 wood (n = 6) it is 86 m wide against an observed 35 m. That "
             "is not a wild club; it is a club about which almost nothing is known. Quote the blue bar when "
             "describing what has happened, and the orange bar when committing to a carry over trouble.",
             size=7.8)

    y = heading(fig, L, y - 0.020, "Carry-over-hazard numbers", 11)
    y = para(fig, L, y + 0.002,
             "The 10th percentile is the honest answer to “will it clear?” - it fails one shot in ten; "
             "the 5th is the number for water.", size=7.6)
    cols = [C("CLUB", 0.0), C("N", 0.115, "r"), C("MEDIAN CARRY", 0.215, "r"),
            C("p25", 0.285, "r"), C("p10 · CLEARS 9 IN 10", 0.415, "r"),
            C("p05 · CLEARS 19 IN 20", 0.565, "r"),
            C("SHORTEST LOGGED", 0.675, "r"), C("TOLERANCE FLOOR", 0.785, "r"),
            C("SAFETY MARGIN", 0.798, "l")]
    rows = []
    for c in CLUB_ORDER:
        r = t.loc[c]
        loss = r.med - r.p10
        mk, col = (("+", GOOD) if loss <= 10 else
                   ("!", WARNING) if loss <= 18 else ("x", CRITICAL))
        rows.append([(c, INK, "bold"), f"{int(r.n)}", (f"{r.med:.0f} m", INK, "bold"),
                     f"{r.p25:.0f}", (f"{r.p10:.0f} m", INK, "bold"),
                     f"{r.p05:.0f} m", f"{r.lo:.0f} m", f"{r.ti_lo:.0f} m",
                     (f"{mk}  −{loss:.0f} m", col, "bold")])
    y = draw_table(fig, L, y - 0.008, cols, rows, size=7.4)

    y = heading(fig, L, y - 0.024,
                "Read the last column as your safety margin", 11)
    para(fig, L, y + 0.002,
         "It is the drop from median carry to the one-in-ten short shot. The pitching wedge gives up 4 m and "
         "the 9 iron 7 m: with those two you can attack a front pin. The 5 iron gives up 39 m and the driver "
         "30 m - with those, the pin is irrelevant and the front edge is the target. Note that the margin is "
         "not proportional to distance: the 8 iron surrenders 13 m and the 6 iron 7 m, though they carry "
         "within 16 m of each other. That asymmetry is a striking problem, not a yardage one.", size=7.8)

    footer(fig, 6, TOTAL,
           "Tolerance factor k by Howe's approximation, two-sided, p = 0.80 content at γ = 0.90 "
           "confidence. It assumes normality, so it is optimistic for the 8 iron, which fails page 4's test, "
           "and the empirical percentiles should be preferred there.")


def p07_gapping(fig, D):
    t, gaps = D["t"], D["gaps"]
    y = header(fig, "Page 7", "Gapping: does the ladder have rungs?",
               "A gap is only real if the longer club reliably out-carries the shorter one. P(longer wins) "
               "counts that over every shot pair: at 0.50 the two clubs are interchangeable, and below about "
               "0.75 you cannot tell them apart on the course.")

    ax = fig.add_axes([L + 0.030, y - 0.298, R - L - 0.030, 0.260])
    style(ax, xgrid=True, ygrid=False)
    ys = list(range(len(CLUB_ORDER)))[::-1]
    for i, c in zip(ys, CLUB_ORDER):
        r = t.loc[c]
        ax.plot([r.p10, r.p90], [i, i], color=BLUE_250, lw=2.0,
                solid_capstyle="butt", zorder=3)
        ax.plot([r.p25, r.p75], [i, i], color=S1, lw=7.0,
                solid_capstyle="butt", zorder=4)
        ax.scatter([r.med], [i], s=40, color=SURFACE, lw=0, zorder=5)
        ax.scatter([r.med], [i], s=19, color=INK, lw=0, zorder=6)
    for _, g in gaps.iterrows():
        ia, ib = ys[CLUB_ORDER.index(g.a)], ys[CLUB_ORDER.index(g.b)]
        col, mk, _ = gap_verdict(g)
        ax.annotate("", xy=(t.loc[g.a].med, ia), xytext=(t.loc[g.b].med, ib),
                    arrowprops=dict(arrowstyle="-", color=col, lw=1.0,
                                    shrinkA=7, shrinkB=7), zorder=2)
        ax.text((t.loc[g.a].med + t.loc[g.b].med) / 2, (ia + ib) / 2,
                f"{mk} {g.gap:+.0f} m", fontsize=6.9, color=col, weight="bold",
                ha="center", va="center",
                bbox=dict(fc=SURFACE, ec="none", pad=1.2))
    ax.set_yticks(ys)
    ax.set_yticklabels([SHORT[c] for c in CLUB_ORDER], fontsize=8, color=INK,
                       weight="bold")
    ax.set_xlabel("Carry distance (m)")
    ax.set_xlim(55, 215)
    ax.set_ylim(-0.7, len(CLUB_ORDER) - 0.3)
    ax.set_title("Clubs in loft order, top to bottom. Heavy bar = IQR, thin bar = p10-p90.",
                 fontsize=7.3, color=MUTED, loc="left", pad=5)

    cols = [C("STEP", 0.0), C("GAP IN MEDIAN CARRY", 0.195, "r"),
            C("95% CI ON THE GAP", 0.325, "r"), C("P(LONGER WINS)", 0.425, "r"),
            C("COHEN d", 0.505, "r"), C("MANN-WHITNEY p", 0.630, "r"),
            C("VERDICT", 0.655, "l", 0.225)]
    rows = []
    for _, g in gaps.iterrows():
        col, mk, v = gap_verdict(g)
        rows.append([(f"{SHORT[g.a]} → {SHORT[g.b]}", INK, "bold"),
                     (f"{g.gap:+.1f} m", INK, "bold"),
                     f"{g.lo:+.0f} to {g.hi:+.0f}", (f"{g.pi:.2f}", col, "bold"),
                     f"{g.d:+.2f}",
                     f"{g.p:.4f}" if g.p >= 0.0001 else "<0.0001",
                     (f"{mk}  {v}", col, "bold")])
    y = draw_table(fig, L, y - 0.340, cols, rows, size=7.4)

    y = heading(fig, L, y - 0.024, "Three findings, in order of cost", 11.5)
    bullets(fig, L, y + 0.002, [
        ("The 5 iron / 6 iron rung is inverted", CRITICAL,
         f"The 5 iron's median carry is {abs(gaps.iloc[2].gap):.1f} m short of the 6 iron's and it wins only "
         f"{gaps.iloc[2].pi * 100:.0f}% of pairs. The 95% CI on the gap runs from {gaps.iloc[2].lo:+.0f} to "
         f"{gaps.iloc[2].hi:+.0f} m, so the direction is not established - but nothing in the data supports "
         "the 5 iron being the longer club. Either the shaft or the lie is wrong for you, or the club is long "
         "enough that you are steering it. On this evidence it adds no reachable distance."),
        ("The 8 iron / 9 iron rung barely exists", WARNING,
         "4.9 m apart, P(win) = 0.62, d = 0.23, and Mann-Whitney does not reject at p = 0.12. Two clubs are "
         "covering one club's worth of ground. On a 130 m approach the choice between them is a coin flip "
         "dressed as a decision - which is a strong argument for taking the 9 iron every time and removing "
         "the deliberation entirely."),
        ("Everything from the 9 iron down is clean, and the PW/GW step is too big", GOOD,
         "9i→PW (P = 0.89), PW→GW (P = 1.00, d = 3.61) and GW→SW (P = 0.87) all separate "
         "properly. But the PW→GW step is 22 m against a bag average of 11 m: there is a hole between 93 "
         "and 115 m, exactly where a scoring approach lives. A 50° wedge, or a rehearsed three-quarter "
         "pitching wedge, fills it."),
    ], hsize=8.7, bsize=7.7, gap=0.011)

    footer(fig, 7, TOTAL,
           "P(longer wins) is the probabilistic index P(A > B) estimated over all n_A × n_B shot pairs; "
           "it is Mann-Whitney U rescaled and needs no distributional assumption. Cohen d uses the pooled SD "
           "and is reported for comparability only. The colour rule is identical in the chart and the table.")


def p08_ellipses(fig, D):
    t, full = D["t"], D["full"]
    y = header(fig, "Page 8", "Two-dimensional dispersion",
               "Distance error and direction error are not independent, so they are drawn together: looking "
               "down the target line, offline across and carry up. The ellipses hold 50% and 90% of the "
               "fitted bivariate normal; the dashed centre line is the target.")

    panels = [c for c in CLUB_ORDER if t.loc[c].n >= 8]
    pw, ph, gx, gy = 0.268, 0.095, 0.038, 0.044
    y0 = y - 0.018 - ph
    for i, c in enumerate(panels[:9]):
        rr, cc = divmod(i, 3)
        ax = fig.add_axes([L + cc * (pw + gx), y0 - rr * (ph + gy), pw, ph])
        style(ax)
        g = full[full["Club Type"] == c]
        X = g["Carry Deviation Distance [m]"].values
        Y = g["Carry Distance [m]"].values
        mu = np.array([X.mean(), Y.mean()])
        cov = np.cov(np.vstack([X, Y]))
        ev, evec = np.linalg.eigh(cov)
        ang = np.degrees(np.arctan2(evec[1, -1], evec[0, -1]))
        for q, fc, ec, lwd in ((0.50, S1, "none", 0), (0.90, "none", S1, 1.1)):
            s = np.sqrt(stats.chi2.ppf(q, 2))
            ax.add_patch(Ellipse(mu, 2 * s * np.sqrt(ev[-1]),
                                 2 * s * np.sqrt(ev[0]), angle=ang, fc=fc,
                                 alpha=0.16 if fc != "none" else 1.0,
                                 ec=ec, lw=lwd, zorder=2))
        ax.axvline(0, color=AXIS, lw=0.8, ls=(0, (4, 3)), zorder=1)
        ax.scatter(X, Y, s=9, color=BLUE_550, lw=0, alpha=0.7, zorder=3)
        ax.scatter([mu[0]], [mu[1]], marker="+", s=40, color=INK, lw=1.2, zorder=4)
        span = max(30, np.abs(X).max() * 1.12)
        ax.set_xlim(-span, span)
        ax.set_ylim(Y.mean() - 3.2 * Y.std(ddof=1) - 4,
                    Y.mean() + 3.2 * Y.std(ddof=1) + 4)
        ax.set_title(f"{c}   n = {len(g)}", fontsize=7.8, color=INK,
                     weight="bold", loc="left", pad=3)
        if rr == 2:
            ax.set_xlabel("offline (m):  left ←   → right", fontsize=6.6,
                          labelpad=1)
        if cc == 0:
            ax.set_ylabel("carry (m)", fontsize=6.6, labelpad=1)

    y = heading(fig, L, y0 - 2 * (ph + gy) - 0.032, "Directional bias, tested", 11)
    cols = [C("CLUB", 0.0), C("N", 0.140, "r"), C("MEAN OFFLINE", 0.245, "r"),
            C("MEDIAN", 0.340, "r"), C("SD", 0.412, "r"),
            C("ANGULAR SD", 0.485, "r"), C("CARRY / OFFLINE r", 0.600, "r"),
            C("90% AREA", 0.665, "r"), C("WILCOXON", 0.732, "r"),
            C("BIAS", 0.752, "l", 0.128)]
    rows = []
    for c in CLUB_ORDER:
        r = t.loc[c]
        if r.lat_p >= 0.05:
            v, col, mk = "centred", GOOD, "+"
        elif abs(r.lat_mean) > 8:
            v, col, mk = f"pushed {abs(r.lat_mean):.0f} m right", CRITICAL, "x"
        else:
            v, col, mk = (f"{abs(r.lat_mean):.0f} m "
                          f"{'right' if r.lat_mean > 0 else 'left'}", WARNING, "!")
        rows.append([(c, INK, "bold"), f"{int(r.n)}",
                     (f"{r.lat_mean:+.1f} m", INK, "bold"), f"{r.lat_med:+.1f} m",
                     f"{r.lat_sd:.1f} m", f"{r.ang_sd:.1f}°",
                     (f"{r.rho:+.2f}", CRITICAL if abs(r.rho) > 0.5 else INK2,
                      "bold" if abs(r.rho) > 0.5 else "normal"),
                     f"{r.ell90:.2f} ha",
                     f"{r.lat_p:.4f}" if r.lat_p >= 0.0001 else "<0.0001",
                     (f"{mk}  {v}", col, "bold")])
    y = draw_table(fig, L, y, cols, rows, size=7.3)

    y = heading(fig, L, y - 0.018,
                "Two things the ellipses show that the SDs hide", 11)
    bullets(fig, L, y + 0.002, [
        ("The wedges tilt.", CRITICAL,
         "Gap wedge r = −0.71 and pitching wedge r = −0.54 between offline and carry. Your wedge "
         "miss is a single fault, not two - the ball starts right and comes up short together, which is the "
         "signature of a face open to the path with the low point behind the ball. One correction fixes both "
         "axes; treating distance control and direction as separate practice tasks wastes half the work."),
        ("Bias and spread are different problems with different fixes.", SERIOUS,
         "The 7 iron has the tightest offline SD in the bag (7.2 m) and the largest push (+10.8 m): its "
         "ellipse is small and sitting in the wrong place, which is an aim or face-angle problem correctable "
         "in one session. The driver is the reverse - mean offline +0.8 m, SD 20.6 m. Perfectly aimed, and "
         "41 m wide at two sigma."),
    ], hsize=8.6, bsize=7.7, gap=0.010)

    footer(fig, 8, TOTAL,
           "5 wood omitted from the panels (n = 6). Offline is Garmin's carry deviation distance, positive to "
           "the right. The 90% area is the ellipse's footprint on the ground in hectares - the smallest green "
           "the club could hold nine times in ten, if aimed at its own centre.")


def p09_scaling(fig, D):
    t, fit = D["t"], D["scaling"]
    y = header(fig, "Page 9", "Does the miss scale with the club?",
               "If direction error were a constant angle, offline spread would rise in proportion to carry "
               "and the whole bag would sit on one line through the origin. It nearly does - which means "
               "dispersion is one property of your swing rather than ten properties of ten clubs.")

    ax = fig.add_axes([L + 0.030, y - 0.285, 0.385, 0.258])
    style(ax)
    xs = np.linspace(70, 196, 100)
    ax.plot(xs, fit["b0"] + fit["b1"] * xs, color=AXIS, lw=1.2, zorder=2)
    ax.plot(xs, fit["origin"] * xs, color=S2, lw=1.2, zorder=2)
    for c in CLUB_ORDER:
        r = t.loc[c]
        ax.scatter([r.med], [r.lat_sd], s=14 + 1.5 * r.n, color=S1,
                   alpha=0.75, lw=0, zorder=3)
        below = c in ("5 Wood", "6 Iron")
        ax.text(r.med, r.lat_sd + (-1.6 if below else 1.1), SHORT[c],
                fontsize=6.8, color=INK2, ha="center",
                va="top" if below else "bottom")
    ax.set_xlabel("Median carry (m)")
    ax.set_ylabel("Offline SD (m)")
    ax.set_title("Offline spread against distance", fontsize=9.5, color=INK,
                 weight="bold", loc="left", pad=6)
    ax.set_xlim(70, 198)
    ax.set_ylim(0, 26)
    ax.legend(handles=[
        Line2D([], [], color=AXIS, lw=1.2,
               label=f"WLS fit: SD = {fit['b0']:.1f} + {fit['b1']:.3f}·carry  "
                     f"(R² = {fit['r2']:.2f})"),
        Line2D([], [], color=S2, lw=1.2,
               label=f"Through the origin: a {fit['cone']:.1f}° cone")],
        loc="upper left", handlelength=1.8, borderpad=0.2)

    ax2 = fig.add_axes([L + 0.505, y - 0.285, 0.375, 0.258])
    style(ax2)
    d = np.linspace(0, 200, 50)
    k = np.tan(np.radians(fit["cone"]))
    for m, alpha in ((1, 0.22), (2, 0.11)):
        ax2.add_patch(Polygon(np.vstack([np.column_stack([-m * k * d, d]),
                                         np.column_stack([m * k * d, d])[::-1]]),
                              fc=S1, alpha=alpha, ec="none", zorder=2))
    ax2.axvline(0, color=AXIS, lw=0.8, ls=(0, (4, 3)), zorder=1)
    for c in ("Sand Wedge", "9 Iron", "7 Iron", "Driver"):
        yv = t.loc[c].med
        ax2.scatter([0], [yv], s=15, color=INK, lw=0, zorder=4)
        ax2.text(2.5, yv,
                 f" {SHORT[c]} at {yv:.0f} m:  ±{2 * k * yv:.0f} m at 2σ",
                 fontsize=6.9, color=INK2, va="center")
    ax2.set_xlim(-45, 45)
    ax2.set_ylim(0, 200)
    ax2.set_xlabel("Offline (m)")
    ax2.set_ylabel("Carry (m)")
    ax2.set_title(f"The cone: {fit['cone']:.1f}° either side, at 1σ and 2σ",
                  fontsize=9.5, color=INK, weight="bold", loc="left", pad=6)

    y = heading(fig, L, y - 0.324, "The fit, and the two clubs that break it", 11)
    y = para(fig, L, y + 0.002,
             f"A weighted least-squares fit (weights n−1) explains {fit['r2'] * 100:.0f}% of the "
             f"variation in offline SD across the bag, with a slope of {fit['b1']:.3f} m of spread per metre "
             f"of carry (95% CI {fit['b1lo']:.3f} to {fit['b1hi']:.3f}, p = {fit['p']:.3f}). Forced through "
             f"the origin the slope becomes a single angle: {fit['cone']:.1f}°. That is the number to "
             "carry into course strategy, because it converts any yardage into a width.", size=7.8)

    cols = [C("CLUB", 0.0), C("MEDIAN CARRY", 0.185, "r"),
            C("OFFLINE SD", 0.285, "r"), C("PREDICTED BY THE FIT", 0.425, "r"),
            C("RESIDUAL", 0.495, "r"), C("2σ WIDTH ON THE GROUND", 0.645, "r"),
            C("READ AS", 0.675, "l")]
    rows = []
    for c in CLUB_ORDER:
        r = t.loc[c]
        pred = fit["b0"] + fit["b1"] * r.med
        res = r.lat_sd - pred
        if res < -2.5:
            v, col, mk = "tighter than the bag average", GOOD, "+"
        elif res > 2.5:
            v, col, mk = "looser than the bag average", CRITICAL, "x"
        else:
            v, col, mk = "on the line", INK2, "·"
        rows.append([(c, INK, "bold"), f"{r.med:.0f} m",
                     (f"{r.lat_sd:.1f} m", INK, "bold"), f"{pred:.1f} m",
                     (f"{res:+.1f}", col, "bold"), f"{4 * r.lat_sd:.0f} m",
                     (f"{mk}  {v}", col, "normal")])
    y = draw_table(fig, L, y - 0.008, cols, rows, size=7.4)

    y = heading(fig, L, y - 0.024,
                f"What a {fit['cone']:.1f}-degree cone costs on the course", 11)
    y = para(fig, L, y + 0.002,
             "At driver distance the cone is 33 m wide at one sigma and 66 m at two. A 40 m fairway is held "
             "about three-quarters of the time on the cone, and about two-thirds using the driver's own "
             "measured spread - even when nothing goes wrong. That is not a swing fault, it is the arithmetic "
             "of the club, and it is the case for hitting less club off a tight tee: the cone narrows in "
             "proportion, so trading driver for 5 wood buys back a third of the width at a cost of 26 m. The "
             "5 wood's own dispersion is unmeasured at n = 6, so test that before trusting it.", size=7.8)
    para(fig, L, y - 0.008,
         "The 7 iron sits 5 m below the line and the pitching wedge 4 m above it. The 7 iron's advantage is "
         "the one genuinely well-established dispersion result in this report (n = 31): whatever you are doing "
         "with that club is worth generalising. The pitching wedge's excess rests on 8 shots and should not "
         "be acted on yet.", size=7.8)

    footer(fig, 9, TOTAL,
           "Each point is one club, sized by n; weights are n−1, so the 7 and 8 irons carry the fit and "
           "the 5 wood barely moves it. The cone assumes zero mean offline - where a club is biased (page 8) "
           "the cone is centred on the bias, not on the target.")


def p10_variance(fig, D):
    y = header(fig, "Page 10", "Where the variance comes from",
               "Two decompositions. Left: how much of each club's carry spread is explained by ball speed "
               "alone, against ball speed plus launch angle and spin. Right: how much of it is the day, and "
               "how much is the swing. Both point the same way.")

    r2 = D["r2"]
    clubs = [c for c in CLUB_ORDER if c in r2]
    ax = fig.add_axes([L + 0.030, y - 0.275, 0.385, 0.232])
    style(ax, xgrid=True, ygrid=False)
    for i, c in enumerate(clubs):
        a, b = r2[c]
        ax.plot([a, b], [i, i], color=GRID, lw=1.4, zorder=2)
        ax.scatter([a], [i], s=32, color=S1, lw=0, zorder=3)
        ax.scatter([b], [i], s=32, color=S2, lw=0, zorder=3)
        ax.text(b + 0.025, i, f"{b:.2f}", fontsize=6.8, color=INK2, va="center")
    ax.set_yticks(range(len(clubs)))
    ax.set_yticklabels([SHORT[c] for c in clubs], fontsize=7.6, color=INK)
    ax.set_xlim(0, 1.16)
    ax.set_xlabel("R² of carry, within the club")
    ax.set_title("Speed is not the story", fontsize=9.5, color=INK,
                 weight="bold", loc="left", pad=17)
    ax.legend(handles=[
        Line2D([], [], color=S1, lw=0, marker="o", ms=5, label="Ball speed only"),
        Line2D([], [], color=S2, lw=0, marker="o", ms=5,
               label="+ launch angle + spin")],
        loc="lower left", bbox_to_anchor=(0, 1.005), ncol=2, handlelength=1.0,
        borderpad=0.1)

    vc = D["vc"]
    vclubs = [c for c in CLUB_ORDER if not np.isnan(vc[c][2])]
    ax2 = fig.add_axes([L + 0.505, y - 0.275, 0.375, 0.232])
    style(ax2)
    idx = np.arange(len(vclubs))
    within = np.array([vc[c][1] for c in vclubs])
    between = np.array([vc[c][0] for c in vclubs])
    ax2.bar(idx, within, width=0.60, color=S1, lw=0, zorder=3)
    ax2.bar(idx, between, width=0.60, bottom=within + 0.5, color=S2, lw=0, zorder=3)
    for i, c in enumerate(vclubs):
        ax2.text(i, within[i] + between[i] + 1.8, f"{vc[c][2] * 100:.0f}%",
                 fontsize=6.8, color=INK2, ha="center")
    ax2.set_xticks(idx)
    ax2.set_xticklabels([SHORT[c] for c in vclubs], fontsize=7.6, color=INK)
    ax2.set_ylabel("SD of carry (m)")
    ax2.set_ylim(0, 46)
    ax2.set_title("Shot-to-shot, not day-to-day", fontsize=9.5, color=INK,
                  weight="bold", loc="left", pad=17)
    ax2.text(0.99, 0.96, "the figure above each bar is the ICC", ha="right",
             va="top", transform=ax2.transAxes, fontsize=6.6, color=MUTED)
    ax2.legend(handles=[
        Line2D([], [], color=S1, lw=6, label="Within session - the swing"),
        Line2D([], [], color=S2, lw=6, label="Between sessions - the day")],
        loc="lower left", bbox_to_anchor=(0, 1.005), ncol=2, handlelength=1.0,
        borderpad=0.1)

    y = heading(fig, L, y - 0.318,
                "Clubhead speed explains almost none of your scoring-iron spread", 11)
    y = para(fig, L, y + 0.002,
             "For the 8 iron, ball speed alone accounts for R² = 0.29 of the carry variation; adding "
             "launch angle and spin takes it to 0.79. The 9 iron goes 0.43 → 0.89 and the gap wedge "
             "0.49 → 0.98. In plain terms: when your 8 iron comes up short it is usually not because you "
             "swung slower - it is because the ball came off at the wrong angle with the wrong spin. That is a "
             "strike-quality and low-point problem, and it responds to strike drills rather than speed work. "
             "The driver and 7 iron are the exceptions (0.66 and 0.94 from speed alone), where distance "
             "genuinely does track how hard you hit it.", size=7.8)

    y = heading(fig, L, y - 0.020, "Variance components by club", 11)
    cols = [C("CLUB", 0.0), C("SESSIONS", 0.145, "r"),
            C("SD WITHIN SESSION", 0.29, "r"), C("SD BETWEEN SESSIONS", 0.435, "r"),
            C("ICC", 0.49, "r"), C("TOTAL SD", 0.575, "r"),
            C("INTERPRETATION", 0.605, "l", 0.27)]
    rows = []
    for c in CLUB_ORDER:
        sb, sw, icc, ns = vc[c]
        if np.isnan(icc):
            rows.append([(c, INK, "bold"), f"{ns}", f"{sw:.1f} m", "—",
                         "—", f"{sw:.1f} m",
                         ("·  one session - no day effect estimable",
                          MUTED, "normal")])
            continue
        if icc < 0.05:
            v, col, mk = "the day barely matters; range = course", GOOD, "+"
        elif icc < 0.20:
            v, col, mk = "mild day effect", WARNING, "!"
        else:
            v, col, mk = "drifts between days - average sessions", CRITICAL, "x"
        rows.append([(c, INK, "bold"), f"{ns}", f"{sw:.1f} m", f"{sb:.1f} m",
                     (f"{icc:.3f}", col, "bold"), f"{np.hypot(sw, sb):.1f} m",
                     (f"{mk}  {v}", col, "normal")])
    y = draw_table(fig, L, y, cols, rows, size=7.4)

    y = heading(fig, L, y - 0.024,
                "The 5 iron and 7 iron are the ones that drift", 11)
    y = para(fig, L, y + 0.002,
             "ICC = 0.19 for the 5 iron and 0.28 for the 7 iron, against under 0.05 for everything else. The "
             "5 iron's two sessions sat 39 m apart in median carry - 109 m on 11 April, 148 m on 16 April. "
             "That is not a club with a wide distribution, it is a club you have not settled on a method with. "
             "Averaging those two sessions produces a yardage that was never hit on either day, which is "
             "exactly the failure mode a variance-components model exists to catch.", size=7.8)
    para(fig, L, y - 0.008,
         "The counterpart is the good news: for five of seven repeated clubs, less than 5% of the carry "
         "variance is between-session. Your range numbers are not a range artefact - they will hold on the "
         "course, and the independent on-course data on page 12 confirms it.", size=7.8)

    footer(fig, 10, TOTAL,
           "Random-intercept models fitted by REML on session. With only two or three sessions per club the "
           "between-session variance is itself poorly identified, so these ICCs should be read as ranks "
           "rather than point estimates. Clubs hit in a single session are listed but not modelled.")


def p11_wedge(fig, D):
    lw = D["lw"]
    y = header(fig, "Page 11", "Distance control: the lob wedge blocks",
               "Both lob-wedge blocks were hit to a nominated carry - 30 m and 50 m - which makes them the "
               "only part of this data set with a known target. That converts dispersion into something a "
               "distribution alone cannot give you: accuracy, separable from precision.")

    for i, (key, tgt, col) in enumerate((("30", 30, S1), ("50", 50, S2))):
        ax = fig.add_axes([L + 0.030 + i * 0.455, y - 0.240, 0.375, 0.212])
        style(ax)
        x = lw[f"x{key}"]
        ax.hist(x, bins=np.arange(np.floor(x.min()) - 1, np.ceil(x.max()) + 3, 2.5),
                color=col, alpha=0.55, lw=0, zorder=3)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        top = ax.get_ylim()[1]
        ax.axvline(tgt, color=INK, lw=1.2, zorder=4)
        ax.axvline(x.mean(), color=col, lw=1.2, ls=(0, (4, 3)), zorder=4)
        ax.text(tgt + 0.5, top * 0.97, f"target {tgt} m", fontsize=7,
                color=INK, va="top", weight="bold")
        ax.text(x.mean() - 0.5, top * 0.80, f"mean {x.mean():.1f} m", fontsize=7,
                color=col, va="top", weight="bold", ha="right")
        ax.set_xlabel("Carry (m)")
        ax.set_ylabel("Shots")
        ax.set_title(f"{tgt} m block   n = {len(x)}", fontsize=9.5, color=INK,
                     weight="bold", loc="left", pad=6)

    y = heading(fig, L, y - 0.282,
                "Both blocks land short; neither is significant on its own", 11)
    cols = [C("BLOCK", 0.0), C("N", 0.085, "r"), C("TARGET", 0.165, "r"),
            C("MEAN CARRY", 0.265, "r"), C("BIAS", 0.335, "r"),
            C("BIAS %", 0.405, "r"), C("SD", 0.465, "r"), C("CV", 0.525, "r"),
            C("95% CI ON BIAS", 0.625, "r"), C("t TEST p", 0.690, "r"),
            C("VERDICT", 0.715, "l", 0.165)]
    rows = []
    for key, tgt in (("30", 30), ("50", 50)):
        x = lw[f"x{key}"]
        tt = stats.ttest_1samp(x, tgt)
        ci = tt.confidence_interval()
        bias = x.mean() - tgt
        sig = tt.pvalue < 0.05
        v, col, mk = (("short, significant", CRITICAL, "x") if sig and bias < 0
                      else ("long, significant", CRITICAL, "x") if sig
                      else ("short, not significant", WARNING, "!"))
        rows.append([(f"{tgt} m", INK, "bold"), f"{len(x)}", f"{tgt}.0 m",
                     (f"{x.mean():.1f} m", INK, "bold"),
                     (f"{bias:+.1f} m", col, "bold"), f"{100 * bias / tgt:+.1f}%",
                     f"{x.std(ddof=1):.2f} m",
                     (f"{100 * x.std(ddof=1) / x.mean():.1f}%", INK, "bold"),
                     f"{ci.low - tgt:+.1f} to {ci.high - tgt:+.1f}",
                     f"{tt.pvalue:.3f}", (f"{mk}  {v}", col, "bold")])
    y = draw_table(fig, L, y, cols, rows, size=7.5, ls=1.5)

    y = heading(fig, L, y - 0.024,
                "Precision improves with length; accuracy does not", 11)
    y = para(fig, L, y + 0.002,
             f"The 30 m block carries a CV of {lw['cv30']:.1f}% against {lw['cv50']:.1f}% at 50 m - roughly "
             f"double the relative scatter at the shorter target, from a smaller absolute SD "
             f"({lw['s30']:.2f} m against {lw['s50']:.2f} m). This is the standard finding for partial wedges "
             "and it has a mechanical cause: at 30 m you are further down the speed range, where a given error "
             "in clubhead speed or strike location is a larger fraction of the total energy. It is also why "
             "the shortest wedge shots are the hardest to control, and why a rehearsed clock system beats feel "
             "below about 40 m.", size=7.8)
    y = para(fig, L, y - 0.008,
             f"The bias is the more useful finding. Both blocks land short by nearly the same fraction - "
             f"{100 * lw['b30'] / 30:+.1f}% at 30 m and {100 * lw['b50'] / 50:+.1f}% at 50 m - so this is a "
             "proportional calibration error rather than a fixed offset. Neither is individually significant "
             "at these sample sizes, but a proportional error agreeing in sign across two independent targets "
             "is worth a note: your internal yardage for the lob wedge reads about 5-7% long. Recalibrating "
             "the number is free; correcting a swing that is not broken is not.", size=7.8)

    ax = fig.add_axes([L + 0.030, y - 0.208, 0.375, 0.170])
    style(ax)
    for key, tgt, col in (("30", 30, S1), ("50", 50, S2)):
        x = lw[f"x{key}"]
        ax.scatter(tgt + RNG.normal(0, 0.055, len(x)) * 22, x - tgt, s=17,
                   color=col, alpha=0.75, lw=0, zorder=3)
        ax.plot([tgt - 5, tgt + 5], [x.mean() - tgt] * 2, color=col, lw=1.6,
                zorder=4)
        ax.text(tgt, x.mean() - tgt + 0.55, f"{x.mean() - tgt:+.1f} m", fontsize=7,
                color=col, ha="center", weight="bold", va="bottom")
    ax.axhline(0, color=INK, lw=1.0, zorder=2)
    ax.set_xticks([30, 50])
    ax.set_xticklabels(["30 m target", "50 m target"], fontsize=7.6, color=INK)
    ax.set_xlim(20, 60)
    ax.set_ylabel("Carry error (m)")
    ax.set_title("Every shot's error against its own target", fontsize=9.5,
                 color=INK, weight="bold", loc="left", pad=6)

    yy = heading(fig, L + 0.475, y - 0.008, "What is missing", 11)
    yy = para(fig, L + 0.475, yy + 0.002,
              "The rest of the bag has no target attached, so only precision can be measured - never "
              "accuracy. A club can be beautifully repeatable and 8 m off the number written on your yardage "
              "card, and nothing in pages 3 to 9 would reveal it.", size=7.8, frac=0.405)
    yy = para(fig, L + 0.475, yy - 0.008,
              "The fix costs nothing: nominate a carry before each block and log it in the Note field, as "
              "these two blocks already do. Ten shots at a nominated number per club turns this report from a "
              "description of your dispersion into a calibration of your yardage card - which is the version "
              "that saves shots.", size=7.8, frac=0.405)
    para(fig, L + 0.475, yy - 0.008,
         "It also makes the wedge matrix possible: three clubs at three rehearsed lengths gives nine "
         "calibrated carries between 30 and 115 m, which would close the PW-to-GW hole found on page 7 "
         "without adding a club.", size=7.8, frac=0.405)

    footer(fig, 11, TOTAL,
           "Both blocks were hit on 14 April 2026 in a single session, so the within-block precision here "
           "excludes any day-to-day component and is a best case. One-sample t tests against the nominated "
           "target, n = 8 and n = 13.")


def p12_oncourse(fig, D):
    oc, t = D["oc"], D["t"]
    y = header(fig, "Page 12", "Does it hold up on the course?",
               f"An independent check from {D['n_course']} GPS-tracked strokes over {D['n_rounds']} rounds, May "
               "to August 2026. Course shots mix full swings with layups and chips, so each club's lengths "
               "are split by a two-component Gaussian mixture and only the upper component is compared.")

    pairs = [(a, b) for a, b in
             [("Driver", "Driver"), ("6 Iron", "6 Iron"), ("7 Iron", "7 Iron"),
              ("8 Iron", "8 Iron"), ("9 Iron", "9 Iron"),
              ("Pitching Wedge", "Pitching Wedge"), ("Sand Wedge", "Sand Wedge"),
              ("Gap Wedge", "52 Degree Wedge")] if b in oc.index]
    ax = fig.add_axes([0.165, y - 0.245, R - 0.165, 0.220])
    style(ax, xgrid=True, ygrid=False)
    for i, (rc, occ) in enumerate(pairs):
        rt, om = t.loc[rc].total, oc.loc[occ].mu_full
        ax.plot([rt, om], [i, i], color=GRID, lw=1.4, zorder=2)
        ax.scatter([rt], [i], s=36, color=S1, lw=0, zorder=3)
        ax.scatter([om], [i], s=36, color=S2, lw=0, zorder=3)
        dlt = om - rt
        col = GOOD if abs(dlt) < 6 else (WARNING if abs(dlt) < 13 else CRITICAL)
        ax.text(max(rt, om) + 4, i, f"{dlt:+.0f} m", fontsize=7.2, color=col,
                weight="bold", va="center")
    ax.set_yticks(range(len(pairs)))
    ax.set_yticklabels([p[0] for p in pairs], fontsize=8, color=INK)
    ax.set_xlabel("Total distance (m)")
    ax.set_xlim(80, 235)
    ax.set_ylim(-0.7, len(pairs) - 0.3)
    ax.legend(handles=[
        Line2D([], [], color=S1, lw=0, marker="o", ms=5,
               label="Range, median total - R10 flight model, April"),
        Line2D([], [], color=S2, lw=0, marker="o", ms=5,
               label="Course, full-swing mode - GPS, May to August")],
        loc="lower left", bbox_to_anchor=(0.0, 1.005), ncol=2, handlelength=1.0,
        borderpad=0.1)

    y = heading(fig, L, y - 0.286,
                "The irons play longer outside; the driver plays shorter", 11)
    cols = [C("CLUB", 0.0), C("RANGE TOTAL", 0.175, "r"),
            C("COURSE SHOTS", 0.275, "r"), C("FULL SWINGS", 0.393, "r"),
            C("FULL-SWING MODE", 0.490, "r"), C("SD", 0.545, "r"),
            C("PARTIAL MODE", 0.632, "r"), C("DELTA", 0.680, "r"),
            C("LIKELY CAUSE", 0.700, "l", 0.178)]
    rows = []
    for rc, occ in pairs:
        o, rt = oc.loc[occ], t.loc[rc].total
        dlt = o.mu_full - rt
        if rc == "Driver":
            cause, col = "a range block hides misses", CRITICAL
        elif abs(dlt) < 6:
            cause, col = "agrees inside noise", GOOD
        else:
            cause, col = "summer roll and warmer air", WARNING
        rows.append([(rc, INK, "bold"), f"{rt:.0f} m", f"{int(o.n)}",
                     f"{o.w_full * 100:.0f}%", (f"{o.mu_full:.0f} m", INK, "bold"),
                     f"{o.sd_full:.1f} m", f"{o.mu_part:.0f} m",
                     (f"{dlt:+.0f} m", col, "bold"), (cause, INK2, "normal")])
    y = draw_table(fig, L, y, cols, rows, size=7.4)

    y = heading(fig, L, y - 0.020, "Reading the disagreement", 11)
    y = para(fig, L, y + 0.002,
             "The mid-irons run 4 to 15 m longer on the course than the R10's total for the same club, and "
             "three causes pull the same way without the data being able to separate them: the rounds were "
             "played in May-August air (roughly 1.16 g/L against the range's 1.19-1.23, worth about +2%), "
             "summer fairways give more roll than range turf, and the GPS length is measured ball-to-ball on "
             "the ground, which credits every metre of bounce. The direction and rough size are what matter - "
             "add about 8 m to the range total for a mid-iron in summer, and nothing in winter.", size=7.8)
    y = para(fig, L, y - 0.008,
             "The driver is the honest one. It plays 17 m shorter on the course and its course SD (28.5 m) is "
             "half again its range SD (19.1 m). A range block is a best case - same lie, same ball, no "
             "consequence, no first tee. That gap is not measurement error; it is what happens when the shot "
             "counts, and it is the strongest argument in this report for planning off the p10 column on "
             "page 6 rather than the median.", size=7.8)

    y = heading(fig, L, y - 0.020, "Lie matters more than club", 11)
    cols2 = [C("CLUB AND LIE", 0.0), C("SHOTS", 0.165, "r"),
             C("MEDIAN DISTANCE", 0.295, "r"),
             C("INTERQUARTILE RANGE", 0.445, "r"), C("IQR WIDTH", 0.525, "r"),
             C("", 0.555, "l", 0.33)]
    rows2 = []
    for c in ("7 Iron", "8 Iron"):
        for lie in ("fairway", "tee", "rough"):
            g = D["oc_raw"][(D["oc_raw"].club == c) & (D["oc_raw"].lie == lie)]
            if len(g) < 8:
                continue
            q1, q3 = g.distance_m.quantile([0.25, 0.75])
            w = q3 - q1
            col = CRITICAL if w > 60 else (WARNING if w > 35 else GOOD)
            rows2.append([(f"{c} from the {lie}", INK, "bold"), f"{len(g)}",
                          (f"{g.distance_m.median():.0f} m", INK, "bold"),
                          f"{q1:.0f} - {q3:.0f} m", (f"{w:.0f} m", col, "bold"),
                          ("" if lie != "rough" else
                           ("←  the rough roughly doubles the spread", col,
                            "normal"))])
    draw_table(fig, L, y, cols2, rows2, size=7.4)

    footer(fig, 12, TOTAL,
           "Course distances are start-to-end GPS separations from Shot Scope - total including roll, and "
           "including every mishit. The mixture is fitted per club with two components and ten restarts; the "
           "reported mode is the longer component. The gap wedge is logged on the course as a 52-degree wedge.")


def p13_conclusions(fig, D):
    t, gaps = D["t"], D["gaps"]
    y = header(fig, "Page 13", "What to do about it",
               "Findings ranked by expected strokes saved, each with its statistical warrant and what "
               "would overturn it.")

    y = numbered(fig, L, y, [
        ("1", "Take the 5 iron out of the bag until it is refit", CRITICAL,
         f"It carries {abs(gaps.iloc[2].gap):.0f} m shorter than the 6 iron with three times the spread "
         f"(s = {t.loc['5 Iron'].sd:.1f} m) and wins {gaps.iloc[2].pi * 100:.0f}% of head-to-head pairs. Its "
         f"10th percentile is {t.loc['5 Iron'].p10:.0f} m - a club you cannot commit to. Warrant: n = 17 "
         f"across two sessions; the 95% CI on the gap ({gaps.iloc[2].lo:+.0f} to {gaps.iloc[2].hi:+.0f} m) "
         "does not establish the inversion, but it firmly excludes the 5 iron being usefully longer. "
         "Overturned by: 20 shots in a single settled session with a median above 150 m. Until then a 5 wood "
         "or a hybrid covers 150-160 m better."),
        ("2", "Fix the aim before the swing on the 7 and 9 irons", CRITICAL,
         "Mean offline +10.8 m (7i) and +8.9 m (9i), both p < 0.001, sitting on top of the smallest offline "
         "SD in the bag for the 7 iron. A biased-but-tight club is the cheapest fix in golf: the pattern is "
         "already repeatable, it is simply pointed wrong. Check alignment and face angle at address first - "
         "the club path data (mean +2.5° to +5.7° with the face open to it) says the ball is "
         "starting right rather than curving there. Warrant: n = 31 and n = 26, significant under both t and "
         "Wilcoxon, and present in both sessions for each club."),
        ("3", "Practise strike quality, not clubhead speed, in the scoring irons", SERIOUS,
         "Ball speed alone explains only 29% (8i), 43% (9i) and 49% (GW) of within-club carry variation; "
         "adding launch and spin takes those to 0.79, 0.89 and 0.98. Your short shots are launch-and-spin "
         "failures, which means low point and face contact. Warrant: OLS within club, n ≥ 13. This is "
         "also what produced the 8 iron's 63.9 m outlier and its −2.22 skew."),
        ("4", "Fill the 93-115 m hole, and stop deliberating between 8 and 9 iron", WARNING,
         "PW→GW is a 22 m step against a bag average of 11 m, sitting exactly in scoring range. Meanwhile "
         "8i→9i is 4.9 m with P(win) = 0.62 - two clubs doing one club's job. A 50° wedge, or a "
         "rehearsed three-quarter pitching wedge calibrated the way page 11's blocks were, closes the hole; "
         "defaulting to the 9 iron in the overlap removes a decision the data says is a coin flip."),
        ("5", "Recalibrate the lob wedge yardage down by about 6%", WARNING,
         f"Both nominated blocks landed short by nearly the same fraction "
         f"({100 * D['lw']['b30'] / 30:+.1f}% at 30 m, {100 * D['lw']['b50'] / 50:+.1f}% at 50 m). Neither is "
         "individually significant, but a proportional error agreeing in sign across two targets is worth a "
         "card change rather than a swing change. Warrant: weak - n = 8 and n = 13 in one session. Confirm "
         "with a second nominated block before acting."),
        ("6", "Plan off the 10th percentile, not the median", GOOD,
         "The driver plays 17 m shorter on the course than on the range and half again as wide (SD 28.5 m "
         "against 19.1 m). The median is what a club does in a range bay; the p10 column on page 6 is what it "
         "does when the shot counts. For any carry over trouble, that column is the number."),
    ], hsize=9.5, bsize=7.8, gap=0.013)

    rule(fig, y - 0.006)
    y = heading(fig, L, y - 0.026,
                "The measurement plan that would make the next report definitive", 11.5)
    y = para(fig, L, y + 0.002,
             "Half the conclusions above are limited by n, not by analysis. Five clubs have fewer than 18 "
             "strikes, and a spread estimated from eight shots is uncertain by a factor of three. Two changes "
             "to how the data is collected would remove that limit entirely:", size=7.9)
    y = para(fig, L, y - 0.008,
             "•  Two clubs per session, not ten.  Fifty strikes of one club across three sessions pins "
             "its dispersion to ±20% and separates the day effect from the swing. Ten clubs at ten balls "
             "each measures nothing about any of them. Five sessions on this rotation covers the bag.",
             size=7.9)
    y = para(fig, L, y - 0.006,
             "•  Nominate a carry and log it.  The lob-wedge blocks are the only shots here with a "
             "target, and they are the only shots that could be tested for accuracy rather than merely "
             "described for precision. One line in the Note field turns every block into a calibration.",
             size=7.9)
    para(fig, L, y - 0.008,
         "With those two changes the same script produces tolerance intervals narrow enough to build a "
         "yardage card on, ICCs that are point estimates rather than ranks, and a wedge matrix of nine "
         "calibrated carries. The analysis is not the binding constraint here - the sample is.", size=7.9)

    w, h, gp = 0.208, 0.082, 0.0227
    yt = 0.056
    nfail = int((t.sw_p < 0.05).sum())
    nbroken = int((gaps.pi < 0.70).sum())
    nmarg = int(((gaps.pi >= 0.70) & (gaps.pi < 0.80)).sum())
    tile(fig, L, yt, w, h, f"{int(t.n.sum())}", "full-swing strikes",
         "over 10 clubs, plus\n21 partial wedges", INK, 19)
    tile(fig, L + w + gp, yt, w, h, f"{nfail}", "club failing normality",
         "the 8 iron, on a single\nthinned strike", INK, 19)
    tile(fig, L + 2 * (w + gp), yt, w, h, f"{nbroken}", "rungs broken",
         f"plus {nmarg} more marginal,\nof nine steps", INK, 19)
    tile(fig, L + 3 * (w + gp), yt, w, h, "~50", "shots per club needed",
         "to state dispersion\nto within ±20%", INK, 19)

    footer(fig, 13, TOTAL,
           "Generated by distance_report.py from data.xlsx (sheet Michiel, 11-19 April 2026) and "
           "shotscope/golf_shots.csv (14 rounds, May-August 2026).")


# ================================================================= main ====
def build(player, out):
    raw, df, full, artefact = load(player)
    t = club_table(full)
    gaps = gap_table(full)

    lw = {}
    for key, tgt in (("30", 30), ("50", 50)):
        x = df.loc[df.intent == f"LW{key}", "Carry Distance [m]"].values
        lw.update({f"x{key}": x, f"n{key}": len(x), f"m{key}": x.mean(),
                   f"s{key}": x.std(ddof=1), f"b{key}": x.mean() - tgt,
                   f"cv{key}": 100 * x.std(ddof=1) / x.mean()})

    m = sm.WLS(t["lat_sd"], sm.add_constant(t["med"]), weights=t["n"] - 1).fit()
    m0 = sm.WLS(t["lat_sd"], t[["med"]], weights=t["n"] - 1).fit()
    scaling = dict(b0=float(m.params.iloc[0]), b1=float(m.params.iloc[1]),
                   r2=float(m.rsquared), p=float(m.pvalues.iloc[1]),
                   b1lo=float(m.conf_int().iloc[1, 0]),
                   b1hi=float(m.conf_int().iloc[1, 1]),
                   origin=float(m0.params.iloc[0]),
                   cone=float(np.degrees(np.arctan(m0.params.iloc[0]))))

    oc_raw, oc = oncourse()
    D = dict(player=player, raw=raw, df=df, full=full, artefact=artefact, t=t,
             gaps=gaps, lw=lw, scaling=scaling, cone=scaling["cone"],
             vc=variance_components(full), r2=strike_r2(full),
             oc=oc, oc_raw=oc_raw, n_used=len(df),
             n_course=len(oc_raw), n_rounds=oc_raw["round_date"].nunique(),
             sessions=sorted(df["session"].unique()),
             max_cs=float(raw.loc[raw["Club Speed [km/h]"] < 200,
                                  "Club Speed [km/h]"].max()))

    pages = [p01_cover, p02_method, p03_distributions, p04_shape, p05_uncertainty,
             p06_intervals, p07_gapping, p08_ellipses, p09_scaling, p10_variance,
             p11_wedge, p12_oncourse, p13_conclusions]
    with PdfPages(out) as pdf:
        for fn in pages:
            fig = plt.figure(figsize=A4)
            fn(fig, D)
            pdf.savefig(fig)
            plt.close(fig)
        meta = pdf.infodict()
        meta["Title"] = f"Carry distance, dispersion and gapping - {player}"
        meta["Author"] = player
        meta["Subject"] = "Garmin Approach R10 launch-monitor analysis, April 2026"
    print(f"wrote {out}  ({len(pages)} pages, {len(df)} shots, "
          f"{int(t.n.sum())} full swings)")
    return D


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", default="Michiel")
    ap.add_argument("--out", default="distance_report.pdf")
    a = ap.parse_args()
    build(a.player, a.out)
