# DONE — pic2omap

Hotové úkoly. Migrují z `TODO.md` po dokončení. Detail v `DIARY.md` / `docs/diary/`.

## Slovanka2016 Stage 2/3 test (sezení 7)

- [x] **Downscale 143 Mpx → 6.5 Mpx** — Slovanka2016.png (14094×10158) downscaled na 3000 px max dimension (scale 21.3%) jako `resources/Slovanka2016_small.png`. Pragmatický kompromis: zachovává detail orienťáckých symbolů (1.4 m/px), redukuje Stage 2/3 čas. [2026-05-19 sezení 7]
- [x] **Stage 2 + 3 + pic2db detect na Slovanka small** — orientation_v1 detekoval 0.00° z 34 modrých magnetic north lines (raster north-up, navzdory declination 3.75° v `.pgw`). pic2db produkoval 4968 objektů. [2026-05-19 sezení 7]
- [x] **`load_priority_masks` UTF-8 fix** — opencv `cv2.imread()` na Windows používá fopen, který neumí UTF-8 cesty (Slovanka má barvy s českou diakritikou v názvech, např. `priority01_Bílá_nad_skoro_všemi.png`). Fix: `np.frombuffer(Path.read_bytes()) + cv2.imdecode()`, obchází fopen encoding. [2026-05-19 sezení 7]
- [x] **v2 disambiguation funguje na Slovanka custom palette** — Yellow over green priorities 24 (Žlutá 100%) → 401.1, 27 (Žlutá 50%) → 403.1 správně namapovány. 1019× 403.1 + 292× 401.1 + 171× 403 default. [2026-05-19 sezení 7]
- [x] **Slovanka GT comparison** — BLACK 526.0: 448/402 = 1.11× (slušné), GREEN 406.1+408.1: 1115/1356 = 0.82× (mírně under), BROWN 101+102: 1923/587 = 3.27× (over-segm, horší než forest sample), YELLOW: 1482/1135 = 1.31× (over kvůli 403.1). [2026-05-19 sezení 7]

## 103 Form line experiment (sezení 7)

- [~] **`form_line_v1`** — co-linear pair heuristika nad mid peak brown skeletonu. Filter krátké (5-50 px) + paralelní soused (cosine ≥ 0.85) do 30 px. **Výsledek**: 20 detekováno / GT 3 = 6.7× over-claim. Odpojeno z `cmd_detect`, soubor jako reference. Stejný pattern jako `erosion_gully_v1` — sparse GT v over-segmented bucketu. Memory: `sparse-gt-naive-detector-trap`. [2026-05-19 sezení 7]

## Black area detector (sezení 7)

- [x] **`area_v1` BLACK kategorie** — extension přes `MIN_AREA_PX_PER_CATEGORY[BLACK]=20` + `DEFAULT_SYMBOL_PER_CATEGORY[BLACK]="526"` + `ALLOWED_ISOM_PREFIX_PER_CATEGORY[BLACK]="5"` (man-made). Forest sample: 59 detekováno / GT 50 = **1.18×** (mírná over-detection z balvanů a road fragmentů). KISS — žádný nový soubor, jen 1 dict entry per parametr. Disambiguation v2 nepomohla (BLACK priority je AMBIGUOUS: 526/527.1/528/202/601.1 sdílí priority 1). [2026-05-19 sezení 7]
- [x] **`pic2db.cmd_detect` BLACK area volání** — symbol filter `{526, 527, 527.1, 528}`. [2026-05-19 sezení 7]

## Per-priority area disambiguation v2 (sezení 7)

- [x] **`area_v1` + `--omap` flag** — per-component priority overlap voting → konkrétní ISOM kód místo default per kategorie. Heuristiky: filter OOM-specific (411.X), sémantický filtr (jen 4XX vegetation pro GREEN/YELLOW), majority threshold 0.50. Forest sample zlepšení: 4× 408 + 3× 404 (= 8 % areas s konkrétním kódem místo default). Memory: priority 10 Green 50% Yellow má UNIQUE mapping na 527 Settlement v OMAP, ale sémantický filtr to správně odmítl. [2026-05-19 sezení 7]
- [x] **`build_priority_to_area_code`** — helper v `area_v1.py`, extrahuje priority → ISOM kód mapping ze `SymbolLibrary` per ColorCategory. Heuristika filtruje OOM-only kódy (411.X) a sémanticky nekompatibilní (5XX v GREEN). [2026-05-19 sezení 7]
- [x] **`load_priority_masks`** — načte všechny `priority{NN}_*.png` z Stage 2 výstupu. [2026-05-19 sezení 7]
- [x] **`pic2db.py --omap` flag** — opt-in v2 disambiguation. Bez flagu zůstává v1 default-per-category chování. [2026-05-19 sezení 7]

## %AUDIT:CODE + %AUDIT:DOCS (sezení 7)

