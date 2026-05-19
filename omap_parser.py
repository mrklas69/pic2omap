"""
Parser OMAP souborů (OpenOrienteering Mapper, .omap / .xmap).

Načte XML, extrahuje barvy a symboly do SymbolLibrary.
KISS: používá pouze stdlib xml.etree.ElementTree (žádný lxml).

Použití:
    from omap_parser import parse_omap
    library = parse_omap("resources/complete map.omap")
    print(f"{len(library.colors)} barev, {len(library.symbols)} symbolů")
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from omap_model import (
    NO_COLOR,
    AreaSymbol,
    CapStyle,
    Color,
    CombinedSymbol,
    JoinStyle,
    LineSymbol,
    PointSymbol,
    SymbolBase,
    SymbolLibrary,
    SymbolType,
    TextSymbol,
)


# OMAP XML namespace — všechny tagy v souboru jsou prefixované tímto URI.
# ET vrací tagy jako "{namespace}tag", takže si připravíme helper.
OMAP_NS = "http://openorienteering.org/apps/mapper/xml/v2"


def _tag(name: str) -> str:
    """
    Pomocník: vytvoří plné jméno tagu s namespace.
    "colors" -> "{http://openorienteering.org/apps/mapper/xml/v2}colors"
    """
    return f"{{{OMAP_NS}}}{name}"


def _attr_int(elem: ET.Element, name: str, default: int = 0) -> int:
    """Bezpečné čtení int atributu (vrátí default, pokud chybí)."""
    val = elem.get(name)
    return int(val) if val is not None else default


def _attr_float(elem: ET.Element, name: str, default: float = 0.0) -> float:
    """Bezpečné čtení float atributu."""
    val = elem.get(name)
    return float(val) if val is not None else default


def _attr_bool(elem: ET.Element, name: str, default: bool = False) -> bool:
    """
    Bezpečné čtení boolean atributu. OMAP používá "true"/"false" string.
    Pokud atribut chybí, vrátí default.
    """
    val = elem.get(name)
    if val is None:
        return default
    # OMAP používá lowercase "true"/"false", ale buďme tolerantní
    return val.lower() == "true"


def _attr_str(elem: ET.Element, name: str, default: str = "") -> str:
    """Bezpečné čtení string atributu."""
    return elem.get(name, default)


# --- Parsování barev ---

def _parse_color(elem: ET.Element) -> Color:
    """
    Parsuje jeden <color> element ze sekce <colors>.

    Struktura:
        <color priority="0" name="Purple" c="0.2" m="1" y="0" k="0" opacity="1">
            <spotcolors><namedcolor>PURPLE</namedcolor></spotcolors>
            <cmyk method="custom"/>
            <rgb method="cmyk" r="0.8" g="0" b="1"/>
        </color>
    """
    priority = _attr_int(elem, "priority")
    name = _attr_str(elem, "name")
    c = _attr_float(elem, "c")
    m = _attr_float(elem, "m")
    y = _attr_float(elem, "y")
    k = _attr_float(elem, "k")
    opacity = _attr_float(elem, "opacity", 1.0)

    # RGB hodnoty jsou v <rgb r="..." g="..." b="..."/> child elementu.
    # Pokud chybí (staré soubory?), spočítáme RGB triviálně z CMYK.
    rgb_elem = elem.find(_tag("rgb"))
    if rgb_elem is not None:
        r = _attr_float(rgb_elem, "r")
        g = _attr_float(rgb_elem, "g")
        b = _attr_float(rgb_elem, "b")
    else:
        # Fallback: jednoduchá CMYK→RGB konverze (neuvažuje ICC profily).
        # OOM používá sofistikovanější výpočet, ale pro fallback to stačí.
        r = (1 - c) * (1 - k)
        g = (1 - m) * (1 - k)
        b = (1 - y) * (1 - k)

    # Spot color name — pokud existuje <namedcolor>, vezmeme jeho text.
    # Cesta: <spotcolors><namedcolor>NÁZEV</namedcolor></spotcolors>
    spot_name: Optional[str] = None
    spot_elem = elem.find(_tag("spotcolors"))
    if spot_elem is not None:
        named = spot_elem.find(_tag("namedcolor"))
        if named is not None and named.text:
            spot_name = named.text.strip()

    return Color(
        priority=priority,
        name=name,
        c=c, m=m, y=y, k=k,
        r=r, g=g, b=b,
        opacity=opacity,
        spot_color_name=spot_name,
    )


# --- Parsování symbolů ---

def _parse_description(symbol_elem: ET.Element) -> str:
    """Extrahuje text z <description>...</description> child elementu."""
    desc_elem = symbol_elem.find(_tag("description"))
    if desc_elem is not None and desc_elem.text:
        return desc_elem.text.strip()
    return ""


def _common_symbol_kwargs(elem: ET.Element) -> dict:
    """
    Společné atributy pro všechny typy symbolů (id, code, name, description).
    type přidává konkrétní parser, protože je už znám z větvení.
    """
    return {
        "id": _attr_int(elem, "id"),
        "code": _attr_str(elem, "code"),
        "name": _attr_str(elem, "name"),
        "description": _parse_description(elem),
    }


def _parse_line_symbol(elem: ET.Element) -> LineSymbol:
    """
    <symbol type="2" id="0" code="101" name="Contour">
        <description>...</description>
        <line_symbol color="7" line_width="210" dashed="true" dash_length="6000" ...>
            <mid_symbol>...</mid_symbol>     <!-- volitelně -->
            <start_symbol>...</start_symbol> <!-- volitelně -->
            <end_symbol>...</end_symbol>     <!-- volitelně -->
        </line_symbol>
    </symbol>
    """
    line_elem = elem.find(_tag("line_symbol"))
    # Pokud někdy chybí line_symbol child (poškozený soubor), vrátíme prázdný.
    if line_elem is None:
        return LineSymbol(
            **_common_symbol_kwargs(elem),
            type=SymbolType.LINE,
        )

    # Konverze int → enum (cap_style, join_style). IntEnum přijímá int přímo.
    cap_int = _attr_int(line_elem, "cap_style", CapStyle.FLAT.value)
    join_int = _attr_int(line_elem, "join_style", JoinStyle.BEVEL.value)

    return LineSymbol(
        **_common_symbol_kwargs(elem),
        type=SymbolType.LINE,
        color_ref=_attr_int(line_elem, "color", NO_COLOR),
        line_width=_attr_int(line_elem, "line_width"),
        minimum_length=_attr_int(line_elem, "minimum_length"),
        # Enum konstruktor: CapStyle(0) → CapStyle.FLAT. Pokud OMAP přidá novou
        # hodnotu, kterou neznáme, padne to — což je správné (signál pro update modelu).
        cap_style=CapStyle(cap_int),
        join_style=JoinStyle(join_int),
        dashed=_attr_bool(line_elem, "dashed"),
        dash_length=_attr_int(line_elem, "dash_length"),
        break_length=_attr_int(line_elem, "break_length"),
        segment_length=_attr_int(line_elem, "segment_length"),
        has_mid_symbol=line_elem.find(_tag("mid_symbol")) is not None,
        has_start_symbol=line_elem.find(_tag("start_symbol")) is not None,
        has_end_symbol=line_elem.find(_tag("end_symbol")) is not None,
    )


def _parse_point_symbol(elem: ET.Element) -> PointSymbol:
    """
    <symbol type="1" id="14" code="112" name="Small knoll">
        <point_symbol rotatable="false" inner_radius="375" inner_color="7" outer_width="0" outer_color="-1" elements="0"/>
    </symbol>
    """
    point_elem = elem.find(_tag("point_symbol"))
    if point_elem is None:
        return PointSymbol(
            **_common_symbol_kwargs(elem),
            type=SymbolType.POINT,
        )

    return PointSymbol(
        **_common_symbol_kwargs(elem),
        type=SymbolType.POINT,
        rotatable=_attr_bool(point_elem, "rotatable"),
        inner_radius=_attr_int(point_elem, "inner_radius"),
        inner_color_ref=_attr_int(point_elem, "inner_color", NO_COLOR),
        outer_width=_attr_int(point_elem, "outer_width"),
        outer_color_ref=_attr_int(point_elem, "outer_color", NO_COLOR),
        elements_count=_attr_int(point_elem, "elements"),
    )


def _parse_area_symbol(elem: ET.Element) -> AreaSymbol:
    """
    <symbol type="4" id="..." code="401" name="Open land">
        <area_symbol inner_color="18" min_area="0" patterns="0"/>
    </symbol>
    Patterns (>0) = oblast má vzor (např. tečky pro otevřený les se stromy).
    """
    area_elem = elem.find(_tag("area_symbol"))
    if area_elem is None:
        return AreaSymbol(
            **_common_symbol_kwargs(elem),
            type=SymbolType.AREA,
        )

    return AreaSymbol(
        **_common_symbol_kwargs(elem),
        type=SymbolType.AREA,
        inner_color_ref=_attr_int(area_elem, "inner_color", NO_COLOR),
        min_area=_attr_int(area_elem, "min_area"),
        patterns_count=_attr_int(area_elem, "patterns"),
    )


def _parse_text_symbol(elem: ET.Element) -> TextSymbol:
    """
    <symbol type="8" id="5" code="105" name="Contour value">
        <text_symbol icon_text="225" rotatable="true">
            <font family="Arial" size="3114"/>
            <text color="7" .../>
        </text_symbol>
    </symbol>
    """
    text_elem = elem.find(_tag("text_symbol"))
    if text_elem is None:
        return TextSymbol(
            **_common_symbol_kwargs(elem),
            type=SymbolType.TEXT,
        )

    # Font je v child elementu <font family="..." size="..."/>
    font_family = ""
    font_size = 0
    font_elem = text_elem.find(_tag("font"))
    if font_elem is not None:
        font_family = _attr_str(font_elem, "family")
        font_size = _attr_int(font_elem, "size")

    # Barva je v <text color="N" .../> child elementu, ne na text_symbol.
    color_ref = NO_COLOR
    text_inner = text_elem.find(_tag("text"))
    if text_inner is not None:
        color_ref = _attr_int(text_inner, "color", NO_COLOR)

    return TextSymbol(
        **_common_symbol_kwargs(elem),
        type=SymbolType.TEXT,
        color_ref=color_ref,
        font_family=font_family,
        font_size=font_size,
        rotatable=_attr_bool(text_elem, "rotatable"),
    )


def _parse_combined_symbol(elem: ET.Element) -> CombinedSymbol:
    """
    Combined symbol = kombinace více sub-symbolů. Strukturu zatím neznáme
    detailně z testovacích dat — uložíme jako prázdný parts seznam a doplníme,
    až narazíme na konkrétní data.

    TODO: dohledat strukturu v OMAP spec a doplnit. Combined symbolů je v
    complete map.omap jen ~9, takže to není blocker.
    """
    return CombinedSymbol(
        **_common_symbol_kwargs(elem),
        type=SymbolType.COMBINED,
        parts=[],  # zatím prázdné
    )


def _parse_symbol(elem: ET.Element) -> Optional[SymbolBase]:
    """
    Hlavní dispatch — podle "type" atributu zavolá správný typový parser.
    Vrací None, pokud type neznáme (graceful degradation).
    """
    type_int = _attr_int(elem, "type", 0)

    # Mapování type kódu na parser. dict je rychlejší a čitelnější než if/elif.
    parsers = {
        SymbolType.POINT.value: _parse_point_symbol,
        SymbolType.LINE.value: _parse_line_symbol,
        SymbolType.AREA.value: _parse_area_symbol,
        SymbolType.TEXT.value: _parse_text_symbol,
        SymbolType.COMBINED.value: _parse_combined_symbol,
    }
    parser = parsers.get(type_int)
    if parser is None:
        # Neznámý typ — vrátíme None, hlavní funkce ho vyfiltruje.
        return None
    return parser(elem)


# --- Hlavní vstupní bod ---

def parse_omap(path: str | Path) -> SymbolLibrary:
    """
    Načte OMAP soubor a vrátí naplněnou SymbolLibrary.

    Args:
        path: cesta k .omap nebo .xmap souboru.

    Returns:
        SymbolLibrary se všemi barvami a symboly ze souboru.

    Raises:
        FileNotFoundError: pokud soubor neexistuje.
        ET.ParseError: pokud XML je rozbité.
    """
    path = Path(path)
    # parse() načte celý XML strom do paměti. Pro 1-2 MB OMAP to není problém.
    tree = ET.parse(path)
    root = tree.getroot()  # <map> kořenový element

    # Měřítko mapy z <georeferencing scale="10000">.
    # Default 10000 (klasická lesní orienťačka 1:10 000) pokud chybí.
    scale = 10000
    geo_elem = root.find(_tag("georeferencing"))
    if geo_elem is not None:
        scale = _attr_int(geo_elem, "scale", 10000)

    # Sekce <colors count="N"> obsahuje N <color> elementů.
    # findall vrací všechny matching direct children.
    colors: list[Color] = []
    colors_elem = root.find(_tag("colors"))
    if colors_elem is not None:
        for color_elem in colors_elem.findall(_tag("color")):
            colors.append(_parse_color(color_elem))

    # Sekce <barrier> obaluje <symbols> v některých OMAP verzích.
    # Hledáme <symbols> kdekoliv pod root (jednodušší než vědět přesnou strukturu).
    # ".//tag" je XPath: rekurzivně všude pod root.
    symbols: list[SymbolBase] = []
    symbols_container = root.find(f".//{_tag('symbols')}")
    if symbols_container is not None:
        for symbol_elem in symbols_container.findall(_tag("symbol")):
            parsed = _parse_symbol(symbol_elem)
            if parsed is not None:
                symbols.append(parsed)

    return SymbolLibrary(scale=scale, colors=colors, symbols=symbols)
