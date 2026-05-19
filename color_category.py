"""
Sémantické rodiny barev pro orienťácké mapy.

Problém: OMAP soubory mají často 20-40 barev, ale mnoho z nich jsou
odstíny / "knockout" varianty stejné základní barvy (Brown, Brown 50%,
OpenOrienteering Orange všechny patří k vrstevnicím = BROWN family).

Při color separation v rasteru se anti-aliased pixely rozsekají mezi
blízké palette barvy → vrstevnice se ztrácí. Sloučení do rodin to opraví.

Klasifikace: HSV hue (robustní k jasu), s fallbackem na BLACK/WHITE/GRAY
podle saturace a value. OpenCV používá rozsah H ∈ [0, 179] (ne [0, 360]).
"""

from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np

from color_profile import ColorProfile


class ColorCategory(Enum):
    """
    Sémantické rodiny barev v orienťáckých mapách (ISOM/ISSprOM).
    Hodnoty jsou stringy pro snadnou serializaci (file names, JSON).
    """
    BLACK = "black"      # linie (cesty, ploty, balvany, čísla)
    WHITE = "white"      # pozadí, průchodný les
    GRAY = "gray"        # bare rock, někdy Black 30%
    BROWN = "brown"      # vrstevnice, form lines, earth banks, OOM Orange
    YELLOW = "yellow"    # otevřená země, polonotevřená
    GREEN = "green"      # vegetace všech hustot
    BLUE = "blue"        # voda, mokřady
    PURPLE = "purple"    # kurz, kontroly, OOB
    RED = "red"          # loga, varovné značky (zřídka)


# --- Thresholdy pro klasifikaci ---
# Saturace pod tímto = barva je "bezbarvá" (BLACK/WHITE/GRAY podle value).
# OpenCV S ∈ [0, 255]. 40 = ~16% saturace.
SATURATION_THRESHOLD: int = 40

# Value (jas) hranice pro bezbarvé pixely.
# V < DARK → BLACK, V > LIGHT → WHITE, jinak → GRAY.
VALUE_DARK_THRESHOLD: int = 64    # ~25% jasu = tmavé
VALUE_LIGHT_THRESHOLD: int = 220  # ~86% jasu = světlé

# Hue hranice pro chromatic barvy. OpenCV H ∈ [0, 179] (ne 0-360).
# Intervaly jsou [low, high) tzn. low <= h < high.
# RED má wrap-around (vysoký hue + nízký hue).
HUE_BROWN: tuple[int, int] = (3, 16)     # ~6-32° v 360-stupňové škále
HUE_YELLOW: tuple[int, int] = (16, 32)   # ~32-64°
HUE_GREEN: tuple[int, int] = (32, 87)    # ~64-174°
HUE_BLUE: tuple[int, int] = (87, 130)    # ~174-260°
HUE_PURPLE: tuple[int, int] = (130, 160) # ~260-320°
# RED: hue ≥ 160 OR hue < 3 (wrap-around přes 0)


