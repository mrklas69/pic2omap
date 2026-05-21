"""
georef — pixel ↔ OMAP coord transformace.

Sdílený základ pro celý projekt: db2omap (export pixel → coord), omap_mask
(opačný směr coord → pixel pro masku z geometrie) i compare_to_omap (coord bbox
pro CSV review). Dvě cesty:

  - rigorózní (build_georef_transform): pixel → UTM (.pgw) → OMAP coord
    (projectedToMap), složení afinních matic. Vyžaduje .pgw + <projected_crs>.
  - bbox-fit fallback (_compute_coord_bbox + _make_transform): lineární fit
    pixel rozsahu do bboxu template <objects>, když není .pgw / je Local CRS.

Historie: tyto funkce dříve žily v db2omap; vyčleněny (sezení 14, %AUDIT:CODE),
protože db2omap je "zamražený PoC", ale georef z něj importuje víc modulů — jméno
modulu pak nelhalo o roli.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np


def _compute_coord_bbox(template_path: Path) -> tuple[int, int, int, int]:
    """
    Spočítá bounding box všech coords v template <objects> (min_x, min_y, max_x, max_y).

    Slouží jako kalibrace pixel → OMAP coord. Čteme přímo z XML regexem
    (nepotřebujeme plný parse objektů, jen čísla v <coords>).
    """
    data = template_path.read_text(encoding="utf-8")
    # Vyřízni jen <objects>...</objects>, ať nechytáme coords ze <symbols> definic.
    m = re.search(r"<objects[ >].*?</objects>", data, re.S)
    if not m:
        raise SystemExit(f"Template {template_path} nemá <objects> sekci.")
    # Coord token: "X Y" volitelně následované " FLAG", oddělené ; nebo koncem.
    nums = re.findall(r"(-?\d+) (-?\d+)(?: \d+)?(?=;|</)", m.group())
    if not nums:
        raise SystemExit(f"Template {template_path} nemá žádné coords pro kalibraci.")
    xs = [int(a) for a, _ in nums]
    ys = [int(b) for _, b in nums]
    return min(xs), min(ys), max(xs), max(ys)


def _make_transform(
    coord_bbox: tuple[int, int, int, int],
    png_w: int,
    png_h: int,
):
    """
    Vrátí funkci pixel (px, py) → OMAP coord (mx, my).

    Lineární fit pixel rozsahu (0..W, 0..H) do coord bboxu. OMAP object coords
    používají top-down konvenci (y roste DOLŮ, stejně jako pixel y — ověřeno ze
    zdrojáku Mapperu, georeferencing.cpp: scale(s, -s) flipuje až map↔projected,
    ne uvnitř paper-space). Proto pixel→map NEMÁ y-flip: horní pixel (py=0) →
    nejmenší map_y. Nezávislý x/y scale = mírné protažení, relativní rozmístění
    zůstává.
    """
    min_x, min_y, max_x, max_y = coord_bbox
    span_x = max_x - min_x
    span_y = max_y - min_y

    def transform(px: float, py: float) -> tuple[int, int]:
        mx = min_x + (px / png_w) * span_x
        # Bez flipu: pixel 0 (nahoře) → coord min_y (top-down konvence OMAP).
        my = min_y + (py / png_h) * span_y
        return int(round(mx)), int(round(my))

    return transform


# --- Rigorózní georef přes .pgw + OMAP georeferencing ---
#
# Princip: OMAP object coords jsou paper-space (1/1000 mm na papíře mapy), PNG je
# render téhož papíru. Takže pixel -> OMAP coord je čistá podobnostní transformace
# (scale + translace + y-flip), BEZ rotace. Rotace (declination/grivation) a UTM
# slouží jen pro reálný svět. Řetězec: pixel --[.pgw]--> UTM --[projectedToMap]--> coord.
# Rotace grivation z .pgw a z projectedToMap se ve složení vyruší.
#
# Znaménková konvence ověřena empiricky na Slovance (_georef_probe): theta = -grivation,
# y-flip = diag(1,-1) -> 100 % GT coords uvnitř PNG, 92.9 % centroidů na ne-bílém pixelu.


def _parse_pgw(path: Path) -> np.ndarray:
    """
    World file (6 floatů A,D,B,E,C,F) -> homogenní 3x3 matice pixel -> UTM.

    Pořadí v .pgw souboru je ESRI konvence (A,D,B,E,C,F po řádcích), proto
    rozbalujeme přesně v tomto pořadí. Transformace:
        UTM_x = A*px + B*py + C
        UTM_y = D*px + E*py + F
    """
    a, d, b, e, c, f = (float(x) for x in path.read_text().split())
    return np.array([[a, b, c], [d, e, f], [0, 0, 1]], dtype=float)


def _parse_georef(template_path: Path) -> dict | None:
    """
    Vytáhne scale, grivation, scale factor a OBA ref_pointy z <georeferencing>.

    OMAP georef má dva ref_pointy: map ref (přímo v <georeferencing>, paper-space)
    a projected ref (uvnitř <projected_crs>, UTM). POZOR: nelze brát "první
    <ref_point> v souboru" — když je přítomen map ref, je první ON, ne projected.
    Proto čteme projected ref cíleně z bloku <projected_crs>.

    Vrací None pokud chybí <projected_crs> ref_point (Local CRS, např. forest
    sample) — pak nelze postavit rigorózní georef a caller spadne na bbox-fit.
    Grivation (úhel grid north vs map north) má přednost před declination.
    """
    data = template_path.read_text(encoding="utf-8")
    geo_m = re.search(r"<georeferencing\b[^>]*>", data)
    if geo_m is None:
        return None
    tag = geo_m.group()  # otevírací tag — scale/grivation/aux jsou jeho atributy
    scale_m = re.search(r'scale="([\d.]+)"', tag)
    if scale_m is None:
        return None
    rot_m = re.search(r'grivation="(-?[\d.]+)"', tag) or re.search(r'declination="(-?[\d.]+)"', tag)
    grivation = float(rot_m.group(1)) if rot_m else 0.0
    # Combined scale factor (gauss-krüger/UTM zkreslení). PoC bere jen explicitní
    # auxiliary_scale_factor; grid scale factor projekce zanedbáváme (~0.0x %).
    aux_m = re.search(r'auxiliary_scale_factor="([\d.]+)"', tag)
    aux_scale = float(aux_m.group(1)) if aux_m else 1.0

    # Celý blok kvůli ref_pointům (otevírací tag nestačí).
    full_m = re.search(r"<georeferencing\b.*?</georeferencing>", data, re.S)
    if full_m is None:
        return None
    geo_full = full_m.group()
    # proj_ref: ref_point UVNITŘ <projected_crs>.
    proj_block = re.search(r"<projected_crs\b.*?</projected_crs>", geo_full, re.S)
    if proj_block is None:
        return None  # Local CRS → fallback na bbox-fit
    proj_ref_m = re.search(r'<ref_point x="(-?[\d.]+)" y="(-?[\d.]+)"', proj_block.group())
    if proj_ref_m is None:
        return None
    # map_ref: root-level ref_point PŘED <projected_crs> (default 0,0 když chybí).
    head = geo_full[: geo_full.find("<projected_crs")]
    map_ref_m = re.search(r'<ref_point x="(-?[\d.]+)" y="(-?[\d.]+)"', head)
    map_ref = (float(map_ref_m.group(1)), float(map_ref_m.group(2))) if map_ref_m else (0.0, 0.0)
    return {
        "scale": float(scale_m.group(1)),
        "grivation": grivation,
        "aux_scale": aux_scale,
        "proj_ref": (float(proj_ref_m.group(1)), float(proj_ref_m.group(2))),
        "map_ref": map_ref,
    }


def _build_map_to_proj(geo: dict) -> np.ndarray:
    """
    MapToProj (OMAP coord -> UTM) jako homogenní 3x3. Věrné OOM updateTransformation:

        proj = proj_ref + scale*aux*1e-6 * R(-grivation) * diag(1,-1) * (map - map_ref)

    scale*1e-6 = metry terénu na 1 coord unit (1 unit = 1e-3 mm papír * scale),
    aux = auxiliary_scale_factor. R(-grivation) a diag(1,-1) jsou ověřená znaménková
    konvence (viz hlavička sekce). map_ref se odečítá (OOM translate(-map_ref)).
    """
    s = geo["scale"] * geo["aux_scale"] * 1e-6
    th = np.deg2rad(-geo["grivation"])
    rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    flip_y = np.array([[1, 0], [0, -1]])
    lin = s * rot @ flip_y
    proj_ref = np.array(geo["proj_ref"], dtype=float)
    # map_ref z <georeferencing> je v mm; object coords jsou 1/1000 mm → ×1000 do coord units
    # (jinak se odečítá 1000× menší offset → translation posun masky/exportu, viz Garching).
    map_ref = np.array(geo["map_ref"], dtype=float) * 1000.0
    # proj = lin @ (map - map_ref) + proj_ref = lin @ map + (proj_ref - lin @ map_ref)
    offset = proj_ref - lin @ map_ref
    return np.array([[lin[0, 0], lin[0, 1], offset[0]],
                     [lin[1, 0], lin[1, 1], offset[1]],
                     [0, 0, 1]], dtype=float)


def build_georef_transform(
    template_omap: Path,
    pgw_path: Path,
    pgw_width: int,
    mask_width: int,
):
    """
    Vrátí transform(px, py) -> (mx, my) [OMAP coord] přes .pgw + georef.

    Args:
        template_omap: OMAP se sekcí <georeferencing> (scale, grivation, ref_point).
        pgw_path: world file příslušející k rastru o šířce pgw_width.
        pgw_width: šířka PNG, ke kterému .pgw patří (typicky plný export).
        mask_width: šířka claim masky, na které běžela detekce (může být downscale).

    Vrací None pokud georef nelze sestavit (chybí ref_point / scale).
    """
    geo = _parse_georef(template_omap)
    if geo is None:
        return None

    pgw = _parse_pgw(pgw_path)            # pixel_full -> UTM
    m2p = _build_map_to_proj(geo)         # map -> UTM
    proj_to_map = np.linalg.inv(m2p)      # UTM -> map

    # Škálování mask pixelů na full pixely (detekce mohla běžet na downscale).
    # pixel_full = pixel_mask * (pgw_width / mask_width).
    ratio = pgw_width / mask_width
    scale_mask = np.array([[ratio, 0, 0], [0, ratio, 0], [0, 0, 1]], dtype=float)

    # pixel_mask -> pixel_full -> UTM -> map
    pixel_to_map = proj_to_map @ pgw @ scale_mask

    def transform(px: float, py: float) -> tuple[int, int]:
        v = pixel_to_map @ np.array([px, py, 1.0])
        return int(round(v[0])), int(round(v[1]))

    return transform
