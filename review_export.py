"""
Review krok 4: porovnání DB (iter_N.json) proti OMAP ground truth na úrovni
jednotlivých ISOM kódů + export review artefaktů (CSV).

Na rozdíl od `compare_to_omap` (GT vs Stage 3 masky, per category/type — Fáze 0
metrika) tento modul porovnává GT proti **DB snapshotu** per ISOM kód: "našel
detektor správné symboly ve správném počtu?". Výstupy:
    - per-symbol tabulka (stdout, `format_per_symbol_table`)
    - SUMA CSV (per kód, GT vs DB)
    - GT export CSV (OMAP objekty s pozicí v coord systému)
    - detekce CSV (naše objekty s pozicí v raster systému)

Konzumuje `GroundTruth` z `compare_to_omap` (jediný zdroj GT build). CLI je
v `compare_to_omap.py` — ten tyto funkce volá v `--db` / `--csv-dir` módu.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from compare_to_omap import GroundTruth
from omap_model import SymbolBase, SymbolLibrary, SymbolType
from omap_parser import iter_map_objects, omap_tag, parse_coords


# --- Per-symbol DB ↔ OMAP tabulka (review krok 4) ---
#
# Stálá metrika kroku 4: "našel detektor správné symboly ve správném počtu?".


def _gt_by_code(gt: GroundTruth) -> dict[str, tuple[int, str]]:
    """
    Zploští GT symbol_breakdown na mapu kód → (počet, název).

    symbol_breakdown je per (kategorie, typ); každý ISOM kód spadá typicky do
    jednoho bucketu, ale pro robustnost počty sčítáme. Combined/text symboly tu
    nejsou (build_ground_truth je skipuje) — porovnáváme jen detekovatelné typy.
    """
    by_code: dict[str, tuple[int, str]] = {}
    for items in gt.symbol_breakdown.values():
        for cnt, code, name in items:
            prev_cnt, _ = by_code.get(code, (0, name))
            by_code[code] = (prev_cnt + cnt, name)
    return by_code


def load_db(db_dir: Path, iteration: int | None):
    """
    Načte DBSnapshot (iter_N.json) a vrátí (snap, číslo iterace).

    iteration=None → použij db/latest.txt. Re-use DBSnapshot (jediný zdroj
    formátu DB), aby se logika čtení neduplikovala.
    """
    from db_model import DBSnapshot

    db_path_dir = db_dir / "db"
    if iteration is None:
        latest = db_path_dir / "latest.txt"
        iteration = int(latest.read_text().strip()) if latest.exists() else 0
    snap = DBSnapshot.load(db_path_dir / f"iter_{iteration}.json")
    return snap, iteration


def db_symbol_counts(snap) -> dict[str, int]:
    """Počty objektů per symbol_code z DBSnapshotu."""
    from collections import Counter
    return dict(Counter(o.symbol_code for o in snap.objects))


def _symbol_status(gt: int, db: int) -> str:
    """
    Klasifikuje shodu GT vs DB pro jeden symbol. Prahy ratio volné (detekce je
    hrubá, over-segmentace běžná): OK = ratio v [0.7, 1.4].
    """
    if gt == 0:
        return "EXTRA"        # detekováno, ale GT to neočekává
    if db == 0:
        return "MISSING"      # GT existuje, vůbec nedetekováno
    ratio = db / gt
    if ratio < 0.7:
        return "UNDER"
    if ratio > 1.4:
        return "OVER"
    return "OK"


def format_per_symbol_table(
    omap_path: Path,
    gt: GroundTruth,
    db_counts: dict[str, int],
    iteration: int,
    library: SymbolLibrary,
) -> str:
    """
    Tabulka kód | název | GT | DB | ratio | status, seřazená podle GT desc.

    Sjednocení kódů z GT i DB (EXTRA = detekováno mimo GT). Názvy pro DB-only
    kódy dohledá z library. Na konci souhrn počtů per status.
    """
    gt_by_code = _gt_by_code(gt)
    all_codes = set(gt_by_code) | set(db_counts)

    rows: list[tuple[str, str, int, int, str]] = []
    for code in all_codes:
        gt_cnt, name = gt_by_code.get(code, (0, ""))
        if not name:
            sym = library.find_by_code(code)
            name = sym.name if sym else "?"
        db_cnt = db_counts.get(code, 0)
        rows.append((code, name, gt_cnt, db_cnt, _symbol_status(gt_cnt, db_cnt)))
    # Řazení: GT desc (nejdůležitější symboly nahoře), pak kód.
    rows.sort(key=lambda r: (-r[2], r[0]))

    out: list[str] = []
    out.append(f"=== Per-symbol DB ↔ OMAP: {omap_path.name} (iter {iteration}) ===")
    out.append("")
    out.append(f"  {'kód':<8} {'název':<34} {'GT':>4} {'DB':>4} {'ratio':>6}  status")
    from collections import Counter
    status_tally: Counter = Counter()
    for code, name, gt_cnt, db_cnt, status in rows:
        status_tally[status] += 1
        name_short = name if len(name) <= 34 else name[:31] + "..."
        ratio = f"{db_cnt / gt_cnt:.2f}x" if gt_cnt else "  inf"
        out.append(f"  {code:<8} {name_short:<34} {gt_cnt:>4} {db_cnt:>4} {ratio:>6}  {status}")
    out.append("")
    # Souhrn: kolik symbolů v jakém stavu (pomáhá vidět pokrytí jedním pohledem).
    tally_str = "  ".join(f"{s}={status_tally[s]}"
                          for s in ("OK", "OVER", "UNDER", "MISSING", "EXTRA")
                          if status_tally[s])
    out.append(f"Souhrn: {tally_str}  (symbolů celkem {len(rows)})")
    return "\n".join(out)


# --- GT objekty s pozicí + poziční matching DB ↔ OMAP ---
#
# Pro GT-master DETAIL CSV: každý OMAP objekt (ground truth) + jestli jsme ho
# odhalili. Souřadnice sjednocujeme v OMAP coord prostoru (DB pixel → coord přes
# db2omap georef), matchujeme prostorově (nearest centroid), kódy porovnáme až
# potom → odhalí mislabel (GT 115 vs naše 101 na stejném místě).


@dataclass
class GTObject:
    """Jeden objekt z OMAP <objects> (ground truth) s centroidem v OMAP coord."""
    gt_id: int            # pořadové číslo (index v <objects>, 1-based)
    code: str             # ISOM kód symbolu
    name: str
    geometry_type: str    # line / area / point / text / combined
    cx: float             # centroid OMAP coord x
    cy: float             # centroid OMAP coord y (paper-space, roste dolů)


def _symbol_geometry_type(symbol: SymbolBase) -> str:
    """SymbolType → string geometry_type (konzistentní s db_model MapObject)."""
    return {
        SymbolType.LINE: "line",
        SymbolType.AREA: "area",
        SymbolType.POINT: "point",
        SymbolType.TEXT: "text",
        SymbolType.COMBINED: "combined",
    }.get(symbol.type, "?")


def _object_centroid(obj_elem) -> tuple[float, float] | None:
    """
    Centroid objektu = průměr bodů z <coords>. Flag (curve/hole) nás nezajímá,
    jen pozice. Vrací None pokud objekt nemá použitelné coords.
    """
    coords_elem = obj_elem.find(omap_tag("coords"))
    if coords_elem is None or not coords_elem.text:
        return None
    pts = parse_coords(coords_elem.text)
    if not pts:
        return None
    xs = [x for x, _, _ in pts]
    ys = [y for _, y, _ in pts]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def parse_gt_objects(omap_path: Path, library: SymbolLibrary) -> list[GTObject]:
    """
    Projde <objects> v OMAP a vrátí GT objekty s centroidem. Re-use sid→symbol
    lookup; objekty bez symbolu / bez coords se přeskočí.
    """
    tree = ET.parse(omap_path)
    root = tree.getroot()
    sid_to_symbol = {s.id: s for s in library.symbols}

    objs: list[GTObject] = []
    gid = 0
    for obj in iter_map_objects(root):
        sid = int(obj.get("symbol", -1))
        if sid < 0 or sid not in sid_to_symbol:
            continue
        cen = _object_centroid(obj)
        if cen is None:
            continue
        sym = sid_to_symbol[sid]
        gid += 1
        objs.append(GTObject(gid, sym.code, sym.name, _symbol_geometry_type(sym),
                             cen[0], cen[1]))
    return objs


def _coord_to_loc(cx: float, cy: float,
                  coord_bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    """
    OMAP coord → normalizovaný xLoc/yLoc <0, 10>, origin vlevo-dole.
    OMAP y roste dolů (max_y = spodek), takže yLoc flipujeme (spodek = 0).
    """
    min_x, min_y, max_x, max_y = coord_bbox
    sx = max_x - min_x
    sy = max_y - min_y
    xloc = 10.0 * (cx - min_x) / sx if sx else 0.0
    yloc = 10.0 * (max_y - cy) / sy if sy else 0.0
    return xloc, yloc


# Pozn.: per-objekt poziční matching GT↔DB byl zkoušen (sezení 11), ale vyžaduje
# přesný georef (forest .pgw nemá, Garching .pgw je jen ~5 mm přesný) + odfiltrovat
# legendu. Nearest-centroid produkoval >90 % falešných párů → odloženo (viz TODO).
# Review teď stojí na: SUMA counts + GT export + naše detekce vedle sebe (ruční křížení).


# --- CSV export (review artefakty) ---
#
# encoding="utf-8-sig" = UTF-8 s BOM → Excel správně rozpozná diakritiku v názvech.
# Oddělovač čárka (RFC 4180), desetinné s tečkou. Pro CZ Excel se středníkem to lze
# změnit (volba --csv-sep), ale default držíme standardní.


def write_summary_csv(path: Path, gt: GroundTruth, db_counts: dict[str, int],
                      library: SymbolLibrary) -> int:
    """
    SUMA CSV: per ISOM kód kolik symbolů jsme odhalili (DB) vs kolik je v OMAP (GT).

    Sloupce: isom_code, name, detected_db, in_omap_gt, ratio, status.
    Řazení podle GT desc (nejvýznamnější symboly nahoře). Vrací počet řádků.
    """
    import csv

    gt_by_code = _gt_by_code(gt)
    all_codes = set(gt_by_code) | set(db_counts)
    rows: list[tuple[str, str, int, int, str]] = []
    for code in all_codes:
        gt_cnt, name = gt_by_code.get(code, (0, ""))
        if not name:
            sym = library.find_by_code(code)
            name = sym.name if sym else "?"
        db_cnt = db_counts.get(code, 0)
        rows.append((code, name, db_cnt, gt_cnt, _symbol_status(gt_cnt, db_cnt)))
    rows.sort(key=lambda r: (-r[3], r[0]))

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["isom_code", "name", "detected_db", "in_omap_gt", "ratio", "status"])
        for code, name, db_cnt, gt_cnt, status in rows:
            ratio = f"{db_cnt / gt_cnt:.2f}" if gt_cnt else ""
            w.writerow([code, name, db_cnt, gt_cnt, ratio, status])
    return len(rows)


def write_gt_csv(path: Path, gt_objs: list[GTObject],
                 coord_bbox: tuple[int, int, int, int]) -> int:
    """
    GT export: všechny OMAP objekty (správné řešení) s pozicí. Bez párování.

    Sloupce: gt_id, isom_code, name, geometry_type, xLoc, yLoc.
    Pozice z OMAP coord (přesná v coord systému), normalizovaná na <0, 10>,
    origin vlevo-dole. Seřazeno dle kódu, pak gt_id (stejné symboly pohromadě).
    """
    import csv

    rows = sorted(gt_objs, key=lambda g: (g.code, g.gt_id))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["gt_id", "isom_code", "name", "geometry_type", "xLoc", "yLoc"])
        for g in rows:
            xl, yl = _coord_to_loc(g.cx, g.cy, coord_bbox)
            wr.writerow([g.gt_id, g.code, g.name, g.geometry_type, f"{xl:.2f}", f"{yl:.2f}"])
    return len(rows)


def write_detected_csv(path: Path, snap) -> int:
    """
    Naše detekce s pozicí — odpovídá `mark` obrázku (raster systém, ne OMAP coord).

    Sloupce: id, isom_code, geometry_type, xLoc, yLoc.
    Pozice = pixel centroid bbox normalizovaný na <0, 10> přes raster, origin
    vlevo-dole. POZOR: jiný souřadný systém než review_gt.csv (ten je v OMAP coord).
    Bez přesného georef se 1:1 neslícují (title pruh, nevyplnění rasteru) — proto
    naše objekty hledej v `mark` obrázku, GT v OOM. Seřazeno dle kódu, pak ID.
    """
    import csv

    h, w_img = snap.image_shape
    rows = sorted(snap.objects, key=lambda o: (o.symbol_code, o.id))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["id", "isom_code", "geometry_type", "xLoc", "yLoc"])
        for o in rows:
            cx = (o.bbox[0] + o.bbox[2]) / 2
            cy = (o.bbox[1] + o.bbox[3]) / 2
            xl = 10.0 * cx / w_img
            yl = 10.0 * (1 - cy / h)
            wr.writerow([o.id, o.symbol_code, o.geometry_type, f"{xl:.2f}", f"{yl:.2f}"])
    return len(rows)
