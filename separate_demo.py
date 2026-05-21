"""
CLI demo: color separation pipeline na zadaný PNG + OMAP soubor.

Použití:
    python separate_demo.py "resources/forest sample.png" "resources/forest sample.omap"

Výstup:
    output/<image_stem>/
        priority00_Purple.png         # binární maska pro každou barvu
        priority01_Black.png
        ...
        _overview.png                  # quantized verze celého obrazu
        _report.txt                    # statistika per barva (% pixelů)
"""

import sys
from pathlib import Path

import cv2
import numpy as np

# UTF-8 stdout pro českou diakritiku ve Windows konzoli.
from cli_utils import force_utf8_console, imread_unicode
force_utf8_console()

from color_category import (
    build_category_map_with_overrides,
    group_profiles_by_category,
)
from color_profile import build_color_profiles, deduplicate_by_rgb
from color_separator import (
    make_overview,
    merge_masks_by_category,
    save_category_masks,
    save_masks,
    separate_colors,
)
from omap_parser import parse_omap


def main(image_path_str: str, omap_path_str: str) -> None:
    image_path = Path(image_path_str)
    omap_path = Path(omap_path_str)

    if not image_path.exists():
        print(f"CHYBA: obraz neexistuje: {image_path}", file=sys.stderr)
        sys.exit(1)
    if not omap_path.exists():
        print(f"CHYBA: OMAP neexistuje: {omap_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Načítám OMAP: {omap_path.name}")
    library = parse_omap(omap_path)
    all_profiles = build_color_profiles(library)
    profiles = deduplicate_by_rgb(all_profiles)
    print(f"  {len(library.colors)} barev v library, {len(profiles)} unikátních RGB")

    print(f"Načítám obraz: {image_path.name}")
    image_bgr = imread_unicode(str(image_path))  # ne cv2.imread — diakritika v cestě
    if image_bgr is None:
        print("CHYBA: nelze načíst obraz", file=sys.stderr)
        sys.exit(1)
    h, w = image_bgr.shape[:2]
    print(f"  rozlišení: {w}x{h} ({w * h:,} pixelů)")

    print("Color separation běží...")
    assignment, masks = separate_colors(image_bgr, profiles)

    # Output adresář pojmenovaný podle vstupního obrazu (bez koncovky).
    # .stem = "forest sample" pro "forest sample.png"
    output_dir = Path("output") / image_path.stem
    priority_dir = output_dir / "priority"
    category_dir = output_dir / "category"
    print(f"Ukládám per-priority masky do: {priority_dir}")
    save_masks(masks, profiles, priority_dir)

    # Sloučení do sémantických kategorií (Brown family, Green family, ...).
    print("Slučuji do sémantických rodin (ColorCategory)...")
    category_map = build_category_map_with_overrides(profiles)
    category_masks = merge_masks_by_category(masks, category_map)
    print(f"Ukládám per-category masky do: {category_dir}")
    save_category_masks(category_masks, category_dir)

    # Report o kategorizaci — které profiles spadly do které rodiny.
    grouped = group_profiles_by_category(profiles, category_map)
    print("\nKategorizace barev:")
    for cat, stats in grouped.items():
        # Vypíšeme jména barev v této kategorii (s jejich priority)
        members = ", ".join(
            f"#{p} {n}" for p, n in zip(stats.profile_priorities, stats.profile_names)
        )
        print(f"  {cat.value:7s} ({len(stats.profile_priorities)}x): {members}")

    # Overview = quantized verze obrazu (každý pixel přebarven na svou palette barvu).
    overview = make_overview(image_bgr, assignment, profiles)
    cv2.imwrite(str(output_dir / "_overview.png"), overview)

    # Report: kolik procent pixelů zabírá každá barva.
    # Slouží k rychlému přehledu, které barvy v obrazu dominují.
    total_pixels = h * w
    report_lines = [f"Color separation report: {image_path.name}"]
    report_lines.append(f"Rozlišení: {w}x{h} ({total_pixels:,} pixelů)")
    report_lines.append(f"Palette: {len(profiles)} unikátních barev")
    report_lines.append("")
    report_lines.append(f"{'Priority':>8s}  {'Pixelů':>10s}  {'Procent':>7s}  Barva")
    # Sort by pixel count desc — dominantní barvy nahoru.
    sorted_priorities = sorted(
        masks.keys(),
        key=lambda p: int(np.count_nonzero(masks[p])),
        reverse=True,
    )
    for priority in sorted_priorities:
        count = int(np.count_nonzero(masks[priority]))
        pct = 100.0 * count / total_pixels
        # Najít jméno podle priority
        prof = next(p for p in profiles if p.priority == priority)
        report_lines.append(
            f"{priority:>8d}  {count:>10,}  {pct:>6.2f}%  {prof.name} (RGB {prof.rgb})"
        )

    report_text = "\n".join(report_lines)
    print()
    print(report_text)
    (output_dir / "_report.txt").write_text(report_text, encoding="utf-8")

    print(f"\nHotovo. Výstup v: {output_dir}/")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        # Default pro snadné testování
        image_arg = "resources/forest sample.png"
        omap_arg = "resources/forest sample.omap"
        print(f"Použiji default: {image_arg} + {omap_arg}")
    else:
        image_arg = sys.argv[1]
        omap_arg = sys.argv[2]
    main(image_arg, omap_arg)
