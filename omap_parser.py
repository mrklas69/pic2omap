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


def omap_tag(name: str) -> str:
    """
    Pomocník: vytvoří plné jméno tagu s namespace.
    "colors" -> "{http://openorienteering.org/apps/mapper/xml/v2}colors"
    """
    return f"{{{OMAP_NS}}}{name}"


def iter_map_objects(root: ET.Element) -> list[ET.Element]:
    """
    Vrátí skutečné mapové objekty = <object> jako přímé děti <objects> kontejneru.

    POZOR: prosté ".//object" by chytlo i phantom <object> uvnitř <symbols>
    definic — template geometrie patternů/elementů (souřadnice kruhu pro 115
    Depression, čar pro 418 atd.), ne mapové objekty. XPath ".//objects/object"
    je odfiltruje. Single source of truth pro tento (netriviální) výběr.
    """
    return root.findall(f".//{omap_tag('objects')}/{omap_tag('object')}")


def parse_coords(text: str) -> list[tuple[int, int, int]]:
    """
    Coord string z <coords> → seznam (x, y, flag). Token: 'X Y' nebo 'X Y FLAG',
    oddělené ';'. Flag (curve-start, hole-point, …) = 0 když chybí.

    Single source of truth pro coord-token parsing. Konzumenti, kterým flag
    nestačí (centroid, bbox), si ho z výsledku zahodí — netřeba druhý parser.
    """
    out: list[tuple[int, int, int]] = []
    for tok in text.split(";"):
        parts = tok.split()
        if len(parts) >= 2:
            flag = int(parts[2]) if len(parts) >= 3 else 0
            out.append((int(parts[0]), int(parts[1]), flag))
    return out


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
    rgb_elem = elem.find(omap_tag("rgb"))
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
    spot_elem = elem.find(omap_tag("spotcolors"))
    if spot_elem is not None:
        named = spot_elem.find(omap_tag("namedcolor"))
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


# --- Secondary color resolution ---
#
# Některé OMAP symboly mají primární barvu (color="-1", inner_color="-1") a
# skutečnou barvu schovanou v sub-strukturách:
#   - LineSymbol  → mid_symbol / start_symbol / end_symbol (např. 110 Erosion gully)
#   - AreaSymbol  → pattern direct color / nested symbol (např. 407 Undergrowth)
#   - PointSymbol → elements → nested symbol (např. 115 Depression)
# Tyto helpery vrátí první non-NO_COLOR nalezenou v sub-strukturách,
# nebo NO_COLOR pokud žádná není (Text/Combined symboly atd.).
#
# Helpery jsou vzájemně rekurzivní (point_symbol → element → point_symbol → ...),
# ale OMAP strom má vždy omezenou hloubku (max ~3 úrovně), takže žádné riziko
# nekonečné rekurze.


def _color_ref_from_symbol_body(body_elem: ET.Element) -> int:
    """
    Vytáhne primární barvu z elementu <line_symbol> / <area_symbol> / <point_symbol>.
    Bere přímý atribut, nezasahuje rekurzivně.
    """
    tag = body_elem.tag
    if tag == omap_tag("line_symbol"):
        return _attr_int(body_elem, "color", NO_COLOR)
    if tag == omap_tag("area_symbol"):
        return _attr_int(body_elem, "inner_color", NO_COLOR)
    if tag == omap_tag("point_symbol"):
        # Pro point: inner > outer (stejná logika jako symbol_to_color_ref v compare_to_omap)
        inner = _attr_int(body_elem, "inner_color", NO_COLOR)
        if inner != NO_COLOR:
            return inner
        return _attr_int(body_elem, "outer_color", NO_COLOR)
    return NO_COLOR


