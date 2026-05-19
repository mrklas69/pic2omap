"""
Vrstva 2 nad SymbolLibrary: barevné profily pro detector.

Z OMAP Color (CMYK+RGB+spot) derivuje ColorProfile, který má precomputed
LAB hodnotu pro rychlé matchování v rasteru.

Proč LAB? RGB je vnímatelně nelineární — vzdálenost (R1,G1,B1)→(R2,G2,B2)
neodpovídá tomu, jak lidský zrak vidí podobnost barev. LAB (CIELAB) je
vnímatelně lineární: euklidovská vzdálenost ≈ vizuální podobnost.
OpenCV cv2.cvtColor(..., COLOR_RGB2LAB) na uint8 vstupu vrací LAB v rozsahu
L=[0,255], a=[0,255], b=[0,255] (OpenCV-specific scaling).
"""

from dataclasses import dataclass

import cv2
import numpy as np

from omap_model import Color, SymbolLibrary


@dataclass
class ColorProfile:
    """
    Barevný profil pro detector. Drží reference na původní Color z library
    plus precomputed LAB hodnotu (rychlé matchování v color separation).

    priority: stejné jako Color.priority — slouží jako stable identifier
              napříč pipeline (output masky pojmenované podle priority).
    """
    priority: int
    name: str
    rgb: tuple[int, int, int]    # (R, G, B) v 0-255
    lab: tuple[int, int, int]    # (L, a, b) v 0-255 (OpenCV scaling)

    @property
    def lab_array(self) -> np.ndarray:
        """LAB jako numpy array (3,) — pro vektorové operace."""
        return np.array(self.lab, dtype=np.float32)


def _rgb_to_lab_single(r: int, g: int, b: int) -> tuple[int, int, int]:
    """
    Převede jednu RGB hodnotu (0-255) na LAB pomocí OpenCV.

    OpenCV pracuje v BGR, ale convertColor s RGB2LAB očekává RGB.
    Vstup musí být 3D ndarray (1,1,3) uint8 — color conversion nepřijímá
    1D ani 2D. Výstup pak stejný shape, vezmeme pixel [0,0].
    """
    # Reshape na 1x1x3 RGB pixel
    pixel = np.array([[[r, g, b]]], dtype=np.uint8)
    lab_pixel = cv2.cvtColor(pixel, cv2.COLOR_RGB2LAB)
    # lab_pixel.shape = (1, 1, 3), bereme single pixel a převedeme na tuple
    l, a, b_lab = lab_pixel[0, 0]
    return (int(l), int(a), int(b_lab))


def color_to_profile(color: Color) -> ColorProfile:
    """Vytvoří ColorProfile z jednoho OMAP Color objektu."""
    rgb = color.rgb_tuple  # (R, G, B) v 0-255
    lab = _rgb_to_lab_single(*rgb)
    return ColorProfile(
        priority=color.priority,
        name=color.name,
        rgb=rgb,
        lab=lab,
    )


def build_color_profiles(library: SymbolLibrary) -> list[ColorProfile]:
    """
    Z celé SymbolLibrary vyrobí seznam ColorProfile, zachovává pořadí
    podle priority. priority je stable index — výstupní masky pojmenované
    podle priority budou napříč souboru konzistentní.
    """
    # List comprehension: pro každou barvu zavolej color_to_profile.
    # Pythonic ekvivalent ke smyčce s appendem.
    return [color_to_profile(c) for c in library.colors]


def deduplicate_by_rgb(profiles: list[ColorProfile]) -> list[ColorProfile]:
    """
    Některé OMAP soubory mají duplicitní barvy s různými priorities
    (např. complete map.omap má 4 různé "Blue" s identickým #21D1FF —
    knockout chaining pro tisk). Pro color separation je to redundance.

    Vrací jen unikátní RGB hodnoty, zachovává první výskyt (= nejnižší priority).
    """
    seen: set[tuple[int, int, int]] = set()
    unique: list[ColorProfile] = []
    for prof in profiles:
        if prof.rgb not in seen:
            seen.add(prof.rgb)
            unique.append(prof)
    return unique
