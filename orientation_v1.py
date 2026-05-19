"""
Orientation detector v1 — detekce rotace mapy z paralelních north lines (601.x).

Vstup: BGR raster.
Výstup: float (rotace ve stupních CCW od north=up) NEBO None.

Algoritmus:
1. Downscale velkého rastru pro efektivitu (MAX_RASTER_DIM).
2. Pro každou kandidátskou barvu (BLUE, BLACK) vytvoř binary mask.
3. HoughLinesP na maska → list (x1,y1,x2,y2,length,angle).
4. Length-weighted histogram angles → najít dominantní peak.
5. Vyhodnotit: cluster size + dominance vůči druhému peaku.
6. Pokud OK → rotation_deg = 90° - peak_angle (vertical north lines → 0°).
7. Vrátit nejsilnější kandidát z všech barev.

Klíčové insights z pre-flightu:
- Slovanka2016: 34 × 601.1 modrých magnetic north lines → blue mask + Hough
  najde 10 čar v 90° (vertical) → rotation = 0°.
- Forest sample: bez 601.x → žádná barva nemá silný paralelní cluster → None.

Note: rotation se vztahuje k orientaci RASTRU (image space), ne k world coord
v georef. Magnetic declination žije v `.pgw`, ne v rasteru.
"""

from __future__ import annotations

import math
from typing import Callable

import cv2
import numpy as np


# === Empirické parametry ===
MAX_RASTER_DIM = 2000          # downscale velkého rastru
HOUGH_RHO = 1                  # px
HOUGH_THETA = math.pi / 360    # 0.5° rozlišení (potřeba pro přesnou rotaci)
HOUGH_THRESHOLD = 30           # min Hough pixelů pro line (tenké north lines!)
HOUGH_MIN_LINE_LENGTH_RATIO = 0.04   # ~33 mm north line @ 1:15000 scale
HOUGH_MAX_LINE_GAP_RATIO = 0.005
BIN_DEG = 1.0
MIN_PEAK_LINES = 3             # min počet line segments v dominantním clusteru
PEAK_DOMINANCE_RATIO = 3.0     # peak ≥ X× druhý cluster pro confirmation
PEAK_SPREAD_DEG = 2.0          # ±° kolem peak considered "same cluster"

# === Kandidátské barvy pro north lines ===
# Lambdy přijímají (B, G, R) ndarray channels, vrací bool mask.
# Order matters: zkoušíme nejdříve specifické (blue), pak fallback (black).
NorthLineColorPredicate = Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray]

CANDIDATE_COLORS: list[tuple[str, NorthLineColorPredicate]] = [
    # Blue-dominant: 601.1 / 601.3 (modré north lines, např. Slovanka).
    # B > R+30 AND B > G+30 chytá různé odstíny modré včetně 50% transparency.
    ("blue", lambda b, g, r: (
        (b.astype(int) > r.astype(int) + 30)
        & (b.astype(int) > g.astype(int) + 30)
        & (b > 100)
    )),
    # Black: 601 / 601.1 default black north lines.
    # Threshold < 100 pro tmavé pixely (anti-aliased black je ~50-100).
    ("black", lambda b, g, r: (b < 100) & (g < 100) & (r < 100)),
]


def detect_orientation(raster_bgr: np.ndarray, verbose: bool = False) -> float | None:
    """
    Detekuje rotaci mapy z dominantních paralelních north lines.

    Args:
        raster_bgr: BGR ndarray (H, W, 3).
        verbose: vypisuj diagnostiku per kandidátská barva.

    Returns:
        Rotace ve stupních CCW od north=up. None pokud žádná barva nemá
        dostatečně silný paralelní cluster.
    """
    # Downscale velkého rastru — rotace je scale-invariant.
    h, w = raster_bgr.shape[:2]
    scale = 1.0
    if max(h, w) > MAX_RASTER_DIM:
        scale = MAX_RASTER_DIM / max(h, w)
        small = cv2.resize(
            raster_bgr,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_AREA,
        )
    else:
        small = raster_bgr
    sh, sw = small.shape[:2]
    diag = math.hypot(sh, sw)
    min_line_length = int(diag * HOUGH_MIN_LINE_LENGTH_RATIO)
    max_line_gap = int(diag * HOUGH_MAX_LINE_GAP_RATIO)

    if verbose:
        print(f"  [orientation_v1] downscale: {w}x{h} → {sw}x{sh}")
        print(f"  [orientation_v1] Hough min_len={min_line_length} max_gap={max_line_gap}")

    # BGR channels (předem rozdělené pro per-color predikáty).
    b_ch, g_ch, r_ch = small[:, :, 0], small[:, :, 1], small[:, :, 2]

    # Per-color evaluation. Vítěz = nejvyšší peak_weight × cluster_size.
    best_rotation: float | None = None
    best_score: float = 0.0
    best_color_name: str = ""

    for color_name, predicate in CANDIDATE_COLORS:
        mask_bool = predicate(b_ch, g_ch, r_ch)
        mask = mask_bool.astype(np.uint8) * 255
        n_pixels = int(mask_bool.sum())
        if n_pixels < 100:
            if verbose:
                print(f"  [orientation_v1] {color_name}: {n_pixels} pixelů — skip (málo)")
            continue

        result = _evaluate_color_mask(mask, min_line_length, max_line_gap, color_name, verbose)
        if result is None:
            continue

        rotation_deg, score = result
        if score > best_score:
            best_score = score
            best_rotation = rotation_deg
            best_color_name = color_name

    if best_rotation is not None and verbose:
        print(f"  [orientation_v1] WINNER: {best_color_name}, rotation={best_rotation:.3f}°")

    return best_rotation


