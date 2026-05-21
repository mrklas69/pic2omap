"""
build_dataset — tiling reálných (PNG, .omap) párů na dlaždice pro ML segmentaci ploch.

Komponenta #2 ML pilotu. Produkuje DETERMINISTICKÉ dlaždice (image + mask) + manifest.
Augmentace zde NENÍ — patří na trénink (on-the-fly v albumentations, víc diverzity,
menší dataset). Builder běží na CPU (tady), trénink na GPU ("mrkla").

Split bez leakage (dlaždice ze stejné mapy nesmí být v train i val zároveň): pilot
dělí Slovanku PROSTOROVĚ (horní pás = train, spodní = within-domain val, mezi nimi
gap), Garching jde celý do `test` (cross-domain). Forest (malý, bbox-fit) vynechán.

Výstup:
    output/dataset/<split>/images/<map>_y_x.png   (RGB dlaždice)
    output/dataset/<split>/masks/<map>_y_x.png    (uint8 class indexy)
    output/dataset/manifest.json                  (split, class distribuce, seznam dlaždic)

Použití:
    python build_dataset.py                 # default konfig (DATASET_MAPS)
    python build_dataset.py --tile 512 --stride 512 --out output/dataset
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from cli_utils import force_utf8_console
from omap_mask import NUM_CLASSES, CLASS_NAMES, build_area_mask

# Defaulty spatial splitu (single source of truth — DATASET_MAPS i _tile_split).
DEFAULT_VAL_FRAC = 0.25   # spodní podíl výšky → val
DEFAULT_GAP_FRAC = 0.05   # pás mezi train/val zahozen (proti leakage na hranici)

# Konfigurace zdrojových map. pgw_width = šířka PNG, ke které .pgw patří (kvůli
# škálování, když rasterizujeme na downscale render).
#
# split:
#   "spatial" → mapu rozdělit prostorově: horní pás = train, spodní = val,
#               mezi nimi gap (proti leakage na hranici). Within-domain val =
#               čistý signál "učí se model?" (Slovanka — jediná velká lesní mapa).
#   "test"    → celá mapa do "test" splitu (cross-domain stress test, jiná doména).
DATASET_MAPS: list[dict] = [
    {
        "name": "Slovanka2016",
        "omap": "resources/Slovanka2016.omap",
        "png": "resources/Slovanka2016.png",      # full 14094x10158
        "pgw": "resources/Slovanka2016.pgw",
        "pgw_width": 14094,
        "split": "spatial",
        "val_frac": DEFAULT_VAL_FRAC,   # spodních 25 % výšky = val
        "gap_frac": DEFAULT_GAP_FRAC,   # 5 % pás mezi train/val zahozen (žádný overlap leakage)
    },
    {
        "name": "Garching",
        "omap": "resources/complete map.omap",
        "png": "resources/complete map.png",       # 2480x3508 (sprint = jiná doména)
        "pgw": "resources/complete map.pgw",
        "pgw_width": 2480,
        "split": "test",
    },
]


def _tile_split(cfg: dict, y: int, tile: int, h: int) -> str | None:
    """Určí split dlaždice. Pro 'spatial' podle y (train horní / gap / val spodní)."""
    if cfg["split"] != "spatial":
        return cfg["split"]
    val_min = h * (1 - cfg.get("val_frac", DEFAULT_VAL_FRAC))
    train_max = val_min - h * cfg.get("gap_frac", DEFAULT_GAP_FRAC)
    if y + tile <= train_max:
        return "train"
    if y >= val_min:
        return "val"
    return None  # gap pás → zahodit

# Dlaždice s méně než tímto podílem "inkoustu" (ne-bílých pixelů) jsou mimo mapu
# nebo prázdný okraj → zahodit. Bílý průchodný les uvnitř mapy projde, protože
# je obklopen čarami/plochami (málokdy je celá 512px dlaždice čistě bílá uvnitř).
MIN_INK_FRACTION = 0.05
# Pixel je "bílý" (papír/pozadí), pokud všechny kanály >= tohle.
WHITE_THRESHOLD = 245


def _tile_positions(dim: int, tile: int, stride: int) -> list[int]:
    """Počáteční souřadnice dlaždic v jedné ose; poslední zarovnaná na kraj (pokryje okraj)."""
    if dim <= tile:
        return [0]
    pos = list(range(0, dim - tile + 1, stride))
    if pos[-1] != dim - tile:
        pos.append(dim - tile)
    return pos


def _ink_fraction(tile_bgr: np.ndarray) -> float:
    """Podíl ne-bílých (inkoustových) pixelů v dlaždici."""
    white = np.all(tile_bgr >= WHITE_THRESHOLD, axis=2)
    return 1.0 - float(white.mean())


def _class_px(mask_tile: np.ndarray) -> dict[int, int]:
    """Per-class počet pixelů v dlaždici (jen třídy > 0; pozadí dopočitatelné)."""
    return {c: int((mask_tile == c).sum()) for c in range(1, NUM_CLASSES) if (mask_tile == c).any()}


def _accumulate(into: dict[int, int], add: dict[int, int]) -> None:
    for c, n in add.items():
        into[c] = into.get(c, 0) + n


def build(out_dir: Path, tile: int, stride: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_tiles: list[dict] = []
    split_stats: dict[str, dict] = {}

    for cfg in DATASET_MAPS:
        png = cv2.imread(cfg["png"])
        if png is None:
            print(f"  [skip] nelze načíst {cfg['png']}")
            continue
        h, w = png.shape[:2]
        pgw = Path(cfg["pgw"]) if cfg.get("pgw") else None
        mask, mstats = build_area_mask(Path(cfg["omap"]), w, h, pgw, cfg.get("pgw_width"))

        kept: dict[str, int] = {}
        skipped_ink = skipped_gap = 0
        for y in _tile_positions(h, tile, stride):
            split = _tile_split(cfg, y, tile, h)
            if split is None:
                skipped_gap += 1
                continue
            for x in _tile_positions(w, tile, stride):
                img_t = png[y:y + tile, x:x + tile]
                if _ink_fraction(img_t) < MIN_INK_FRACTION:
                    skipped_ink += 1
                    continue
                msk_t = mask[y:y + tile, x:x + tile]
                img_dir = out_dir / split / "images"
                msk_dir = out_dir / split / "masks"
                img_dir.mkdir(parents=True, exist_ok=True)
                msk_dir.mkdir(parents=True, exist_ok=True)
                stem = f"{cfg['name']}_{y}_{x}"
                cv2.imwrite(str(img_dir / f"{stem}.png"), img_t)
                cv2.imwrite(str(msk_dir / f"{stem}.png"), msk_t)
                cpx = _class_px(msk_t)
                ss = split_stats.setdefault(split, {"maps": set(), "num_tiles": 0, "class_px": {}})
                ss["maps"].add(cfg["name"])
                ss["num_tiles"] += 1
                _accumulate(ss["class_px"], cpx)
                manifest_tiles.append({
                    "id": stem, "map": cfg["name"], "split": split,
                    "x": x, "y": y, "tile": tile,
                    "image": f"{split}/images/{stem}.png",
                    "mask": f"{split}/masks/{stem}.png",
                    "class_px": cpx,
                })
                kept[split] = kept.get(split, 0) + 1
        kept_str = ", ".join(f"{s}:{n}" for s, n in kept.items()) or "0"
        print(f"  {cfg['name']:14} ({w}x{h}): {kept_str} "
              f"(skip ink:{skipped_ink} gap:{skipped_gap}), georef: {mstats['georef']}")

    # Sety map → seřazené listy (JSON-serializovatelné).
    for ss in split_stats.values():
        ss["maps"] = sorted(ss["maps"])
    manifest = {
        "tile_size": tile, "stride": stride, "num_classes": NUM_CLASSES,
        "class_names": {0: "background", **CLASS_NAMES},
        "splits": split_stats, "tiles": manifest_tiles,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== dataset → {out_dir} ===")
    for split, ss in split_stats.items():
        tot = sum(ss["class_px"].values()) or 1
        print(f"  [{split}] mapy={ss['maps']} dlaždic={ss['num_tiles']}")
        for c, n in sorted(ss["class_px"].items(), key=lambda t: -t[1]):
            print(f"      {c} {CLASS_NAMES.get(c, '?'):8} {n:>13,} px ({100*n/tot:5.1f} % plochy)")
    print(f"  manifest:          {out_dir / 'manifest.json'}")


def main() -> None:
    force_utf8_console()
    ap = argparse.ArgumentParser(description="Tiling (PNG, .omap) párů na ML dataset.")
    ap.add_argument("--tile", type=int, default=512, help="velikost dlaždice (px)")
    ap.add_argument("--stride", type=int, default=512, help="krok mezi dlaždicemi (px)")
    ap.add_argument("--out", default="output/dataset", help="výstupní adresář")
    args = ap.parse_args()
    build(Path(args.out), args.tile, args.stride)


if __name__ == "__main__":
    main()
