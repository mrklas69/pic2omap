"""
omap_mask — rasterizace ploch z .omap geometrie na per-pixel sémantickou masku.

Účel: vyrobit trénovací/evaluační páry (obrázek, maska) pro ML segmentaci ploch.
Maska bere třídu z AUTORITATIVNÍ .omap geometrie (ne z barvy pixelu PNG) — jinak
by se model učil jen color separation, kterou už umíme v cv2 (nulová ML hodnota).

Pipeline:
    .omap <object> (area symboly) → coords → coord→pixel transform → fillPoly →
    uint8 maska class indexů (ColorCategory úroveň, viz CATEGORY_TO_CLASS).

Georef (coord→pixel) znovupoužívá db2omap parsery (.pgw + <georeferencing>),
jen obrací směr (db2omap dělá pixel→coord pro export, my coord→pixel pro masku).
Bez .pgw spadne na bbox-fit (anizotropní, méně přesný — forest sample).

Použití:
    python omap_mask.py "resources/complete map.omap" "resources/complete map.png" \\
        --pgw "resources/complete map.pgw" --out output/garching_overlay.png

První účel = reality-check: overlay masky na PNG ukáže, jak dobře georef sedí
(les pod zelenou maskou = OK; posun = ten ~5mm georef problém z dřívějška).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from cli_utils import force_utf8_console, imread_unicode
from color_category import ColorCategory, classify_rgb
from georef import _build_map_to_proj, _compute_coord_bbox, _parse_georef, _parse_pgw
from omap_model import AreaSymbol, CombinedSymbol, SymbolBase, SymbolLibrary, SymbolType
from omap_parser import iter_map_objects, omap_tag, parse_coords, parse_omap

import xml.etree.ElementTree as ET


# --- OMAP coord flagy (core/map_coord.h) ---
# Pro výplň plochy nás zajímají jen dva: CurveStart (Bezier) a HolePoint (díra).
# GapPoint/DashPoint/ClosePoint výplň neovlivňují.
FLAG_CURVE_START = 1   # tento bod = anchor, následující 2 body = Bezier control pointy
FLAG_HOLE_POINT = 16   # poslední bod prstence; další body začínají nový prstenec (díru)

# Kolik segmentů na jednu kubickou Bezier křivku (tessellation). 8 = hladké dost
# pro ~0.3 m/px render, levné. Plochy nepotřebují víc (hranice nejsou kritické).
BEZIER_STEPS = 8


# --- Třídy masky (ColorCategory úroveň, pilot rozhodnutí Q7) ---
# 0 = pozadí (nezakryté = bílá/papír). Pevné mapování → konzistence napříč mapami
# (izomorfismus: stejná třída = stejný index v každém datasetu).
CATEGORY_TO_CLASS: dict[ColorCategory, int] = {
    ColorCategory.GREEN: 1,    # vegetace (les, hustník)
    ColorCategory.YELLOW: 2,   # otevřená/polootevřená země
    ColorCategory.BLUE: 3,     # voda, mokřad
    ColorCategory.GRAY: 4,     # zástavba (ISSprOM building), holá skála
    ColorCategory.BLACK: 5,    # zástavba (ISOM building), zpevněné plochy
    ColorCategory.BROWN: 6,    # hnědé plochy (zřídka — earth)
    ColorCategory.PURPLE: 7,   # OOB / kurz (obvykle mimo trénink)
}
NUM_CLASSES = 8  # 0..7

# Vizualizační paleta (BGR pro cv2). Pozadí (0) se v overlay nekreslí.
CLASS_PALETTE_BGR: dict[int, tuple[int, int, int]] = {
    1: (0, 170, 0),       # green
    2: (60, 220, 255),    # yellow
    3: (230, 150, 0),     # blue
    4: (140, 140, 140),   # gray
    5: (30, 30, 30),      # black
    6: (60, 110, 160),    # brown
    7: (200, 0, 200),     # purple
}


def _resolve_area_fill(
    sym: SymbolBase, library: SymbolLibrary, sid_to_sym: dict[int, SymbolBase]
) -> tuple[int, int] | None:
    """
    Plocha → (class index, priorita barvy). None = symbol není kreslitelná plocha.

    AreaSymbol: třída + priorita z VÝPLŇOVÉ barvy (inner_color), záměrně NE secondary
    (pattern). Symbol bez inner_color (inner=-1, barva jen v <pattern>) není samostatná
    plocha — je to overlay vzor přes jinou plochu (severky 601, šrafy 407). Rasterizovat
    ho jako plný polygon by přemazal plochy pod ním (severky = obdélník přes celou mapu →
    43 % modrá). Vrací None → caller ho přeskočí.

    CombinedSymbol (ISSprOM budova 526.1, canopy 526.2, voda 304/305, paved 529): geometrii
    má objekt, ale výplňovou barvu až sub-symbol. Vezmi první AREA part s platnou výplní
    (rekurze 1 úrovně). Bez toho se combined objekty (Garching: 404 = +33 % ploch) tiše
    ztratí a cross-domain GT maska je neúplná.

    Class i priorita pocházejí z jednoho zdroje (dřív rozdělené v build_area_mask).
    """
    if isinstance(sym, AreaSymbol):
        color = library.get_color(sym.inner_color_ref)
        if color is None:
            return None
        cls = CATEGORY_TO_CLASS.get(classify_rgb(*color.rgb_tuple))
        return (cls, color.priority) if cls is not None else None
    if isinstance(sym, CombinedSymbol):
        for part_id in sym.parts:
            part = sid_to_sym.get(part_id)
            if isinstance(part, AreaSymbol):
                fill = _resolve_area_fill(part, library, sid_to_sym)
                if fill is not None:
                    return fill
    return None


# --- Parsování geometrie objektu na prstence (outer + holes) ---
# Coord-token parsing = parse_coords (omap_parser, single source of truth).


def _cubic_bezier(p0, p1, p2, p3, steps: int) -> list[tuple[float, float]]:
    """Body kubické Bezier křivky pro t v (0, 1] (p0 už je v outputu, p3 přidá další iterace)."""
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def _coords_to_rings(coords: list[tuple[int, int, int]]) -> list[list[tuple[float, float]]]:
    """
    Coords (x, y, flag) → seznam prstenců. HolePoint (16) ukončuje prstenec,
    další body začínají nový (díru). CurveStart (1) tessellatuje kubickou Bezier
    (následující 2 body = control, +3 = další anchor; control pointy se nezahrnou).
    """
    rings: list[list[tuple[float, float]]] = []
    ring: list[tuple[float, float]] = []
    i, n = 0, len(coords)
    while i < n:
        x, y, flag = coords[i]
        if flag & FLAG_CURVE_START and i + 3 < n:
            p0 = (x, y)
            p1, p2 = coords[i + 1][:2], coords[i + 2][:2]
            p3 = coords[i + 3][:2]
            ring.append(p0)
            ring.extend(_cubic_bezier(p0, p1, p2, p3, BEZIER_STEPS)[:-1])  # p3 přidá další iter
            i += 3
            continue
        ring.append((float(x), float(y)))
        if flag & FLAG_HOLE_POINT:  # konec prstence
            rings.append(ring)
            ring = []
        i += 1
    if len(ring) >= 3:
        rings.append(ring)
    return rings


# --- Coord → pixel transform ---


def _coord_to_pixel_matrix(
    omap_path: Path, pgw_path: Path | None, png_w: int, png_h: int, pgw_width: int | None
) -> tuple[np.ndarray, str]:
    """
    Vrátí (3x3 matici coord→pixel, popis georef). Rigorózní (.pgw + georef) má
    přednost, jinak bbox-fit (lineární, anizotropní). Inverzní směr k db2omap:
        map→pixel = scale_to_mask @ inv(pgw) @ map_to_proj
    (pgw = pixel→UTM, map_to_proj = map→UTM; UTM se zkrátí, zbude map→pixel).
    """
    geo = _parse_georef(omap_path)
    if geo is not None and pgw_path is not None and pgw_path.exists():
        pgw = _parse_pgw(pgw_path)              # pixel(full) → UTM
        m2p = _build_map_to_proj(geo)           # map → UTM
        map_to_pixel_full = np.linalg.inv(pgw) @ m2p
        # PNG, na který rasterizujeme, může být downscale oproti .pgw rozlišení.
        ratio = png_w / (pgw_width or png_w)
        scale = np.array([[ratio, 0, 0], [0, ratio, 0], [0, 0, 1]], dtype=float)
        return scale @ map_to_pixel_full, f".pgw + georef (rigorózní, ratio={ratio:.4f})"

    # Fallback: bbox-fit. coord bbox → pixel (0..W, 0..H), bez rotace.
    min_x, min_y, max_x, max_y = _compute_coord_bbox(omap_path)
    sx, sy = (max_x - min_x) or 1, (max_y - min_y) or 1
    mat = np.array([[png_w / sx, 0, -png_w / sx * min_x],
                    [0, png_h / sy, -png_h / sy * min_y],
                    [0, 0, 1]], dtype=float)
    return mat, "bbox-fit (lineární, anizotropní — bez .pgw)"


def _apply(mat: np.ndarray, ring: list[tuple[float, float]]) -> np.ndarray:
    """Aplikuje 3x3 transform na prstenec coordů → (N, 2) int32 pixely (pro fillPoly)."""
    pts = np.array([[x, y, 1.0] for x, y in ring]).T   # 3 x N
    px = (mat @ pts)[:2].T                              # N x 2
    return np.round(px).astype(np.int32)


# --- Hlavní rasterizace ---


def build_area_mask(
    omap_path: Path, png_w: int, png_h: int, pgw_path: Path | None, pgw_width: int | None
) -> tuple[np.ndarray, dict]:
    """
    Vyrobí (H, W) uint8 masku class indexů z area objektů .omap.

    Objekty kreslí v pořadí priority barvy (vyšší priority index = spodní vrstva,
    kreslí se dřív) → detailnější plochy navrch, věrně OOM stacku. Vrací (maska, stats).
    """
    library = parse_omap(omap_path)
    # Všechny symboly (ne jen AREA) — combined symbol dohledává své AREA party odsud.
    sid_to_sym = {s.id: s for s in library.symbols}

    mat, georef_desc = _coord_to_pixel_matrix(omap_path, pgw_path, png_w, png_h, pgw_width)

    # Posbírej area objekty s jejich class + priority pro řazení.
    root = ET.parse(omap_path).getroot()
    todo: list[tuple[int, int, list]] = []  # (priority, class_idx, rings)
    skipped_no_class = 0
    for obj in iter_map_objects(root):
        sym = sid_to_sym.get(int(obj.get("symbol", -1)))
        if sym is None:
            continue
        fill = _resolve_area_fill(sym, library, sid_to_sym)
        if fill is None:
            skipped_no_class += 1
            continue
        cls, priority = fill
        coords_elem = obj.find(omap_tag("coords"))
        if coords_elem is None or not coords_elem.text:
            continue
        rings = _coords_to_rings(parse_coords(coords_elem.text))
        todo.append((priority, cls, rings))

    mask = np.zeros((png_h, png_w), dtype=np.uint8)
    class_counts: dict[int, int] = {}
    # Vyšší priority (spodní vrstva) první → detaily přepíšou pozadí.
    for _prio, cls, rings in sorted(todo, key=lambda t: -t[0]):
        if not rings:
            continue
        outer = _apply(mat, rings[0])
        cv2.fillPoly(mask, [outer], int(cls))
        # Díry (další prstence) → přemaluj zpět na pozadí (0).
        for hole in rings[1:]:
            if len(hole) >= 3:
                cv2.fillPoly(mask, [_apply(mat, hole)], 0)

    for c in range(1, NUM_CLASSES):
        cnt = int((mask == c).sum())
        if cnt:
            class_counts[c] = cnt

    stats = {
        "objects_drawn": len(todo),
        "skipped_no_class": skipped_no_class,
        "georef": georef_desc,
        "class_counts": class_counts,
        "total_px": png_w * png_h,
    }
    return mask, stats


def colorize_mask(mask: np.ndarray) -> np.ndarray:
    """Class index maska → BGR vizualizace (pozadí černé)."""
    vis = np.zeros((*mask.shape, 3), dtype=np.uint8)
    for cls, bgr in CLASS_PALETTE_BGR.items():
        vis[mask == cls] = bgr
    return vis


def overlay_on_image(png: np.ndarray, mask: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    """Poloprůhledný overlay barevné masky na PNG (jen tam, kde class > 0)."""
    vis = colorize_mask(mask)
    out = png.copy()
    fg = mask > 0
    out[fg] = (alpha * vis[fg] + (1 - alpha) * png[fg]).astype(np.uint8)
    return out


# --- Class name helper pro report (veřejné — importuje build_dataset/train) ---
CLASS_NAMES = {v: k.value for k, v in CATEGORY_TO_CLASS.items()}


def main() -> None:
    force_utf8_console()
    ap = argparse.ArgumentParser(description="Rasterizace ploch z .omap na sémantickou masku.")
    ap.add_argument("omap", help="cesta k .omap")
    ap.add_argument("png", help="cesta k rastru (render téže mapy)")
    ap.add_argument("--pgw", help="world file pro rigorózní georef (jinak bbox-fit)")
    ap.add_argument("--pgw-width", type=int, help="šířka PNG, ke kterému .pgw patří (default = šířka png)")
    ap.add_argument("--out", help="kam uložit overlay PNG (default output/<png>_overlay.png)")
    ap.add_argument("--save-mask", help="volitelně uložit raw masku (PNG, class indexy)")
    args = ap.parse_args()

    omap_path = Path(args.omap)
    png = imread_unicode(args.png)  # ne cv2.imread — selže na diakritice v cestě (Blatná)
    if png is None:
        raise SystemExit(f"Nelze načíst PNG: {args.png}")
    h, w = png.shape[:2]
    pgw_path = Path(args.pgw) if args.pgw else None

    mask, stats = build_area_mask(omap_path, w, h, pgw_path, args.pgw_width)

    out_path = Path(args.out) if args.out else Path("output") / f"{Path(args.png).stem}_overlay.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), overlay_on_image(png, mask))
    if args.save_mask:
        Path(args.save_mask).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(args.save_mask, mask)

    print(f"=== omap_mask: {omap_path.name} → {Path(args.png).name} ({w}x{h}) ===")
    print(f"  georef:            {stats['georef']}")
    print(f"  area objektů:      {stats['objects_drawn']} (přeskočeno bez třídy: {stats['skipped_no_class']})")
    print(f"  pokrytí ploch:")
    tot = stats["total_px"]
    for cls, cnt in sorted(stats["class_counts"].items(), key=lambda t: -t[1]):
        print(f"    {cls} {CLASS_NAMES.get(cls, '?'):8} {cnt:>12,} px  ({100*cnt/tot:5.1f} %)")
    print(f"  overlay:           {out_path}")


if __name__ == "__main__":
    main()