def _evaluate_color_mask(
    mask: np.ndarray,
    min_line_length: int,
    max_line_gap: int,
    color_name: str,
    verbose: bool,
) -> tuple[float, float] | None:
    """
    Pro daný binary mask: Hough + cluster analysis → (rotation_deg, score) nebo None.

    Score = peak_weight × cluster_size (vyšší = silnější signál).
    """
    lines = cv2.HoughLinesP(
        mask,
        rho=HOUGH_RHO,
        theta=HOUGH_THETA,
        threshold=HOUGH_THRESHOLD,
        minLineLength=min_line_length,
        maxLineGap=max_line_gap,
    )
    if lines is None or len(lines) == 0:
        if verbose:
            print(f"  [orientation_v1] {color_name}: 0 lines")
        return None

    # Per-line: angle (mod 180°) + length.
    angles_deg: list[float] = []
    lengths: list[float] = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        a = math.atan2(dy, dx)
        # Mod π — line direction symmetry.
        if a > math.pi / 2:
            a -= math.pi
        elif a <= -math.pi / 2:
            a += math.pi
        angles_deg.append(math.degrees(a))
        lengths.append(L)

    angles_arr = np.array(angles_deg)
    lengths_arr = np.array(lengths)

    # Histogram vážený length.
    bin_edges = np.arange(-90 - BIN_DEG / 2, 90 + BIN_DEG / 2 + BIN_DEG, BIN_DEG)
    hist, _ = np.histogram(angles_arr, bins=bin_edges, weights=lengths_arr)

    # Peak + 2nd peak (pro dominance check).
    sorted_idx = np.argsort(hist)[::-1]
    peak_idx = int(sorted_idx[0])
    peak_angle = (bin_edges[peak_idx] + bin_edges[peak_idx + 1]) / 2
    peak_weight = hist[peak_idx]

    second_weight = 0.0
    for idx in sorted_idx[1:]:
        cand_angle = (bin_edges[idx] + bin_edges[idx + 1]) / 2
        d = abs(cand_angle - peak_angle)
        if min(d, 180 - d) >= 2 * PEAK_SPREAD_DEG:
            second_weight = float(hist[idx])
            break

    # Cluster lines kolem peaku.
    def angle_dist(a, b):
        d = abs(a - b)
        return min(d, 180 - d)

    cluster = [(a, L) for a, L in zip(angles_deg, lengths)
               if angle_dist(a, peak_angle) <= PEAK_SPREAD_DEG]
    cluster_size = len(cluster)

    if verbose:
        dominance = peak_weight / max(second_weight, 1.0)
        print(f"  [orientation_v1] {color_name}: {len(lines)} lines, "
              f"peak={peak_angle:.2f}° weight={peak_weight:.0f} "
              f"cluster={cluster_size} dominance={dominance:.1f}×")

    # Validace clusteru.
    if cluster_size < MIN_PEAK_LINES:
        return None
    if peak_weight < PEAK_DOMINANCE_RATIO * max(second_weight, 1.0):
        return None

    # Weighted mean angle kolem peaku — přesnější než bin střed.
    # Wrap-around: pokud peak blízko ±90°, použít cyclic mean.
    cluster_a = np.array([a for a, L in cluster])
    cluster_w = np.array([L for a, L in cluster])
    if abs(peak_angle) > 80:
        # Cyclic mean (line direction má 180° periodicitu, *2 pro plnou periodu).
        cyc_rad = np.deg2rad(cluster_a * 2.0)
        mx = float(np.sum(cluster_w * np.cos(cyc_rad)) / cluster_w.sum())
        my = float(np.sum(cluster_w * np.sin(cyc_rad)) / cluster_w.sum())
        mean_deg = math.degrees(math.atan2(my, mx)) / 2.0
    else:
        mean_deg = float(np.average(cluster_a, weights=cluster_w))

    # Rotation_deg: vertikální line (peak 90° v image coords) → north=up → 0°.
    # Pokud peak je blíž k -90° než +90°, vezmi z -90° (line direction symmetry).
    if abs(mean_deg - 90) < abs(mean_deg + 90):
        rotation_deg = 90.0 - mean_deg
    else:
        rotation_deg = -90.0 - mean_deg

    score = peak_weight * cluster_size  # bigger = stronger
    return rotation_deg, score
