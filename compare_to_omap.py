"""
Porovnání pipeline výstupu (Stage 3) s ground truth z OMAP souboru.

Smysl: dostat **metriku úspěchu** pro Fázi 0 — kolik objektů by detektor
měl najít (z OMAP) vs kolik jich pipeline aktuálně najde (z PNG masek).

Ground truth (OMAP):
    Projdeme <objects> v OMAP XML. Každý <object symbol="N"> ukazuje
    na SymbolBase v library, ten zase na barvu a má svůj typ
    (LINE/AREA/POINT). Sloučíme přes (ColorCategory, ComponentType).

Pipeline:
    Pro každou (category, type) kombinaci načteme cat_<color>_<type>.png
    z Stage 3 výstupu a spočítáme connected components.

KISS poznámka: skript je standalone — nepřidává parsing objektů do
omap_model/omap_parser. Pro symbol DB je `<objects>` irelevantní, kompletní
mapový dokument zatím nepotřebujeme.

CLI:
    python compare_to_omap.py "resources/forest sample.omap"
    python compare_to_omap.py "resources/forest sample.omap" \\
        --stage3-dir "output/forest sample/components"
    python compare_to_omap.py "resources/forest sample.omap" \\
        --symbols 101,102,103
"""

import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from color_category import ColorCategory, build_category_map_with_overrides
from color_profile import build_color_profiles
from components import ComponentType
from omap_model import (
    NO_COLOR,
    AreaSymbol,
    LineSymbol,
    PointSymbol,
    SymbolBase,
    SymbolLibrary,
    SymbolType,
)
from omap_parser import OMAP_NS, parse_omap


def _tag(name: str) -> str:
    """Plné jméno OMAP XML tagu s namespace (lokální helper, DRY s omap_parser)."""
    return f"{{{OMAP_NS}}}{name}"


# --- Mapování symbol → (ComponentType, color_ref) ---

def symbol_to_component_type(symbol: SymbolBase) -> ComponentType | None:
    """
    Mapuje symbol typ na očekávaný topologický typ rasteru.

    LineSymbol  → LINE   (vrstevnice, cesty, ploty, …)
    AreaSymbol  → AREA   (les, otevřená země, jezera, …)
    PointSymbol → POINT  (balvany, jámy, kupy, …)
    TextSymbol, CombinedSymbol → None (zatím skip — OCR ani composite recognition nemáme)

    isinstance funguje díky dataclass inheritance — všechny tyto třídy
    dědí ze SymbolBase, ale runtime typ je konkrétní podtřída.
    """
    if isinstance(symbol, LineSymbol):
        return ComponentType.LINE
    if isinstance(symbol, AreaSymbol):
        return ComponentType.AREA
    if isinstance(symbol, PointSymbol):
        return ComponentType.POINT
    return None


def symbol_to_color_ref_with_source(symbol: SymbolBase) -> tuple[int, bool]:
    """
    Vrátí (color_ref, used_secondary). 2-úrovňový fallback:
        1. Primary — color_ref / inner_color_ref / outer_color_ref na samotném
           symbolu.
        2. Secondary — secondary_color_ref z parseru (mid_symbol / pattern /
           element). Naplněno parserem pro symboly, které mají primární barvu
           NO_COLOR a skutečnou barvu schovanou v sub-struktuře.
           Příklady (forest sample):
               110 Erosion gully  → primary=-1, secondary=Brown (7)
               115 Depression     → primary=-1, secondary=Brown (7)
               407 Undergrowth    → primary=-1, secondary=Green-pattern (17)
               416 Veg. boundary  → primary=-1, secondary=Black (1)

    used_secondary = True pokud se vybrala secondary (= diagnostika).
    """
    if isinstance(symbol, LineSymbol):
        if symbol.color_ref != NO_COLOR:
            return symbol.color_ref, False
        return symbol.secondary_color_ref, True
    if isinstance(symbol, AreaSymbol):
        if symbol.inner_color_ref != NO_COLOR:
            return symbol.inner_color_ref, False
        return symbol.secondary_color_ref, True
    if isinstance(symbol, PointSymbol):
        if symbol.inner_color_ref != NO_COLOR:
            return symbol.inner_color_ref, False
        if symbol.outer_color_ref != NO_COLOR:
            return symbol.outer_color_ref, False
        return symbol.secondary_color_ref, True
    return NO_COLOR, False


