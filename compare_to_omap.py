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


def symbol_to_color_ref(symbol: SymbolBase) -> int:
    """
    Vrátí color reference (priority index) symbolu jako 'hlavní' barvu.

    LineSymbol → color_ref
    AreaSymbol → inner_color_ref (výplň)
    PointSymbol → inner_color_ref pokud existuje, jinak outer_color_ref
        (jednoduché bodové symboly mívají jen inner, složitější obrysové
         struktury mají i outer)
    Jinde NO_COLOR.

    Vrátí NO_COLOR (-1) pokud symbol nemá použitelnou barvu — volající
    pak typicky objekt z porovnání vynechá.
    """
    if isinstance(symbol, LineSymbol):
        return symbol.color_ref
    if isinstance(symbol, AreaSymbol):
        return symbol.inner_color_ref
    if isinstance(symbol, PointSymbol):
        if symbol.inner_color_ref != NO_COLOR:
            return symbol.inner_color_ref
        return symbol.outer_color_ref
    return NO_COLOR


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
    objects_skipped_no_color: int = 0   # Line/Area/Point bez použitelné barvy
    # Detail no-color: list (code, name) pro symboly, kde k tomu došlo
    no_color_symbols: list[tuple[str, str]] = field(default_factory=list)
    # Celkem zpracováno objektů (validní GT objekty)
    objects_counted: int = 0


def build_ground_truth(
    omap_path: Path,
    library: SymbolLibrary,
    category_map: dict[int, ColorCategory],
) -> GroundTruth:
    """
    Projde <objects> v OMAP XML, naplní GroundTruth.

    Postup per objekt:
        1. Přečíst symbol="N" atribut.
        2. -1 nebo neznámé → objects_without_symbol++.
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

    # XPath ".//object" = všechny <object> kdekoliv pod root (bez ohledu na hloubku).
    for obj in root.findall(".//" + _tag("object")):
        sid = int(obj.get("symbol", -1))

        # Krok 1+2: symbol=-1 nebo neznámý ID → skip s počítadlem.
        if sid < 0 or sid not in sid_to_symbol:
            gt.objects_without_symbol += 1
            continue

        # Krok 3: typ symbolu.
        symbol = sid_to_symbol[sid]
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

        # Krok 4+5: barva → kategorie.
        color_ref = symbol_to_color_ref(symbol)
        if color_ref == NO_COLOR or color_ref not in category_map:
            # Symbol bez hlavní barvy (typicky AreaSymbol s patterns_count > 0,
            # kde inner_color=-1 a barva je dána pattern children).
            gt.objects_skipped_no_color += 1
            gt.no_color_symbols.append((symbol.code, symbol.name))
            continue
        category = category_map[color_ref]

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
) -> str:
    """
    Vyformátuje human-readable porovnání. Pokud pipeline_counts=None,
    vypíše jen GT část.
    """
    out: list[str] = []
    out.append(f"=== Compare to OMAP: {omap_path.name} ===")
    out.append("")
    out.append(f"Zpracováno objektů: {gt.objects_counted}")
    out.append(
        f"Skip — bez symbolu (-1): {gt.objects_without_symbol}, "
        f"text: {gt.objects_skipped_text}, "
        f"combined: {gt.objects_skipped_combined}, "
        f"no-color: {gt.objects_skipped_no_color}"
    )
    # Pokud máme nějaké no-color, vypíšeme unikátní (code, name) páry s počtem.
    # Hodí se k debugu — jestli to jsou legitimní pattern areas, nebo bug v mappingu.
    if gt.no_color_symbols:
        from collections import Counter
        # Counter na list tuplů → {(code, name): count}
        nc_counts = Counter(gt.no_color_symbols)
        out.append("No-color symbols (objekty bez použitelné barvy):")
        # Sort podle počtu desc, pak podle kódu
        for (code, name), cnt in sorted(nc_counts.items(), key=lambda kv: (-kv[1], kv[0][0])):
            name_short = name if len(name) <= 36 else name[:33] + "..."
            out.append(f"  {cnt:>3}× {code:<8} {name_short}")
    out.append("")

    # Které kategorie se v reportu objevily — sjednocení GT i pipeline (pokud existuje).
    all_categories: set[ColorCategory] = set()
    for cat, _ in gt.counts.keys():
        all_categories.add(cat)
    if pipeline_counts is not None:
        for (cat, _), cnt in pipeline_counts.items():
            if cnt > 0:
                all_categories.add(cat)

    # Stabilní pořadí: podle .value (alphabetical) — robustní napříč Python verzemi.
    categories_sorted = sorted(all_categories, key=lambda c: c.value)

    for cat in categories_sorted:
        out.append(f"--- {cat.value.upper()} ---")
        # Hlavička tabulky POINT/LINE/AREA × GT / Pipe / Δ / Ratio
        if pipeline_counts is not None:
            out.append(f"  {'Type':<6}  {'GT':>5}  {'Pipe':>5}  {'Diff':>5}  {'Ratio':>6}")
        else:
            out.append(f"  {'Type':<6}  {'GT':>5}")

        for ctype in ComponentType:
            gt_cnt = gt.counts.get((cat, ctype), 0)
            if pipeline_counts is not None:
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


# --- CLI ---

def main() -> None:
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
    args = parser.parse_args()

    if not args.omap_file.exists():
        raise SystemExit(f"OMAP soubor neexistuje: {args.omap_file}")

    # Načti symbol DB.
    library = parse_omap(args.omap_file)
    profiles = build_color_profiles(library)
    category_map = build_category_map_with_overrides(profiles)

    # Build GT.
    gt = build_ground_truth(args.omap_file, library, category_map)

    # Volitelně pipeline counts.
    pipeline_counts: dict[tuple[ColorCategory, ComponentType], int] | None = None
    if args.stage3_dir is not None:
        if not args.stage3_dir.exists():
            print(f"VAROVÁNÍ: --stage3-dir {args.stage3_dir} neexistuje, vypisuju jen GT.")
        else:
            pipeline_counts = load_pipeline_counts(args.stage3_dir)

    print(format_report(args.omap_file, gt, pipeline_counts))


if __name__ == "__main__":
    main()