def _color_ref_from_wrapped_symbol(symbol_wrapper: ET.Element) -> int:
    """
    Z <symbol> wrapperu (obsahuje line_symbol / area_symbol / point_symbol)
    vytáhne barvu. Pokud primární barva v těle symbolu je NO_COLOR a tělo je
    point_symbol s elementy, jde se rekurzivně dál (Vineyard-style nesting).
    """
    for child_tag in ("line_symbol", "area_symbol", "point_symbol"):
        body = symbol_wrapper.find(omap_tag(child_tag))
        if body is None:
            continue
        color = _color_ref_from_symbol_body(body)
        if color != NO_COLOR:
            return color
        # Recurse: point_symbol může mít <element> children s vnořenými barvami.
        if child_tag == "point_symbol":
            color = _secondary_color_for_point(body)
            if color != NO_COLOR:
                return color
    return NO_COLOR


def _secondary_color_for_line(line_elem: ET.Element) -> int:
    """
    Hledá barvu v mid_symbol / start_symbol / end_symbol child elementech
    <line_symbol>. Každý z nich obsahuje <symbol> wrapper, ten <point_symbol>
    (nebo line/area_symbol) s barvou.
    """
    for sub_tag in ("mid_symbol", "start_symbol", "end_symbol"):
        sub = line_elem.find(omap_tag(sub_tag))
        if sub is None:
            continue
        wrapper = sub.find(omap_tag("symbol"))
        if wrapper is None:
            continue
        color = _color_ref_from_wrapped_symbol(wrapper)
        if color != NO_COLOR:
            return color
    return NO_COLOR


def _secondary_color_for_area(area_elem: ET.Element) -> int:
    """
    Hledá barvu v <pattern> child elementech <area_symbol>.
    Dvě varianty:
        - pattern type="1" (line pattern): barva přímo jako 'color' atribut.
        - pattern type="2" (point pattern): vnořený <symbol> wrapper s body.
    """
    for pattern in area_elem.findall(omap_tag("pattern")):
        ptype = _attr_int(pattern, "type", 0)
        if ptype == 1:
            # Line pattern — color atribut přímo na <pattern>.
            color = _attr_int(pattern, "color", NO_COLOR)
            if color != NO_COLOR:
                return color
            # Některé varianty mohou mít i nested — pokračujeme do fallbacku.
        # Point pattern (ptype=2) nebo line pattern bez direct color: hledej nested.
        wrapper = pattern.find(omap_tag("symbol"))
        if wrapper is None:
            continue
        color = _color_ref_from_wrapped_symbol(wrapper)
        if color != NO_COLOR:
            return color
    return NO_COLOR


def _secondary_color_for_point(point_elem: ET.Element) -> int:
    """
    Hledá barvu v <element> children <point_symbol>.
    Každý <element> obsahuje <symbol> wrapper → line/area/point_symbol s barvou.
    """
    for element in point_elem.findall(omap_tag("element")):
        wrapper = element.find(omap_tag("symbol"))
        if wrapper is None:
            continue
        color = _color_ref_from_wrapped_symbol(wrapper)
        if color != NO_COLOR:
            return color
    return NO_COLOR


# --- Parsování symbolů ---

def _parse_description(symbol_elem: ET.Element) -> str:
    """Extrahuje text z <description>...</description> child elementu."""
    desc_elem = symbol_elem.find(omap_tag("description"))
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
    line_elem = elem.find(omap_tag("line_symbol"))
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
        has_mid_symbol=line_elem.find(omap_tag("mid_symbol")) is not None,
        has_start_symbol=line_elem.find(omap_tag("start_symbol")) is not None,
        has_end_symbol=line_elem.find(omap_tag("end_symbol")) is not None,
        secondary_color_ref=_secondary_color_for_line(line_elem),
    )


def _parse_point_symbol(elem: ET.Element) -> PointSymbol:
    """
    <symbol type="1" id="14" code="112" name="Small knoll">
        <point_symbol rotatable="false" inner_radius="375" inner_color="7" outer_width="0" outer_color="-1" elements="0"/>
    </symbol>
    """
    point_elem = elem.find(omap_tag("point_symbol"))
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
        secondary_color_ref=_secondary_color_for_point(point_elem),
    )


