"""
Stage 3 / krok 3: skeletonizace LINE masek na 1-pixelové středovky.

Vstup: LINE sub-masky z components.py (jen liniové komponenty per kategorie).
Výstup: 1-pixelová "kostra" — středovka každé linie. Příprava pro Stage 5
(vektorizace), kdy kostra → polyline → Bezier.

Algoritmus: scikit-image skeletonize (default = Zhang-Suen).
Důvody:
- Zachovává konektivitu (na rozdíl od morfologického ztenčení erosion-loop).
- Robustní vůči mírnému zvlnění hrany (anti-aliasing).
- Garantuje 1-pixelovou šířku výstupu.

POINT a AREA masky se neskeletonizují — body jsou už malé (skelet =
1 pixel = stejné info, ztratíme tvar), plochy potřebují jiný přístup
(rozeznání pattern fill, vnější hranice → kontura, ne kostra).
"""

from pathlib import Path

import cv2
import numpy as np
from skimage.morphology import skeletonize

from color_category import ColorCategory
from components import ComponentType


def skeletonize_mask(mask: np.ndarray) -> np.ndarray:
    """
    Aplikuje Zhang-Suen skeletonizaci na binární masku.

    Args:
        mask: (H, W) uint8, 0/255.

    Returns:
        (H, W) uint8 0/255 — 1-pixelová kostra. Tam, kde mask byla 0,
        zůstane 0. Tam, kde byla původně 255, je 255 jen na "ose" linie.

    skimage.skeletonize očekává bool nebo {0,1}, vrací bool.
    Konvertujeme z uint8 0/255 → bool → skeletonize → uint8 0/255 zpět.
    """
    # Bool input: True pro popředí (255), False pro pozadí (0).
    # Použití > 0 místo == 255 pro robustnost (občas mask má hodnoty 1, 127, …).
    bool_mask = mask > 0
    if not bool_mask.any():
        # Prázdná maska → prázdná kostra, žádný výpočet.
        return np.zeros_like(mask)
    skel_bool = skeletonize(bool_mask)
    # Bool → uint8: True * 255 = 255, False * 255 = 0.
    return (skel_bool.astype(np.uint8) * 255)


def skeletonize_line_masks(
    per_category: dict[ColorCategory, dict[ComponentType, np.ndarray]],
) -> dict[ColorCategory, np.ndarray]:
    """
    Pro každou kategorii skeletonizuje její LINE masku.

    Args:
        per_category: výstup z components.split_category_masks().

    Returns:
        dict {category → skeleton mask}. Obsahuje jen kategorie, které
        opravdu mají nějakou LINE komponentu (prázdné se vynechají, ať
        výstupní složka není zaplevelena).
    """
    skeletons: dict[ColorCategory, np.ndarray] = {}
    for category, type_masks in per_category.items():
        line_mask = type_masks.get(ComponentType.LINE)
        if line_mask is None:
            continue
        # Skip, pokud LINE maska je prázdná (žádné liniové komponenty pro tuto kategorii).
        if not line_mask.any():
            continue
        skeletons[category] = skeletonize_mask(line_mask)
    return skeletons


def count_skeleton_pixels(skeleton: np.ndarray) -> int:
    """Počet "nenulových" pixelů v kostře — proxy pro celkovou délku linií."""
    return int(np.count_nonzero(skeleton))


def save_skeletons(
    skeletons: dict[ColorCategory, np.ndarray],
    output_dir: Path,
) -> None:
    """Uloží kostry. Jméno: cat_<color>_skeleton.png."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for category, skel in skeletons.items():
        filename = f"cat_{category.value}_skeleton.png"
        cv2.imwrite(str(output_dir / filename), skel)


def format_skeleton_report(
    skeletons: dict[ColorCategory, np.ndarray],
    per_category: dict[ColorCategory, dict[ComponentType, np.ndarray]],
) -> str:
    """
    Report: pro každou kategorii kolik LINE pixelů bylo před/po skeletonizaci.

    Poměr after/before je nepřímý odhad střední tloušťky linie:
    skeleton má šířku 1px, takže before/after ≈ střední tloušťka v px.
    """
    lines = [
        f"{'Kategorie':<10s}  {'LINE px':>10s}  {'Skel px':>10s}  {'Tloušťka':>10s}"
    ]
    # Sort podle počtu skeleton pixelů descending — nejhustší linie nahoru.
    sorted_cats = sorted(
        skeletons.keys(),
        key=lambda c: count_skeleton_pixels(skeletons[c]),
        reverse=True,
    )
    for category in sorted_cats:
        skel = skeletons[category]
        line_mask = per_category[category][ComponentType.LINE]
        before = int(np.count_nonzero(line_mask))
        after = count_skeleton_pixels(skel)
        # Ochrana proti dělení nulou (před == 0 by znamenalo, že není co skeletonizovat).
        thickness = (before / after) if after > 0 else 0.0
        lines.append(
            f"{category.value:<10s}  "
            f"{before:>10,}  "
            f"{after:>10,}  "
            f"{thickness:>9.2f}x"
        )
    return "\n".join(lines)
