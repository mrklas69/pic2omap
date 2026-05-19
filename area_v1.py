"""
Area detector v1 + v2 — solid fill plochy per ColorCategory.

Vstup:
    output/<sample>/components/cat_<category>_area.png  (stage 3 area bucket)
    output/<sample>/priority/priority{NN}_*.png         (stage 2, pro v2 disambiguation)

Výstup:
    list[MapObject] s geometry_type="area",
    + claim_mask (uint16) s MapObject.id pro každý detekovaný pixel

Metoda:
    Connected components na cat_<cat>_area.png. Filtruj podle minimální velikosti
    (vyloučí fragmenty z over-segmentace). Density check eliminuje zaplněné protáhlé
    fragmenty linií, které propadly do area bucketu.

v1 (default): symbol_code = `DEFAULT_SYMBOL_PER_CATEGORY[cat]` (např. GREEN→406).

v2 (per-priority disambiguation): pokud caller předá `priority_to_code` mapping,
detektor pro každou komponentu spočítá overlap s jednotlivými priority maskami,
najde dominantní priority a z mappingu vyzvedne konkrétní ISOM kód
(např. priority 21 Yellow 70% → 404 Rough open land with scattered trees).
Pokud priority nemá unambiguous kód, fallback na default.

Co stále NEUMÍ:
    - Pattern fill areas (407, 409 Undergrowth, 404, 415 — line/dot patterns) jsou
      v stage 3 buď v point/line bucketu, nebo fragmentované.

Viz docs/db_schema.md (datový model) + memory `verify-domain-claims-against-source`.
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

from color_category import ColorCategory
from db_model import MapObject
from omap_model import NO_COLOR, AreaSymbol, SymbolLibrary, SymbolType


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

# v2 disambiguation: jiná confidence pro priority-resolved kódy (vyšší, protože
# víme od které OMAP color přišly), vs default fallback (= CONFIDENCE).
CONFIDENCE_DISAMBIGUATED = 0.80

# Majority threshold pro v2 disambiguation: dominantní priority musí pokrýt
# ALESPOŇ tento podíl pixelů komponenty. Jinak fallback na default kód.
# Důvod: bez prahu vyhrávají i okrajové priority s 10-20 % overlapu (např.
# Green 50% Yellow jako lem velké 406 area → falešně klasifikováno jako
# 527 Settlement). 50% = "víc než ostatní dohromady" — typická "majority"
# definice. Komponenty z cat_*_area.png typicky pokrývají 2-3 priority,
# tedy 60% byl moc přísný a zabil i legitimní disambiguation (např. 404 priority 21).
MAJORITY_THRESHOLD = 0.50

# OOM-specific area symboly, které nemají odraz v ISOM/ISSprOM specifikaci.
# Filtrujeme je při per-priority disambiguation — bez nich se priority 13/15/16
# odemknou z AMBIGUOUS (více kódů) do UNIQUE (jen 410/408/006).
# Pattern: 411 Forest runnable in one direction má varianty 411.0 / 411.1 / 411.2.
OOM_SPECIFIC_PATTERNS = (
    re.compile(r"^411(\.\d+)?$"),    # Forest runnable in one direction (OMAP-only)
)


def _is_oom_specific_code(code: str) -> bool:
    """True pokud ISOM kód je OOM-internal varianta (ne IOF spec)."""
    return any(p.match(code) for p in OOM_SPECIFIC_PATTERNS)


# Sémantické rodiny ISOM kódů (per první číslice):
#   1XX = Landforms (brown — vrstevnice, banks, knolls)
#   2XX = Rock (black/gray)
#   3XX = Water (blue)
#   4XX = Vegetation (green / yellow)
#   5XX = Man-made (black — buildings, roads, fences)
#   6XX = Technical (north lines, registration)
#   7XX = Course planning (purple)
#
# Pro GREEN/YELLOW disambiguation chceme jen 4XX symboly. OMAP design
# choice (např. forest sample.omap priority 10 "Green 50% Yellow" → 527
# Settlement) je pro nás false positive — Settlement není vegetation.
ALLOWED_ISOM_PREFIX_PER_CATEGORY: dict[ColorCategory, str] = {
    ColorCategory.GREEN: "4",     # Vegetation only (40X, 41X)
    ColorCategory.YELLOW: "4",    # Vegetation only
    # Až přibyde BROWN area detektor, "1" + některé z "2".
    # BLACK area detektor: "5" (man-made).
}


def _is_semantically_compatible(code: str, category: ColorCategory) -> bool:
    """
    Sémantická kontrola: kód patří do ISOM rodiny očekávané pro kategorii.
    Bez tohoto filtru by GREEN area mohla dostat 527 Settlement (man-made)
    jen proto, že OMAP color profile používá Green 50% Yellow paletu.
    """
    allowed_prefix = ALLOWED_ISOM_PREFIX_PER_CATEGORY.get(category)
    if allowed_prefix is None:
        return True  # Kategorie bez restrikce.
    return code.startswith(allowed_prefix)


def build_priority_to_area_code(
    library: SymbolLibrary,
    category: ColorCategory,
    category_map: dict[int, ColorCategory],
) -> dict[int, str]:
    """
    Pro danou kategorii postaví mapping priority → ISOM kód area symbolu.

    Heuristika:
        1. Pro každý AreaSymbol v library najdi jeho priority (`inner_color_ref`,
           fallback `secondary_color_ref` pro pattern areas).
        2. Filter na kategorii (priority musí spadat do dané ColorCategory).
        3. Per priority sloučíme všechny ISOM kódy.
        4. Pokud po filtru OOM-specific (411.X) zbyl jeden kód → mapuj.
           Pokud zbylo víc → priority je "ambiguous" (vynech z mappingu →
           caller fallne na default).
        5. Pokud žádný non-OOM-specific neexistuje → vynech.

    Args:
        library: parsovaný OMAP (zdroj area symbol definic).
        category: filtr — bere se jen area s priority spadající do této kategorie.
        category_map: priority → ColorCategory (z color_category.build_category_map).

    Returns:
        dict {priority_int: isom_code_str} pro unambiguous priority.
        Ostatní priority chybí — fallback na default per kategorii.
    """
    # Per priority akumulujeme kandidátní kódy (AreaSymbol code).
    candidates: dict[int, list[str]] = {}
    for sym in library.symbols_by_type(SymbolType.AREA):
        # isinstance pro type narrowing (mypy/IDE happy + safety).
        if not isinstance(sym, AreaSymbol):
            continue
        # Primary inner_color, fallback secondary (pattern areas).
        ref = sym.inner_color_ref if sym.inner_color_ref != NO_COLOR else sym.secondary_color_ref
        if ref == NO_COLOR or ref not in category_map:
            continue
        if category_map[ref] != category:
            continue
        candidates.setdefault(ref, []).append(sym.code)

    # Per priority: filtruj OOM-specific (411.X) a semanticky nekompatibilní kódy
    # (5XX Settlement v GREEN je OMAP design choice, ale my chceme jen vegetation).
    result: dict[int, str] = {}
    for prio, codes in candidates.items():
        # Dvojí filtr: ne OOM-specific AND semanticky pasující kategorii.
        clean = [
            c for c in codes
            if not _is_oom_specific_code(c) and _is_semantically_compatible(c, category)
        ]
        if len(clean) == 1:
            result[prio] = clean[0]
        # Pokud clean je prázdný (jen OOM-specific nebo wrong category) NEBO > 1
        # (genuine ambiguity v rámci kategorie), vynech — caller fallne na default.

    return result


def load_priority_masks(priority_dir: Path) -> dict[int, np.ndarray]:
    """
    Načte všechny priority{NN}_*.png masky z Stage 2 výstupu.

    Klíč = priority číslo (int, extrahované z názvu souboru).
    Hodnota = uint8 binary mask (0/255), shape jako zdrojový raster.

    Vrací prázdný dict pokud adresář neexistuje (= bez disambiguation,
    caller fallne na default).
    """
    masks: dict[int, np.ndarray] = {}
    if not priority_dir.is_dir():
        return masks
    # Pattern: priority{NN}_<name>.png. NN je 0-2 číslic, parse přes split.
    for png_path in priority_dir.glob("priority*.png"):
        # "priority07_Brown.png" → "07_Brown" → "07"
        stem = png_path.stem[len("priority"):]
        num_str = stem.split("_", 1)[0]
        try:
            prio = int(num_str)
        except ValueError:
            continue  # Neobvyklý filename, ignoruj.
        mask = cv2.imread(str(png_path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue
        masks[prio] = mask
    return masks


def _disambiguate_component(
    component_pixels: np.ndarray,
    priority_masks: dict[int, np.ndarray],
    priority_to_code: dict[int, str],
    majority_threshold: float = MAJORITY_THRESHOLD,
) -> str | None:
    """
    Pro jednu komponentu (bool maska pixelů) najdi dominantní priority a
    z mappingu vyzvedni ISOM kód.

    Args:
        component_pixels: bool mask (H, W), True kde komponenta žije.
        priority_masks: priority → binární maska (uint8 0/255).
        priority_to_code: priority → ISOM kód (unambiguous z build_priority_to_area_code).
        majority_threshold: dominantní priority musí pokrývat ≥ tento podíl
            pixelů komponenty. Jinak vrátí None (= caller použije default).

    Returns:
        ISOM kód jako string, nebo None pokud:
            - žádný overlap s priority maskami,
            - dominantní priority není v `priority_to_code` mappingu,
            - dominantní priority nedosáhla majority threshold.
    """
    component_size = int(component_pixels.sum())
    if component_size == 0:
        return None
    best_prio: int | None = None
    best_overlap = 0
    for prio, mask in priority_masks.items():
        # Overlap = počet pixelů komponenty, které mají priority mask "1".
        # Vektorová AND: bool & (uint8 > 0). .sum() je rychlejší než np.count_nonzero
        # u bool array.
        overlap = int((component_pixels & (mask > 0)).sum())
        if overlap > best_overlap:
            best_overlap = overlap
            best_prio = prio
    if best_prio is None or best_overlap == 0:
        return None
    # Majority check: bez ní by vyhrály okrajové priority s 10-20 % overlapu.
    if best_overlap / component_size < majority_threshold:
        return None
    return priority_to_code.get(best_prio)  # None pokud priority není v mappingu


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
    priority_to_code: dict[int, str] | None = None,
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
        priority_to_code: optional v2 disambiguation. Pokud zadán, pro každou
            komponentu se zjistí dominantní priority a vyzvedne se konkrétní ISOM
            kód. Pokud None nebo priority není v mappingu, fallback na
            DEFAULT_SYMBOL_PER_CATEGORY[category].

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

    # Default ISOM kód podle kategorie (fallback pro v2 disambiguation).
    if category not in DEFAULT_SYMBOL_PER_CATEGORY:
        raise SystemExit(f"area_v1 nepodporuje kategorii {category} (jen GREEN, YELLOW).")
    default_code = DEFAULT_SYMBOL_PER_CATEGORY[category]
    # detection_method = jméno detektoru (= název souboru), ne per-kategorie.
    detection_method = "area_v1"

    # v2 disambiguation enabled? Načti priority masky z output/<sample>/priority/.
    # Bez priority_to_code (= v1 mode) tento krok přeskoč.
    priority_masks: dict[int, np.ndarray] = {}
    if priority_to_code is not None:
        priority_masks = load_priority_masks(out_dir / "priority")

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

        # v2 disambiguation: pokud máme priority_to_code mapping + priority masky,
        # zkus najít konkrétní kód. Jinak fallback na default per kategorii.
        symbol_code = default_code
        confidence = CONFIDENCE
        if priority_to_code is not None and priority_masks:
            # Bool maska pixelů této komponenty (pro overlap voting).
            component_pixels = labels == i
            resolved = _disambiguate_component(
                component_pixels, priority_masks, priority_to_code,
            )
            if resolved is not None:
                symbol_code = resolved
                confidence = CONFIDENCE_DISAMBIGUATED

        obj = MapObject(
            id=next_id,
            symbol_code=symbol_code,
            geometry_type="area",
            category=category,
            # bbox inkluzivně do x+w-1, y+h-1 (konzistence s brown_line_v1).
            bbox=(int(x), int(y), int(x + comp_w - 1), int(y + comp_h - 1)),
            pixel_count=int(area),
            pixel_blob_id=next_id,
            confidence=confidence,
            detected_in_iter=iteration,
            detection_method=detection_method,
        )
        objects.append(obj)
        # Claim mask: pixel hodnota = MapObject.id.
        claim_mask[labels == i] = next_id
        next_id += 1

    return objects, claim_mask