def symbol_to_color_ref(symbol: SymbolBase) -> int:
    """
    Vrátí color reference (priority index) symbolu jako 'hlavní' barvu.
    Tenký wrapper nad symbol_to_color_ref_with_source — zahazuje informaci,
    odkud se barva vzala (pro volající, kteří diagnostiku nepotřebují).
    """
    color, _ = symbol_to_color_ref_with_source(symbol)
    return color


# --- Ground truth z OMAP ---

@dataclass
class GroundTruth:
    """
    Statistika OMAP souboru: kolik objektů per (kategorie, typ) + breakdown
    per ISOM symbol (code+name), plus počítadlo přeskočených objektů.
    """
    # counts[(category, type)] = počet objektů
    counts: dict[tuple[ColorCategory, ComponentType], int] = field(default_factory=dict)

    # symbol_breakdown[(cat, type)] = list (count, code, name), seřazený desc podle count
    # Slouží k debugu — vidět, které ISOM kódy do bucketu spadly.
    symbol_breakdown: dict[
        tuple[ColorCategory, ComponentType],
        list[tuple[int, str, str]],
    ] = field(default_factory=dict)

    # Diagnostika: symbol=-1 (interní pattern helpers, nemají symbol referenci)
    objects_without_symbol: int = 0
    # Skipped — rozdělené per důvod (přehlednější diagnostika):
    objects_skipped_text: int = 0       # TextSymbol — OCR nedetekujeme
    objects_skipped_combined: int = 0   # CombinedSymbol — composite recognition nedetekujeme
    objects_skipped_no_color: int = 0   # Line/Area/Point bez použitelné barvy (ani primary, ani secondary)
    # Detail no-color: list (code, name) pro symboly, kde k tomu došlo
    no_color_symbols: list[tuple[str, str]] = field(default_factory=list)
    # Diagnostika secondary fallbacku: objekty, jejichž barva se vzala ze
    # secondary_color_ref (pattern / mid_symbol / element). Pomáhá ověřit,
    # že parser secondary resolver pokrývá očekávané symboly.
    objects_via_secondary: int = 0
    secondary_resolved_symbols: list[tuple[str, str]] = field(default_factory=list)
    # Celkem zpracováno objektů (validní GT objekty)
    objects_counted: int = 0


