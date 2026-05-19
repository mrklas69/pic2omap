# TODO — pic2omap

Pracovní úkoly. Hotové migrují do `DONE.md`. Brainstorming nápadů → `IDEAS.md`.

## Stage 4 — Detektory (priority pro další sezení)

- [ ] **Per-priority area disambiguation v2** — pro každou area komponentu zjistit dominantní `priority/priorityNN_*.png` overlap → mapuj `inner_color` na konkrétní ISOM kód (406 vs 408 vs 410, 401 vs 403). Žádný nový detektor, jen vylepšení existujícího `area_v1`. Aktuálně defaultuje na 406 / 403.
- [ ] **Black area detector (526 Building)** — největší neclaimed area kategorie (50× ve forest sample). Vstup `cat_black_area.png`. Podobné `area_v1`, jen jiná default barva + kód. Plus 527 Settlement (8×) jako varianta.
- [ ] **Stage 2/3 pipeline na Slovanka2016** — risk: 14094×10158 = 143 Mpx, stage 3 morphology/components by trvalo dlouho. Možnost: downscale na ~3000 px max rozměr pro stage 2/3, full pipeline. Otestuje generalization detektorů na druhou mapu.
- [~] **109 Erosion gully discrimination v2** — `erosion_gully_v1` (crossing + pointed cap) **odpojen**, 0/17 precision. GT je jen **2 × 109** ve forest sample. Vyžaduje pozici-based check ("leží mezi 101 sousedy" — sample sousedů perpendiculárně k tangentě segmentu). Soubor zůstává jako reference (helpery `crossing_signal`, `pointed_cap_count`). Memory: `erosion-gully-vs-index-contour`.
- [ ] **103 Form line (dashed brown)** — dash pattern detector v skeletonu (segment-mezi-mezery). Ujme se další chunk z brown mid peaku (43 segmentů zatím unclaimed).
- [ ] **110 Small erosion gully** — `line_width=0` + `mid_symbol` Brown tečka. 16× ve forest sample. Patří do **point/dot detectoru** (sequence clustering), ne brown line. Budoucí `brown_dot_v1`.
- [ ] **Lake/pond detector (301/302)** — solid blue area. Distinct barva (modrá), low ambiguity.
- [ ] **Pattern fill detector** — 407/409 Undergrowth (zelená šrafa), 415 Cultivated land. Vyžaduje line-density / Fourier detekci pattern fillu jako area type.

## Orientation + Stripe filter

- [ ] **Stripe filter pro rotated maps** (`area_v1._is_vertical_stripe`) — pokud `orientation_deg != 0`, transformovat bbox podle rotace a pak měřit šířku v north-aligned coord. v1 řeší jen orientation=0 case (forest sample).
- [ ] **orientation_v1 fine-tuning** — peak BIN_DEG=1.0° dává rozlišení 1°. Pro fine rotation může chtít 0.25° (s 4× větším histogramem). Plus snížit min_line_length pro mapy s krátkými north lines.
- [ ] **Multi-mapa validace orientation_v1** — currently tested only Slovanka (returns 0.0°, expected 0.0°). Najít rotovanou mapu (declination je v `.pgw`, ne v rasteru — Slovanka má raster north-up i přes deklinaci 3.75°).

## DB infrastruktura

- [ ] **`diff` verb (pic2db.py)** — implementovat porovnání dvou iter_N.json. Vyžaduje persistent ID matching přes IoU bbox + symbol_code (zatím schema-only).
- [ ] **`export` verb (db2omap)** — serializace DBSnapshot → OMAP XML. Vyžaduje:
  - Polyline vektorizace pixel_blob_id → OMAP coords (Schneider Bezier fit?)
  - Symbol library mapping (symbol_code → OMAP symbol id)
  - Pixel → OMAP coord transform (georef-based, plus rotation)
- [ ] **Multi-iter podpora** — re-link iterace fáze B: po point detection re-evaluovat fragmentované linie. Vyžaduje matching MapObject napříč iteracemi.

## Stage 2/3 — Cleanup

- [ ] **Brown skeleton contamination** — urban roads ISSprOM 529/503 padají do `cat_brown_clean.png`. Color separator nebo per-OMAP-version paletu. Příklad: forest sample #122.
- [ ] **AREA filtrování fragmentů** — krátké tlusté fragmenty čar (density > 0.5) se schovaly v AREA. `area_v1` má částečný density filter, ale fragmentů zůstává hodně. Možnost: dilate-then-erode pro odstranění tenkých výběžků.
- [ ] **Pattern detection (P2)** — `cat_green_area.png` obsahuje šrafu (svislé čárky 407/409). Stripe filter pomohl, ale ne dokonale. Vyžaduje Fourier / autokorelační detektor pattern.
- [ ] **Per-DPI škálování thresholdů** — všechny px-based thresholdy (`MIN_AREA_PX`, `STRIPE_MAX_WIDTH`, `POINT_MAX_AREA`, atd.) jsou kalibrované na forest sample. Pro Slovanka (143 Mpx, jiná scale) bude třeba lineární škálování.

## Ground truth — metriky

- [ ] **IoU / geometrická metrika** — counts jsou hrubá metrika (oversegmentace skrytá ve fragmentaci). Po Stage 5 (vektorizace) přidat porovnání délek linií v mm a ploch v mm², přepočet OMAP units → pixel via georef.
- [ ] **Per-object GT matching** — z OMAP coords vytvořit pixel coordinates jednotlivých objektů (vyžaduje georef transform), pak matchnout s detekovanými MapObject. Precision/recall per ISOM kód.

## Symbol layer 2 (pro Stage 4)

- [ ] **SymbolProfile** — `symbol_profile.py`: per-symbol key features (line width v px po georef, dashed Y/N, dash period, point shape signature, area pattern fingerprint). Builder ze `SymbolLibrary`.

## Dokumentace

- [ ] **Single source of truth pro pipeline status** — tabulka 8 stages se ☐/✓ existuje na 5+ místech (README, IDEAS, DIARY). Drift hrozí. Návrh: README = kanonický, ostatní jen odkazují. Vyřešit při příštím `%AUDIT:DOCS`.
- [ ] **`docs/db_schema.md` rozšířit** — popsat fáze A vs B, claim conflict resolution (brown line vs area overlap), 16-bit PNG mask format details.

## Infrastruktura

- [ ] **`requirements.txt`** — explicitní seznam závislostí (numpy, opencv-python, scikit-image). Verze podle aktuálního pip freeze.
- [ ] **Sprint scope** — sehnat oficiální `ISSprOM_2019-2.omap` template z OOM symbol sets distribuce. Bez něj nelze pokrýt sprint mapy.
- [ ] **Test ve Slovanka palette** — Slovanka má jinou color paletu než forest sample (priority 19 = Blue vs Yellow). `color_category.py` overrides možná nejsou robustní napříč mapami. Validovat.

## Otevřené architektonické otázky

- [~] **Metrika úspěchu pro Fázi 0** — počty objektů per (category, type) implementovány. Slabost: counts jsou hrubé. Doplnit IoU / geometrickou metriku po Stage 5.
- [ ] **Detekce OMAP spec verze** — soubory neuvádějí ISOM 2000 vs 2017-2 explicitně. Heuristika: měřítko + jména barev + struktura symbolů.
- [ ] **Per-OMAP-file color palette** — priority indexy se mezi soubory liší (Slovanka 19=Blue, forest sample 19=Yellow). Detector musí parsovat colors z konkrétního OMAP, ne hardcoded.
