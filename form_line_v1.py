"""
Form line detector v1 — 103 Form line (dashed brown contour). EXPERIMENT — DISCONNECTED.

ISOM 103 Form line = intermediate contour pro terénní rozdíl < 5m. V OMAP:
    color="7" (Brown), line_width=140 (0.14 mm), dashed=true.

V rasteru se projeví jako **sekvence krátkých skeleton segmentů** ve stejné
lineární orientaci s pravidelnými mezerami. Po Stage 3 8-conn components
každý dash = samostatná komponenta (gap mezi dashemi je obvykle 3-5 px).

Detektor cílí na mid peak (brown thickness 2.4-3.4 px, mezi 101 thin a 102
thick). Mid peak na forest sample obsahuje ~43 segmentů, z toho 3 jsou
skutečně Form line (GT). Zbytek = junction pixely, fragmenty 101/102, šum.

Heuristika v1 (KISS):
    1. Filter na short segments (5 < length < 50 px).
    2. Pro každý short segment spočítej orientaci (PCA dominant axis).
    3. Hledej co-linear soused (cosine ≥ 0.85) ve vzdálenosti < 30 px.
    4. Pokud najdeš ≥ 1 souseda → kandidát 103 Form line.

**Výsledek**: 20 detekováno / GT 3 = 6.7× over-claim. Stejná situace jako
erosion_gully_v1 — málo GT (3) vs hodně kandidátů v mid peaku (43) =
neudržitelná precision. Co-linearity check sám nestačí: junction pixely,
anti-aliasing fragmenty 101/102 a krátké brown line varianty (104/106 Earth
bank) splňují stejné kritérium.

**Stav**: odpojeno z `pic2db.cmd_detect`. Soubor držíme jako referenční
implementaci pro v2 (vyžaduje pozici-based check — Form line je dlouhá
sekvence ≥ 3 dashů, ne 2; gap regularity check).

Viz memory `erosion-gully-vs-index-contour` pro analogický pattern (1-2 GT
v over-segmented bucketu → každý naivní detector over-claimuje).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from color_category import ColorCategory
from db_model import MapObject
from peak_visualizer import classify_segments


# Empirické thresholdy — kalibrace na forest sample (631×478, ~300 DPI).
MIN_DASH_LENGTH = 5         # Pod tímto = šum, ne dash.
MAX_DASH_LENGTH = 50        # Nad tímto = celistvá vrstevnice, ne dash.
MAX_PAIR_DISTANCE = 30      # Max vzdálenost k paralelnímu sousedu (px).
MIN_COSINE = 0.85           # Min |cos(theta)| pro co-linearity (≈ ≤ 32°).

# Confidence — Form line je secondary classifier nad existujícím mid peak.
CONFIDENCE = 0.60

DETECTION_METHOD = "form_line_v1"


def _segment_orientation(pixels_yx: np.ndarray) -> np.ndarray:
    """
    PCA: dominantní osa segmentu jako jednotkový 2D vektor (vx, vy).

    pixels_yx: shape (N, 2), souřadnice (y, x) pixelů segmentu.
    Vrací jednotkový vektor směru. Pro segment s 1 pixelem vrací (1, 0)
    (degenerated, ale safe).
    """
    if len(pixels_yx) < 2:
        return np.array([1.0, 0.0])
    centered = pixels_yx - pixels_yx.mean(axis=0)
    # SVD na centered → V[0] je dominantní směr. Trvá O(N), pro malé segmenty
    # (< 100 px) instantní.
    # SVD vrací V s shape (2, 2), první row = dominant axis.
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    direction = vh[0]
    # Normalize (SVD vrátí už jednotkové, ale safety).
    norm = np.linalg.norm(direction)
    if norm == 0:
        return np.array([1.0, 0.0])
    return direction / norm


def _segment_centroid(pixels_yx: np.ndarray) -> np.ndarray:
    """Centroid (y, x) — průměr pixel souřadnic."""
    return pixels_yx.mean(axis=0)


def detect(
    out_dir: Path,
    image_shape: tuple[int, int],
    starting_id: int,
    iteration: int,
) -> tuple[list[MapObject], np.ndarray]:
    """
    Form line detekce nad mid peak brown skeletonu.

    Args:
        out_dir: kořen output/<sample>/.
        image_shape: (h, w) zdrojového rasteru.
        starting_id: první volný MapObject.id.
        iteration: číslo iterace.

    Returns:
        (objects, claim_mask) — list MapObject + uint16 mask.
    """
    skeleton_path = out_dir / "skeleton" / "cat_brown_skeleton.png"
    clean_path = out_dir / "morphology" / "cat_brown_clean.png"
    if not skeleton_path.exists() or not clean_path.exists():
        raise SystemExit(
            f"Form line detector vyžaduje Stage 3 výstupy:\n"
            f"  {skeleton_path}\n  {clean_path}"
        )

    skeleton = cv2.imread(str(skeleton_path), cv2.IMREAD_GRAYSCALE)
    clean = cv2.imread(str(clean_path), cv2.IMREAD_GRAYSCALE)
    skeleton_bin = (skeleton > 0).astype(np.uint8) * 255
    clean_bin = (clean > 0).astype(np.uint8) * 255

    # peak_visualizer.classify_segments vrátí labels + groups.
    # Bereme jen mid peak (mezi 101 thin a 102 thick).
    labels, groups = classify_segments(skeleton_bin, clean_bin)
    mid_label_ids = groups.get("mid", [])

    h, w = image_shape
    claim_mask = np.zeros((h, w), dtype=np.uint16)

    # Pre-cache per-label features: pixels, length, orientation, centroid.
    # Bereme jen short mid segments (kandidáti na dash).
    candidates: dict[int, dict] = {}
    for label_id in mid_label_ids:
        # np.where na celém labels je drahé per-segment, ale pro 43 mid segments OK.
        ys, xs = np.where(labels == label_id)
        length = len(xs)
        if length < MIN_DASH_LENGTH or length > MAX_DASH_LENGTH:
            continue
        pixels_yx = np.column_stack([ys, xs])
        candidates[label_id] = {
            "pixels": pixels_yx,
            "length": length,
            "centroid": _segment_centroid(pixels_yx),
            "direction": _segment_orientation(pixels_yx),
            "bbox": (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
        }

    # Pro každého kandidáta najdi co-linear souseda < MAX_PAIR_DISTANCE.
    # Pokud existuje, označ jako Form line dash.
    form_line_labels: set[int] = set()
    cand_list = list(candidates.items())
    for i, (lid_a, feat_a) in enumerate(cand_list):
        if lid_a in form_line_labels:
            continue  # Už spárováno přes předchozí dash.
        for lid_b, feat_b in cand_list[i + 1:]:
            if lid_b in form_line_labels:
                continue
            # Vzdálenost centroidů (euklidovsky).
            dist = float(np.linalg.norm(feat_a["centroid"] - feat_b["centroid"]))
            if dist > MAX_PAIR_DISTANCE:
                continue
            # Co-linearity: |cosine| mezi orientacemi.
            # abs() protože směr může být inverzní (PCA neopravuje znaménko).
            cosine = abs(float(np.dot(feat_a["direction"], feat_b["direction"])))
            if cosine < MIN_COSINE:
                continue
            # Splňuje obě podmínky → oba dashe jsou Form line.
            form_line_labels.add(lid_a)
            form_line_labels.add(lid_b)
            break  # Stačí jeden pair, dál nepokračuj pro lid_a.

    # Build MapObjects.
    objects: list[MapObject] = []
    next_id = starting_id
    for label_id in form_line_labels:
        feat = candidates[label_id]
        obj = MapObject(
            id=next_id,
            symbol_code="103",
            geometry_type="line",
            category=ColorCategory.BROWN,
            bbox=feat["bbox"],
            pixel_count=int(feat["length"]),
            pixel_blob_id=next_id,
            confidence=CONFIDENCE,
            detected_in_iter=iteration,
            detection_method=DETECTION_METHOD,
        )
        objects.append(obj)
        claim_mask[labels == label_id] = next_id
        next_id += 1

    return objects, claim_mask