def build_ground_truth(
    omap_path: Path,
    library: SymbolLibrary,
    category_map: dict[int, ColorCategory],
    symbols_filter: set[str] | None = None,
) -> GroundTruth:
    """
    Projde <objects> v OMAP XML, naplní GroundTruth.

    Postup per objekt:
        1. Přečíst symbol="N" atribut.
        2. -1 nebo neznámé → objects_without_symbol++.
        2b. Pokud je aktivní symbols_filter, objekt s code mimo filtr se
            **totálně přeskočí** (nezapočítá se do žádné statistiky ani
            diagnostiky). Důvod: chceme čistý GT jen pro zvolené symboly,
            aby Stage 4 detektor mohl mířit na přesný target.
        3. Najít symbol v library, určit ComponentType (Line/Area/Point).
        4. Text/Combined nebo bez barvy → objects_skipped++.
        5. Color ref → ColorCategory přes category_map.
        6. counts[(category, type)] += 1, breakdown[...] += 1.
    """
    # ET načte celý XML do paměti. OMAP soubory pod 5 MB to bez problémů zvládnou.
    tree = ET.parse(omap_path)
    root = tree.getroot()

    # Lookup symbol_id → SymbolBase. SymbolBase.id = OMAP <symbol id="N">.
    sid_to_symbol = {s.id: s for s in library.symbols}

    gt = GroundTruth()
    # defaultdict pro pohodlnější inkrementaci, na konci konvertujeme zpět na dict
    counts: dict[tuple[ColorCategory, ComponentType], int] = defaultdict(int)
    # Vnořený defaultdict: (cat, type) → {symbol_id → count}
    breakdown_acc: dict[
        tuple[ColorCategory, ComponentType],
        dict[int, int],
    ] = defaultdict(lambda: defaultdict(int))

    # POZOR: hledáme jen <object> v <objects> sekci (skutečné mapové objekty).
    # ".//object" by chytlo i 134 phantom <object> uvnitř <symbols> definic —
    # to jsou template geometrie patternů/elementů (např. souřadnice kruhu pro
    # 115 Depression, čar pro 418 Special vegetation feature), ne mapové objekty.
    # XPath ".//objects/object" = <object> jako přímé děti <objects> kontejneru.
    for obj in root.findall(f".//{_tag('objects')}/{_tag('object')}"):
        sid = int(obj.get("symbol", -1))

        # Krok 1+2: symbol=-1 nebo neznámý ID → skip s počítadlem.
        # Po fixu cesty by mělo být 0 (každý objekt v <objects> má symbol atribut).
        if sid < 0 or sid not in sid_to_symbol:
            gt.objects_without_symbol += 1
            continue

        # Krok 3: typ symbolu.
        symbol = sid_to_symbol[sid]

        # Krok 2b: pokud je aktivní --symbols filtr, přeskoč objekty mimo seznam.
        # Filtr aplikujeme **až po** symbol lookup (potřebujeme symbol.code).
        # Skip je totální — neinkrementuje žádné počítadlo, aby diagnostika
        # (no_color, secondary_resolved, …) odrážela jen filtrovaný podset.
        if symbols_filter is not None and symbol.code not in symbols_filter:
            continue

        ctype = symbol_to_component_type(symbol)
        if ctype is None:
            # TextSymbol nebo CombinedSymbol — zatím nedetekujeme.
            # Lazy import alternativa nepotřeba, importy už máme nahoře — ale
            # nechceme tady tahat TextSymbol/CombinedSymbol jen pro isinstance,
            # použijeme atribut .type přes SymbolType enum.
            if symbol.type == SymbolType.TEXT:
                gt.objects_skipped_text += 1
            elif symbol.type == SymbolType.COMBINED:
                gt.objects_skipped_combined += 1
            else:
                # Sem by se nemělo dostat (jen 5 typů existuje), ale safety.
                gt.objects_skipped_no_color += 1
            continue

        # Krok 4+5: barva → kategorie (s diagnostikou, odkud).
        color_ref, used_secondary = symbol_to_color_ref_with_source(symbol)
        if color_ref == NO_COLOR or color_ref not in category_map:
            # Symbol bez použitelné barvy ani v primary, ani v secondary.
            # Po fixu (2026-05-19 sezení 5) by mělo být blízko 0 — pokud tu
            # něco zbylo, je to kandidát na další rozšíření secondary resolveru.
            gt.objects_skipped_no_color += 1
            gt.no_color_symbols.append((symbol.code, symbol.name))
            continue
        category = category_map[color_ref]
        if used_secondary:
            # Objekt zachycen díky fallbacku — započítej do diagnostiky.
            gt.objects_via_secondary += 1
            gt.secondary_resolved_symbols.append((symbol.code, symbol.name))

        # Krok 6: inkrementuj.
        key = (category, ctype)
        counts[key] += 1
        breakdown_acc[key][sid] += 1
        gt.objects_counted += 1

    gt.counts = dict(counts)

    # Sestav symbol_breakdown: pro každý bucket list (count, code, name) podle počtu desc.
    for key, sid_counts in breakdown_acc.items():
        items: list[tuple[int, str, str]] = []
        for sid, cnt in sid_counts.items():
            s = sid_to_symbol[sid]
            items.append((cnt, s.code, s.name))
        # Sort podle počtu sestupně. Při shodě podle ISOM kódu vzestupně.
        items.sort(key=lambda x: (-x[0], x[1]))
        gt.symbol_breakdown[key] = items

    return gt


# --- Pipeline counts z PNG masek ---

def count_components_in_mask(mask_path: Path) -> int:
    """
    Spočítá connected components v binární PNG masce.

    cv2.connectedComponents s 8-konektivitou (stejně jako v components.py,
    DRY princip pro detekci). Vrací num_labels včetně pozadí (label 0),
    takže skutečný počet objektů = num_labels - 1.

    Pokud soubor nelze načíst, vrátí 0 (degraded gracefully).
    """
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        return 0
    num_labels, _ = cv2.connectedComponents(mask, connectivity=8)
    return max(0, num_labels - 1)


