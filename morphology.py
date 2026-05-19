"""
Stage 3 / krok 1: morfologické čištění per-category masek.

Vstup: binární masky (uint8 0/255) z color_separator (Stage 2).
Po color separation jsou na hranách barev 1-2px anti-aliasing artefakty:
izolované pixely "vyšumují" z masek, malé díry uvnitř ploch.

Konzervativní strategie: 2x2 opening pro všechny barevné kategorie,
žádné closing. Důvod: vrstevnice na rendered PNG jsou ~1px tlusté,
3x3 opening by je smazalo. Closing skrýva problémy, ne řeší — řešíme
později podle vizuálního zhodnocení.

WHITE je pozadí (není mapový obsah), morfologii neaplikujeme — výsledek
by mohl "zaplnit" mapový obsah uvnitř WHITE oblastí.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from color_category import ColorCategory


@dataclass(frozen=True)
class MorphParams:
    """
    Parametry morfologického čištění pro jednu kategorii.

    Kernel velikost N znamená NxN obdélníkový strukturní element.
    0 = operace se vynechá (pro skip jednotlivé operace nebo celé kategorie).
    """
    # Opening (erosion → dilation): odstraní izolované pixely a tenké výběžky.
    # Konzervativní default 2 = mírné čištění aliasing artefaktů.
    open_kernel: int = 2
    # Closing (dilation → erosion): zaplní malé díry uvnitř objektů,
    # spojí přerušené čáry. Defaultně vypnuto (riziko slévání).
    close_kernel: int = 0


# Per-category parametry. Konzervativní start: všude jen 2x2 opening.
# Po vizuálním zhodnocení doladíme (např. closing pro vrstevnice rozsekané
# překryvem cest, větší kernel pro plochy).
CATEGORY_PARAMS: dict[ColorCategory, MorphParams] = {
    ColorCategory.BLACK: MorphParams(open_kernel=2),
    ColorCategory.BROWN: MorphParams(open_kernel=2),
    ColorCategory.GREEN: MorphParams(open_kernel=2),
    ColorCategory.YELLOW: MorphParams(open_kernel=2),
    ColorCategory.BLUE: MorphParams(open_kernel=2),
    ColorCategory.PURPLE: MorphParams(open_kernel=2),
    ColorCategory.GRAY: MorphParams(open_kernel=2),
    ColorCategory.RED: MorphParams(open_kernel=2),
    # WHITE = pozadí, morfologii neaplikujeme (viz docstring modulu).
    ColorCategory.WHITE: MorphParams(open_kernel=0, close_kernel=0),
}


@dataclass
class CleanStats:
    """Statistika čištění jedné masky — kolik pixelů zmizelo/přibylo."""
    category: ColorCategory
    pixels_before: int
    pixels_after: int

    @property
    def pixels_diff(self) -> int:
        """Záporné = ubylo (typické pro opening), kladné = přibylo (closing)."""
        return self.pixels_after - self.pixels_before

    @property
    def pct_change(self) -> float:
        """Procentuální změna vůči vstupu. 0 pokud vstup byl prázdný."""
        if self.pixels_before == 0:
            return 0.0
        return 100.0 * self.pixels_diff / self.pixels_before


def clean_mask(mask: np.ndarray, params: MorphParams) -> np.ndarray:
    """
    Aplikuje morfologické čištění na jednu binární masku.

    Args:
        mask: binární maska (H, W) uint8, hodnoty 0/255.
        params: parametry pro tuto kategorii.

    Returns:
        Vyčištěná maska stejného shape/dtype.

    Pořadí: nejdřív opening (odstraní šum), pak closing (zaplní díry).
    Důvod: closing před opening by mohl rozšířit šum předtím, než ho odstraníme.
    """
    result = mask
    if params.open_kernel > 0:
        # Obdélníkový kernel — pro orienťácké mapy nemá smysl elliptic
        # (linie i plochy jsou geometricky pravoúhlé v rastrové reprezentaci).
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (params.open_kernel, params.open_kernel)
        )
        result = cv2.morphologyEx(result, cv2.MORPH_OPEN, kernel)
    if params.close_kernel > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (params.close_kernel, params.close_kernel)
        )
        result = cv2.morphologyEx(result, cv2.MORPH_CLOSE, kernel)
    return result


def clean_category_masks(
    category_masks: dict[ColorCategory, np.ndarray],
    params_map: dict[ColorCategory, MorphParams] | None = None,
) -> tuple[dict[ColorCategory, np.ndarray], list[CleanStats]]:
    """
    Vyčistí všechny per-category masky.

    Args:
        category_masks: vstupní masky, např. z merge_masks_by_category().
        params_map: per-category params. None → použije CATEGORY_PARAMS default.

    Returns:
        (cleaned_masks, stats_list) — vyčištěné masky + statistika per kategorii.
    """
    if params_map is None:
        params_map = CATEGORY_PARAMS

    cleaned: dict[ColorCategory, np.ndarray] = {}
    stats: list[CleanStats] = []

    for category, mask in category_masks.items():
        # Pokud kategorie nemá params, fallback na defaultní MorphParams() = 2x2 opening.
        params = params_map.get(category, MorphParams())
        pixels_before = int(np.count_nonzero(mask))
        cleaned_mask = clean_mask(mask, params)
        pixels_after = int(np.count_nonzero(cleaned_mask))
        cleaned[category] = cleaned_mask
        stats.append(
            CleanStats(
                category=category,
                pixels_before=pixels_before,
                pixels_after=pixels_after,
            )
        )

    return cleaned, stats


def load_category_masks(input_dir: Path) -> dict[ColorCategory, np.ndarray]:
    """
    Načte per-category masky z disku (output cat_*.png ze Stage 2).

    Soubor cat_<value>.png → ColorCategory podle .value stringu.
    Načte v grayscale módu (cv2.IMREAD_GRAYSCALE) — masky jsou single-channel.

    Soubory, jejichž jméno neodpovídá žádné ColorCategory.value, přeskočí.
    """
    masks: dict[ColorCategory, np.ndarray] = {}
    # Lookup table: hodnota (např. "brown") → enum item.
    by_value = {cat.value: cat for cat in ColorCategory}

    for path in sorted(input_dir.glob("cat_*.png")):
        # Z "cat_brown.png" vytáhneme "brown".
        value = path.stem[len("cat_"):]
        category = by_value.get(value)
        if category is None:
            # Nejde o naši kategorii, ignoruj (např. ručně vložený soubor).
            continue
        mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue
        masks[category] = mask
    return masks


def save_cleaned_masks(
    masks: dict[ColorCategory, np.ndarray],
    output_dir: Path,
) -> None:
    """Uloží vyčištěné masky. Jméno: cat_<value>_clean.png."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for category, mask in masks.items():
        filename = f"cat_{category.value}_clean.png"
        cv2.imwrite(str(output_dir / filename), mask)


def format_stats_report(stats: list[CleanStats]) -> str:
    """Textový report o čištění — pro výpis a uložení do souboru."""
    lines = [
        f"{'Kategorie':<10s}  {'Před':>10s}  {'Po':>10s}  {'Diff':>10s}  {'Změna':>8s}"
    ]
    # Sort podle absolutní velikosti změny (descending) — zajímavější nahoru.
    for s in sorted(stats, key=lambda x: abs(x.pixels_diff), reverse=True):
        lines.append(
            f"{s.category.value:<10s}  "
            f"{s.pixels_before:>10,}  "
            f"{s.pixels_after:>10,}  "
            f"{s.pixels_diff:>+10,}  "
            f"{s.pct_change:>+7.2f}%"
        )
    return "\n".join(lines)
