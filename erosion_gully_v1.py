"""
Erosion gully detector v1 — refinement detektor nad brown_line_v1.

Problém: brown_line_v1 klasifikuje thick brown segmenty jako 102 Index contour,
ale 109 Erosion gully má prakticky identický raster signál (stejná barva, šířka,
délka). Thickness peak je sám neumí odlišit.

Discriminating signals (kombinace dvou):

**1. Pointed cap (PRIMÁRNÍ)** — `pointed_cap_count`
    109 má v OMAP `cap_style="3"` + `pointed_cap_length` → čára se na koncích
    **zužuje do špičky**. V rasteru = DT na endpointu **nižší** než median DT
    segmentu. Detekce: endpoint_DT ≤ cap_factor × median_DT.

    Pozor: dříve hypotéza "endpoint blob" (DT vyšší) byla špatně — chytala
    urban road junction blobs (false positive #122). 109 má opačný signál.

**2. Crossing signal (SEKUNDÁRNÍ)** — `crossing_signal`
    Suma `adjacent_other_count` (jiné labely v dilatovaném okolí) +
    `branch_pixel_count` (junction pixely uvnitř segmentu). 109 protíná
    vrstevnice ortogonálně, vznikají buď separované komponenty (a) nebo
    sloučené přes 8-conn junction (b).

**Combine rule**:
    spikes ≥ 2 (oba konce s markerem)    → strong 109
    spikes ≥ 1 AND crossings ≥ 3         → medium 109
    Sám crossing signal nestačí — chytá i 102 mezi 101 (junction topologie),
    cliff overlay (106 hash marks), urban roads (color separation contamination).
    Viz memory `erosion-gully-vs-index-contour` (case studies #116/137/122/119).

Co v1 zatím nepoužívá:
    - Pozice mezi 101 sousedy (silný signál pro 102, viz memory).
    - 101 → 109 reclassification (small 109 fragmenty mohou být v thin peaku).
    - Length check.

Viz memory `erosion-gully-vs-index-contour` pro doménový kontext.
"""

from __future__ import annotations

import cv2
import numpy as np

from db_model import MapObject


# Empirické thresholdy — kalibrace na forest sample. Pro jiné DPI / sample
# může být potřeba doladit (zejména CAP_FACTOR závisí na rendering rozlišení).
CROSSING_THRESHOLD = 3        # sekundární topologický signál
CAP_FACTOR = 0.7              # endpoint DT ≤ 0.7× median DT = pointed cap

# Confidence pro reklasifikovaný 109. Nižší než čistý 102, protože je to
# secondary classifier nad detekovaným 102.
CONFIDENCE_109 = 0.70

DETECTION_METHOD = "erosion_gully_v1"


def adjacent_other_count(claim_mask: np.ndarray, object_id: int, kernel_size: int = 3) -> int:
    """
    Kolik unikátních jiných segmentů se dotkne dilatovaného segmentu.

    Použití: zachytí crossing, kde se kontury a rýha v skeletu **NEZmergovaly**
    do jedné komponenty (mezera ve skeletu na crossingu).
    """
    seg_mask = (claim_mask == object_id).astype(np.uint8)
    # Edge case: segment může být prázdný (špatný ID) — fail soft.
    if seg_mask.sum() == 0:
        return 0
    kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
    # iterations=1 → posun o ~1 px v každém směru.
    dilated = cv2.dilate(seg_mask, kernel, iterations=1)
    # Overlap region: rozšířená oblast minus segment sám, minus background.
    overlap = (dilated > 0) & (claim_mask != object_id) & (claim_mask > 0)
    other_labels = np.unique(claim_mask[overlap])
    return int(len(other_labels))


def branch_pixel_count(claim_mask: np.ndarray, object_id: int) -> int:
    """
    Počet pixelů uvnitř segmentu s 3+ sousedy ve stejném segmentu (junctions).

    Použití: zachytí crossing, kde 8-conn `cv2.connectedComponents` **zmergoval**
    rýhu + kontury do jedné komponenty přes junction pixel.

    Skeleton je 1px → "normální" pixel má 2 sousedy (pokračování čáry), endpoint
    má 1 soused, junction (větvení) 3+. Branch pixel = topologický signál
    pro průnik nebo Y-rozdělení.
    """
    seg_mask = (claim_mask == object_id).astype(np.uint8)
    if seg_mask.sum() == 0:
        return 0
    # 3×3 kernel — central=0, sousedi=1. filter2D s touto kernel spočítá
    # počet sousedů pro každý pixel (centrum se nepočítá samo).
    # Max sousedů = 8 → uint8 result stačí, žádný overflow.
    # (cv2 nepodporuje uint8 → int32 conversion, držíme se uint8.)
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
    neighbor_count = cv2.filter2D(seg_mask, ddepth=-1, kernel=kernel)
    # Branch pixel = patří do segmentu A má 3+ sousedy uvnitř.
    branches = (seg_mask == 1) & (neighbor_count >= 3)
    return int(branches.sum())


