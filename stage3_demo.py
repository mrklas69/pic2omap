"""
CLI demo Stage 3: morfologické čištění → connected components → skeletonizace.

Použití:
    python stage3_demo.py "output/forest sample/category"

Předpokládá, že vstupní složka obsahuje cat_*.png z Stage 2 color separation.
Výstupy se zapisují do sourozenecké složky <input>/../morphology/ resp. components/
resp. skeleton/.

Adresářová struktura výstupu:

    output/forest sample/
        category/                # vstup ze Stage 2
            cat_brown.png
            cat_green.png
            ...
        morphology/              # Stage 3.1
            cat_brown_clean.png
            ...
        components/              # Stage 3.2
            cat_brown_line.png
            cat_brown_point.png
            cat_brown_area.png
            ...
        skeleton/                # Stage 3.3
            cat_brown_skeleton.png
            ...
        _stage3_report.txt       # report všech tří kroků
"""

import sys
from pathlib import Path

# UTF-8 stdout pro českou diakritiku ve Windows konzoli.
from cli_utils import force_utf8_console
force_utf8_console()

from components import (
    format_components_report,
    save_split_masks,
    split_category_masks,
)
from morphology import (
    clean_category_masks,
    format_stats_report,
    load_category_masks,
    save_cleaned_masks,
)
from skeleton import (
    format_skeleton_report,
    save_skeletons,
    skeletonize_line_masks,
)


def main(category_dir_str: str) -> None:
    category_dir = Path(category_dir_str)
    if not category_dir.is_dir():
        print(f"CHYBA: vstupní složka neexistuje: {category_dir}", file=sys.stderr)
        sys.exit(1)

    # Výstupní složky = sourozenci vstupu.
    base_dir = category_dir.parent
    morph_dir = base_dir / "morphology"
    comp_dir = base_dir / "components"
    skel_dir = base_dir / "skeleton"

    # --- Krok 1: morfologické čištění ---
    print(f"[1/3] Načítám per-category masky z: {category_dir}")
    raw_masks = load_category_masks(category_dir)
    if not raw_masks:
        print("CHYBA: žádné cat_*.png masky nenalezeny", file=sys.stderr)
        sys.exit(1)
    print(f"      {len(raw_masks)} kategorií")

    print(f"      Morfologie (opening 2x2 default)...")
    cleaned_masks, clean_stats = clean_category_masks(raw_masks)
    save_cleaned_masks(cleaned_masks, morph_dir)
    print(f"      Uloženo do: {morph_dir}")

    # --- Krok 2: connected components + klasifikace ---
    print(f"[2/3] Connected components per kategorie...")
    per_category, comp_stats = split_category_masks(cleaned_masks)
    save_split_masks(per_category, comp_dir)
    print(f"      Uloženo do: {comp_dir}")

    # --- Krok 3: skeletonizace LINE masek ---
    print(f"[3/3] Skeletonizace LINE masek...")
    skeletons = skeletonize_line_masks(per_category)
    save_skeletons(skeletons, skel_dir)
    print(f"      Uloženo do: {skel_dir} ({len(skeletons)} kategorií s liniemi)")

    # --- Report ---
    report_sections: list[str] = []
    report_sections.append(f"=== Stage 3 report — vstup: {category_dir.name} ===\n")

    report_sections.append("[Krok 1] Morfologické čištění (opening 2x2):\n")
    report_sections.append(format_stats_report(clean_stats))
    report_sections.append("")

    report_sections.append("[Krok 2] Connected components (klasifikace POINT/LINE/AREA):\n")
    report_sections.append(format_components_report(comp_stats))
    report_sections.append("")

    report_sections.append("[Krok 3] Skeletonizace LINE masek:\n")
    report_sections.append(format_skeleton_report(skeletons, per_category))

    report_text = "\n".join(report_sections)
    print()
    print(report_text)

    report_path = base_dir / "_stage3_report.txt"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\nReport zapsán do: {report_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default pro snadné testování.
        default = "output/forest sample/category"
        print(f"Použiji default: {default}")
        main(default)
    else:
        main(sys.argv[1])
