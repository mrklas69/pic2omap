# DONE — pic2omap

Hotové úkoly. Migrují z `TODO.md` po dokončení. Detail v `DIARY.md` / `docs/diary/`.

## Ground truth — fix podhodnocené GT (sezení 5)

- [x] **Secondary color resolution** — rozšíření `omap_model` (Line/Area/PointSymbol dostaly `secondary_color_ref: int`) + `omap_parser` (helpery `_secondary_color_for_{line,area,point}` + `_color_ref_from_wrapped_symbol` s rekurzí pro Vineyard-style nesting). `compare_to_omap.symbol_to_color_ref_with_source` má 2-úrovňový fallback. Posun GT: 156 přeskočených objektů → 0; ratiosy se zpřesnily (BROWN line 2.26× → 1.89×, GREEN area 2.27× → 1.24×). [2026-05-19 sezení 5]
- [x] **Phantom objects XPath fix** — `.//object` chytalo i 134 template `<object>` uvnitř `<symbols>` definic (souřadnice patternů/elementů). Změna na `.//objects/object` (přímé děti `<objects>` kontejneru). `objects_without_symbol: 134 → 0`. [2026-05-19 sezení 5]
- [x] **UTF-8 console fix** — `sys.stdout.reconfigure(encoding="utf-8")` na startu `compare_to_omap.main`. Diakritika v reportu na Windows cp1250 konzoli teď funguje. [2026-05-19 sezení 5]

## Dokumentace (sezení 5)

- [x] **README update** — nové ratiosy (BROWN 1.89×, BLACK 0.63×, GREEN 1.24×, YELLOW 0.83×) + popis secondary-color fallbacku. [2026-05-19 sezení 5]
- [x] **`docs/spec_check_ISSprOM-2019-2.md`** — oprava rozbité diakritiky (`mapítko`, `nepouzívá`, `pouzít`, `Pravdĕpodobný`, `níze`, `broun`) + překlad 4 anglických bloků do češtiny (sekce 1-4 v "Poznámkách"). Důvod: konzistence napříč docs. Druhý spec_check (ISOM-2017-2) byl v pohodě. [2026-05-19 sezení 5]

## Ground truth comparison

- [x] **`compare_to_omap.py`** — standalone CLI skript: načte OMAP, mapuje `<objects>` na (ColorCategory, ComponentType) via existující symbol library + category map. Pipeline strana: počítá connected components v `cat_<color>_<type>.png`. Výstup: tabulka GT/Pipe/Diff/Ratio per kategorie + ISOM symbol breakdown + diagnostika skipped objektů. První **metrika úspěchu Fáze 0**. Klíčový vedlejší nález: 156 objektů ve forest sample má `inner_color="-1"` (barva přes patterns) — vyřešeno v sezení 5. [2026-05-19 sezení 4]

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