def load_pipeline_counts(
    stage3_dir: Path,
) -> dict[tuple[ColorCategory, ComponentType], int]:
    """
    Pro každou kombinaci (category, type) najde cat_<color>_<type>.png a
    spočítá komponenty. Pokud soubor neexistuje, kombinace v dictu chybí
    (interpretuje se jako 'nepřipraveno', ne '0 komponent').
    """
    counts: dict[tuple[ColorCategory, ComponentType], int] = {}
    for cat in ColorCategory:
        for ctype in ComponentType:
            filename = f"cat_{cat.value}_{ctype.value}.png"
            path = stage3_dir / filename
            if path.exists():
                counts[(cat, ctype)] = count_components_in_mask(path)
    return counts


# --- Formátování reportu ---

def _format_ratio(gt: int, pipe: int) -> str:
    """
    Ratio pipeline/GT jako string. Edge cases:
        gt=0, pipe=0 → '-'    (oba nulové, není co měřit)
        gt=0, pipe>0 → 'inf'  (pipeline leak v kategorii, kde GT nic neočekává)
        else → '{ratio:.2f}x'
    """
    if gt == 0 and pipe == 0:
        return "-"
    if gt == 0:
        return "inf"
    return f"{pipe / gt:.2f}x"


def format_report(
    omap_path: Path,
    gt: GroundTruth,
    pipeline_counts: dict[tuple[ColorCategory, ComponentType], int] | None,
    symbols_filter: set[str] | None = None,
) -> str:
    """
    Vyformátuje human-readable porovnání. Pokud pipeline_counts=None,
    vypíše jen GT část.

    Pokud je aktivní symbols_filter, pipeline sekce je **skryta**, i když
    pipeline_counts byly načteny. Důvod: GT je filtrované per-symbol, ale
    pipeline produkuje per-category masky (cat_brown_line.png = všechny
    brown linie, ne jen 101/102/103). Smíchat to v jedné tabulce by dalo
    matoucí ratio. Plné srovnání má smysl až po Stage 4 (per-symbol pipeline).
    """
    # Filtr potlačuje pipeline sekci, i když ji uživatel zadal přes --stage3-dir.
    show_pipeline = pipeline_counts is not None and symbols_filter is None

    out: list[str] = []
    out.append(f"=== Compare to OMAP: {omap_path.name} ===")
    if symbols_filter is not None:
        # Stabilní pořadí pro reprodukovatelný výpis (set je neuspořádaný).
        filter_list = ",".join(sorted(symbols_filter))
        out.append(f"Filter: --symbols {filter_list}")
        if pipeline_counts is not None:
            # Uživatel zadal --stage3-dir, ale filtr Pipe sekci skryl — vysvětli proč.
            out.append(
                "  (Pipe sekce skryta: GT je per-symbol, pipeline je per-category. "
                "Smysluplné srovnání bude po Stage 4.)"
            )
    out.append("")
    out.append(f"Zpracováno objektů: {gt.objects_counted}")
    out.append(
        f"  z toho via secondary fallback: {gt.objects_via_secondary}"
    )
    out.append(
        f"Skip — bez symbolu (-1): {gt.objects_without_symbol}, "
        f"text: {gt.objects_skipped_text}, "
        f"combined: {gt.objects_skipped_combined}, "
        f"no-color: {gt.objects_skipped_no_color}"
    )
    # Lokální helper: vypíše unikátní (code, name) páry s počtem, sort desc → code asc.
    # Použité pro 2 sekce níže — DRY.
    from collections import Counter

    def _format_symbol_counter(pairs: list[tuple[str, str]]) -> list[str]:
        c = Counter(pairs)
        lines: list[str] = []
        for (code, name), cnt in sorted(c.items(), key=lambda kv: (-kv[1], kv[0][0])):
            name_short = name if len(name) <= 36 else name[:33] + "..."
            lines.append(f"  {cnt:>3}× {code:<8} {name_short}")
        return lines

    # Resolved via secondary — co se nám díky fallbacku podařilo zachytit.
    if gt.secondary_resolved_symbols:
        out.append("Resolved via secondary (pattern / mid_symbol / element):")
        out.extend(_format_symbol_counter(gt.secondary_resolved_symbols))
    # No-color — co i přes secondary fallback zbylo. Po fixu očekáváme prázdný seznam.
    if gt.no_color_symbols:
        out.append("No-color symbols (ani primary, ani secondary fallback nepomohl):")
        out.extend(_format_symbol_counter(gt.no_color_symbols))
    out.append("")

    # Které kategorie se v reportu objevily — sjednocení GT i pipeline (pokud existuje).
    all_categories: set[ColorCategory] = set()
    for cat, _ in gt.counts.keys():
        all_categories.add(cat)
    if show_pipeline:
        for (cat, _), cnt in pipeline_counts.items():
            if cnt > 0:
                all_categories.add(cat)

    # Stabilní pořadí: podle .value (alphabetical) — robustní napříč Python verzemi.
    categories_sorted = sorted(all_categories, key=lambda c: c.value)

    for cat in categories_sorted:
        out.append(f"--- {cat.value.upper()} ---")
        # Hlavička tabulky POINT/LINE/AREA × GT / Pipe / Δ / Ratio
        if show_pipeline:
            out.append(f"  {'Type':<6}  {'GT':>5}  {'Pipe':>5}  {'Diff':>5}  {'Ratio':>6}")
        else:
            out.append(f"  {'Type':<6}  {'GT':>5}")

        for ctype in ComponentType:
            gt_cnt = gt.counts.get((cat, ctype), 0)
            if show_pipeline:
                pipe_cnt = pipeline_counts.get((cat, ctype), 0)
                delta = pipe_cnt - gt_cnt
                ratio = _format_ratio(gt_cnt, pipe_cnt)
                out.append(
                    f"  {ctype.value:<6}  {gt_cnt:>5}  {pipe_cnt:>5}  "
                    f"{delta:>+5}  {ratio:>6}"
                )
            else:
                out.append(f"  {ctype.value:<6}  {gt_cnt:>5}")

        # Symbol breakdown — pro každý typ vypiš ISOM kódy, které do bucketu spadly.
        # Užitečné pro pochopení "co tam vlastně z GT je".
        for ctype in ComponentType:
            items = gt.symbol_breakdown.get((cat, ctype), [])
            if not items:
                continue
            out.append(f"  Symbols ({ctype.value}):")
            for cnt, code, name in items:
                # Cropped name na 32 znaků pro hezky zarovnaný výpis.
                name_short = name if len(name) <= 32 else name[:29] + "..."
                out.append(f"    {cnt:>3}× {code:<8} {name_short}")
        out.append("")

    return "\n".join(out)


