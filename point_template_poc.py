"""
PoC: diskriminativní template-matching detekce bodového symbolu (inspirováno bráškou).

Bráška hledal symbol VIZUÁLNĚ (Claude vision na zvětšených dlaždicích) a rozlišoval
tvar: 536 = T (vodorovná NAHOŘE), 537 Křížek = svislice i nad čárkou, budova = plný
blok. Plain cv2.matchTemplate na T tvar selhal (T generický → 157 kandidátů).

Tady to napodobíme algoritmicky DISKRIMINATIVNĚ:
    - foreground = T čáry (kde MÁ být černá),
    - forbidden = prstenec kolem T (kde MÁ být bílá) → penalizuje černé NAD vodorovnou
      (= kříž 537) a po STRANÁCH nohy (= plný blok / budova).
    skóre = (podíl foreground černé) − λ·(podíl forbidden černé).
Vysoké skóre jen když T přesně sedí A okolí je čisté — to rozliší 536 od look-alikes.

Self-kalibrace měřítka: forest DPI je nejisté (memory png-dpi-pitfalls), takže zkusíme
rozsah a vybereme scale s nejostřejším peakem.

Spuštění:  python point_template_poc.py 536
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np

from omap_parser import _tag


def parse_point_geometry(omap_path: Path, code: str):
    """Geometrie bodového symbolu: list (kind, coords[(x,y)], line_width) z OMAP."""
    root = ET.parse(omap_path).getroot()
    for sym in root.iter(_tag("symbol")):
        if sym.get("code") != code:
            continue
        ps = sym.find(_tag("point_symbol"))
        if ps is None:
            return None
        elements = []
        for el in ps.findall(_tag("element")):
            sub = el.find(_tag("symbol"))
            obj = el.find(_tag("object"))
            if sub is None or obj is None:
                continue
            body = list(sub)[0] if len(sub) else None
            kind = body.tag.split("}")[1] if body is not None else "?"
            lw = int(body.get("line_width", 0)) if body is not None else 0
            coords_el = obj.find(_tag("coords"))
            pts = []
            if coords_el is not None and coords_el.text:
                for a, b in re.findall(r"(-?\d+) (-?\d+)(?: \d+)?", coords_el.text):
                    pts.append((int(a), int(b)))
            elements.append((kind, pts, lw))
        return elements
    return None


def render_foreground(elements, scale: float, pad_px: int) -> np.ndarray:
    """Binární template (1 = symbol čáry) v daném měřítku (px/unit)."""
    all_pts = [p for _, pts, _ in elements for p in pts]
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    minx, miny = min(xs), min(ys)
    maxx, maxy = max(xs), max(ys)
    w = int(round((maxx - minx) * scale)) + 2 * pad_px + 1
    h = int(round((maxy - miny) * scale)) + 2 * pad_px + 1
    fg = np.zeros((h, w), dtype=np.uint8)

    def to_px(p):
        return (int(round((p[0] - minx) * scale)) + pad_px,
                int(round((p[1] - miny) * scale)) + pad_px)

    for kind, pts, lw in elements:
        thick = max(1, int(round(lw * scale)))
        if kind == "line_symbol":
            for i in range(len(pts) - 1):
                cv2.line(fg, to_px(pts[i]), to_px(pts[i + 1]), 1, thick)
    return fg


def discriminative_kernel(fg: np.ndarray, ring_px: int, lam: float) -> np.ndarray:
    """
    Signed kernel: foreground +1/n_fg, forbidden prstenec −λ/n_forbidden.

    Forbidden = dilatace fg mínus fg (těsné okolí, kde MÁ být bílo). Černé v něm
    (kříž nad vodorovnou, plný blok kolem nohy) skóre srazí.
    """
    kernel = np.ones((ring_px * 2 + 1, ring_px * 2 + 1), np.uint8)
    dil = cv2.dilate(fg, kernel, iterations=1)
    forbidden = (dil > 0) & (fg == 0)
    n_fg = int(fg.sum())
    n_fb = int(forbidden.sum())
    k = np.zeros(fg.shape, dtype=np.float32)
    if n_fg:
        k[fg > 0] = 1.0 / n_fg
    if n_fb:
        k[forbidden] = -lam / n_fb
    return k


def detect_scale(black01: np.ndarray, elements, dpi: int, lam: float):
    """Pro daný DPI vrať (skóre mapa, template_w, template_h)."""
    scale = dpi / 25400.0  # px/unit (unit = 1/1000 mm na papíře)
    pad = 3
    fg = render_foreground(elements, scale, pad)
    h, w = fg.shape
    ring = max(2, int(round(0.30 * w)))  # prstenec ~30 % šířky symbolu
    k = discriminative_kernel(fg, ring_px=ring, lam=lam)
    score = cv2.filter2D(black01, cv2.CV_32F, k, borderType=cv2.BORDER_CONSTANT)
    return score, w, h


def nms(peaks, min_dist):
    peaks = sorted(peaks, key=lambda p: -p[2])
    kept = []
    for x, y, s in peaks:
        if all((x - kx) ** 2 + (y - ky) ** 2 >= min_dist ** 2 for kx, ky, _ in kept):
            kept.append((x, y, s))
    return kept


def main():
    code = sys.argv[1] if len(sys.argv) > 1 else "536"
    omap = Path("resources/forest sample.omap")
    black = cv2.imdecode(
        np.frombuffer(Path("output/forest sample/category/cat_black.png").read_bytes(), np.uint8),
        cv2.IMREAD_GRAYSCALE,
    )
    black01 = (black > 0).astype(np.float32)

    elements = parse_point_geometry(omap, code)
    print(f"Symbol {code}: {len(elements)} elementů")
    for kind, pts, lw in elements:
        print(f"  {kind}: {pts} lw={lw}")

    lam = 1.0
    # Self-kalibrace: vyber DPI s nejvyšším top peakem (template nejlíp sedí).
    best = None
    for dpi in (140, 170, 200, 230, 260, 290, 320):
        score, tw, th = detect_scale(black01, elements, dpi, lam)
        top = float(score.max())
        print(f"  DPI {dpi}: template {tw}x{th}px, max score={top:.3f}")
        if best is None or top > best[0]:
            best = (top, dpi, score, tw, th)

    top, dpi, score, tw, th = best
    print(f"\nNejlepší škála: DPI {dpi} (max score {top:.3f})")
    # Peaky: relativně k top peaku (symboly téhož tvaru mají podobné skóre).
    thr = top * 0.80
    ys, xs = np.where(score >= thr)
    peaks = [(int(x), int(y), float(score[y, x])) for x, y in zip(xs, ys)]
    kept = nms(peaks, min_dist=max(6, tw))
    print(f"Kandidáti (score >= {thr:.3f} = 80 % top), po NMS: {len(kept)}")

    img = cv2.imread("resources/forest sample.png")
    h, w = black01.shape
    for i, (x, y, s) in enumerate(sorted(kept, key=lambda p: -p[2])):
        xloc, yloc = 10 * x / w, 10 * (1 - y / h)
        print(f"  {i+1}: px=({x},{y}) score={s:.3f}  xLoc={xloc:.1f} yLoc={yloc:.1f}")
        cv2.circle(img, (x, y), 11, (0, 0, 255), 2)
        cv2.putText(img, f"{i+1}", (x + 9, y - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    out = Path("output/forest sample/_tower_poc.png")
    cv2.imwrite(str(out), img)
    print(f"\nVykresleno -> {out}")


if __name__ == "__main__":
    main()
