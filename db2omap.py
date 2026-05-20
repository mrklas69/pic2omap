"""
db2omap — PoC export DBSnapshot → OMAP XML.

Cíl tohoto PoC: ukázat, že detekované objekty umíme zapsat do otevíratelného
OMAP souboru. NENÍ to plná Stage 5/7/8 implementace:

    - Vektorizace je hrubá: area = vnější kontura komponenty (approxPolyDP),
      line = kontura skeletonu (vizuálně čára, ale zdvojená kolem 1px kostry).
      Žádné Bezier vyhlazení, žádné napojování přerušených linií.
    - Georef je zjednodušený: pixel → OMAP coord lineární fit do bbox template
      objektů, nezávislý x/y scale (mírné protažení). Bez .pgw / rotace.
    - Symboly + barvy + georeferencing se přebírají z template OMAP — my
      nahrazujeme jen obsah <objects>.

Použití (přes pic2db.py export verb):
    python pic2db.py export "output/forest sample" --to omap \\
        --template "resources/forest sample.omap" --out "output/forest sample/export.omap"

Předpoklad: detekované symbol_code musí existovat v template library (po
template-aware fixu v brown_line_v1 / area_v1 to platí — viz memory
`template-aware-symbol-codes`).
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

from db_model import DBSnapshot, MapObject
from omap_parser import parse_omap


# OMAP object type pro path (line i area). Point=0, path=1, text=4.
OMAP_TYPE_PATH = 1

# approxPolyDP epsilon v pixelech — zjednodušení kontury. Menší = víc bodů
# (věrnější tvar), větší = méně bodů (hladší, ale hrubší). 1.5 px je kompromis
# pro render ~600 px na šířku.
APPROX_EPSILON_PX = 1.5

# Minimum bodů, aby měl path smysl (degenerátní 1-2 body přeskočíme).
MIN_COORDS = 3


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

    Lineární fit pixel rozsahu (0..W, 0..H) do coord bboxu. Y se zrcadlí
    (OMAP y roste nahoru, pixel y dolů). Nezávislý x/y scale = mírné protažení,
    ale relativní rozmístění objektů zůstává.
    """
    min_x, min_y, max_x, max_y = coord_bbox
    span_x = max_x - min_x
    span_y = max_y - min_y

    def transform(px: float, py: float) -> tuple[int, int]:
        mx = min_x + (px / png_w) * span_x
        # Flip y: pixel 0 (nahoře) → coord max_y (nahoře v map space).
        my = max_y - (py / png_h) * span_y
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
    Vytáhne scale, grivation a projected ref_point z <georeferencing>.

    Vrací None pokud chybí ref_point (např. Local CRS forest sample) — pak
    nelze postavit rigorózní georef a caller spadne na bbox-fit fallback.
    Grivation (úhel grid north vs map north) má přednost před declination;
    bez obou je rotace 0.
    """
    data = template_path.read_text(encoding="utf-8")
    geo_m = re.search(r"<georeferencing\b[^>]*>", data)
    if geo_m is None:
        return None
    geo = geo_m.group()
    scale_m = re.search(r'scale="([\d.]+)"', geo)
    if scale_m is None:
        return None
    # Grivation preferovaná (UTM grid), fallback declination, jinak 0.
    rot_m = re.search(r'grivation="(-?[\d.]+)"', geo) or re.search(r'declination="(-?[\d.]+)"', geo)
    grivation = float(rot_m.group(1)) if rot_m else 0.0
    ref_m = re.search(r'<ref_point x="(-?[\d.]+)" y="(-?[\d.]+)"', data)
    if ref_m is None:
        return None  # bez ref_point není kotva na reálný svět
    return {
        "scale": float(scale_m.group(1)),
        "grivation": grivation,
        "proj_ref": (float(ref_m.group(1)), float(ref_m.group(2))),
    }


def _build_map_to_proj(geo: dict) -> np.ndarray:
    """
    MapToProj (OMAP coord -> UTM) jako homogenní 3x3.

        proj = proj_ref + scale*1e-6 * R(-grivation) * diag(1,-1) * map

    scale*1e-6 = metry terénu na 1 coord unit (1 unit = 1e-3 mm papír * scale).
    R(-grivation) a diag(1,-1) jsou ověřená znaménková konvence (viz hlavička sekce).
    """
    s = geo["scale"] * 1e-6
    th = np.deg2rad(-geo["grivation"])
    rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    flip_y = np.array([[1, 0], [0, -1]])
    lin = s * rot @ flip_y
    cx, cy = geo["proj_ref"]
    return np.array([[lin[0, 0], lin[0, 1], cx],
                     [lin[1, 0], lin[1, 1], cy],
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


def _object_coords_list(
    obj: MapObject,
    claim_mask: np.ndarray,
    transform,
) -> list[str]:
    """
    Z pixelů jednoho objektu (claim_mask == obj.id) vyrobí seznam <coords> elementů.

    Větvení dle geometry_type:
    - "line"  → path-tracing kostry (segment-trace) → JEDNA NEBO VÍC otevřených
                polyline (každá hrana grafu mezi uzly = jeden segment). Bez tracingu
                by findContours obkroužil 1px skeleton = zdvojená smyčka.
    - "area"  → vnější kontura komponenty (findContours), OOM ji vyplní. Vždy 1 prvek.

    Vrací prázdný seznam pokud je objekt degenerátní (žádný segment dost dlouhý).
    Více prvků = více OMAP <object> se stejným symbolem (větvený / slitý objekt).
    """
    if obj.geometry_type == "line":
        polylines = _trace_skeleton(obj, claim_mask)
        min_points = 2  # linie může být krátká (median 16 px)
    else:
        # Area: bool maska pixelů → uint8 0/255 pro findContours.
        mask = (claim_mask == obj.id).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return []
        # Největší kontura (objekt může mít drobné satelitní pixely).
        contour = max(contours, key=cv2.contourArea)
        approx = cv2.approxPolyDP(contour, APPROX_EPSILON_PX, closed=True)
        # approx má tvar (N, 1, 2) — squeeze na (N, 2); zabalíme do seznamu (1 prvek).
        polylines = [approx.reshape(-1, 2)]
        min_points = MIN_COORDS

    # Každou polyline → <coords> string. Bez flagů — OOM uzavře area path podle
    # symbol typu, line nechá otevřený.
    out: list[str] = []
    for points in polylines:
        if points is None or len(points) < min_points:
            continue
        parts = [f"{mx} {my}" for mx, my in (transform(float(px), float(py)) for px, py in points)]
        coord_str = ";".join(parts) + ";"
        out.append(f'<coords count="{len(points)}">{coord_str}</coords>')
    return out


# 4-sousedi (kolmé) a diagonální 8-sousedi — pro walk preferujeme kolmé kroky
# (hladší trasa, méně zubatění než když začneme diagonálou).
_N4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]
_N8_DIAG = [(-1, -1), (-1, 1), (1, -1), (1, 1)]


def _trace_skeleton(obj: MapObject, claim_mask: np.ndarray) -> list[np.ndarray]:
    """
    Segment-trace 1px kostry objektu → seznam polyline (N, 2) v (x, y).

    Kostru chápeme jako graf: uzly = pixely se stupněm != 2 (endpointy deg 1,
    junctiony deg >= 3), hrany = řetězy deg-2 pixelů mezi uzly. Každou hranu
    vytrasujeme jako samostatnou polyline → neztratíme žádnou délku ani u silně
    větvených objektů (na rozdíl od greedy walku, který bral jen první větev).

    Algoritmus (v1, KISS):
    1. Crop na bbox objektu (set lokálních (r, c) → rychlý lookup sousedů).
    2. Stupeň každého pixelu = počet 8-sousedů v kostře.
    3. Z každého uzlu trasuj každou výchozí hranu po deg-2 pixelech až k dalšímu uzlu.
    4. Čisté smyčky (komponenty bez uzlu, samé deg 2) trasuj zvlášť.
    5. approxPolyDP na každý segment (closed=False — otevřená linie).

    Pozn.: L-rohy v 8-souvislé kostře mohou dát deg 3 a rozseknout segment v ohybu;
    pro v1 to akceptujeme (délka se neztratí, jen vznikne víc kratších paths).
    """
    ys, xs = np.where(claim_mask == obj.id)
    if len(ys) < 2:
        return []
    y0, x0 = int(ys.min()), int(xs.min())
    pts = set(zip((ys - y0).tolist(), (xs - x0).tolist()))

    def nbrs(p: tuple[int, int]) -> list[tuple[int, int]]:
        r, c = p
        return [(r + dr, c + dc) for dr, dc in _N4 + _N8_DIAG if (r + dr, c + dc) in pts]

    deg = {p: len(nbrs(p)) for p in pts}

    # Hranu reprezentujeme jako uspořádanou dvojici (menší, větší) → symetrie.
    visited: set[tuple] = set()

    def edge(a, b):
        return (a, b) if a <= b else (b, a)

    def walk(node, step) -> list[tuple[int, int]]:
        """Walk od uzlu přes deg-2 pixely až k dalšímu uzlu (nebo zpět do smyčky)."""
        seg = [node, step]
        visited.add(edge(node, step))
        prev, cur = node, step
        while deg[cur] == 2:
            nxt = next((n for n in nbrs(cur) if n != prev and edge(cur, n) not in visited), None)
            if nxt is None:
                break  # hrana už projitá (uzavřeli jsme smyčku)
            visited.add(edge(cur, nxt))
            seg.append(nxt)
            prev, cur = cur, nxt
        return seg

    segments: list[list[tuple[int, int]]] = []
    # 1) Segmenty vycházející z uzlů (endpointy + junctiony).
    for node in (p for p in pts if deg[p] != 2):
        for s in nbrs(node):
            if edge(node, s) not in visited:
                segments.append(walk(node, s))
    # 2) Čisté smyčky bez uzlu — nenavštívené hrany mezi samými deg-2 pixely.
    for p in pts:
        for s in nbrs(p):
            if edge(p, s) not in visited:
                segments.append(walk(p, s))

    # Lokální (r, c) → globální (x, y); approxPolyDP zjednodušení.
    out: list[np.ndarray] = []
    for seg in segments:
        poly = np.array([[c + x0, r + y0] for r, c in seg], dtype=np.int32)
        approx = cv2.approxPolyDP(poly.reshape(-1, 1, 2), APPROX_EPSILON_PX, closed=False)
        pp = approx.reshape(-1, 2)
        if len(pp) >= 2:
            out.append(pp)
    return out


def export(
    db_dir: Path,
    template_omap: Path,
    out_path: Path,
    iteration: int | None = None,
    pgw_path: Path | None = None,
    pgw_width: int | None = None,
) -> int:
    """
    Hlavní export: DBSnapshot → OMAP XML (přes template).

    Args:
        db_dir: output/<sample>/ (obsahuje db/iter_N.json + claim_mask_iter_N.png).
        template_omap: existující OMAP — zdroj symbols/colors/georef.
        out_path: kam zapsat výsledný .omap.
        iteration: číslo iterace (None = latest dle db/latest.txt).
        pgw_path: world file pro rigorózní georef (None = bbox-fit fallback).
        pgw_width: šířka PNG, ke kterému .pgw patří (None = shodná s claim maskou).

    Returns:
        0 OK, jinak chyba.
    """
    db_path_dir = db_dir / "db"
    if iteration is None:
        latest = db_path_dir / "latest.txt"
        iteration = int(latest.read_text().strip()) if latest.exists() else 0
    db_path = db_path_dir / f"iter_{iteration}.json"
    mask_path = db_path_dir / f"claim_mask_iter_{iteration}.png"
    if not db_path.exists() or not mask_path.exists():
        print(f"Chybí DB nebo claim mask pro iter {iteration}: {db_path}")
        return 1

    snap = DBSnapshot.load(db_path)
    # 16-bit claim mask (IMREAD_UNCHANGED zachová uint16).
    claim_mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
    if claim_mask is None:
        print(f"Nelze načíst claim mask: {mask_path}")
        return 1

    png_h, png_w = snap.image_shape

    # Symbol mapping: symbol_code → OMAP symbol.id (template-aware kódy sedí).
    library = parse_omap(template_omap)
    code_to_id = {s.code: s.id for s in library.symbols}

    # Volba georef: rigorózní (.pgw + georef) má přednost, jinak bbox-fit fallback.
    transform = None
    georef_used = "bbox-fit (lineární, anizotropní)"
    if pgw_path is not None and pgw_path.exists():
        transform = build_georef_transform(
            template_omap, pgw_path, pgw_width or png_w, png_w
        )
        if transform is not None:
            georef_used = f".pgw + georef (rigorózní, pgw_width={pgw_width or png_w})"
        else:
            print(f"  [varování] {template_omap.name} nemá použitelný georef "
                  f"(chybí ref_point/scale) — padám na bbox-fit.")
    coord_bbox = _compute_coord_bbox(template_omap)
    if transform is None:
        transform = _make_transform(coord_bbox, png_w, png_h)

    # Vygeneruj <object> elementy.
    object_xmls: list[str] = []
    skipped_no_symbol = 0
    skipped_degenerate = 0
    for obj in snap.objects:
        sid = code_to_id.get(obj.symbol_code)
        if sid is None:
            skipped_no_symbol += 1
            continue
        # Line objekt může dát víc segmentů (větvený/slitý) → víc <object> se stejným sid.
        coords_list = _object_coords_list(obj, claim_mask, transform)
        if not coords_list:
            skipped_degenerate += 1
            continue
        for coords_xml in coords_list:
            object_xmls.append(f'<object type="{OMAP_TYPE_PATH}" symbol="{sid}">{coords_xml}</object>')

    # Injektuj do template: nahraď obsah <objects ...>...</objects>.
    template_data = template_omap.read_text(encoding="utf-8")
    new_objects = (
        f'<objects count="{len(object_xmls)}">'
        + "".join(object_xmls)
        + "</objects>"
    )
    # re.sub s funkcí, ať se vyhneme problémům s backslashy v náhradě.
    new_data, n_sub = re.subn(
        r"<objects[ >].*?</objects>",
        lambda _m: new_objects,
        template_data,
        count=1,
        flags=re.S,
    )
    if n_sub == 0:
        print(f"Template {template_omap} nemá <objects> sekci k nahrazení.")
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(new_data, encoding="utf-8")

    print(f"=== db2omap export: {out_path} ===")
    print(f"  template:          {template_omap.name}")
    print(f"  georef:            {georef_used}")
    print(f"  objektů zapsáno:   {len(object_xmls)}")
    print(f"  přeskočeno (symbol neznámý):  {skipped_no_symbol}")
    print(f"  přeskočeno (degenerátní):     {skipped_degenerate}")
    print(f"  coord bbox:        x[{coord_bbox[0]}..{coord_bbox[2]}] y[{coord_bbox[1]}..{coord_bbox[3]}]")
    return 0