- [x] **`detection_method` rename** — `brown_line_v1` (bylo `brown_thickness_v1`), `area_v1` (bylo `{cat}_area_v1`). Sjednocuje grep-friendly identifikaci s názvy detektorů. [2026-05-19 sezení 7]
- [x] **`cli_utils.force_utf8_console()`** — extrahován DRY helper, 9 souborů dedupováno (4 řádky × 9 → 2 řádky × 9). [2026-05-19 sezení 7]
- [x] **`_resolve_db_path` natural sort** — `iter_2 < iter_10` místo lexikografického. [2026-05-19 sezení 7]
- [x] **Pipeline status SSOT** — README.md = kanonický (Stage 4 ☐ next → ☐ in progress, per-detector status tabulka, Stage 4 metriky v Markdown). IDEAS.md 8-stages duplicitní tabulka redukována na historický odkaz. [2026-05-19 sezení 7]
- [x] **`@TODO` markery v kódu → TODO.md** — `area_v1.py` stripe filter (odkaz na TODO.md), `omap_parser.py` CombinedSymbol parts (nová položka v TODO.md "Parser"). [2026-05-19 sezení 7]
- [x] **`db_schema.md` status update** — "návrh (Sezení 5)" → "Implementováno (Sezení 6)". [2026-05-19 sezení 7]
- [x] **README.md Repository layout** — doplněno 12 nových souborů (pic2db, db_model, detektory, probes, cli_utils) v kategorizovaných sekcích (Entry points / DB infra / Stage 2-3 / Stage 4 / Exploratory). [2026-05-19 sezení 7]
- [x] **IDEAS.md "Zodpovězeno" sekce** — aktualizováno po Sezeních 3-6 (metrika úspěchu, DB mezivrstva, CoVe rozhodnutí). [2026-05-19 sezení 7]
- [x] **Typografické opravy** — `spec_check_ISSprOM-2019-2.md` "nĕco" → "něco", "prib." → "přib." (2× výskyt). DIARY/2026-05-19 Sezení 6 H2→H1 heading (konzistence se Sezeními 1-5), "step 0" → "krok 0". [2026-05-19 sezení 7]

## Architektura pic2db / db2omap (sezení 6)

- [x] **DB schema** (`docs/db_schema.md`) — kanonická specifikace: MapObject + NonMapElement + DBSnapshot. Disk layout `iter_N.json` + 16-bit `claim_mask_iter_N.png`. CLI verby subcommand router. Persistent IDs napříč iter (IoU bbox matching). Stop kritéria fáze B. [2026-05-19 sezení 6]
- [x] **Data model** (`db_model.py`) — dataclasses + JSON save/load + round-trip smoke test. Rozšířen o `map_orientation_deg: float | None = 0.0`. [2026-05-19 sezení 6]
- [x] **CLI router** (`pic2db.py`) — argparse subcommands: `detect` (orchestrace + claim mask + 16-bit PNG), `list` (tabulkový výpis, `--symbols` filter), `mark` (overlay + `--with-ids` popisky), `diff`/`export` stuby. [2026-05-19 sezení 6]

## Stage 4 — Detektory (sezení 6)

- [x] **`brown_line_v1`** — thickness peak → 101 Contour (thin) / 102 Index contour (thick). Reuse `peak_visualizer.classify_segments`. Forest sample: 138 objektů (112×101 + 26×102), over-segmentace 2.09×. Mid peak (43 segmentů) záměrně unclaimed. [2026-05-19 sezení 6]
- [x] **`area_v1`** — generic area detector parametrizovaný `ColorCategory`. Per-category `MIN_AREA_PX` (GREEN=30, YELLOW=20), per-category stripe filter (GREEN only). Forest sample: 59 × 406 (post-stripe filter) + 26 × 403 (exact GT match). [2026-05-19 sezení 6]
- [x] **`orientation_v1`** — per-color binary mask (BLUE + BLACK kandidáti) + HoughLinesP + length-weighted histogram angles + dominance check. Slovanka2016: 0.0° (dominance 2010×, raster north-up navzdory deklinaci 3.75° v `.pgw`). Forest sample: None (fallback). [2026-05-19 sezení 6]
- [~] **`erosion_gully_v1`** — experiment failed (0/17 precision na forest sample, real GT = 2 × 109). Helpery `crossing_signal` + `pointed_cap_count` zůstávají jako reference. Odpojen z `cmd_detect`. Memory `erosion-gully-vs-index-contour` drží lessons learned. [2026-05-19 sezení 6]

## Helper scripts (sezení 6 — Stage 4 exploration)

- [x] **`peak_visualizer.py`** — rozdělí brown skeleton na thin/mid/thick podle peak, overlay s ID popisky (`font_scale=0.2`). Reuse v brown_line_v1. [2026-05-19 sezení 6]
- [x] **`border_overlay.py`, `border_probe.py`, `thickness_probe.py`** — exploratorní skripty pro segment klasifikaci podle border ratio + thickness peaks. Informovaly návrh brown_line_v1. [2026-05-19 sezení 6]

## GT comparison rozšíření (sezení 6)

- [x] **`compare_to_omap.py --symbols` filter** — totální skip objektů mimo seznam (diagnostika odráží jen filtrovaný podset). Pipe sekce skryta s aktivním filtrem (GT je per-symbol, pipeline per-category). Příprava pro per-symbol detektor validaci. [2026-05-19 sezení 6]

## Test resources (sezení 6)

- [x] **`Slovanka2016.omap + .png + .pgw`** — větší orienťácká mapa s 34 × 601.1 modrými magnetic north lines pro orientation_v1 validaci. 14094×10158 raster, scale 1:15000, declination 3.75° v georef. [2026-05-19 sezení 6]

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
