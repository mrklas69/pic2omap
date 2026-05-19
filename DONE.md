# DONE — pic2omap

Hotové úkoly. Migrují z `TODO.md` po dokončení. Detail v `DIARY.md` / `docs/diary/`.

## Stage 3 — Per-category raster ops

- [x] **Morfologie** (`morphology.py`) — opening 2×2 default per category, WHITE skip. `CATEGORY_PARAMS` dict pro per-category override. Stats reportu (pixels před/po). [2026-05-19 sezení 3]
- [x] **Connected components** (`components.py`) — `cv2.connectedComponentsWithStats` 8-konektivita, klasifikace POINT/LINE/AREA podle area + density + aspect_ratio. WHITE skip (nemá smysl jako pozadí / open forest). [2026-05-19 sezení 3]
- [x] **Skeletonizace** (`skeleton.py`) — `skimage.morphology.skeletonize` (Zhang-Suen) na LINE masky → 1px středovky. Připravka pro Stage 5 vektorizaci. [2026-05-19 sezení 3]
- [x] **Stage 3 CLI** (`stage3_demo.py`) — orchestrátor morphology → components → skeleton, `_stage3_report.txt`. Testováno na forest sample. [2026-05-19 sezení 3]

## Stage 2 — Color separation

- [x] **Symbol DB** (`omap_model.py`, `omap_parser.py`) — extrakce dataclass modelu z OMAP XML (stdlib `xml.etree`). [2026-05-19 sezení 2]
- [x] **Color profile vrstva 2** (`color_profile.py`) — precomputed LAB hodnoty, RGB dedup pro knockout duplicity. [2026-05-19 sezení 2]
- [x] **Color category** (`color_category.py`) — sémantické rodiny (BROWN, GREEN, …) klasifikací HSV hue + NAME_OVERRIDES. Řeší anti-aliasing leak vrstevnic do OOM Orange. [2026-05-19 sezení 2]
- [x] **Color separator** (`color_separator.py`, `separate_demo.py`) — palette-based LAB nearest-neighbor, per-priority + per-category masks, quantized overview. Funguje na forest sample. [2026-05-19 sezení 2]
- [x] **IOF spec verifikace** — paralelní agenti porovnali oba OMAP soubory s ISOM 2017-2 + ISSprOM 2019-2 PDF. Reporty `docs/spec_check_*.md`. Klíčový nález: OMAP soubory používají ISOM 2000 numbering, ne aktuální IOF. [2026-05-19 sezení 2]

## Setup

- [x] **Projekt init** — přejmenování `u_bonexu/` → `Pic2Omap/`, struktura `resources/` + `docs/diary/`, řídící docs (IDEAS, RESEARCH, DIARY, TODO). Git init + první commit. [2026-05-19 sezení 1+2]
- [x] **Rešerše existujících nástrojů** — CoVe, OCAD, Karttapullautin, NYPL map-vectorizer, akademické U-Net papery. End-to-end raster→OMAP neexistuje. `RESEARCH.md`. [2026-05-19 sezení 1]
