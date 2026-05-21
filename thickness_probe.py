"""
Diagnostický probe — distribuce tlouštěk skeleton fragmentů.

Cíl: zjistit, jestli skeleton segmenty z `cat_<color>_skeleton.png` tvoří
bimodální distribuci tlouštěk (= dva clustery → 101 Contour vs 102 Index
contour separovatelné), nebo unimodální (= klasifikace přes tloušťku samotnou
neprojde, potřeba další features).

**Nevýstupem** je klasifikace per segment — to je úkol pro Stage 4 detektor.
Tady **měříme**, ať víme, na čem stavět.

Metoda:
    1. Skeleton (`cat_<color>_skeleton.png`, 1px středovky) → connected
       components → každý fragment dostane label.
    2. Clean mask (`cat_<color>_clean.png`, full-thickness po Stage 3
       morfologii) → distance transform → každý mask pixel zná vzdálenost
       k pozadí (= poloměr lokální tloušťky).
    3. Pro každý skeleton fragment: vyber jeho pixely, vyčti z DT hodnoty,
       *2 = lokální tloušťka v px. Median přes pixely = robustní per-segment
       tloušťka (odolnější k endpointům, kde distance klesá k 0).

CLI:
    python thickness_probe.py "output/forest sample"
    python thickness_probe.py "output/forest sample" --category brown
"""

import argparse
from pathlib import Path

import cv2
import numpy as np


def measure_segment_thickness(
    skeleton: np.ndarray,
    clean_mask: np.ndarray,
) -> list[tuple[int, float]]:
    """
    Pro každý connected component ve skeletonu vrátí (length_px, median_thickness_px).

    skeleton, clean_mask:
        uint8 binární obrázky (0 / nenula). Stejné rozměry.

    Vrací list (length, median_thickness) v pořadí labelů.
    Délka list = počet segmentů (= num_labels - 1, label 0 je pozadí).

    Postup:
        - cv2.connectedComponents s 8-konektivitou (stejně jako components.py).
        - cv2.distanceTransform na clean_mask (L2, kernel 5×5 — best approx).
        - Per segment: median z DT × 2 (DT je poloměr, full tloušťka = 2×).
    """
    # 8-konektivita drží konzistenci s components.py — DRY princip detekce.
    num_labels, labels = cv2.connectedComponents(skeleton, connectivity=8)

    # Distance transform: pro každý mask pixel L2 vzdálenost k nejbližšímu
    # background pixelu. Pro skeleton pixel uvnitř mask čáry to ~= poloměr
    # lokální tloušťky. Kernel 5×5 dává nejlepší L2 aproximaci v cv2.
    dt = cv2.distanceTransform(clean_mask, cv2.DIST_L2, 5)

    results: list[tuple[int, float]] = []
    for label_id in range(1, num_labels):  # 0 = pozadí
        # Bool maska skeleton pixelů patřících tomuto segmentu.
        segment_mask = labels == label_id
        length = int(segment_mask.sum())
        # *2 protože DT je poloměr od skeletu (středovky) k okraji čáry.
        # Median je robustnější než mean: endpointy mají DT≈0 (rohy mask),
        # rozhrabaly by průměr směrem dolů.
        thickness_values = dt[segment_mask] * 2.0
        median = float(np.median(thickness_values))
        results.append((length, median))

    return results


def format_ascii_histogram(
    values: list[float],
    bins: int = 20,
    width: int = 50,
    label: str = "",
) -> str:
    """
    ASCII histogram pro textový report (KISS, bez matplotlib závislosti).

    bins: počet binů. width: max šířka baru ve znacích.
    label: prefix pro každý řádek (např. "px").

    Vrací multiline string. Prázdný input → "(žádné segmenty)".
    """
    if not values:
        return "(žádné segmenty)"
    arr = np.asarray(values)
    counts, edges = np.histogram(arr, bins=bins)
    max_count = int(counts.max()) if counts.size else 0
    lines: list[str] = []
    for i in range(bins):
        # Bar délka proporční k max binu — vizuální cluster detection bez čísel.
        bar_len = int(width * counts[i] / max_count) if max_count else 0
        bar = "#" * bar_len  # ASCII '#' místo unicode bloku — bezpečné na cp1250 stderr fallback
        lines.append(f"  {edges[i]:6.2f}-{edges[i + 1]:6.2f} {label} | {bar} ({counts[i]})")
    return "\n".join(lines)


