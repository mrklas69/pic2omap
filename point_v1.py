"""
Point detector v1 — bodové symboly (knoll, depression, pit, special veg, balvan…).

Vstup:
    output/<sample>/components/cat_<category>_point.png  (stage 3 point bucket)

Výstup:
    list[MapObject] s geometry_type="point",
    + claim_mask (uint16) s MapObject.id pro každý detekovaný pixel.

Metoda:
    Connected components na cat_<cat>_point.png. Bodové symboly jsou malé kompaktní
    útvary. Filtr velikostí (okno MIN..MAX area) + protáhlostí (aspect — vyřadí
    fragmenty linií, které propadly do point bucketu).

POZOR — point bucket je SILNĚ zašuměný:
    Forest sample: brown 291 komponent vs **7** GT bodů (115/116), black 226 vs 4,
    green 196 vs 21. Point symboly jsou drobné (median 8 px, 4–30 px) a topí se ve
    fragmentech vrstevnic/cest, mid-symbolech a anti-aliasu. Naivní "komponenta =
    bod" over-claimuje 10–40× (memory `sparse-gt-naive-detector-trap`).

    v1 je proto JEN odrazový můstek pro ladění detekce: filtruje velikostí + tvarem,
    ale over-claim akceptuje (uvidíš ho v `compare_to_omap --db`). Disambiguace per
    symbol (115 oblouk vs 116 plný trojúhelník vs 112 tečka), pozice-based check
    (depression leží v důlku vrstevnic) a izolovanost od linií jsou v2+.

Záměrně NEfiltrujeme agresivně tvarem (fill/solidity): point symboly jsou tvarově
různorodé — 116 Pit je plný, 115 Small depression je obrys/oblouk (nízký fill).
Tvrdý fill práh by vyřadil legitimní obrysové značky.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from color_category import ColorCategory
from db_model import MapObject


# Default ISOM kód per kategorie — nejčastější bodový symbol té barvy ve forest GT.
# (brown: 115 Depression 6× + 116 Pit 1×; black: 536 Tower/Grave; green: 418/419
# Special vegetation feature.) Point symboly se ale mezi mapami hodně liší — toto
# je hrubý default; přesnější rozlišení per tvar/pozice je v2.
DEFAULT_SYMBOL_PER_CATEGORY: dict[ColorCategory, str] = {
    ColorCategory.BROWN: "115",   # Small depression
    ColorCategory.BLACK: "536",   # Small tower (forest); obecně balvan/věž
    ColorCategory.GREEN: "418",   # Special vegetation feature
}

# Velikostní okno bodu v px (kalibrace forest sample ~300 DPI, render 631×478).
# Pod MIN = anti-alias / šum, nad MAX = fragment area/linie (ne bod).
# Per-category, protože různé symboly mají různou velikost; pro jiný DPI škálovat.
MIN_AREA_PX_PER_CATEGORY: dict[ColorCategory, int] = {
    ColorCategory.BROWN: 6,
    ColorCategory.BLACK: 6,
    ColorCategory.GREEN: 6,
}
MAX_AREA_PX_PER_CATEGORY: dict[ColorCategory, int] = {
    ColorCategory.BROWN: 60,
    ColorCategory.BLACK: 60,
    ColorCategory.GREEN: 60,
}

# Maximální protáhlost (delší strana / kratší). Bodové symboly jsou ~kruhové
# (aspect ~1). Vyšší = fragment linie. POZOR: 113 Elongated knoll je protáhlý —
# tento filtr ho vyřadí (forest GT ho nemá, takže OK; pro mapy s 113 zvednout).
MAX_ASPECT_RATIO = 2.5

# Confidence — point detekce je nejistá (vysoký over-claim), nízká hodnota.
CONFIDENCE = 0.40


def detect(
    out_dir: Path,
    image_shape: tuple[int, int],
    category: ColorCategory,
    starting_id: int,
    iteration: int,
    min_area_px: int | None = None,
    max_area_px: int | None = None,
    max_aspect: float = MAX_ASPECT_RATIO,
    default_code: str | None = None,
) -> tuple[list[MapObject], np.ndarray]:
    """
    Detektor bodových symbolů pro danou kategorii.

    Args:
        out_dir: kořen output/<sample>/.
        image_shape: (h, w) zdrojového rasteru — claim_mask má stejné rozměry.
        category: ColorCategory (BROWN / BLACK / GREEN podporované v1).
        starting_id: první volný MapObject.id (persistent ID continuity).
        iteration: číslo iterace.
        min_area_px / max_area_px: velikostní okno bodu (None → per-category default).
        max_aspect: max protáhlost (delší/kratší strana bboxu).
        default_code: template-aware kód (None → holý DEFAULT_SYMBOL_PER_CATEGORY).

    Returns:
        (objects, claim_mask) — list MapObject + uint16 mask s ID per pixel.
    """
    if category not in DEFAULT_SYMBOL_PER_CATEGORY:
        supported = ", ".join(c.value for c in DEFAULT_SYMBOL_PER_CATEGORY)
        raise SystemExit(f"point_v1 nepodporuje kategorii {category} (jen {supported}).")

    point_mask_path = out_dir / "components" / f"cat_{category.value}_point.png"
    if not point_mask_path.exists():
        raise SystemExit(
            f"Point detector vyžaduje Stage 3 výstup:\n"
            f"  {point_mask_path}\n"
            f"Spusť `python stage3_demo.py <obrázek>` první."
        )

    # cv2.imread na Windows neumí UTF-8 cesty → načti přes Path.read_bytes + imdecode.
    data = np.frombuffer(point_mask_path.read_bytes(), dtype=np.uint8)
    mask = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    mask_bin = (mask > 0).astype(np.uint8) * 255

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_bin, connectivity=8)

    if min_area_px is None:
        min_area_px = MIN_AREA_PX_PER_CATEGORY[category]
    if max_area_px is None:
        max_area_px = MAX_AREA_PX_PER_CATEGORY[category]
    if default_code is None:
        default_code = DEFAULT_SYMBOL_PER_CATEGORY[category]
    detection_method = "point_v1"

    h, w = image_shape
    claim_mask = np.zeros((h, w), dtype=np.uint16)
    objects: list[MapObject] = []
    next_id = starting_id

    for i in range(1, n_labels):
        x, y, comp_w, comp_h, area = stats[i]

        # Velikostní okno: vyřadí šum (moc malé) i fragmenty area/linií (moc velké).
        if area < min_area_px or area > max_area_px:
            continue
        # Protáhlost: vyřadí kousky linií (vrstevnice, cesty) v point bucketu.
        aspect = max(comp_w, comp_h) / max(1, min(comp_w, comp_h))
        if aspect > max_aspect:
            continue

        obj = MapObject(
            id=next_id,
            symbol_code=default_code,
            geometry_type="point",
            category=category,
            bbox=(int(x), int(y), int(x + comp_w - 1), int(y + comp_h - 1)),
            pixel_count=int(area),
            pixel_blob_id=next_id,
            confidence=CONFIDENCE,
            detected_in_iter=iteration,
            detection_method=detection_method,
        )
        objects.append(obj)
        claim_mask[labels == i] = next_id
        next_id += 1

    return objects, claim_mask
