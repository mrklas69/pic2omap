"""
CLI: načte OMAP soubor a vypíše přehled symbolové databáze.

Použití:
    python dump_symbols.py "resources/complete map.omap"

Slouží jako sanity check parseru a první pohled na obsah konkrétního OMAP.
"""

import sys
from collections import Counter
from pathlib import Path

# Windows konzole má cp1250 / cp852 — vynutíme UTF-8, ať se tiskne česky správně.
from cli_utils import force_utf8_console
force_utf8_console()

from omap_model import (
    AreaSymbol,
    LineSymbol,
    PointSymbol,
    SymbolType,
    TextSymbol,
    omap_to_mm,
)
from omap_parser import parse_omap


def main(omap_path: str) -> None:
    """Hlavní funkce. Načte soubor a vytiskne přehled."""
    path = Path(omap_path)
    if not path.exists():
        print(f"CHYBA: soubor neexistuje: {path}", file=sys.stderr)
        sys.exit(1)

    print(f"\n=== {path.name} ===")
    lib = parse_omap(path)
    print(f"Měřítko: 1:{lib.scale}")
    print(f"Barev: {len(lib.colors)}")
    print(f"Symbolů: {len(lib.symbols)}")

    # --- Přehled symbolů po typech ---
    # Counter automaticky spočítá výskyty každé hodnoty.
    type_counts = Counter(s.type for s in lib.symbols)
    print("\nSymboly po typech:")
    # Iterace v pořadí enum (POINT, LINE, AREA, TEXT, COMBINED)
    for symbol_type in SymbolType:
        # .name dá string "POINT" atd., type_counts.get(...) vrátí 0 pokud chybí
        count = type_counts.get(symbol_type, 0)
        print(f"  {symbol_type.name:10s} {count:3d}")

    # --- Výpis barev (priority + name + RGB hex) ---
    print(f"\nBarvy ({len(lib.colors)}):")
    for color in lib.colors:
        # Hex zápis: #RRGGBB. f"{n:02X}" naformátuje na 2 hex znaky velkými písmeny.
        r, g, b = color.rgb_tuple
        hex_color = f"#{r:02X}{g:02X}{b:02X}"
        # Spot color name v závorce, pokud existuje
        spot = f" [{color.spot_color_name}]" if color.spot_color_name else ""
        print(f"  {color.priority:3d}  {hex_color}  {color.name}{spot}")

    # --- Příklad: 10 line symbolů s rozměry v mm ---
    line_symbols = lib.symbols_by_type(SymbolType.LINE)
    if line_symbols:
        print(f"\nLine symboly (prvních 10 z {len(line_symbols)}):")
        # Hlavička sloupců — pomocí formátovacích specifikátorů zarovnáme
        print(f"  {'ISOM':8s} {'name':30s} {'width':>7s} {'color':>5s} {'dashed':>7s}")
        for sym in line_symbols[:10]:
            # isinstance pro type narrowing, aby IDE/linter pochopil typ
            assert isinstance(sym, LineSymbol)
            width_mm = omap_to_mm(sym.line_width)
            color = lib.get_color(sym.color_ref)
            color_name = color.name if color else "-"
            dashed = "yes" if sym.dashed else "no"
            # Truncate name na 30 znaků, ať se to vejde
            name_short = sym.name[:30]
            print(f"  {sym.code:8s} {name_short:30s} {width_mm:6.2f}mm {color_name:5s} {dashed:>7s}")

    # --- Příklad: 10 area symbolů ---
    area_symbols = lib.symbols_by_type(SymbolType.AREA)
    if area_symbols:
        print(f"\nArea symboly (prvních 10 z {len(area_symbols)}):")
        print(f"  {'ISOM':8s} {'name':30s} {'color':30s} {'patterns':>8s}")
        for sym in area_symbols[:10]:
            assert isinstance(sym, AreaSymbol)
            color = lib.get_color(sym.inner_color_ref)
            color_name = color.name if color else "-"
            name_short = sym.name[:30]
            print(f"  {sym.code:8s} {name_short:30s} {color_name:30s} {sym.patterns_count:>8d}")

    # --- Příklad: 10 point symbolů ---
    point_symbols = lib.symbols_by_type(SymbolType.POINT)
    if point_symbols:
        print(f"\nPoint symboly (prvních 10 z {len(point_symbols)}):")
        print(f"  {'ISOM':8s} {'name':30s} {'radius':>8s} {'color':>5s} {'elem':>4s}")
        for sym in point_symbols[:10]:
            assert isinstance(sym, PointSymbol)
            radius_mm = omap_to_mm(sym.inner_radius)
            color = lib.get_color(sym.inner_color_ref)
            color_name = color.name if color else "-"
            name_short = sym.name[:30]
            print(f"  {sym.code:8s} {name_short:30s} {radius_mm:7.2f}mm {color_name:5s} {sym.elements_count:>4d}")

    # --- Text symboly (stručný výpis) ---
    text_symbols = lib.symbols_by_type(SymbolType.TEXT)
    if text_symbols:
        print(f"\nText symboly ({len(text_symbols)}):")
        for sym in text_symbols:
            assert isinstance(sym, TextSymbol)
            color = lib.get_color(sym.color_ref)
            color_name = color.name if color else "-"
            print(f"  {sym.code:8s} {sym.name:30s} font: {sym.font_family} size: {sym.font_size}")

    # --- ISOM kódy souhrnem ---
    # Set z .code dá unikátní kódy. Sorted pro deterministický výstup.
    # Některé kódy mají subindex (např. "106.1"), takže sort jako string je OK.
    codes = sorted(set(s.code for s in lib.symbols if s.code))
    print(f"\nISOM kódy celkem ({len(codes)} unikátních):")
    # Vypíšeme po řádcích po 10 kódech kvůli čitelnosti
    for i in range(0, len(codes), 10):
        print("  " + "  ".join(f"{c:8s}" for c in codes[i:i+10]))


if __name__ == "__main__":
    # Default cesta pokud nebyl předán argument
    default_path = "resources/complete map.omap"
    arg_path = sys.argv[1] if len(sys.argv) > 1 else default_path
    main(arg_path)