def crossing_signal(claim_mask: np.ndarray, object_id: int) -> int:
    """
    Kombinovaný topologický signál: sousední jiné segmenty + branch pixely.

    Suma zachycuje oba scénáře crossing (merged vs unmerged ve skeletu).
    """
    return (
        adjacent_other_count(claim_mask, object_id)
        + branch_pixel_count(claim_mask, object_id)
    )


def pointed_cap_count(
    claim_mask: np.ndarray,
    distance_transform: np.ndarray,
    object_id: int,
    cap_factor: float = CAP_FACTOR,
) -> int:
    """
    Počet endpointů segmentu s pointed cap (DT významně nižší než median segment DT).

    ISOM 109 má v OMAP `cap_style="3"` + `pointed_cap_length` — čára se zužuje
    do špičky. V rasteru DT na endpointu je menší než v interiéru (tělo
    čáry je širší než cap).

    Args:
        claim_mask: uint16, MapObject.id per pixel.
        distance_transform: float ndarray, DT z cat_brown_clean.png.
        object_id: kterého segmentu se ptáme.
        cap_factor: práh — endpoint_DT ≤ cap_factor × median_DT = pointed cap.

    Returns:
        Počet endpointů s pointed cap. 0 = normal ends, 2 = oba s cap (typické 109).
    """
    seg_mask = (claim_mask == object_id).astype(np.uint8)
    if seg_mask.sum() == 0:
        return 0

    # Endpointy — pixely segmentu s přesně 1 sousedem.
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
    neighbor_count = cv2.filter2D(seg_mask, ddepth=-1, kernel=kernel)
    endpoints_mask = (seg_mask == 1) & (neighbor_count == 1)
    if not endpoints_mask.any():
        return 0

    # Median DT v interiéru segmentu — "polovina typické šířky".
    segment_dt = distance_transform[seg_mask == 1]
    median_dt = float(np.median(segment_dt))
    # Příliš tenký segment (median < 0.5 px) — cap detection nespolehlivá.
    if median_dt < 0.5:
        return 0

    # Endpoint DT významně nižší než median → pointed cap.
    endpoint_dts = distance_transform[endpoints_mask]
    return int(np.sum(endpoint_dts <= cap_factor * median_dt))


def refine(
    objects: list[MapObject],
    claim_mask: np.ndarray,
    clean_mask: np.ndarray,
    crossing_threshold: int = CROSSING_THRESHOLD,
    cap_factor: float = CAP_FACTOR,
) -> tuple[list[MapObject], dict[tuple[int, int], int]]:
    """
    Re-evaluuje 102 kandidáty kombinací pointed cap + crossing signal.

    **Reklasifikační pravidlo**:
        caps ≥ 2                              → strong 109 (oba konce zúžené)
        caps ≥ 1 AND crossings ≥ threshold    → medium 109
        ostatní                               → zůstává 102

    Pointed cap je primární ISOM signál (cap_style=3 v OMAP). Crossing je
    sekundární — backup, kdy se podařilo detekovat jen 1 cap (druhý konec
    fragmentovaný, přerušený jiným objektem).

    Mutuje MapObject in-place.

    Args:
        objects: všechny detekované MapObject (filtruje 102 interně).
        claim_mask: uint16 z brown_line_v1.
        clean_mask: cat_brown_clean.png (uint8, 0/255 nebo 0/1) — pro DT.
        crossing_threshold: práh sekundárního topologického signálu.
        cap_factor: práh endpoint DT (≤ cap_factor × median DT = pointed cap).

    Returns:
        (objects, histogram) — histogram {(crossings, caps): počet}.
    """
    # DT spočítej 1× nad celým clean masem — pointed_cap_count ho pak používá
    # per segment bez recompute.
    clean_bin = (clean_mask > 0).astype(np.uint8)
    distance_transform = cv2.distanceTransform(clean_bin, cv2.DIST_L2, 5)

    histogram: dict[tuple[int, int], int] = {}

    for obj in objects:
        if obj.symbol_code != "102":
            continue

        crossings = crossing_signal(claim_mask, obj.id)
        caps = pointed_cap_count(claim_mask, distance_transform, obj.id, cap_factor)

        key = (crossings, caps)
        histogram[key] = histogram.get(key, 0) + 1

        # Kombinované pravidlo (viz docstring).
        is_strong = caps >= 2
        is_medium = caps >= 1 and crossings >= crossing_threshold

        if is_strong or is_medium:
            obj.symbol_code = "109"
            obj.detection_method = DETECTION_METHOD
            obj.confidence = CONFIDENCE_109

    return objects, histogram
