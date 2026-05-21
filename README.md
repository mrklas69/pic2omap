# pic2omap

Raster orienteering map → OMAP vectorization (work in progress).

Experimental pipeline that takes a rendered orienteering map (PNG) and tries to
reconstruct a vector `.omap` file readable by [OpenOrienteering Mapper](https://www.openorienteering.org/).
The focus is on the gap left by existing tools — area symbols, point symbols, and
automatic mapping to ISOM / ISSprOM symbol sets. Color line vectorization is
already solved by [CoVe](https://github.com/lpechacek/cove) (integrated in OOM).

**Status: WIP, research-stage. Not yet a usable tool.**

## Architecture (sezení 6)

```
PNG → pic2db → output/<sample>/db/iter_N.json → db2omap → OMAP
```

- **pic2db** — raster → structured DB intermediate (annotative claiming, iterative).
- **db.json** — single source of truth about detected content. Editable, diff-able.
- **db2omap** — serialization DB → OMAP XML. PoC stage: contours + linear georef
  fit, symbols/colors/georef taken from a template OMAP. Not production geometry yet.

Canonical data model + CLI verbs: [`docs/db_schema.md`](docs/db_schema.md).

## Pipeline status

| # | Stage | Status |
|---|-------|--------|
| — | Ground truth metric (`compare_to_omap.py`) | ✓ |
| 1 | Preprocess (deskew, denoise) | ☐ |
| 2 | Color separation (palette-based, LAB nearest) | ✓ |
| 3 | Per-color raster ops (morphology, components, skeletonization) | ✓ |
| 4 | Symbol recognition — detectors | ☐ in progress |
| 5 | Vectorization (skeleton → polyline → Bezier) | ◐ PoC (contours only) |
| 6 | Topology fix | ☐ |
| 7 | Georeferencing | ◐ PoC (linear bbox fit) |
| 8 | OMAP XML serialization (`db2omap`) | ◐ PoC |

### Stage 4 detector status (sezení 8)

Detectors are template-aware — exact ISOM codes are resolved from the supplied
`--omap` library (forest sample `101`, Slovanka `101.0`). Area disambiguation
groups symbols by RGB and picks the base variant, because OMAP often has
RGB-identical pairs (`403.0` Rough open land ≡ `403.1` "Paseka na zelené") that
color separation cannot tell apart.

| Detector | Symbols | Result |
|---|---|---|
| `orientation_v1` | (step 0 — map rotation) | Slovanka 0.0° / forest fallback 0° |
| `brown_line_v1` | 101/102 (template-aware) | forest 112×101, 26×102 / Slovanka 1825×101.0, 98×102.0 |
| `area_v1` (GREEN) | 406/407/408 + default | forest 59 / Slovanka 1115 (766×406.1) |
| `area_v1` (YELLOW) | 401/403/404 + default | forest 26 / Slovanka 1482 (1182×403.0) |
| `area_v1` (BLACK) | 526 Building | forest 59 / Slovanka 448 (1.11× GT) |
| `area_v1` (GRAY) | 526.1 buildings (sezení 11) | Garching 241 buildings (gray fill, ISSprOM combined) |
| `point_v1` | 115/536/418 + template-aware default | forest 440 (brown 235/black 58/green 147) — over-claims, point bucket noise |

Sezení 11 additions: GRAY building detector + ISSprOM combined-code resolver
(`526.1.1` → combined `526.1`); `point_v1` (point bucket, over-claims — point
symbols drown in line fragments); discriminative template-matching PoC
(`point_template_poc.py` — finds both 536 towers top-3 from 226 fragments by
matching the exact T shape from OMAP geometry). Review tooling: `mark --by-type`
(3 images point/line/area), `compare_to_omap --db --csv-dir` (per-symbol GT↔DB
table + CSV exports).

## Detector metrics (forest sample, iter_1)

```
Symbol               Pic2db   GT    Ratio
101 Contour            112    51    2.20×   (over-segmented)
102 Index contour       26    15    1.73×   (+ contaminations)
406 default green       59    99    0.60×   (post stripe filter)
403 default yellow      26    26    1.00×   (exact match)
Total objects:         223
Claimed pixels:        8.3 %
```

Per-color category aggregates (Stage 3 vs OMAP ground truth, after secondary
color fallback added in sezení 5):

```
BROWN line ratio:  1.89x  (oversegmented contours — broken by black overlays)
BLACK line ratio:  0.63x  (paths joined at intersections)
GREEN area ratio:  1.24x  (near 1:1 after secondary-color fallback)
YELLOW area ratio: 0.83x  (areas joined across neighbour boundaries)
```

Secondary-color fallback (sezení 5): GT now also counts objects whose color
lives in `<pattern>` / `<mid_symbol>` / `<element>` sub-structures (e.g.
Undergrowth 407/409, Erosion gully 110, Depression 115, Vegetation
boundary 416). Without the fallback, 156 objects (~29 % of the map) were
being silently skipped.

## Repository layout

### Entry points
- `pic2db.py` — main CLI (`detect`, `list`, `mark --by-type/--scale`, `export` PoC; `diff` stub)
- `db2omap.py` — DB → OMAP serialization (PoC)
- `separate_demo.py` — Stage 2 (color separation)
- `stage3_demo.py` — Stage 3 (morphology + components + skeleton)
- `compare_to_omap.py` — ground truth metric (`--db` per-symbol table, `--csv-dir` review CSV)
- `dump_symbols.py` — symbol DB overview

### DB infrastructure
- `db_model.py` — `MapObject` / `NonMapElement` / `DBSnapshot` dataclasses + JSON I/O
- `cli_utils.py` — shared CLI helpers (UTF-8 console, `imread_unicode` for diacritic paths)

### Stage 2/3 pipeline
- `omap_model.py`, `omap_parser.py` — OMAP symbol DB (dataclass model + XML parser; `omap_tag`, `iter_map_objects`)
- `georef.py` — pixel ↔ OMAP coord transforms (rigorous `.pgw`+georef / bbox-fit fallback); shared by db2omap, omap_mask, compare_to_omap
- `color_profile.py`, `color_category.py` — color profiles + semantic families
- `color_separator.py` — palette-based LAB separation
- `morphology.py`, `components.py`, `skeleton.py` — Stage 3 ops

### Stage 4 detectors
- `brown_line_v1.py` — 101 / 102 (thickness peak)
- `area_v1.py` — solid fill areas (GREEN/YELLOW/BLACK/GRAY), parameterized by `ColorCategory`
- `point_v1.py` — point symbols via point bucket (size + aspect filter)
- `point_template_poc.py` — discriminative template matching PoC (shape from OMAP geometry)
- `orientation_v1.py` — map rotation from 601.x north lines
- `peak_visualizer.py` — shared utility (thickness classification, ID overlay)

### Exploratory / probes
- `thickness_probe.py` — thickness histogram diagnostic
- `border_probe.py`, `border_overlay.py` — road/contour disambiguation by black border

### Data
- `resources/` — input rasters + reference `.omap` files
- `output/` — generated masks, DB snapshots, overlays (gitignored)
- `docs/` — diary, spec checks, db schema (Czech)

## Dependencies

Python 3.10+, `numpy`, `opencv-python`, `scikit-image` — see `requirements.txt`
(`python -m venv .venv && .venv/Scripts/pip install -r requirements.txt`). ML pilot
training packages (torch, segmentation-models-pytorch, albumentations) are intentionally
kept out of `requirements.txt` — they live in `requirements-ml.txt` and run on the GPU
machine, not in the cv2 dev stack here.

## ML pilot — area segmentation (experimental)

Parallel track (since sezení 12): train a U-Net to segment area symbols, with the mask
taken from `.omap` **geometry** (not PNG colors — otherwise the model just relearns color
separation we already do in cv2). A cheap pilot answers go/no-go before investing in a
synthetic render pipeline for scale.

```
PNG + .omap → omap_mask (mask z geometrie) → build_dataset (tiling 512) → train (U-Net) → eval
```

- **`omap_mask.py`** — per-pixel class mask from `.omap` area geometry (8 ColorCategory classes).
  Resolves area fill from plain `AreaSymbol` *and* from the AREA part of `CombinedSymbol`
  (ISSprOM building `526.1`, canopy, water, paved — 8 of 9 combined symbols carry an area fill).
- **`build_dataset.py`** — tile (image, mask) pairs → `output/dataset/` + `manifest.json`
  (spatial split of one map = within-domain go/no-go signal).
- **`train.py`** — smp U-Net (resnet34 / ImageNet), Dice+CE loss, per-class IoU, best-mIoU
  checkpoint. Mild augmentation (the pilot's val/test are renders, not scans). `--smoke` for a
  CPU pipeline check; `--seed` (reproducible), `--workers`/`--threads` (CPU tuning).
- **`eval.py`** (component #5) — load checkpoint → per-class IoU on a split (reuses
  `train.evaluate`) + colour overlay `photo | GT | prediction`. `--split test/val`.

Full training runs on the GPU box ("mrkla"):

1. zip `output/dataset` (~30 MB) and copy it over (or regenerate via `build_dataset.py`).
2. install `requirements-ml.txt` with a **CUDA** torch build (see the file header).
3. `python train.py --epochs 40 --batch 16` → checkpoint at `output/checkpoints/best.pt`.

**Pilot verdict: U-Net learns.** Within-domain (Slovanka val) mean IoU **0.666**, dominant
classes (bg/green/yellow) 0.91–0.95. Cross-domain (Garching test) looked like only 0.122 —
but that was **misleading, not "ML fails"**, and sezení 15 pinned down why:

- The Garching GT mask used to omit combined buildings (`526.1`); `omap_mask` now resolves the
  AREA part of combined symbols, so the mask is complete (gray buildings/canopy = 8.6 % of it).
- The **dominant** distortion was a **georef shift** of the Garching mask vs raster — a clean
  translation of +129/+417 px (Slovanka's georef is fine). Aligning the mask lifts cross-domain
  mean IoU 0.106 → **0.283**, green 0.12 → **0.62**: the area-class generalization was hidden by
  a broken `.pgw`, not by the method.
- What remains low (gray/black/brown) is a genuine ISOM↔ISSprOM class gap (the model knows
  buildings as BLACK from forest ISOM; Garching is GRAY) plus a single training map.

Next blockers: fix the Garching `.pgw` translation, then more maps / domains. The method is sound.

## Docs

The working documents are in Czech:

- [IDEAS.md](IDEAS.md) — design brainstorm, alternative approaches
- [RESEARCH.md](RESEARCH.md) — survey of existing tools (CoVe, OCAD, Karttapullautin, U-Net papers)
- [DIARY.md](DIARY.md) — session log (detail in `docs/diary/`)
- [TODO.md](TODO.md) / [DONE.md](DONE.md) — work tracking
- [docs/db_schema.md](docs/db_schema.md) — canonical DB model + CLI spec
- [docs/spec_check_ISOM-2017-2.md](docs/spec_check_ISOM-2017-2.md) — IOF spec verification
- [docs/spec_check_ISSprOM-2019-2.md](docs/spec_check_ISSprOM-2019-2.md) — sprint spec verification

## License

Not yet decided. The repository is published for transparency; if you want to
build on it, open an issue first.
