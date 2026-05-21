"""
db2omap — PoC export DBSnapshot → OMAP XML.

Cíl tohoto PoC: ukázat, že detekované objekty umíme zapsat do otevíratelného
OMAP souboru. NENÍ to plná Stage 5/7/8 implementace:

    - Vektorizace: area = vnější kontura komponenty (approxPolyDP), line =
      segment-trace kostry (graf, neztrácí délku) + L-roh merge. Žádné Bezier
      vyhlazení, žádné re-linking přerušených linií.
    - Georef: primárně rigorózní pixel → OMAP coord (`.pgw` + OMAP
      georeferencing, složení afinních matic — viz build_georef_transform).
      Fallback = lineární bbox-fit, když není `.pgw` / je Local CRS.
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

import math
import re
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from db_model import DBSnapshot, MapObject
from georef import _compute_coord_bbox, _make_transform, build_georef_transform
from omap_parser import parse_omap


# OMAP object type pro path (line i area). Point=0, path=1, text=4.
OMAP_TYPE_PATH = 1

# approxPolyDP epsilon v pixelech — zjednodušení kontury. Menší = víc bodů
# (věrnější tvar), větší = méně bodů (hladší, ale hrubší). 1.5 px je kompromis
# pro render ~600 px na šířku.
APPROX_EPSILON_PX = 1.5

# Minimum bodů, aby měl path smysl (degenerátní 1-2 body přeskočíme).
MIN_COORDS = 3

# --- L-roh merge (slévání segmentů ve sdílených uzlech) ---
# Maximální ohyb linie při průchodu uzlem, aby se dva segmenty sloučily.
# Vrstevnice se neohýbají ostře; 89 % deg>=3 uzlů jsou "staircase" artefakty
# 8-souvislé Zhang-Suen kostry (ne větvení) — ty chceme protáhnout rovně.
MERGE_MAX_BEND_DEG = 40.0
# Z kolika koncových pixelů segmentu počítáme směr "ven z uzlu". Víc než 1 krok,
# ať nás neoklame 1px zubatění kostry.
MERGE_DIR_PIXELS = 4


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


def _merge_segments(
    segments: list[list[tuple[int, int]]],
) -> list[list[tuple[int, int]]]:
    """
    Sloučí segmenty, které se ve sdíleném uzlu setkávají skoro rovně (L-roh merge).

    Segment-trace láme linii v každém uzlu se stupněm != 2. Většina těchto uzlů
    (89 % na Slovance) jsou "staircase" pixely 8-souvislé kostry — pouhá zalomení,
    ne větvení. Tady je zase spojíme: ve sdíleném uzlu spárujeme dva segmenty,
    jejichž směry "ven z uzlu" míří dost opačně (linie pokračuje rovně, ohyb
    < MERGE_MAX_BEND_DEG). Ostré větvení (dotyk vrstevnice s valem/kamenem)
    necháme rozdělené — žádný pár nesplní práh.

    Vstup i výstup: seznam segmentů, každý je posloupnost lokálních (r, c) pixelů.
    Pracuje PŘED approxPolyDP, na plné pixelové posloupnosti (přesné směry).
    """
    n = len(segments)
    if n < 2:
        return segments

    # Cosinus prahového úhlu MEZI ven-vektory. Linie jde rovně => ven-vektory míří
    # opačně (úhel ~180°, cos ~ -1). Ohyb < 40° => úhel mezi > 140° => cos < cos(140°).
    cos_threshold = math.cos(math.radians(180.0 - MERGE_MAX_BEND_DEG))

    # Mapa uzel (pixel) -> seznam konců segmentů, které se ho dotýkají.
    # end: 0 = první pixel segmentu (head), 1 = poslední (tail).
    ends: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for i, seg in enumerate(segments):
        ends[seg[0]].append((i, 0))
        ends[seg[-1]].append((i, 1))

    def out_dir(i: int, end: int) -> tuple[float, float] | None:
        """Normalizovaný směr ven z uzlu do segmentu (z prvních/posledních k px)."""
        seg = segments[i]
        k = min(MERGE_DIR_PIXELS, len(seg) - 1)
        if end == 0:
            p_node, p_in = seg[0], seg[k]
        else:
            p_node, p_in = seg[-1], seg[-1 - k]
        dr, dc = p_in[0] - p_node[0], p_in[1] - p_node[1]
        norm = math.hypot(dr, dc)
        if norm == 0:
            return None
        return dr / norm, dc / norm

    # partner[(i, end)] = (j, end2) — symetrické párování konců přes uzly.
    partner: dict[tuple[int, int], tuple[int, int]] = {}
    for node, lst in ends.items():
        if len(lst) < 2:
            continue
        dirs = {ke: d for ke in lst if (d := out_dir(*ke)) is not None}
        keys = list(dirs)
        # Všechny kandidátní páry konců v tomto uzlu, seřazené dle "rovnosti"
        # (nejnižší cos = nejblíž 180° = nejrovnější přechod jde první).
        cand = []
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                ka, kb = keys[a], keys[b]
                if ka[0] == kb[0]:
                    continue  # tentýž segment (smyčka na sebe) — neslučovat
                cos = dirs[ka][0] * dirs[kb][0] + dirs[ka][1] * dirs[kb][1]
                cand.append((cos, ka, kb))
        cand.sort()
        # Greedy: ber nejrovnější páry pod prahem, každý konec použij jednou.
        # (Deg-4 uzel = dvě linie přes sebe → můžou vzniknout dva páry.)
        used: set[tuple[int, int]] = set()
        for cos, ka, kb in cand:
            if cos >= cos_threshold:
                break  # zbytek je ještě víc zalomený → konec
            if ka in used or kb in used:
                continue
            partner[ka] = kb
            partner[kb] = ka
            used.add(ka)
            used.add(kb)

    # Sřetězení: projdeme segmenty jako linked-list přes partner spoje.
    seg_used = [False] * n

    def build_chain(start_i: int, start_end: int) -> list[tuple[int, int]]:
        """Postav řetěz od volného konce (start_end) přes partnery."""
        chain: list[tuple[int, int]] = []
        cur_i, in_end = start_i, start_end
        while True:
            seg_used[cur_i] = True
            seg = segments[cur_i]
            # Orientuj segment tak, aby vstupní konec byl první.
            ordered = seg if in_end == 0 else seg[::-1]
            # Sdílený uzel se nesmí v řetězu zdvojit.
            if chain and chain[-1] == ordered[0]:
                chain.extend(ordered[1:])
            else:
                chain.extend(ordered)
            nxt = partner.get((cur_i, 1 - in_end))  # výstupní konec
            if nxt is None or seg_used[nxt[0]]:
                break
            cur_i, in_end = nxt
        return chain

    out: list[list[tuple[int, int]]] = []
    # 1) Řetězy začínající z volného konce (konec bez partnera).
    for i in range(n):
        for end in (0, 1):
            if not seg_used[i] and (i, end) not in partner:
                out.append(build_chain(i, end))
    # 2) Uzavřené řetězy segmentů (oba konce spárované) — start z libovolného konce.
    for i in range(n):
        if not seg_used[i]:
            out.append(build_chain(i, 0))
    return out


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
    5. L-roh merge (_merge_segments): slij segmenty, které jdou rovně přes uzel
       (staircase artefakty 8-souvislé kostry + slité vrstevnice téhož symbolu).
    6. approxPolyDP na každý slitý segment (closed=False — otevřená linie).
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

    # L-roh merge: slij segmenty pokračující rovně přes sdílený uzel.
    segments = _merge_segments(segments)

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
