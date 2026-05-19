"""
Area detector v1 — solid fill plochy per ColorCategory.

Vstup:
    output/<sample>/components/cat_<category>_area.png  (stage 3 area bucket)

Výstup:
    list[MapObject] s geometry_type="area", symbol_code = default per kategorie
    + claim_mask (uint16) s MapObject.id pro každý detekovaný pixel

Metoda:
    Connected components na cat_<cat>_area.png. Filtruj podle minimální velikosti
    (vyloučí fragmenty z over-segmentace). Density check eliminuje zaplněné protáhlé
    fragmenty linií, které propadly do area bucketu.

Co v1 NEUMÍ (přijde v2):
    - Per-priority disambiguation. Stage 2 produkuje priority/*.png per OMAP barvu,
      ale v1 přiřazuje všem komponentám v kategorii jeden default code (nejčastější).
      v2: pro každou komponentu zjistit dominantní priority mask → mapuj na ISOM kód.
    - Pattern fill areas (407, 409 Undergrowth, 404, 415 — line/dot patterns) jsou
      v stage 3 buď v point/line bucketu, nebo fragmentované — v1 je zatím ignoruje.

Viz docs/db_schema.md (datový model) + memory `verify-domain-claims-against-source`.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from color_category import ColorCategory
from db_model import MapObject


# Filter parametry pro v1 — kalibrace na forest sample (631×478).
# Per-category threshold: yellow je čistší (méně fragmentace), green je
# víc rozsekané kvůli překryvům s vrstevnicemi → potřebuje vyšší min_area.
# Pro jiný DPI / rozlišení škálovat lineárně.
MIN_AREA_PX_PER_CATEGORY: dict[ColorCategory, int] = {
    ColorCategory.GREEN: 30,    # GT 99 solid → 114 detekováno (mírná over-segmentace)
    ColorCategory.YELLOW: 20,   # GT 26 solid → 26 detekováno (exact match)
}

# Density check eliminuje zaplněné protáhlé fragmenty linií (které by jinak
# propadly z line bucketu do area bucketu kvůli pixel anomáliím).
MIN_DENSITY = 0.4

# Stripe filter — ignoruje úzké svislé útvary (pattern fill fragmenty).
# Aktivní per kategorii: zapnuto kde známe problematické pattern symboly.
#   GREEN: 89 × pattern fragments (407 Undergrowth slow + 409 Undergrowth difficult)
#   YELLOW: jen 9 × pattern (415, 404), filter ublíží víc než pomůže
APPLY_STRIPE_FILTER_PER_CATEGORY: dict[ColorCategory, bool] = {
    ColorCategory.GREEN: True,
    ColorCategory.YELLOW: False,
}

# Stripe definice: width ≤ STRIPE_MAX_WIDTH px AND h/w ≥ STRIPE_MIN_ASPECT.
# Kalibrace na forest sample (~1:15000 scale, ~300 DPI).
STRIPE_MAX_WIDTH = 4
STRIPE_MIN_ASPECT = 2.0

# Default ISOM kód per kategorie — nejčastější solid area v dané rodině.
# Konkrétní disambiguation per inner_color přijde v v2.
DEFAULT_SYMBOL_PER_CATEGORY: dict[ColorCategory, str] = {
    ColorCategory.GREEN: "406",    # Forest: slow running (45 z 99 solid green ve forest sample)
    ColorCategory.YELLOW: "403",   # Rough open land (20 z 26 solid yellow)
}

# Confidence — solid area detekce je relativně spolehlivá pokud pass density filter.
# Snížíme confidence kvůli nejistotě v ISOM code (default per kategorie, ne přesný kód).
CONFIDENCE = 0.65


def _is_vertical_stripe(
    comp_w: int,
    comp_h: int,
    map_orientation_deg: float,
) -> bool:
    """
    Detekuje úzké svislé útvary (typicky 407/409 pattern fragmenty).

    Pro orientaci = 0 (north=up) přímo měříme bbox: width × height.
    Pro rotovanou mapu (orientation != 0) musí být transform bbox →
    north-aligned, pak měřit. v1 KISS: zatím jen orientation == 0 case.
    """
    # Tolerance ±5° kolem 0 — Hough peak může lehce uchýlit i pro skutečný
    # north=up rastr. Forest sample fallback orientation=0 spadne sem.
    if abs(map_orientation_deg) > 5.0:
        # Rotovaná mapa — bbox není přímo srovnatelný s "svislé". v1 skip.
        # v2: rotovat (comp_w, comp_h) podle orientation a pak měřit.
        # Viz TODO.md "Stripe filter pro rotated maps".
        return False
    if comp_w > STRIPE_MAX_WIDTH:
        return False
    if comp_h / max(comp_w, 1) < STRIPE_MIN_ASPECT:
        return False
    return True


def detect(
    out_dir: Path,
    image_shape: tuple[int, int],
    category: ColorCategory,
    starting_id: int,
    iteration: int,
    map_orientation_deg: float = 0.0,
    min_area_px: int | None = None,
    min_density: float = MIN_DENSITY,
) -> tuple[list[MapObject], np.ndarray]:
    """
    Detektor solid area pro danou kategorii (green / yellow).

    Args:
        out_dir: kořen output/<sample>/.
        image_shape: (h, w) zdrojového rasteru — claim_mask má stejné rozměry.
        category: ColorCategory.GREEN nebo YELLOW (v1 podporované rodiny).
        starting_id: první volný MapObject.id pro persistent ID continuity.
        iteration: číslo iterace.
        min_area_px: minimum pixelů komponenty (filtr fragmentů).
        min_density: minimum density = area / bbox_area (filtr elongated linií).

    Returns:
        (objects, claim_mask) — list MapObject + uint16 mask s ID per pixel.
    """
    # Stage 3 výstup pro tuto kategorii.
    area_mask_path = out_dir / "components" / f"cat_{category.value}_area.png"
    if not area_mask_path.exists():
        raise SystemExit(
            f"Area detector vyžaduje Stage 3 výstup:\n"
            f"  {area_mask_path}\n"
            f"Spusť `python stage3_demo.py <obrázek>` první."
        )

    mask = cv2.imread(str(area_mask_path), cv2.IMREAD_GRAYSCALE)
    # Binarizace pro jistotu (cat_*_area.png by mělo být 0/255, ale safety net).
    mask_bin = (mask > 0).astype(np.uint8) * 255

    # connectedComponentsWithStats vrátí stats array s [x, y, w, h, area] per label.
    # Indexy stats[0] = background (label=0), my procházíme 1..N.
    n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask_bin, connectivity=8,
    )

    # ISOM kód podle kategorie — v1 jediný default per kategorie.
    if category not in DEFAULT_SYMBOL_PER_CATEGORY:
        raise SystemExit(f"area_v1 nepodporuje kategorii {category} (jen GREEN, YELLOW).")
    symbol_code = DEFAULT_SYMBOL_PER_CATEGORY[category]
    # detection_method = jméno detektoru (= název souboru), ne per-kategorie.
    # Kategorie už drží MapObject.category — duplikovat ji sem by porušilo SLAP.
    detection_method = "area_v1"

    # Per-category threshold (s možností override přes argument).
    if min_area_px is None:
        min_area_px = MIN_AREA_PX_PER_CATEGORY[category]

    h, w = image_shape
    claim_mask = np.zeros((h, w), dtype=np.uint16)
    objects: list[MapObject] = []
    next_id = starting_id

    for i in range(1, n_labels):
        # CC_STAT_LEFT, _TOP, _WIDTH, _HEIGHT, _AREA — indexy 0..4
        x, y, comp_w, comp_h, area = stats[i]

        if area < min_area_px:
            continue
        density = area / (comp_w * comp_h) if comp_w * comp_h > 0 else 0
        if density < min_density:
            continue
        # Stripe filter — vyhodí pattern fragmenty (úzké svislé) jen pro
        # kategorie, kde mají statisticky problém (GREEN). YELLOW filtruje
        # víc legitních small areas než pattern fragmentů.
        if APPLY_STRIPE_FILTER_PER_CATEGORY.get(category, False):
            if _is_vertical_stripe(int(comp_w), int(comp_h), map_orientation_deg):
                continue

        obj = MapObject(
            id=next_id,
            symbol_code=symbol_code,
            geometry_type="area",
            category=category,
            # bbox inkluzivně do x+w-1, y+h-1 (konzistence s brown_line_v1).
            bbox=(int(x), int(y), int(x + comp_w - 1), int(y + comp_h - 1)),
            pixel_count=int(area),
            pixel_blob_id=next_id,
            confidence=CONFIDENCE,
            detected_in_iter=iteration,
            detection_method=detection_method,
        )
        objects.append(obj)
        # Claim mask: pixel hodnota = MapObject.id.
        claim_mask[labels == i] = next_id
        next_id += 1

    return objects, claim_mask