# --- Per-symbol DB ↔ OMAP tabulka (review krok 4) ---
#
# Na rozdíl od format_report (GT vs Stage 3 masky, per category/type) tato část
# porovnává GT proti DB (iter_N.json) na úrovni jednotlivých ISOM kódů. To je
# stálá metrika kroku 4: "našel detektor správné symboly ve správném počtu?".


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
    Centroid objektu = průměr bodů z <coords>. Coord token "X Y" volitelně s flagem.
    Vrací None pokud objekt nemá použitelné coords.
    """
    import re

    coords_elem = obj_elem.find(_tag("coords"))
    if coords_elem is None or not coords_elem.text:
        return None
    nums = re.findall(r"(-?\d+) (-?\d+)(?: \d+)?", coords_elem.text)
    if not nums:
        return None
    xs = [int(a) for a, _ in nums]
    ys = [int(b) for _, b in nums]
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
    for obj in root.findall(f".//{_tag('objects')}/{_tag('object')}"):
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


# --- CLI ---

def main() -> None:
    # UTF-8 pro Windows konzoli (jinak diakritika v reportu rozsekaná).
    # stderr důležitý kvůli SystemExit zprávám z validace --symbols.
    from cli_utils import force_utf8_console
    force_utf8_console()

    parser = argparse.ArgumentParser(
        description="Porovnání pipeline Stage 3 výstupu s OMAP ground truth.",
    )
    parser.add_argument(
        "omap_file",
        type=Path,
        help="Cesta k OMAP souboru (ground truth).",
    )
    parser.add_argument(
        "--stage3-dir",
        type=Path,
        default=None,
        help="Adresář s cat_<color>_<type>.png maskami "
             "(typicky output/<sample>/components/). Bez něj se vypíše jen GT.",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated ISOM kódy pro filtrování GT na podset symbolů "
             "(např. '101,102,103' pro vrstevnice). Exact match. Při aktivním "
             "filtru se pipeline sekce skryje (GT je per-symbol, pipeline per-category).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Adresář output/<sample>/ s db/iter_N.json. Vypíše per-symbol "
             "tabulku DB ↔ OMAP (GT vs detekováno per ISOM kód) místo "
             "per-category reportu. Stálá metrika kroku 4.",
    )
    parser.add_argument(
        "--iter",
        type=int,
        default=None,
        help="Číslo iterace pro --db (default: db/latest.txt).",
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=None,
        help="Adresář pro zápis CSV (vyžaduje --db): review_suma.csv (per kód), "
             "review_gt.csv (GT objekty z OMAP), review_detail.csv (naše detekce).",
    )
    args = parser.parse_args()

    if not args.omap_file.exists():
        raise SystemExit(f"OMAP soubor neexistuje: {args.omap_file}")

    # Načti symbol DB.
    library = parse_omap(args.omap_file)
    profiles = build_color_profiles(library)
    category_map = build_category_map_with_overrides(profiles)

    # Parse + validuj --symbols. Comma-separated string → set[str].
    # Validace: každý kód musí existovat v library, jinak error (lepší než
    # tichý prázdný GT z překlepu).
    symbols_filter: set[str] | None = None
    if args.symbols is not None:
        # strip per item kvůli toleranci k mezerám okolo čárek ('101, 102, 103')
        requested = {s.strip() for s in args.symbols.split(",") if s.strip()}
        if not requested:
            raise SystemExit("--symbols: prázdný seznam (zadej alespoň jeden kód, např. 101)")
        available = {s.code for s in library.symbols}
        unknown = requested - available
        if unknown:
            # Zobraz alespoň pár dostupných kódů, aby uživatel viděl formát.
            sample = sorted(available)[:10]
            raise SystemExit(
                f"--symbols: neznámé kódy v library: {sorted(unknown)}. "
                f"Dostupné kódy (ukázka): {sample}, …"
            )
        symbols_filter = requested

    # Build GT.
    gt = build_ground_truth(args.omap_file, library, category_map, symbols_filter)

    # --db mód: per-symbol tabulka DB ↔ OMAP (review krok 4) místo per-category.
    if args.db is not None:
        if not args.db.exists():
            raise SystemExit(f"--db adresář neexistuje: {args.db}")
        snap, iteration = load_db(args.db, args.iter)
        db_counts = db_symbol_counts(snap)
        print(format_per_symbol_table(args.omap_file, gt, db_counts, iteration, library))
        if args.csv_dir is not None:
            from db2omap import _compute_coord_bbox

            args.csv_dir.mkdir(parents=True, exist_ok=True)
            # SUMA: per ISOM kód (GT vs DB counts) — hlavní spolehlivá metrika.
            n_suma = write_summary_csv(args.csv_dir / "review_suma.csv", gt, db_counts, library)
            # GT export (OMAP coord) + naše detekce (raster) vedle sebe, bez párování.
            gt_objs = parse_gt_objects(args.omap_file, library)
            coord_bbox = _compute_coord_bbox(args.omap_file)
            n_gt = write_gt_csv(args.csv_dir / "review_gt.csv", gt_objs, coord_bbox)
            n_det = write_detected_csv(args.csv_dir / "review_detail.csv", snap)
            print()
            print(f"CSV: {args.csv_dir / 'review_suma.csv'} ({n_suma} kódů)")
            print(f"CSV: {args.csv_dir / 'review_gt.csv'} ({n_gt} GT objektů z OMAP, coord systém)")
            print(f"CSV: {args.csv_dir / 'review_detail.csv'} ({n_det} naše detekce, raster systém)")
        return
    if args.csv_dir is not None:
        raise SystemExit("--csv-dir vyžaduje --db (CSV se generují z DB snapshotu).")

    # Volitelně pipeline counts.
    pipeline_counts: dict[tuple[ColorCategory, ComponentType], int] | None = None
    if args.stage3_dir is not None:
        if not args.stage3_dir.exists():
            print(f"VAROVÁNÍ: --stage3-dir {args.stage3_dir} neexistuje, vypisuju jen GT.")
        else:
            pipeline_counts = load_pipeline_counts(args.stage3_dir)

    print(format_report(args.omap_file, gt, pipeline_counts, symbols_filter))


if __name__ == "__main__":
    main()
