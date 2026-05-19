"""
Stage 3 / krok 2: connected components + klasifikace na LINE/AREA/POINT.

Vstup: vyčištěné per-category binární masky (z morphology.py).
Cíl: rozdělit každou masku na tři sub-masky podle typu objektu:

- POINT: malé kompaktní komponenty (body, balvany, jámy, čísla kontrol)
- LINE:  protáhlé/řídké komponenty (vrstevnice, cesty, ploty, potoky)
- AREA:  velké kompaktní komponenty (plochy zeleně, žluté, vodní plochy)

Heuristika klasifikace per komponenta:

    area     = počet 255 pixelů v komponentě
    w, h     = rozměry bounding boxu
    density  = area / (w * h) — jak moc komponenta vyplňuje svůj bbox.
               Plocha má density typicky > 0.5, linie < 0.3.

    if area < MIN_AREA                                          → NOISE
    elif area <= POINT_MAX_AREA                                  \
         AND density >= POINT_MIN_DENSITY                        \
         AND aspect_ratio <= POINT_MAX_ASPECT                    → POINT
    elif density >= AREA_MIN_DENSITY                             → AREA
    else                                                         → LINE

POINT vyžaduje **smallness AND compactness AND kulatý/čtvercový tvar** —
trojí podmínka. Bez aspect_ratio testu propadají úzké fragmenty s bboxem
typu 8x2 (density 0.5, vypadají kompaktně, ale jsou protáhlé). Skutečné
body (kruhy, tečky, X-značky) mají aspect ratio blízko 1.

Pro Stage 3 MVP používáme jednu sadu thresholdů pro všechny kategorie.
Per-category tuning přijde, až uvidíme reálné statistiky z forest sample.

WHITE kategorie (pozadí / open forest) se přeskakuje úplně — viz split_category_masks().
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

from color_category import ColorCategory


class ComponentType(Enum):
    """Typ topologické struktury objektu v rastru."""
    POINT = "point"   # malá kompaktní komponenta
    LINE = "line"     # protáhlá nebo řídká komponenta
    AREA = "area"     # velká kompaktní komponenta


# --- Thresholdy klasifikace ---
# Hodnoty kalibrované pro forest sample (631x478 px, ~300 DPI render).
# Pro jiná rozlišení bude třeba přepočítat (nebo škálovat lineárně dle DPI).

# Pixely pod tímto = šum po morfologii (izolované 1-3 pixelové artefakty).
# Při 2x2 opening v Stage 3.1 by tohle už nemělo existovat, ale safety net.
MIN_AREA: int = 4

# Komponenta s plochou ≤ POINT_MAX_AREA může být POINT — ale jen pokud je
# zároveň kompaktní (density >= POINT_MIN_DENSITY). Bez density testu by
# 15-pixelový fragment protáhlé vrstevnice byl mylně klasifikován jako POINT.
# 30 px ≈ kruh průměru 6 px = typická tečka v rendered mapě.
POINT_MAX_AREA: int = 30

# POINT musí být i kompaktní (ne dlouhý úzký fragment). 0.4 = mírnější
# než AREA_MIN_DENSITY: tečky vykreslené anti-aliasingem mívají density
# kolem 0.5-0.8, ale fragmenty vrstevnic (bbox 12x3) mají 0.2-0.4 → LINE.
POINT_MIN_DENSITY: float = 0.4

# POINT musí být i kulatý/čtvercový (aspect ratio bboxu blízko 1).
# 2.0 = bbox max 2x delší v jednom směru. Bod symbol (kruh) má 1.0,
# X-značka cca 1.0-1.2, fragment vrstevnice 3-10 (úzký a dlouhý) → LINE.
POINT_MAX_ASPECT: float = 2.0

# AREA má density bbox výplně ≥ tato hodnota. 0.5 = polovina bboxu plná.
# Linie (vrstevnice) mívá density 0.05-0.15 (tenká čára v dlouhém bboxu).
# Plocha (les) mívá 0.7-1.0.
AREA_MIN_DENSITY: float = 0.5


@dataclass(frozen=True)
class ComponentInfo:
    """
    Metadata jedné komponenty. Užitečné pro debugging a stats.

    Souřadnice ve formátu OpenCV: (x, y) = (sloupec, řádek), origin top-left.
    """
    label: int          # ID komponenty (1..N, 0 je pozadí)
    x: int              # bbox left
    y: int              # bbox top
    w: int              # bbox width
    h: int              # bbox height
    area: int           # pixel count komponenty
    cx: float           # centroid x
    cy: float           # centroid y

    @property
    def density(self) -> float:
        """area / (w * h) — pokud je bbox nulový, vrátíme 0 (degenerated case)."""
        bbox_area = self.w * self.h
        if bbox_area == 0:
            return 0.0
        return self.area / bbox_area

    @property
    def aspect_ratio(self) -> float:
        """
        max(w, h) / min(w, h) — 1.0 = čtverec, >2.0 = výrazně protáhlé.

        Pro klasifikaci "kulatosti" objektu — bod má aspekt ~1, fragment linie
        ~3-10. Pokud je min(w, h) = 0 (degenerated případ 0-dimensional bbox),
        vrátíme infinity = "maximálně protáhlé".
        """
        small = min(self.w, self.h)
        if small == 0:
            return float("inf")
        return max(self.w, self.h) / small


def classify_component(info: ComponentInfo) -> ComponentType | None:
    """
    Klasifikuje jednu komponentu podle thresholdů.

    Returns:
        ComponentType nebo None pro NOISE (komponenta příliš malá → zahodit).
    """
    if info.area < MIN_AREA:
        return None
    # POINT = malý + kompaktní + kulatý/čtvercový. Trojí podmínka.
    # Protáhlé fragmenty linií propadnou níž (aspect_ratio test).
    if (
        info.area <= POINT_MAX_AREA
        and info.density >= POINT_MIN_DENSITY
        and info.aspect_ratio <= POINT_MAX_ASPECT
    ):
        return ComponentType.POINT
    if info.density >= AREA_MIN_DENSITY:
        return ComponentType.AREA
    return ComponentType.LINE


def extract_components(
    mask: np.ndarray,
) -> tuple[np.ndarray, list[ComponentInfo]]:
    """
    Najde connected components v binární masce.

    Args:
        mask: binární maska (H, W) uint8 0/255.

    Returns:
        labels: ndarray (H, W) int32 — pro každý pixel label komponenty
                (0 = pozadí, 1..N = komponenty).
        infos:  list ComponentInfo pro labels 1..N (pozadí vynecháno).

    Používá cv2.connectedComponentsWithStats s 8-konektivitou
    (sousedi i diagonálně) — pro orienťácké linie je důležité, aby
    šikmé tenké čáry nezůstaly rozsekané po pixelech.
    """
    # connectivity=8 = 8-sousední (vč. diagonál). 4 by drobilo šikmé linie.
    # ltype=CV_32S = int32 labels (uint16 by mohl přetéct u velkých map).
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8, ltype=cv2.CV_32S
    )

    infos: list[ComponentInfo] = []
    # Label 0 je pozadí — preskočit. Iterace 1..num_labels-1.
    for label in range(1, num_labels):
        # stats má sloupce: LEFT, TOP, WIDTH, HEIGHT, AREA (přes constanty cv2.CC_STAT_*).
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])
        cx, cy = centroids[label]
        infos.append(
            ComponentInfo(
                label=label,
                x=x, y=y, w=w, h=h, area=area,
                cx=float(cx), cy=float(cy),
            )
        )
    return labels, infos


def split_by_type(
    mask: np.ndarray,
    labels: np.ndarray,
    infos: list[ComponentInfo],
) -> dict[ComponentType, np.ndarray]:
    """
    Z původní masky vyrobí 3 sub-masky podle klasifikace komponent.

    Args:
        mask: původní binární maska (H, W) uint8.
        labels: výstup z extract_components (H, W) int32.
        infos: list komponent.

    Returns:
        dict {ComponentType → mask (H,W) uint8 0/255}.
        Vždy obsahuje všechny tři klíče (POINT, LINE, AREA), i kdyby byly prázdné.
    """
    h, w = mask.shape
    # Inicializace prázdných masek pro všechny tři typy.
    # Iniciálně všechno nuly, plníme labely jen u příslušného typu.
    out: dict[ComponentType, np.ndarray] = {
        ComponentType.POINT: np.zeros((h, w), dtype=np.uint8),
        ComponentType.LINE: np.zeros((h, w), dtype=np.uint8),
        ComponentType.AREA: np.zeros((h, w), dtype=np.uint8),
    }

    # Pro rychlost: vytvoříme lookup table label → component_type (nebo None pro NOISE).
    # Pak iterujeme pixely / pole jen jednou.
    # Větší rychlost než per-component cv2.compare — využije numpy vectorization.
    max_label = max((i.label for i in infos), default=0)
    # Tabulka indexovaná labelem. Hodnota = 0 (nepoužít), 1=POINT, 2=LINE, 3=AREA.
    # Pozadí (label 0) má hodnotu 0 → nezapíše se nikam.
    lut = np.zeros(max_label + 1, dtype=np.uint8)
    for info in infos:
        ctype = classify_component(info)
        if ctype is None:
            continue  # NOISE — zůstane 0 v LUT, nevejde do žádného výstupu.
        # Mapování enum → int 1/2/3 pro masku.
        code = {ComponentType.POINT: 1, ComponentType.LINE: 2, ComponentType.AREA: 3}[ctype]
        lut[info.label] = code

    # Aplikuj LUT: pro každý pixel zjistíme typ a zapíšeme 255 do správné masky.
    # type_map[i,j] = kód typu komponenty na pixelu (0=žádný, 1/2/3).
    type_map = lut[labels]

    out[ComponentType.POINT][type_map == 1] = 255
    out[ComponentType.LINE][type_map == 2] = 255
    out[ComponentType.AREA][type_map == 3] = 255
    return out


@dataclass
class CategoryComponentStats:
    """Stats pro jednu kategorii — počty komponent per typ."""
    category: ColorCategory
    total: int       # celkový počet komponent (před filtrováním šumu)
    noise: int       # zahozeno jako šum (area < MIN_AREA)
    points: int
    lines: int
    areas: int


def split_category_masks(
    category_masks: dict[ColorCategory, np.ndarray],
) -> tuple[
    dict[ColorCategory, dict[ComponentType, np.ndarray]],
    list[CategoryComponentStats],
]:
    """
    Pro každou kategorii: najde komponenty, klasifikuje, rozdělí masku.

    WHITE kategorie se vynechá — je to pozadí / open forest, který nemá
    smysl rozdělovat na POINT/LINE/AREA komponenty. Render PNG ji rozseká
    do podlouhlých "negativních" komponent (bbox skoro celý obraz s nízkou
    výplní) → falešné LINE detekce. Pokud se v budoucnu objeví potřeba
    detekovat open forest jako AREA symbol, řeší se to separátním krokem.

    Returns:
        per_category: vnořený dict {category → {type → mask}}.
        stats: list CategoryComponentStats — kolik komponent kde.
    """
    per_category: dict[ColorCategory, dict[ComponentType, np.ndarray]] = {}
    all_stats: list[CategoryComponentStats] = []

    for category, mask in category_masks.items():
        # Skip WHITE — viz docstring.
        if category == ColorCategory.WHITE:
            continue
        labels, infos = extract_components(mask)
        split = split_by_type(mask, labels, infos)
        per_category[category] = split

        # Statistika — počty per typ.
        noise = 0
        points = 0
        lines = 0
        areas = 0
        for info in infos:
            ctype = classify_component(info)
            if ctype is None:
                noise += 1
            elif ctype == ComponentType.POINT:
                points += 1
            elif ctype == ComponentType.LINE:
                lines += 1
            elif ctype == ComponentType.AREA:
                areas += 1

        all_stats.append(
            CategoryComponentStats(
                category=category,
                total=len(infos),
                noise=noise,
                points=points,
                lines=lines,
                areas=areas,
            )
        )

    return per_category, all_stats


def save_split_masks(
    per_category: dict[ColorCategory, dict[ComponentType, np.ndarray]],
    output_dir: Path,
) -> None:
    """
    Uloží split masky. Jméno: cat_<color>_<type>.png.

    Příklad: cat_brown_line.png, cat_green_area.png.
    Prázdné masky (žádné komponenty daného typu) se taky uloží — pro úplnost
    a snadnou kontrolu, že daná kombinace prostě neexistuje.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for category, type_masks in per_category.items():
        for ctype, mask in type_masks.items():
            filename = f"cat_{category.value}_{ctype.value}.png"
            cv2.imwrite(str(output_dir / filename), mask)


def format_components_report(stats: list[CategoryComponentStats]) -> str:
    """Textový report počtů komponent per kategorie/typ."""
    lines = [
        f"{'Kategorie':<10s}  {'Celkem':>7s}  {'Šum':>5s}  "
        f"{'Body':>5s}  {'Linie':>6s}  {'Plochy':>7s}"
    ]
    # Sort podle celkového počtu komponent (descending) — dominantní kategorie nahoru.
    for s in sorted(stats, key=lambda x: x.total, reverse=True):
        lines.append(
            f"{s.category.value:<10s}  "
            f"{s.total:>7,}  "
            f"{s.noise:>5,}  "
            f"{s.points:>5,}  "
            f"{s.lines:>6,}  "
            f"{s.areas:>7,}"
        )
    return "\n".join(lines)
