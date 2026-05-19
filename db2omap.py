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


def _object_coords_xml(
    obj: MapObject,
    claim_mask: np.ndarray,
    transform,
) -> str | None:
    """
    Z pixelů jednoho objektu (claim_mask == obj.id) vyrobí <coords> XML element.

    Area i line: vnější kontura komponenty přes cv2.findContours + approxPolyDP.
    Pro area je to obrys plochy (OOM ji vyplní), pro line obrys skeletonu
    (vizuálně tenká čára). Vrací None pokud je objekt degenerátní (< MIN_COORDS).
    """
    # Bool maska pixelů tohoto objektu → uint8 0/255 pro findContours.
    mask = (claim_mask == obj.id).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    # Největší kontura (objekt může mít drobné satelitní pixely).
    contour = max(contours, key=cv2.contourArea)
    approx = cv2.approxPolyDP(contour, APPROX_EPSILON_PX, closed=True)
    # approx má tvar (N, 1, 2) — squeeze na (N, 2).
    points = approx.reshape(-1, 2)
    if len(points) < MIN_COORDS:
        return None

    # Sestav coord string "mx my;mx my;...". Bez flagů — OOM uzavře area path
    # podle symbol typu, line nechá otevřený.
    parts = []
    for px, py in points:
        mx, my = transform(float(px), float(py))
        parts.append(f"{mx} {my}")
    coord_str = ";".join(parts) + ";"
    return f'<coords count="{len(points)}">{coord_str}</coords>'


def export(
    db_dir: Path,
    template_omap: Path,
    out_path: Path,
    iteration: int | None = None,
) -> int:
    """
    Hlavní export: DBSnapshot → OMAP XML (přes template).

    Args:
        db_dir: output/<sample>/ (obsahuje db/iter_N.json + claim_mask_iter_N.png).
        template_omap: existující OMAP — zdroj symbols/colors/georef.
        out_path: kam zapsat výsledný .omap.
        iteration: číslo iterace (None = latest dle db/latest.txt).

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

    # Kalibrace transform z template coord bboxu.
    coord_bbox = _compute_coord_bbox(template_omap)
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
        coords_xml = _object_coords_xml(obj, claim_mask, transform)
        if coords_xml is None:
            skipped_degenerate += 1
            continue
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
    print(f"  objektů zapsáno:   {len(object_xmls)}")
    print(f"  přeskočeno (symbol neznámý):  {skipped_no_symbol}")
    print(f"  přeskočeno (degenerátní):     {skipped_degenerate}")
    print(f"  coord bbox:        x[{coord_bbox[0]}..{coord_bbox[2]}] y[{coord_bbox[1]}..{coord_bbox[3]}]")
    return 0
