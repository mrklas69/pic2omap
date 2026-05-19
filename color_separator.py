"""
Stage 2 pipeline: color separation rasterového obrazu.

Princip: máme fixní paletu kanonických OMAP barev (z ColorProfile).
Pro každý pixel rastru najdeme nejbližší barvu v LAB prostoru → assignment.
Output: per-barva binární maska (uint8, 0/255).

Žádný unsupervised K-means — palette je predefined a sémanticky pojmenovaná,
což je výhoda oproti čistému clusteringu.
"""

from pathlib import Path

import cv2
import numpy as np

from color_category import ColorCategory
from color_profile import ColorProfile


def separate_colors(
    image_bgr: np.ndarray,
    profiles: list[ColorProfile],
) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """
    Color separation: každý pixel přiřadí k nejbližší barvě z palety.

    Args:
        image_bgr: vstupní obraz (H, W, 3) v BGR (OpenCV default).
        profiles: seznam barev v paletě.

    Returns:
        assignment: ndarray (H, W) int — index do profiles, nejbližší barva.
        masks: dict {priority -> binary mask (H,W) uint8 0/255}.
               Klíčem je ColorProfile.priority (ne index do profiles!),
               ať je výstup stabilní napříč různě filtrovanými profile listy.
    """
    h, w = image_bgr.shape[:2]

    # 1) Převod celého obrazu na LAB najednou (rychlejší než pixel-by-pixel).
    # cv2 očekává uint8 BGR vstup, vrací LAB uint8 (L=0-255, a=0-255, b=0-255).
    image_lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)

    # 2) Reshape na (H*W, 3) pro vektorové porovnání s paletou.
    # float32 kvůli odčítání (uint8 by overflow při (a-b)**2).
    pixels = image_lab.reshape(-1, 3).astype(np.float32)

    # 3) Palette jako (N_colors, 3) array.
    palette = np.array(
        [p.lab for p in profiles],
        dtype=np.float32,
    )  # shape (N, 3)

    # 4) Vektorový výpočet kvadrátu euklidovské vzdálenosti pixel → palette.
    # pixels shape (P, 3), palette shape (N, 3).
    # Trik: pixels[:, None, :] - palette[None, :, :] dá broadcasting na (P, N, 3),
    # pak suma kvadrátů přes osu 2 → (P, N) matice vzdáleností^2.
    # Bereme argmin přes osu 1 → (P,) indexů nejbližší palette barvy.
    # POZN.: Pro velké obrazy by (P, N, 3) mohlo žrát paměť.
    # 631x478 = 0.3M pixelů, 0.3M * 22 * 3 * 4B = ~80 MB float32 — OK.
    # Pro větší obrazy by se to mělo chunkovat.
    diff = pixels[:, np.newaxis, :] - palette[np.newaxis, :, :]
    dist_sq = np.sum(diff * diff, axis=2)  # (P, N)
    nearest = np.argmin(dist_sq, axis=1)   # (P,)

    # 5) Assignment ndarray (H, W) — pro každý pixel index do profiles.
    assignment = nearest.reshape(h, w)

    # 6) Per-color binární masky.
    masks: dict[int, np.ndarray] = {}
    for idx, prof in enumerate(profiles):
        # mask = bool (H,W), convertujeme na uint8 0/255 pro uložení jako PNG.
        mask = (assignment == idx).astype(np.uint8) * 255
        # Klíč = profile.priority (stabilní cross-library identifier).
        masks[prof.priority] = mask

    return assignment, masks


def save_masks(
    masks: dict[int, np.ndarray],
    profiles: list[ColorProfile],
    output_dir: Path,
) -> None:
    """
    Uloží každou masku jako PNG do output_dir.

    Jméno souboru: priority{NN}_{slug-name}.png
    Slug: jméno barvy se sanitized whitespace + special chars na "_".
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Mapování priority -> profile pro snadné dohledání jména.
    prof_by_priority = {p.priority: p for p in profiles}

    for priority, mask in masks.items():
        prof = prof_by_priority[priority]
        # Slug: lower, non-alnum → "_", strip duplicates.
        # Není potřeba být dokonalý — jen filename safe.
        slug = "".join(c if c.isalnum() else "_" for c in prof.name).strip("_")
        filename = f"priority{priority:02d}_{slug}.png"
        cv2.imwrite(str(output_dir / filename), mask)


def merge_masks_by_category(
    masks: dict[int, np.ndarray],
    category_map: dict[int, ColorCategory],
) -> dict[ColorCategory, np.ndarray]:
    """
    Sloučí per-priority masky do per-category masek.

    Pixel je v category masce, pokud patřil k některé z priorities patřících
    do té kategorie. Logické OR přes binární masky (0/255).

    Args:
        masks: výstup separate_colors(), klíč = priority.
        category_map: výstup build_category_map(), priority → ColorCategory.

    Returns:
        dict {ColorCategory → mask (H,W) uint8 0/255}.
    """
    merged: dict[ColorCategory, np.ndarray] = {}
    for priority, mask in masks.items():
        # category_map by měla mít všechny priorities z masks, ale buďme robustní.
        cat = category_map.get(priority)
        if cat is None:
            continue
        if cat not in merged:
            # První maska pro tuto kategorii — zkopírujeme (jinak bychom modifikovali
            # vstupní mask in-place v dalších iteracích).
            merged[cat] = mask.copy()
        else:
            # Bitwise OR — pixel patří kategorii, pokud byl v jakékoliv z priority masek.
            # cv2.bitwise_or je rychlejší než np.maximum pro uint8.
            merged[cat] = cv2.bitwise_or(merged[cat], mask)
    return merged


def save_category_masks(
    category_masks: dict[ColorCategory, np.ndarray],
    output_dir: Path,
) -> None:
    """
    Uloží per-category masky jako PNG.
    Jméno: cat_<category_value>.png (např. cat_brown.png).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for category, mask in category_masks.items():
        filename = f"cat_{category.value}.png"
        cv2.imwrite(str(output_dir / filename), mask)


def make_overview(
    image_bgr: np.ndarray,
    assignment: np.ndarray,
    profiles: list[ColorProfile],
) -> np.ndarray:
    """
    Vytvoří "quantized" verzi obrazu: každý pixel přebarven na svou
    palette barvu. Užitečné pro vizuální kontrolu — vidíme, co color
    separation udělala s celým obrazem najednou.
    """
    h, w = assignment.shape

    # Palette jako (N, 3) BGR (OpenCV default pro imwrite).
    # Konvertujeme RGB tuple → BGR tuple.
    palette_bgr = np.array(
        [(p.rgb[2], p.rgb[1], p.rgb[0]) for p in profiles],
        dtype=np.uint8,
    )  # (N, 3) BGR

    # Indexace: pro každý pixel vezmi BGR z palety.
    # palette_bgr[assignment] vrací shape (H, W, 3).
    quantized = palette_bgr[assignment]
    return quantized