def format_top_segments(
    segments: list[tuple[int, float]],
    n: int,
    by: str,
    reverse: bool,
) -> list[str]:
    """
    Vrátí formátované řádky pro top N segmentů podle 'length' nebo 'thickness'.
    reverse=True → sestupně (nejtlustší / nejdelší jako první).
    """
    key_index = 0 if by == "length" else 1
    # enumerate od 1 → human-readable segment ID.
    indexed = list(enumerate(segments, 1))
    indexed.sort(key=lambda x: x[1][key_index], reverse=reverse)
    lines: list[str] = []
    for seg_id, (length, thick) in indexed[:n]:
        lines.append(f"  Segment #{seg_id:>3}: length={length:>4}px, thickness={thick:>5.2f}px")
    return lines


def main() -> None:
    from cli_utils import force_utf8_console
    force_utf8_console()

    parser = argparse.ArgumentParser(
        description="Diagnostický probe distribuce tlouštěk skeleton fragmentů "
                    "(příprava pro Stage 4 detektor).",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Adresář s podsložkami morphology/ a skeleton/ (typicky 'output/<sample>').",
    )
    parser.add_argument(
        "--category",
        type=str,
        default="brown",
        help="ColorCategory (brown/black/green/yellow/…). Default 'brown' "
             "pro vrstevnice. Hledá cat_<category>_skeleton.png + cat_<category>_clean.png.",
    )
    args = parser.parse_args()

    skeleton_path = args.output_dir / "skeleton" / f"cat_{args.category}_skeleton.png"
    clean_path = args.output_dir / "morphology" / f"cat_{args.category}_clean.png"

    if not skeleton_path.exists():
        raise SystemExit(f"Skeleton neexistuje: {skeleton_path}")
    if not clean_path.exists():
        raise SystemExit(f"Clean mask neexistuje: {clean_path}")

    skeleton = cv2.imread(str(skeleton_path), cv2.IMREAD_GRAYSCALE)
    clean = cv2.imread(str(clean_path), cv2.IMREAD_GRAYSCALE)

    # Binarize na 0/255 — vstupy mohou mít různé hodnoty (i když Stage 3 ukládá binární).
    # Defenziva: probe je standalone, nepředpokládáme striktně binární input.
    skeleton_bin = ((skeleton > 0).astype(np.uint8)) * 255
    clean_bin = ((clean > 0).astype(np.uint8)) * 255

    segments = measure_segment_thickness(skeleton_bin, clean_bin)

    if not segments:
        print(f"Žádné segmenty v {skeleton_path}.")
        return

    thicknesses = [t for _, t in segments]
    lengths = [float(l) for l, _ in segments]

    # --- Report ---
    print(f"=== Thickness probe: {args.category} ===")
    print(f"Skeleton:   {skeleton_path}")
    print(f"Clean mask: {clean_path}")
    print(f"Segmentů:   {len(segments)}")
    print()

    print("Distribuce median tlouštěk (px):")
    print(format_ascii_histogram(thicknesses, bins=20, label="px"))
    print()

    print("Statistika tloušťky:")
    print(f"  Min: {min(thicknesses):.2f}px,  Max: {max(thicknesses):.2f}px")
    print(f"  Median: {float(np.median(thicknesses)):.2f}px,  Mean: {float(np.mean(thicknesses)):.2f}px")
    print(f"  P25: {float(np.percentile(thicknesses, 25)):.2f}px,  "
          f"P75: {float(np.percentile(thicknesses, 75)):.2f}px")
    print()

    print("Distribuce délek segmentů (skeleton px):")
    print(format_ascii_histogram(lengths, bins=20, label="px"))
    print()

    print("Statistika délky:")
    print(f"  Min: {int(min(lengths))}px,  Max: {int(max(lengths))}px")
    print(f"  Median: {float(np.median(lengths)):.1f}px,  Mean: {float(np.mean(lengths)):.1f}px")
    print(f"  P25: {float(np.percentile(lengths, 25)):.1f}px,  "
          f"P75: {float(np.percentile(lengths, 75)):.1f}px")
    print()

    print("Top 10 nejtlustších segmentů:")
    for line in format_top_segments(segments, n=10, by="thickness", reverse=True):
        print(line)
    print()
    print("Top 10 nejtenčích segmentů:")
    for line in format_top_segments(segments, n=10, by="thickness", reverse=False):
        print(line)
    print()
    print("Top 10 nejdelších segmentů:")
    for line in format_top_segments(segments, n=10, by="length", reverse=True):
        print(line)
    print()
    print("Top 10 nejkratších segmentů:")
    for line in format_top_segments(segments, n=10, by="length", reverse=False):
        print(line)


if __name__ == "__main__":
    main()
