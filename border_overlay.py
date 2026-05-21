"""
Border-based klasifikační overlay — autonomní predikce road / contour /
mixed per brown skeleton segment podle border_ratio.

Vstupy: cat_brown_skeleton.png + cat_brown_clean.png + cat_black_clean.png
Klasifikace per segment:
    ratio < THRESHOLD_CONTOUR    → contour (GREEN)
    ratio > THRESHOLD_ROAD       → road / paved (RED)
    jinak                        → mixed / nejistá (YELLOW)

Výstupy v `<output_dir>/border/`:
    border_overlay.png         — 3-color overlay přes background
    border_overlay_labeled.png — totéž + label_id v centroidech (s --label-ids)

Diagnostika: pro každou třídu vypíše počty + top N IDs (pro manuální verifikaci).

CLI:
    python border_overlay.py "output/forest sample" \\
        --background "resources/forest sample.png" --label-ids
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

# DRY: měření border_ratio z border_probe, anotace z peak_visualizer.
from border_probe import measure_border_ratio
from peak_visualizer import annotate_with_ids, dilate_for_visibility, render_overlay

# Empirické thresholdy z border_probe na forest sample (kernel 5×5).
# Kalibrovat při změně kernelu / DPI / vstupního rasteru.
# Kernel 5 dává čistší disambiguaci než 9 (radius 2 px stačí na border 0.27 mm
# ≈ 2.6 px, větší kernel přibírá false positives ze sousedních black symbolů).
THRESHOLD_CONTOUR = 0.3   # < 0.3 → predicted contour
THRESHOLD_ROAD = 0.7      # > 0.7 → predicted road/paved
# Mezi 0.3-0.7 → mixed (nejistá zóna, potřeba dalších features)


# BGR barvy. Inverzní logika oproti peak_visualizer: tady GREEN = "good"
# (skutečná vrstevnice), RED = "bad" (road/paved area = filter out v Stage 4).
CLASS_COLORS = {
    "contour": (0, 255, 0),   # BGR green
    "mixed": (0, 255, 255),   # BGR yellow
    "road": (0, 0, 255),      # BGR red
}


def classify_by_border_ratio(
    border_data: dict[int, tuple[int, float, int]],
    threshold_contour: float = THRESHOLD_CONTOUR,
    threshold_road: float = THRESHOLD_ROAD,
) -> dict[str, list[int]]:
    """
    Roztřídí segmenty do contour / mixed / road podle border_ratio.

    border_data: {label_id: (length, ratio, overlap)}
    Vrací: {"contour", "mixed", "road"} → list label_id
    """
    groups: dict[str, list[int]] = {"contour": [], "mixed": [], "road": []}
    for label_id, (_, ratio, _) in border_data.items():
        if ratio < threshold_contour:
            groups["contour"].append(label_id)
        elif ratio > threshold_road:
            groups["road"].append(label_id)
        else:
            groups["mixed"].append(label_id)
    return groups


def render_class_mask(
    labels: np.ndarray,
    label_ids: list[int],
) -> np.ndarray:
    """Binární maska 0/255 pro segmenty patřící danému class (DRY z peak_visualizer)."""
    mask = np.isin(labels, label_ids)
    return mask.astype(np.uint8) * 255


def main() -> None:
    from cli_utils import force_utf8_console
    force_utf8_console()

    parser = argparse.ArgumentParser(
        description="Border-based klasifikace brown skeleton segmentů "
                    "(contour / mixed / road).",
    )
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--category", default="brown")
    parser.add_argument("--neighbor", default="black")
    parser.add_argument("--kernel-size", type=int, default=5,
                        help="Liché. Default 5 = radius 2 px (kalibrované "
                             "pro forest sample). Větší kernel chytá false "
                             "positives ze sousedních black symbolů.")
    parser.add_argument("--threshold-contour", type=float, default=THRESHOLD_CONTOUR,
                        help=f"Default {THRESHOLD_CONTOUR}: ratio < toto → contour.")
    parser.add_argument("--threshold-road", type=float, default=THRESHOLD_ROAD,
                        help=f"Default {THRESHOLD_ROAD}: ratio > toto → road.")
    parser.add_argument("--background", type=Path, default=None,
                        help="Podklad (typicky originální raster).")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Default = <output_dir>/border.")
    parser.add_argument("--label-ids", action="store_true",
                        help="Přidá label_id text per třídu (3 samostatné PNG).")
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
    neighbor = cv2.imread(str(neighbor_path), cv2.IMREAD_GRAYSCALE)
    skeleton_bin = (skeleton > 0).astype(np.uint8) * 255
    neighbor_bin = (neighbor > 0).astype(np.uint8) * 255

    labels, border_data = measure_border_ratio(skeleton_bin, neighbor_bin, args.kernel_size)
    groups = classify_by_border_ratio(border_data, args.threshold_contour, args.threshold_road)

    out_dir = args.out_dir if args.out_dir else args.output_dir / "border"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-class masks s dilatací (kvůli viditelnosti 1px skeletonu na overlay).
    class_masks: dict[str, np.ndarray] = {}
    for class_name, label_ids in groups.items():
        mask = render_class_mask(labels, label_ids)
        class_masks[class_name] = dilate_for_visibility(mask)

    # Background.
    if args.background is not None:
        background = cv2.imread(str(args.background), cv2.IMREAD_COLOR)
        if background is None:
            raise SystemExit(f"Nelze načíst background: {args.background}")
        if background.shape[:2] != skeleton.shape:
            raise SystemExit(
                f"Background dimenze {background.shape[:2]} ≠ "
                f"skeleton {skeleton.shape}."
            )
    else:
        h, w = skeleton.shape
        background = np.ones((h, w, 3), dtype=np.uint8) * 255

    # Re-use render_overlay: vezme dict mask → barva. Naše CLASS_COLORS jsou
    # kompatibilní s PEAK_COLORS interfacem (BGR tuple).
    # render_overlay je v peak_visualizeru a iteruje přes PEAK_COLORS klíče,
    # ale ten interface bere mask dict — naše CLASS_COLORS jsou drop-in.
    # Trochu šedivá zóna DRY, ale řeší se přepsáním render_overlay na obecnější.
    overlay = render_overlay_with_colors(background, class_masks, CLASS_COLORS)
    overlay_path = out_dir / "border_overlay.png"
    cv2.imwrite(str(overlay_path), overlay)

    # Report.
    print(f"=== Border classifier overlay: {args.category} vs {args.neighbor} ===")
    print(f"Kernel: {args.kernel_size}×{args.kernel_size}, "
          f"thresholds: contour<{args.threshold_contour}, road>{args.threshold_road}")
    print(f"Segmentů celkem: {len(border_data)}")
    print()
    for class_name in ("contour", "mixed", "road"):
        ids = groups[class_name]
        color_name = {"contour": "GREEN", "mixed": "YELLOW", "road": "RED"}[class_name]
        print(f"  {class_name:<8} ({color_name:<6}): {len(ids):>3} segmentů")
    print()
    print(f"Výstup: {overlay_path}")
    print()

    # Top N IDs per třída (pro manuální verifikaci).
    print("--- Top 10 IDs per třídu (sort by ratio) ---")
    for class_name in ("contour", "mixed", "road"):
        ids = groups[class_name]
        if not ids:
            continue
        # Sort: contour ascending (lowest ratio first = nejjistější contour),
        # road descending (highest ratio first = nejjistější road),
        # mixed by length descending (longest first = relevantnější).
        items = [(lid, *border_data[lid]) for lid in ids]
        if class_name == "contour":
            items.sort(key=lambda x: x[2])  # ratio asc
        elif class_name == "road":
            items.sort(key=lambda x: -x[2])  # ratio desc
        else:
            items.sort(key=lambda x: -x[1])  # length desc
        print(f"  {class_name}:")
        for lid, length, ratio, _ in items[:10]:
            print(f"    #{lid:>3}: length={length:>4}px, ratio={ratio:5.2f}")
    print()

    # Volitelně labeled per třída.
    if args.label_ids:
        for class_name in ("contour", "mixed", "road"):
            single_mask = {class_name: class_masks[class_name]}
            single_color = {class_name: CLASS_COLORS[class_name]}
            labeled = render_overlay_with_colors(background, single_mask, single_color)
            labeled = annotate_with_ids(labeled, labels, groups[class_name])
            labeled_path = out_dir / f"border_{class_name}_labeled.png"
            cv2.imwrite(str(labeled_path), labeled)
            print(f"  border_{class_name}_labeled.png  {len(groups[class_name])} s ID")


def render_overlay_with_colors(
    background: np.ndarray,
    masks: dict[str, np.ndarray],
    colors: dict[str, tuple[int, int, int]],
    alpha: float = 0.85,
) -> np.ndarray:
    """
    Položí barevné masky přes background.

    Obecnější verze render_overlay (peak_visualizer): bere colors dict explicitně,
    místo modulové konstanty PEAK_COLORS. Refaktor TODO: nahradit render_overlay
    touto funkcí, peak_visualizer pak volá s PEAK_COLORS.
    """
    if background.ndim == 2:
        background = cv2.cvtColor(background, cv2.COLOR_GRAY2BGR)
    out = background.copy()
    for name, mask in masks.items():
        color = np.array(colors[name], dtype=np.float32)
        bool_mask = mask > 0
        out[bool_mask] = ((1 - alpha) * out[bool_mask] + alpha * color).astype(np.uint8)
    return out


if __name__ == "__main__":
    main()