def classify_rgb(r: int, g: int, b: int) -> ColorCategory:
    """
    Klasifikuje jednu RGB barvu do sémantické rodiny.

    Postup:
    1. Převést RGB → HSV pomocí OpenCV (1x1 pixel triky).
    2. Pokud saturace < threshold → bezbarvá (BLACK/WHITE/GRAY podle value).
    3. Jinak podle hue do barevné rodiny.

    Args:
        r, g, b: kanály 0-255

    Returns:
        ColorCategory pro tuto barvu.
    """
    # OpenCV BGR→HSV očekává 3D ndarray, takže build single-pixel.
    # cv2 očekává BGR pořadí pro COLOR_BGR2HSV.
    pixel_bgr = np.array([[[b, g, r]]], dtype=np.uint8)
    hsv = cv2.cvtColor(pixel_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[0, 0]
    h, s, v = int(h), int(s), int(v)

    # Bezbarvé barvy: rozhoduje jen value.
    if s < SATURATION_THRESHOLD:
        if v < VALUE_DARK_THRESHOLD:
            return ColorCategory.BLACK
        if v > VALUE_LIGHT_THRESHOLD:
            return ColorCategory.WHITE
        return ColorCategory.GRAY

    # Chromatic: rozhoduje hue.
    # RED má wrap-around — vysoký hue NEBO velmi nízký hue.
    if h >= 160 or h < HUE_BROWN[0]:
        return ColorCategory.RED
    if HUE_BROWN[0] <= h < HUE_BROWN[1]:
        return ColorCategory.BROWN
    if HUE_YELLOW[0] <= h < HUE_YELLOW[1]:
        return ColorCategory.YELLOW
    if HUE_GREEN[0] <= h < HUE_GREEN[1]:
        return ColorCategory.GREEN
    if HUE_BLUE[0] <= h < HUE_BLUE[1]:
        return ColorCategory.BLUE
    if HUE_PURPLE[0] <= h < HUE_PURPLE[1]:
        return ColorCategory.PURPLE

    # Fallback — sem by se nemělo dostat, ale pro safety.
    return ColorCategory.GRAY


def classify_profile(profile: ColorProfile) -> ColorCategory:
    """Klasifikuje ColorProfile do rodiny (wrapper nad classify_rgb)."""
    return classify_rgb(*profile.rgb)


def build_category_map(profiles: list[ColorProfile]) -> dict[int, ColorCategory]:
    """
    Pro celý seznam profiles vrátí mapování priority → ColorCategory.
    Klíč = ColorProfile.priority (stabilní identifier napříč pipeline).
    """
    return {prof.priority: classify_profile(prof) for prof in profiles}


# --- Manuální override ---
# Některé OMAP barvy mají hraniční hue a klasifikace je přiřadí "špatně"
# vůči naší sémantice. Override map: jméno barvy (case-insensitive, partial
# match) → cílová kategorie. Aplikuje se po automatické klasifikaci.
#
# Pravidlo: pokud jméno barvy obsahuje klíč (lowercase substring match),
# přepíše se kategorie. První match vyhrává.
NAME_OVERRIDES: dict[str, ColorCategory] = {
    # "Green 50%, Yellow" má hue ~32 = právě na hranici GREEN/YELLOW.
    # Sémanticky je to světlá vegetace s nízkou hustotou (ISOM 407 Vegetation,
    # slow running, good visibility). Patří k GREEN family.
    "green 50%, yellow": ColorCategory.GREEN,

    # Brown 0-30% / Brown 20-50% pro paved area — světlé varianty Brown.
    # Hue je správný, ale nízká saturace by mohla skončit v GRAY.
    "brown 0-30%": ColorCategory.BROWN,
    "brown 20-50%": ColorCategory.BROWN,
}


def classify_profile_with_override(profile: ColorProfile) -> ColorCategory:
    """
    Klasifikace s aplikací NAME_OVERRIDES. Použij pro produkční pipeline,
    pure classify_profile pro debugging / testování heuristiky.
    """
    name_lower = profile.name.lower()
    for key, category in NAME_OVERRIDES.items():
        if key in name_lower:
            return category
    return classify_profile(profile)


def build_category_map_with_overrides(
    profiles: list[ColorProfile],
) -> dict[int, ColorCategory]:
    """Mapping priority → category s aplikovanými NAME_OVERRIDES."""
    return {
        prof.priority: classify_profile_with_override(prof)
        for prof in profiles
    }


@dataclass
class CategoryStats:
    """Statistika kategorie — kolik profiles do ní spadlo + souhrnný pixel count."""
    category: ColorCategory
    profile_priorities: list[int]    # priorities barev v této kategorii
    profile_names: list[str]         # jejich jména pro report


def group_profiles_by_category(
    profiles: list[ColorProfile],
    category_map: dict[int, ColorCategory],
) -> dict[ColorCategory, CategoryStats]:
    """
    Pro každou ColorCategory vrátí seznam ColorProfile, které do ní patří.
    Užitečné pro reporting a debug.
    """
    grouped: dict[ColorCategory, CategoryStats] = {}
    for prof in profiles:
        cat = category_map[prof.priority]
        if cat not in grouped:
            grouped[cat] = CategoryStats(
                category=cat,
                profile_priorities=[],
                profile_names=[],
            )
        grouped[cat].profile_priorities.append(prof.priority)
        grouped[cat].profile_names.append(prof.name)
    return grouped
