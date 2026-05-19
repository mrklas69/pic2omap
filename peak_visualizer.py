"""
Peak visualizer — rozdělí brown skeleton na 3 vrstvy podle thickness peaku
a vytvoří overlay nad libovolným podkladem (typicky originální raster).

Cíl: empirická identifikace, co se skrývá ve 3 peaks, které našel
`thickness_probe.py` (2.0 / 2.8 / 4.0 px na forest sample).

Vstupy: `output/<sample>/skeleton/cat_<cat>_skeleton.png` +
        `output/<sample>/morphology/cat_<cat>_clean.png`.

Výstupy do `output/<sample>/peaks/` (default):
    - `peak_thin.png`   (samostatná maska, thickness ≤ 2.4 px)
    - `peak_mid.png`    (samostatná maska, 2.4–3.4 px)
    - `peak_thick.png`  (samostatná maska, ≥ 3.4 px)
    - `peak_overlay.png` (všechny tři přes podklad, barevně rozlišené)

Barvy v overlay (BGR / vizuálně):
    RED    = thin  (peak 2.0 px, hypotéza 101 Contour)
    YELLOW = mid   (peak 2.8 px, hypotéza ???)
    GREEN  = thick (peak 4.0 px, hypotéza 102 Index contour)

CLI:
    python peak_visualizer.py "output/forest sample" \\
        --background "resources/forest sample.png"
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


# Peak rozhraní — empirické thresholdy z probe na forest sample.
# Pokud probe ukáže jiný histogram (jiné DPI / sample / kategorie), upravit.
PEAK_THIN_MAX = 2.4    # ≤ 2.4 → thin (peak ~2.0)
PEAK_THICK_MIN = 3.4   # ≥ 3.4 → thick (peak ~4.0)
# Co je mezi: mid (peak ~2.8)


# BGR barvy (cv2 default order) per peak. RGB ekvivalent v komentáři pro lidskou intuici.
PEAK_COLORS = {
    "thin": (0, 0, 255),     # BGR red    — RGB (255, 0, 0)
    "mid": (0, 255, 255),    # BGR yellow — RGB (255, 255, 0)
    "thick": (0, 255, 0),    # BGR green  — RGB (0, 255, 0)
}


def classify_segments(
    skeleton: np.ndarray,
    clean_mask: np.ndarray,
) -> tuple[np.ndarray, dict[str, list[int]]]:
    """
    Klasifikuje skeleton segmenty do thin/mid/thick podle median tloušťky
    (z distance transformu na clean masce).

    Vrací (labels_image, peak_groups), kde:
        labels_image: cv2.connectedComponents výstup (int32), 0 = pozadí
        peak_groups: dict "thin"/"mid"/"thick" → list label_id

    DRY poznámka: logika je shodná s thickness_probe.measure_segment_thickness,
    ale tady navíc vracíme labels_image (potřebné pro renderování masek).
    Refaktor do společného modulu, až budou další konzumenti.
    """
    num_labels, labels = cv2.connectedComponents(skeleton, connectivity=8)
    dt = cv2.distanceTransform(clean_mask, cv2.DIST_L2, 5)

    groups: dict[str, list[int]] = {"thin": [], "mid": [], "thick": []}
    for label_id in range(1, num_labels):  # 0 = pozadí
        segment_mask = labels == label_id
        # *2 protože DT je poloměr od středovky k okraji čáry.
        thickness_values = dt[segment_mask] * 2.0
        thickness = float(np.median(thickness_values))
        if thickness <= PEAK_THIN_MAX:
            groups["thin"].append(label_id)
        elif thickness >= PEAK_THICK_MIN:
            groups["thick"].append(label_id)
        else:
            groups["mid"].append(label_id)

    return labels, groups


def annotate_with_ids(
    canvas: np.ndarray,
    labels: np.ndarray,
    label_ids: list[int],
    color: tuple[int, int, int] = (255, 255, 255),
    outline: tuple[int, int, int] = (0, 0, 0),
    font_scale: float = 0.2,
    font_thickness: int = 1,
) -> np.ndarray:
    """
    Vykreslí label_id jako text v centroidu každého segmentu.
    Bílý text s černým outlinem → čitelné přes libovolný background.

    canvas: BGR obrázek, modifikuje se kopie.
    labels: int32 image z connectedComponents.
    label_ids: které labely anotovat.
    """
    out = canvas.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    for label_id in label_ids:
        # Centroid jako průměr souřadnic — robustní, i pro křivé segmenty.
        ys, xs = np.where(labels == label_id)
        if len(xs) == 0:
            continue
        cx = int(np.mean(xs))
        cy = int(np.mean(ys))
        text = str(label_id)
        # Outline (black) první → text (white) přes něj. cv2 vykresluje
        # nad existující pixely, takže outline 2px tlustý vytvoří kontrast.
        cv2.putText(out, text, (cx, cy), font, font_scale, outline,
                    font_thickness + 2, cv2.LINE_AA)
        cv2.putText(out, text, (cx, cy), font, font_scale, color,
                    font_thickness, cv2.LINE_AA)
    return out


def render_peak_mask(labels: np.ndarray, label_ids: list[int]) -> np.ndarray:
    """Binární maska 0/255 pro segmenty patřící danému peaku."""
    # np.isin vektorizovaná verze "label in label_ids" — rychlejší než for loop.
    mask = np.isin(labels, label_ids)
    return mask.astype(np.uint8) * 255


def dilate_for_visibility(mask: np.ndarray, kernel_size: int = 3) -> np.ndarray:
    """
    Skeleton je 1px středovka → na overlay přes raster špatně viditelná.
    Dilatace 3×3 jádro 1× → ~3px tlustá linie, dobře rozpoznatelná barva.
    """
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    return cv2.dilate(mask, kernel, iterations=1)


def render_overlay(
    background: np.ndarray,
    peak_masks: dict[str, np.ndarray],
    alpha: float = 0.85,
) -> np.ndarray:
    """
    Položí barevné peak masky přes background (BGR formát).

    alpha: 0 = overlay neviditelný, 1 = pouze barva (žádný background pod).
    Default 0.85 = silně zvýrazněné barvy, podklad jen lehce prosvítá.

    Pokud je background grayscale, převede na BGR.
    """
    if background.ndim == 2:
        background = cv2.cvtColor(background, cv2.COLOR_GRAY2BGR)
    out = background.copy()
    for peak_name, mask in peak_masks.items():
        color = np.array(PEAK_COLORS[peak_name], dtype=np.float32)
        # Bool maska kde je peak pixel — tam míchat s alphou.
        bool_mask = mask > 0
        # Vektorová interpolace: new = (1-α)·orig + α·color
        out[bool_mask] = ((1 - alpha) * out[bool_mask] + alpha * color).astype(np.uint8)
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Vizualizace rozdělení skeleton segmentů per thickness peak.",
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
        help="ColorCategory (default 'brown' pro vrstevnice).",
    )
    parser.add_argument(
        "--background",
        type=Path,
        default=None,
        help="Podklad pro overlay (typicky originální raster, např. "
             "'resources/forest sample.png'). Bez něj = bílé pozadí.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Cíl výstupů (default = <output_dir>/peaks).",
    )
    parser.add_argument(
        "--label-ids",
        action="store_true",
        help="Přidej label_id text v centroidu každého segmentu — generuje "
             "navíc peak_<peak>_labeled.png (per-peak, ať se labely nepřekrývaly).",
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
    skeleton_bin = (skeleton > 0).astype(np.uint8) * 255
    clean_bin = (clean > 0).astype(np.uint8) * 255

    labels, groups = classify_segments(skeleton_bin, clean_bin)

    # Default out_dir = <output_dir>/peaks/.
    out_dir = args.out_dir if args.out_dir else args.output_dir / "peaks"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-peak samostatné masky + dilatace pro vizibilitu v overlay.
    peak_masks: dict[str, np.ndarray] = {}
    print(f"=== Peak visualizer: {args.category} ===")
    print(f"Skeleton:   {skeleton_path}")
    print(f"Clean mask: {clean_path}")
    print(f"Segmentů celkem: {sum(len(v) for v in groups.values())}")
    print()
    for peak_name in ("thin", "mid", "thick"):
        mask = render_peak_mask(labels, groups[peak_name])
        peak_masks[peak_name] = dilate_for_visibility(mask)
        peak_path = out_dir / f"peak_{peak_name}.png"
        cv2.imwrite(str(peak_path), peak_masks[peak_name])
        print(f"  {peak_path.name:<20} {len(groups[peak_name]):>4} segmentů")

    # Background pro overlay. Pokud nezadán, bílá plocha.
    if args.background is not None:
        background = cv2.imread(str(args.background), cv2.IMREAD_COLOR)
        if background is None:
            raise SystemExit(f"Nelze načíst background: {args.background}")
        # Sanity check rozměrů — pokud nesedí, dimenze se rozjedou v overlay.
        if background.shape[:2] != skeleton.shape:
            raise SystemExit(
                f"Background dimenze {background.shape[:2]} ≠ "
                f"skeleton {skeleton.shape}. Použij stejný raster, ze kterého "
                f"pipeline vznikla."
            )
    else:
        h, w = skeleton.shape
        background = np.ones((h, w, 3), dtype=np.uint8) * 255

    overlay = render_overlay(background, peak_masks)
    overlay_path = out_dir / "peak_overlay.png"
    cv2.imwrite(str(overlay_path), overlay)
    print(f"  {overlay_path.name:<20} overlay nad "
          f"{'bílým pozadím' if args.background is None else args.background.name}")

    # Volitelně: per-peak labeled výstupy. Per-peak (ne jeden celkový), ať se
    # 181 labelů nepřekrývalo. Každý ukáže jen segmenty toho peaku + IDs.
    if args.label_ids:
        for peak_name in ("thin", "mid", "thick"):
            # Overlay jen daného peaku přes background.
            single_peak_masks = {peak_name: peak_masks[peak_name]}
            labeled = render_overlay(background, single_peak_masks)
            labeled = annotate_with_ids(labeled, labels, groups[peak_name])
            labeled_path = out_dir / f"peak_{peak_name}_labeled.png"
            cv2.imwrite(str(labeled_path), labeled)
            print(f"  {labeled_path.name:<25} {len(groups[peak_name])} segmentů s ID")

    print()
    print(f"Výstupy: {out_dir}")
    print()
    print("Legenda overlay (BGR):")
    print(f"  RED    = thin   (≤ {PEAK_THIN_MAX} px, hypotéza 101 Contour)")
    print(f"  YELLOW = mid    ({PEAK_THIN_MAX}–{PEAK_THICK_MIN} px, hypotéza ???)")
    print(f"  GREEN  = thick  (≥ {PEAK_THICK_MIN} px, hypotéza 102 Index contour)")


if __name__ == "__main__":
    main()
