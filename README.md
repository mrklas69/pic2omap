# pic2omap

Raster orienteering map → OMAP vectorization (work in progress).

Experimental pipeline that takes a rendered orienteering map (PNG) and tries to
reconstruct a vector `.omap` file readable by [OpenOrienteering Mapper](https://www.openorienteering.org/).
The focus is on the gap left by existing tools — area symbols, point symbols, and
automatic mapping to ISOM / ISSprOM symbol sets. Color line vectorization is
already solved by [CoVe](https://github.com/lpechacek/cove) (integrated in OOM).

**Status: WIP, research-stage. Not yet a usable tool.**

## Pipeline status

| # | Stage | Status |
|---|-------|--------|
| 1 | Preprocess (deskew, denoise) | ☐ |
| 2 | Color separation (palette-based, LAB nearest) | ✓ |
| 3 | Per-color raster ops (morphology, components, skeletonization) | ✓ |
| 0 | Ground truth metric (`compare_to_omap.py`) | ✓ |
| 4 | Symbol recognition (contours first) | ☐ next |
| 5 | Vectorization (skeleton → polyline → Bezier) | ☐ |
| 6 | Topology fix | ☐ |
| 7 | Georeferencing | ☐ |
| 8 | OMAP XML serialization | ☐ |

Current metric on `forest sample.omap` (Stage 3 output vs OMAP ground truth,
counts of objects per color category and topological type):

```
BROWN line ratio: 2.26x  (oversegmented contours — broken by black overlays)
BLACK line ratio: 0.84x  (paths joined at intersections)
YELLOW area     : 0.83x  (areas joined across neighbour boundaries)
```

## Repository layout

- `omap_model.py`, `omap_parser.py` — OMAP symbol DB (dataclass model + XML parser)
- `color_profile.py`, `color_category.py` — color profiles + semantic families
- `color_separator.py`, `separate_demo.py` — Stage 2 (palette-based separation)
- `morphology.py`, `components.py`, `skeleton.py`, `stage3_demo.py` — Stage 3
- `compare_to_omap.py` — ground truth comparison (Stage 0 metric)
- `resources/` — input rasters + reference `.omap` files
- `docs/` — diary, spec checks (Czech)

## Dependencies

Python 3.10+, `numpy`, `opencv-python`, `scikit-image`. (No `requirements.txt`
yet — see TODO.)

## Docs

The working documents are in Czech:

- [IDEAS.md](IDEAS.md) — design brainstorm, alternative approaches
- [RESEARCH.md](RESEARCH.md) — survey of existing tools (CoVe, OCAD, Karttapullautin, U-Net papers)
- [DIARY.md](DIARY.md) — session log (detail in `docs/diary/`)
- [TODO.md](TODO.md) / [DONE.md](DONE.md) — work tracking
- [docs/spec_check_ISOM-2017-2.md](docs/spec_check_ISOM-2017-2.md) — IOF spec verification
- [docs/spec_check_ISSprOM-2019-2.md](docs/spec_check_ISSprOM-2019-2.md) — sprint spec verification

## License

Not yet decided. The repository is published for transparency; if you want to
build on it, open an issue first.
