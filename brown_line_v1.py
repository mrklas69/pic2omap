"""
Brown line detector v1 — thickness-based klasifikace vrstevnic.

Vstup:
    output/<sample>/skeleton/cat_brown_skeleton.png   (1px středovky)
    output/<sample>/morphology/cat_brown_clean.png    (clean mask pro distance transform)

Výstup (pro pic2db.cmd_detect):
    - list[MapObject] pro symboly 101 (Contour) a 102 (Index contour)
    - claim_mask: uint16 ndarray (h, w), hodnota = MapObject.id, 0 = unclaimed

Metoda:
    Skeleton segmenty se rozdělí podle median tloušťky (z distance transformu)
    do tří peaks (thin/mid/thick — viz peak_visualizer.PEAK_THIN_MAX/_THICK_MIN).
    - thin  → 101 Contour
    - thick → 102 Index contour
    - mid   → záměrně neclassifikováno (anti-aliasing / nejistá zóna, zůstává unclaimed)

Co v1 neumí (přijde dalšími detektory):
    - 103 Form line (čárkovaná) — vyžaduje detekci dash patternu
    - 110 Erosion gully — krátké segmenty s mid-symbol tečkami
    - 104/106 Earth bank, Minor road — jiné brown line symboly v skeleton

Důsledek: brown line skeleton bude po v1 mít rezidua (mid peak + ostatní brown
symboly). To je OK — fáze B je iterativní, další detektor přidá další claimy.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from color_category import ColorCategory
from db_model import MapObject
from peak_visualizer import classify_segments


# Confidence per peak — thin peak je čistší signal (ostrý peak v histogramu),
# thick peak je rozmazanější. Hodnoty empirické, dotuníme po validaci.
CONFIDENCE_THIN = 0.85    # → 101 Contour
CONFIDENCE_THICK = 0.80   # → 102 Index contour

DETECTION_METHOD = "brown_line_v1"


def detect(
    out_dir: Path,
    image_shape: tuple[int, int],
    starting_id: int,
    iteration: int,
) -> tuple[list[MapObject], np.ndarray]:
    """
    Spustí brown line detekci nad Stage 3 výstupy.

    Args:
        out_dir: kořen output/<sample>/ (obsahuje skeleton/ a morphology/).
        image_shape: (h, w) zdrojového rasteru — claim_mask má stejné rozměry.
        starting_id: první volné MapObject.id (pro persistent IDs napříč detektory).
        iteration: číslo iterace, půjde do MapObject.detected_in_iter.

    Returns:
        (objects, claim_mask). claim_mask je uint16 (h, w), 0 = unclaimed,
        jinak hodnota pixelu = MapObject.id (jediný objekt na pixel).
    """
    skeleton_path = out_dir / "skeleton" / "cat_brown_skeleton.png"
    clean_path = out_dir / "morphology" / "cat_brown_clean.png"

    # Bez Stage 3 výstupů nemůžeme detektor spustit — explicit fail hint pro usera.
    if not skeleton_path.exists() or not clean_path.exists():
        raise SystemExit(
            f"Brown line detector vyžaduje Stage 3 výstupy:\n"
            f"  {skeleton_path}\n  {clean_path}\n"
            f"Spusť `python stage3_demo.py <obrázek>` první."
        )

    # Načtení masek. peak_visualizer očekává binární 0/255 vstup.
    skeleton = cv2.imread(str(skeleton_path), cv2.IMREAD_GRAYSCALE)
    clean = cv2.imread(str(clean_path), cv2.IMREAD_GRAYSCALE)
    # Astype na uint8 + *255 zaručí, že hodnoty jsou {0, 255} (jistota pro
    # connectedComponents, který přijímá thresholdovaný vstup).
    skeleton_bin = (skeleton > 0).astype(np.uint8) * 255
    clean_bin = (clean > 0).astype(np.uint8) * 255

    # classify_segments dělá connectedComponents + distance transform + thickness peak.
    # Vrací (labels_image, {thin: [...], mid: [...], thick: [...]}).
    labels, groups = classify_segments(skeleton_bin, clean_bin)

    h, w = image_shape
    # uint16 claim mask — viz docs/db_schema.md (kapacita 65535 ID per iter).
    claim_mask = np.zeros((h, w), dtype=np.uint16)
    objects: list[MapObject] = []

    # Manual counter — zachovává persistent ID napříč různými skupinami.
    next_id = starting_id

    # Thin peak → 101 Contour.
    for label_id in groups["thin"]:
        obj = _build_object_from_label(
            labels, label_id,
            object_id=next_id,
            symbol_code="101",
            iteration=iteration,
            confidence=CONFIDENCE_THIN,
        )
        objects.append(obj)
        # Pixely segmentu dostanou hodnotu = MapObject.id (1:1 mapping
        # mezi pixel_blob_id a MapObject.id pro v1).
        claim_mask[labels == label_id] = obj.id
        next_id += 1

    # Thick peak → 102 Index contour.
    for label_id in groups["thick"]:
        obj = _build_object_from_label(
            labels, label_id,
            object_id=next_id,
            symbol_code="102",
            iteration=iteration,
            confidence=CONFIDENCE_THICK,
        )
        objects.append(obj)
        claim_mask[labels == label_id] = obj.id
        next_id += 1

    # Mid peak — záměrně přeskočen. Pixely zůstávají unclaimed (0 v claim_mask).
    # Důvod: 2.4–3.4 px peak může být anti-aliasing, junction pixely, form line
    # fragment, ... — bez dalšího signálu neumíme zaříknout.

    return objects, claim_mask


def _build_object_from_label(
    labels: np.ndarray,
    label_id: int,
    object_id: int,
    symbol_code: str,
    iteration: int,
    confidence: float,
) -> MapObject:
    """
    Helper: postaví MapObject z connected component label.

    Vypočítá bbox + pixel_count přímo ze souřadnic. Bbox je inkluzivní
    (max je poslední pixel v segmentu, ne max+1 — konzistentní s OMAP).
    """
    # np.where vrátí (rows, cols) = (ys, xs). Pro bbox potřebujeme min/max obou.
    ys, xs = np.where(labels == label_id)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))

    return MapObject(
        id=object_id,
        symbol_code=symbol_code,
        geometry_type="line",
        category=ColorCategory.BROWN,
        bbox=bbox,
        pixel_count=int(len(xs)),
        # 1:1 mapping: pixel hodnota v claim_mask = MapObject.id.
        # V2 by mohlo mít separátní blob_id (např. když 1 logický objekt
        # má víc disconnected komponent), zatím KISS.
        pixel_blob_id=object_id,
        confidence=confidence,
        detected_in_iter=iteration,
        detection_method=DETECTION_METHOD,
    )
