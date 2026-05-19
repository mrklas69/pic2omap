"""
Datový model symbolové databáze OMAP (OpenOrienteering Mapper).

Mapuje 1:1 strukturu OMAP XML souboru — sekce <colors> a <symbols>.
Jednotky délek jsou v "OMAP units" = mikrometry (1/1000 mm).
Např. line_width=210 znamená 0.21 mm.

Specifikace formátu: https://www.openorienteering.org/api-docs/mapper/file_format.html
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


# --- Konstanty ---

# Speciální hodnota color reference pro "žádná barva" (transparent).
# V OMAP XML se zapisuje jako color="-1".
NO_COLOR: int = -1

# Konverzní faktor: OMAP units → mm. 1 mm = 1000 OMAP units.
# Funkce na převod (drží jeden zdroj pravdy).
def omap_to_mm(value: int) -> float:
    """Převede OMAP units (mikrometry) na milimetry."""
    return value / 1000.0


# --- Enumy ---

class SymbolType(IntEnum):
    """
    Typ symbolu podle OMAP. Číselné hodnoty odpovídají XML atributu type="...".
    Bitové masky (1, 2, 4, 8, 16) — historický artefakt OOM.
    """
    POINT = 1     # bodový (např. balvan, jáma, malý kopeček)
    LINE = 2      # liniový (vrstevnice, plot, cesta)
    AREA = 4      # plošný (pasečina, jezero, otevřený prostor)
    TEXT = 8      # text (čísla kontrol, popisky)
    COMBINED = 16 # kombinovaný (skládá více sub-symbolů, např. železnice = linie + tečky)


class CapStyle(IntEnum):
    """Zakončení čáry. Mapuje OMAP cap_style atribut."""
    FLAT = 0
    ROUND = 1
    SQUARE = 2
    POINTED = 3


class JoinStyle(IntEnum):
    """Spojení čar v rohu. Mapuje OMAP join_style atribut."""
    BEVEL = 0
    MITER = 1
    ROUND = 2


# --- Barvy ---

@dataclass
class Color:
    """
    Jedna barva v <colors> sekci OMAP souboru.

    OOM používá CMYK jako autoritativní (kvůli tisku map), RGB je derivovaný
    pro zobrazení na obrazovce. Pro detektor v rasteru nás zajímá hlavně RGB.

    priority = index do colors[] seznamu, používá se jako reference
    z <line_symbol color="N">, <area_symbol inner_color="N"> apod.
    """
    priority: int          # OMAP atribut "priority", používá se jako reference
    name: str              # např. "Brown", "Green 50%"
    # CMYK složky (0.0-1.0)
    c: float
    m: float
    y: float
    k: float
    # RGB složky (0.0-1.0) — derivované z CMYK nebo spot color
    r: float
    g: float
    b: float
    opacity: float = 1.0
    # Spot color name (PMS apod.) — pokud OOM používá pojmenované složky pro tisk.
    # Optional[str] = "str nebo None" (Python 3.9+ ekvivalent str | None).
    spot_color_name: Optional[str] = None

    @property
    def rgb_tuple(self) -> tuple[int, int, int]:
        """RGB v 0-255 (pro OpenCV / PIL). Hodí se pro detektor."""
        return (int(self.r * 255), int(self.g * 255), int(self.b * 255))


# --- Symboly ---

@dataclass(kw_only=True)
class SymbolBase:
    """
    Společný základ pro všechny typy symbolů.

    kw_only=True znamená, že podtřídy musí předávat parametry pojmenovaně.
    Bez toho by Python nedovolil přidat fieldy bez defaultu do podtříd
    (klasický dataclass inheritance problem).
    """
    id: int                # OMAP atribut "id", interní pořadové číslo v souboru
    code: str              # ISOM kód jako string, např. "101", "106.1", "528.1"
    name: str              # lidsky čitelný název, např. "Contour", "Earth bank"
    type: SymbolType
    description: str = ""  # z <description> child elementu, může být prázdný


@dataclass(kw_only=True)
class LineSymbol(SymbolBase):
    """
    Liniový symbol (vrstevnice, plot, cesta, mez, ...).

    Klíčové atributy pro detektor:
    - color_ref: index do SymbolLibrary.colors → určí barvu v rasteru
    - line_width: tloušťka v OMAP units (mikrometry); detektor potřebuje
      vědět, jak silnou čáru hledat
    - dashed + dash_length + break_length: vzor čárkování (důležité pro
      rozlišení např. plné vrstevnice vs form line — obě hnědé, ale form line je čárkovaná)
    - has_mid_symbol: některé linie mají uprostřed body/značky (Earth wall má tečku, plot má svislici)
    """
    color_ref: int = NO_COLOR
    line_width: int = 0                # v OMAP units
    minimum_length: int = 0
    join_style: JoinStyle = JoinStyle.BEVEL
    cap_style: CapStyle = CapStyle.FLAT
    dashed: bool = False
    dash_length: int = 0
    break_length: int = 0
    segment_length: int = 0
    # Příznaky existence sub-symbolů (start / mid / end).
    # MVP: zatím neukládáme jejich detail, jen víme, že existují.
    has_mid_symbol: bool = False
    has_start_symbol: bool = False
    has_end_symbol: bool = False
    # Fallback barva ze start/mid/end sub-symbolů (viz secondary_color_ref
    # poznámka u SymbolBase). Příklad: 110 Small erosion gully má color_ref=-1
    # a barvu jen v mid_symbol → point_symbol → inner_color="7" (Brown).
    secondary_color_ref: int = NO_COLOR


@dataclass(kw_only=True)
class PointSymbol(SymbolBase):
    """
    Bodový symbol (balvan, jáma, malý kopeček, kámen, ...).

    Geometrii jednotlivých elementů (souřadnice tvarů) zatím neukládáme.
    Pro detektor nám stačí: barva, rozměr (inner_radius), počet elementů
    (komplexita tvaru) a rotatable (může být v rasteru rotovaný?).
    """
    rotatable: bool = False
    inner_radius: int = 0
    inner_color_ref: int = NO_COLOR
    outer_width: int = 0
    outer_color_ref: int = NO_COLOR
    elements_count: int = 0           # počet <element> uzlů uvnitř
    # Fallback barva z <element> sub-symbolů (line/area/point uvnitř bodového
    # symbolu). Příklad: 115 Small depression má inner_color=-1 a barvu jen
    # v element → line_symbol color="7" (Brown).
    secondary_color_ref: int = NO_COLOR


@dataclass(kw_only=True)
class AreaSymbol(SymbolBase):
    """
    Plošný symbol (pasečina, otevřený prostor, jezero, ...).

    Klíčové: inner_color_ref je výplňová barva (typická detekce po
    color separation), patterns_count > 0 znamená, že plocha má vzor
    (tečky, šrafy) — to vyžaduje texturovou analýzu, ne jen barevnou.
    """
    inner_color_ref: int = NO_COLOR
    min_area: int = 0
    patterns_count: int = 0           # počet <pattern> uzlů (vzorová výplň)
    # Fallback barva z <pattern> sub-elementů. Příklad: 407 Undergrowth má
    # inner_color=-1 a barvu jen v <pattern color="17"> (Green šrafa).
    # Pro pattern type=2 (point pattern) se barva čte z vnořeného
    # <point_symbol>/<line_symbol> uvnitř patternu.
    secondary_color_ref: int = NO_COLOR


@dataclass(kw_only=True)
class TextSymbol(SymbolBase):
    """
    Textový symbol (čísla kontrol, popisky, jména objektů).

    Pro detektor: textové prvky jsou jiná disciplína (OCR) — zatím jen
    víme, že existují a jakou mají barvu/font.
    """
    color_ref: int = NO_COLOR
    font_family: str = ""
    font_size: int = 0
    rotatable: bool = False


@dataclass(kw_only=True)
class CombinedSymbol(SymbolBase):
    """
    Kombinovaný symbol = N sub-symbolů zobrazených současně.

    Příklad: hlavní silnice = široká hnědá výplň + tenké černé okraje =
    dva line_symbols slepené do jednoho conceptuálního symbolu.

    parts: seznam ID sub-symbolů (odkazy na jiné Symbol instance v knihovně).
    """
    parts: list[int] = field(default_factory=list)


# --- Kontejner ---

@dataclass
class SymbolLibrary:
    """
    Kompletní symbolová databáze načtená z jednoho OMAP souboru.

    scale: měřítko mapy z <georeferencing scale="..."> (např. 10000 = 1:10000).
    colors: indexované podle priority (colors[0] = priority 0).
    symbols: všechny symboly libovolného typu v jednom seznamu — index je
             pořadí v souboru (rovná se SymbolBase.id).
    """
    scale: int                         # např. 10000 pro 1:10 000
    colors: list[Color] = field(default_factory=list)
    symbols: list[SymbolBase] = field(default_factory=list)

    def get_color(self, ref: int) -> Optional[Color]:
        """
        Vrátí barvu podle reference (priority index), nebo None pokud ref=-1
        nebo mimo rozsah. NO_COLOR (-1) znamená transparentní/žádná barva.
        """
        if ref == NO_COLOR or ref < 0 or ref >= len(self.colors):
            return None
        return self.colors[ref]

    def symbols_by_type(self, symbol_type: SymbolType) -> list[SymbolBase]:
        """Filtr: všechny symboly daného typu (point/line/area/text/combined)."""
        return [s for s in self.symbols if s.type == symbol_type]

    def find_by_code(self, code: str) -> Optional[SymbolBase]:
        """Najdi symbol podle ISOM kódu (např. '101' = Contour)."""
        # next() s default None vrátí první match nebo None
        return next((s for s in self.symbols if s.code == code), None)