def _parse_area_symbol(elem: ET.Element) -> AreaSymbol:
    """
    <symbol type="4" id="..." code="401" name="Open land">
        <area_symbol inner_color="18" min_area="0" patterns="0"/>
    </symbol>
    Patterns (>0) = oblast má vzor (např. tečky pro otevřený les se stromy).
    """
    area_elem = elem.find(omap_tag("area_symbol"))
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
        secondary_color_ref=_secondary_color_for_area(area_elem),
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
    text_elem = elem.find(omap_tag("text_symbol"))
    if text_elem is None:
        return TextSymbol(
            **_common_symbol_kwargs(elem),
            type=SymbolType.TEXT,
        )

    # Font je v child elementu <font family="..." size="..."/>
    font_family = ""
    font_size = 0
    font_elem = text_elem.find(omap_tag("font"))
    if font_elem is not None:
        font_family = _attr_str(font_elem, "family")
        font_size = _attr_int(font_elem, "size")

    # Barva je v <text color="N" .../> child elementu, ne na text_symbol.
    color_ref = NO_COLOR
    text_inner = text_elem.find(omap_tag("text"))
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
    Combined symbol = kombinace více sub-symbolů zobrazených současně.

    Struktura (ISSprOM, např. budova 526.1):
        <symbol type="16" id="111" code="526.1" name="Building">
            <combined_symbol parts="2">
                <part symbol="112"/>   <!-- 526.1.1 area fill -->
                <part symbol="113"/>   <!-- 526.1.2 line outline -->
            </combined_symbol>
        </symbol>

    parts = seznam symbol ID referencí (atribut "symbol" na <part>). Odkazují na
    samostatné Symbol instance v library (tytéž id jako SymbolBase.id). Někdy je
    part bez "symbol" atributu (inline definice) — ten přeskočíme (PoC).
    """
    parts: list[int] = []
    combined_elem = elem.find(omap_tag("combined_symbol"))
    if combined_elem is not None:
        for part in combined_elem.findall(omap_tag("part")):
            # "symbol" atribut = ID referencovaného sub-symbolu. Chybí u inline
            # definic (PoC: ignorujeme, řešíme jen reference na existující symboly).
            sym_id = part.get("symbol")
            if sym_id is not None:
                parts.append(int(sym_id))
    return CombinedSymbol(
        **_common_symbol_kwargs(elem),
        type=SymbolType.COMBINED,
        parts=parts,
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
    geo_elem = root.find(omap_tag("georeferencing"))
    if geo_elem is not None:
        scale = _attr_int(geo_elem, "scale", 10000)

    # Sekce <colors count="N"> obsahuje N <color> elementů.
    # findall vrací všechny matching direct children.
    colors: list[Color] = []
    colors_elem = root.find(omap_tag("colors"))
    if colors_elem is not None:
        for i, color_elem in enumerate(colors_elem.findall(omap_tag("color"))):
            color = _parse_color(color_elem)
            # Invariant priority == poziční index: get_color(ref) indexuje colors[ref],
            # kde ref je priority hodnota (z inner_color/color). build_category_map zase
            # klíčuje podle priority. Obě schémata mlčky předpokládají, že splývají —
            # když ne, get_color tiše vrátí špatnou barvu. Fail-loud (drží ve všech
            # reálných souborech: priority běží 0,1,2,… v pořadí výskytu).
            if color.priority != i:
                raise SystemExit(
                    f"OMAP {Path(path).name}: color #{i} má priority={color.priority} "
                    f"(očekáván {i}). Porušen invariant priority==index — get_color by "
                    f"indexoval špatnou barvu."
                )
            colors.append(color)

    # Sekce <barrier> obaluje <symbols> v některých OMAP verzích.
    # Hledáme <symbols> kdekoliv pod root (jednodušší než vědět přesnou strukturu).
    # ".//tag" je XPath: rekurzivně všude pod root.
    symbols: list[SymbolBase] = []
    symbols_container = root.find(f".//{omap_tag('symbols')}")
    if symbols_container is not None:
        for symbol_elem in symbols_container.findall(omap_tag("symbol")):
            parsed = _parse_symbol(symbol_elem)
            if parsed is not None:
                symbols.append(parsed)

    return SymbolLibrary(scale=scale, colors=colors, symbols=symbols)
