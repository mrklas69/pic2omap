"""
Border probe — per brown skeleton segment spočítá, kolik černých pixelů
leží v jeho dilatovaném okolí.

Cíl: disambiguace 503 Minor road / 529 Paved area (mají paralelní BLACK
border) vs 102 Index contour (čistá brown linie, žádný black border).
Thickness samotná nestačí — 503 brown fill ≈ 4 px, 102 ≈ 4 px (overlap).

Metoda:
    1. Connected components brown skeleton.
    2. Per segment: dilatuj jen tento segment 9×9 kernelem → "neighborhood
       band" radius 4 px kolem skeletu.
    3. AND s cat_black_clean.png → kolik černých pixelů v okolí.
    4. border_ratio = black_pixels_in_band / skeleton_segment_length

Kernel kalibrace pro forest sample (~273 DPI, ~105 µm/px):
    - 503 Minor road brown fill 0.45 mm = 4.3 px (half = 2.15 px od skeletu)
    - 503 black border 0.27 mm = 2.6 px (poloměr 1.3 px)
    - Vzdálenost od skeletu ke středu black borderu = 2.15 + 1.3 = ~3.5 px
    - Kernel 9×9 (radius 4) zachytí border center; 11×11 (radius 5) celý.

Očekávání:
    101 Contour:     ratio ~ 0       (žádný black v okolí)
    102 Index:       ratio ~ 0       (žádný black v okolí)
    103 Form line:   ratio ~ 0       (čárkovaná brown, žádný border)
    503 Minor road:  ratio ~ 1-3     (black border na obou stranách,
                                       ≥ 2 black px per skeleton px)
    529 Paved area:  ratio ~ 1-3     (black bounding line obvodu plochy)

Threshold odhad ~0.5: ratio > 0.5 → road/paved area (filter out při
detekci vrstevnic).

CLI:
    python border_probe.py "output/forest sample"
    python border_probe.py "output/forest sample" --kernel-size 11
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

# DRY: peak categorization a thresholds z visualizeru.
from peak_visualizer import PEAK_THICK_MIN, PEAK_THIN_MAX, classify_segments


def measure_border_ratio(
    skeleton: np.ndarray,
    neighbor_mask: np.ndarray,
    kernel_size: int = 9,
) -> tuple[np.ndarray, dict[int, tuple[int, float, int]]]:
    """
    Per skeleton segment spočítá (length, border_ratio, neighbor_overlap_px).

    border_ratio = neighbor_overlap_px / segment_length_px

    skeleton, neighbor_mask: uint8 0/255, stejné rozměry.
    kernel_size: lichá hodnota; 9 = radius 4 px (default).

    Vrací:
        labels_image: int32 z connectedComponents (sdílí se s peak_visualizer).
        data: dict {label_id: (length, ratio, overlap_px)}
    """
    num_labels, labels = cv2.connectedComponents(skeleton, connectivity=8)
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    # Pre-binarize neighbor (rychlejší než opakovaný > 0 v cyklu).
    neighbor_bool = neighbor_mask > 0

    data: dict[int, tuple[int, float, int]] = {}
    for label_id in range(1, num_labels):
        # Maska jen tohoto segmentu.
        segment_mask = (labels == label_id).astype(np.uint8) * 255
        length = int((segment_mask > 0).sum())
        if length == 0:
            continue
        # Dilatace per-segment (nikoli per-whole-skeleton, kvůli sledování
        # vlivu jednoho segmentu na jeho okolí — ostatní segmenty nás tu
        # nezajímají).
        dilated = cv2.dilate(segment_mask, kernel, iterations=1)
        overlap = int(((dilated > 0) & neighbor_bool).sum())
        ratio = float(overlap) / length
        data[label_id] = (length, ratio, overlap)

    return labels, data


def format_ascii_histogram(
    values: list[float],
    bins: int = 20,
    width: int = 50,
    label: str = "",
) -> str:
    """ASCII histogram. KISS, bez matplotlib. (DRY: stejný kód jako probe — TODO refaktor.)"""
    if not values:
        return "(žádné segmenty)"
    arr = np.asarray(values)
    counts, edges = np.histogram(arr, bins=bins)
    max_count = int(counts.max()) if counts.size else 0
    lines: list[str] = []
    for i in range(bins):
        bar_len = int(width * counts[i] / max_count) if max_count else 0
        lines.append(f"  {edges[i]:6.2f}-{edges[i + 1]:6.2f} {label} | "
                     f"{'#' * bar_len} ({counts[i]})")
    return "\n".join(lines)


def main() -> None:
    from cli_utils import force_utf8_console
    force_utf8_console()

    parser = argparse.ArgumentParser(
        description="Probe presence sousední kategorie v okolí brown skeleton "
                    "(disambiguace 503/529 roads vs 102 contour).",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Adresář s morphology/ + skeleton/ (typicky 'output/<sample>').",
    )
    parser.add_argument(
        "--category",
        type=str,
        default="brown",
        help="Hlavní kategorie (default 'brown' = vrstevnice + roads).",
    )
    parser.add_argument(
        "--neighbor",
        type=str,
        default="black",
        help="Kategorie pro detekci v okolí (default 'black' = borders).",
    )
    parser.add_argument(
        "--kernel-size",
        type=int,
        default=9,
        help="Liché. Default 9 = radius 4 px. Pro forest sample (~273 DPI) "
             "kernel ≥ 9 zachytí black border 503 Minor road.",
    )
    args = parser.parse_args()

    if args.kernel_size % 2 == 0:
        raise SystemExit(f"--kernel-size musí být liché ({args.kernel_size} není).")

    skeleton_path = args.output_dir / "skeleton" / f"cat_{args.category}_skeleton.png"
    clean_path = args.output_dir / "morphology" / f"cat_{args.category}_clean.png"
    neighbor_path = args.output_dir / "morphology" / f"cat_{args.neighbor}_clean.png"

    for p in (skeleton_path, clean_path, neighbor_path):
        if not p.exists():
            raise SystemExit(f"Vstup neexistuje: {p}")

    skeleton = cv2.imread(str(skeleton_path), cv2.IMREAD_GRAYSCALE)
    clean = cv2.imread(str(clean_path), cv2.IMREAD_GRAYSCALE)
    neighbor = cv2.imread(str(neighbor_path), cv2.IMREAD_GRAYSCALE)

    skeleton_bin = (skeleton > 0).astype(np.uint8) * 255
    clean_bin = (clean > 0).astype(np.uint8) * 255
    neighbor_bin = (neighbor > 0).astype(np.uint8) * 255

    # Border ratio per segment.
    labels, border_data = measure_border_ratio(skeleton_bin, neighbor_bin, args.kernel_size)

    # Peak classification (pro per-peak breakdown). DRY z peak_visualizer.
    _, peak_groups = classify_segments(skeleton_bin, clean_bin)

    # --- Report ---
    print(f"=== Border probe: {args.category} vs {args.neighbor} ===")
    print(f"Skeleton:  {skeleton_path}")
    print(f"Clean:     {clean_path}")
    print(f"Neighbor:  {neighbor_path}")
    print(f"Kernel:    {args.kernel_size}×{args.kernel_size} "
          f"(radius {args.kernel_size // 2}px)")
    print(f"Segmentů:  {len(border_data)}")
    print()

    all_ratios = [r for _, r, _ in border_data.values()]
    print("Distribuce border_ratio (všechny segmenty):")
    print(format_ascii_histogram(all_ratios, bins=20))
    print()
    print("Statistika overall:")
    print(f"  Min: {min(all_ratios):.2f}, Max: {max(all_ratios):.2f}")
    print(f"  Median: {float(np.median(all_ratios)):.2f}, Mean: {float(np.mean(all_ratios)):.2f}")
    print(f"  P25: {float(np.percentile(all_ratios, 25)):.2f}, "
          f"P75: {float(np.percentile(all_ratios, 75)):.2f}")
    print()

    # Per-peak breakdown — klíčové pro vyhodnocení.
    for peak_name in ("thin", "mid", "thick"):
        label_ids = peak_groups.get(peak_name, [])
        ratios = [border_data[lid][1] for lid in label_ids if lid in border_data]
        if not ratios:
            continue
        print(f"--- Peak {peak_name} ({len(ratios)} segmentů) ---")
        print(f"  Median ratio: {float(np.median(ratios)):.2f}")
        print(f"  Mean ratio:   {float(np.mean(ratios)):.2f}")
        print(f"  P25: {float(np.percentile(ratios, 25)):.2f}, "
              f"P75: {float(np.percentile(ratios, 75)):.2f}, "
              f"P90: {float(np.percentile(ratios, 90)):.2f}")
        # Top 10 nejvyšší ratio v tomto peaku — kandidáti road/paved area.
        peak_segs = [
            (lid, *border_data[lid])
            for lid in label_ids
            if lid in border_data
        ]
        # x = (label_id, length, ratio, overlap)
        peak_segs.sort(key=lambda x: -x[2])
        print(f"  Top 10 nejvyšší ratio (kandidáti road/paved):")
        for lid, length, ratio, overlap in peak_segs[:10]:
            print(f"    #{lid:>3}: length={length:>3}px, "
                  f"ratio={ratio:5.2f}, overlap={overlap:>4}px")
        print(f"  Top 5 nejnižší ratio (kandidáti čistý contour):")
        for lid, length, ratio, overlap in peak_segs[-5:]:
            print(f"    #{lid:>3}: length={length:>3}px, "
                  f"ratio={ratio:5.2f}, overlap={overlap:>4}px")
        print()


if __name__ == "__main__":
    main()
