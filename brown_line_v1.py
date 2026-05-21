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

import re
from pathlib import Path

import cv2
import numpy as np

from cli_utils import imread_unicode
from color_category import ColorCategory
from db_model import MapObject
from omap_model import LineSymbol, SymbolLibrary, SymbolType
from peak_visualizer import classify_segments


# Confidence per peak — thin peak je čistší signal (ostrý peak v histogramu),
# thick peak je rozmazanější. Hodnoty empirické, dotuníme po validaci.
CONFIDENCE_THIN = 0.85    # → 101 Contour
CONFIDENCE_THICK = 0.80   # → 102 Index contour

DETECTION_METHOD = "brown_line_v1"

# Default ISOM kódy pro thin/thick peaks. Slouží jako fallback pro
# template-aware lookup (resolve_brown_line_codes) — pokud library nemá
# matching symbol, vrátíme tyto defaults. Forest sample.omap má přesně
# tyto kódy bez suffixu, takže fallback "vždy funguje" pro něj.
DEFAULT_THIN_CODE = "101"     # Contour
DEFAULT_THICK_CODE = "102"    # Index contour

# Regex patterny pro template-aware lookup. Slovanka2016 má kódy "101.0" /
# "102.0" (.0 suffix konvence), forest sample "101" / "102". Pattern matchne
# obojí. Stejný idiom jako OOM_SPECIFIC_PATTERNS v area_v1.
_THIN_CODE_PATTERN = re.compile(r"^101(\.\d+)?$")
_THICK_CODE_PATTERN = re.compile(r"^102(\.\d+)?$")


def resolve_brown_line_codes(library: SymbolLibrary) -> tuple[str, str]:
    """
    Pro danou library vyzvedne exact ISOM kódy pro 101 Contour a 102 Index contour.

    Důvod: brown_line_v1 detektor potřebuje claimnout symbol_code, který je
    v té konkrétní library — db2omap export by jinak nenašel matching symbol_id.
    Forest sample.omap: ("101", "102"). Slovanka2016.omap: ("101.0", "102.0").

    Implementace:
        Iteruje LineSymboly v library a první symbol s `code` matchnutým proti
        _THIN_CODE_PATTERN / _THICK_CODE_PATTERN bere jako autoritativní.
        V praxi OMAP soubory mají per Contour / Index contour jeden symbol,
        takže "první match" nehrozí kolize.

    Returns:
        (thin_code, thick_code). Pokud library nemá matching symbol pro některou
        rolí, vrátí DEFAULT_THIN_CODE / DEFAULT_THICK_CODE jako fallback —
        detekce stále poběží, jen na fallback kódu.

    Viz memory `template-aware-symbol-codes` (Slovanka .0 suffix vs forest sample).
    """
    thin_code: str | None = None
    thick_code: str | None = None
    # symbols_by_type vrací list[SymbolBase], castujeme přes isinstance pro IDE.
    for sym in library.symbols_by_type(SymbolType.LINE):
        if not isinstance(sym, LineSymbol):
            continue
        if thin_code is None and _THIN_CODE_PATTERN.match(sym.code):
            thin_code = sym.code
        elif thick_code is None and _THICK_CODE_PATTERN.match(sym.code):
            thick_code = sym.code
        # Early exit jakmile máme oba (typicky se najdou rychle).
        if thin_code is not None and thick_code is not None:
            break
    return (
        thin_code if thin_code is not None else DEFAULT_THIN_CODE,
        thick_code if thick_code is not None else DEFAULT_THICK_CODE,
    )


def detect(
    out_dir: Path,
    image_shape: tuple[int, int],
    starting_id: int,
    iteration: int,
    thin_code: str = DEFAULT_THIN_CODE,
    thick_code: str = DEFAULT_THICK_CODE,
) -> tuple[list[MapObject], np.ndarray]:
    """
    Spustí brown line detekci nad Stage 3 výstupy.

    Args:
        out_dir: kořen output/<sample>/ (obsahuje skeleton/ a morphology/).
        image_shape: (h, w) zdrojového rasteru — claim_mask má stejné rozměry.
        starting_id: první volné MapObject.id (pro persistent IDs napříč detektory).
        iteration: číslo iterace, půjde do MapObject.detected_in_iter.
        thin_code: ISOM kód pro thin peak (default "101"). Pro template-aware
            lookup použij `resolve_brown_line_codes(library)`.
        thick_code: ISOM kód pro thick peak (default "102").

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
    skeleton = imread_unicode(skeleton_path, cv2.IMREAD_GRAYSCALE)
    clean = imread_unicode(clean_path, cv2.IMREAD_GRAYSCALE)
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

    # Thin peak → 101 Contour (exact code z library nebo default).
    for label_id in groups["thin"]:
        obj = _build_object_from_label(
            labels, label_id,
            object_id=next_id,
            symbol_code=thin_code,
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
            symbol_code=thick_code,
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
