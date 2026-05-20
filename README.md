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
| `point_v1` | 115/536/418 + default (sezení 11) | forest 440 (brown 235/black 58/green 147) — over-claims, point bucket noise |
| `erosion_gully_v1` | 109 Erosion gully | disconnected (0/17 precision, see memory) |

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
- `cli_utils.py` — shared CLI helpers (UTF-8 console)

### Stage 2/3 pipeline
- `omap_model.py`, `omap_parser.py` — OMAP symbol DB (dataclass model + XML parser)
- `color_profile.py`, `color_category.py` — color profiles + semantic families
- `color_separator.py` — palette-based LAB separation
- `morphology.py`, `components.py`, `skeleton.py` — Stage 3 ops

### Stage 4 detectors
- `brown_line_v1.py` — 101 / 102 (thickness peak)
- `area_v1.py` — solid fill areas (GREEN/YELLOW/BLACK/GRAY), parameterized by `ColorCategory`
- `point_v1.py` — point symbols via point bucket (size + aspect filter)
- `point_template_poc.py` — discriminative template matching PoC (shape from OMAP geometry)
- `orientation_v1.py` — map rotation from 601.x north lines
- `erosion_gully_v1.py`, `form_line_v1.py` — 109/103 experiments (disconnected, kept as reference)
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
kept out of `requirements.txt` — they run on the GPU machine, not here.

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
