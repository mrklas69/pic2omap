# TODO — pic2omap

Pracovní úkoly. Hotové migrují do `DONE.md`. Brainstorming nápadů → `IDEAS.md`.

## Stage 4 — Detektory (priority pro další sezení)

- [ ] **Per-priority area disambiguation v3** — v2 (`area_v1` + `--omap` flag, sezení 7) zlepšil per-symbol klasifikaci 8 % (4× 408 + 3× 404). Limitace: component-level majority threshold (50 %) je moc přísný pro fragmentovanou Stage 3, 410 Opaque Green stále nedetekováno, 408 hodně pod GT. v3: per-pixel priority assignment + split komponenty na sub-areas per dominantní priority. Vyžaduje rework Stage 3 connected components.
- [ ] **Black area per-shape filter** — `area_v1` BLACK detekuje 59/50 GT (1.18× over) ve forest sample. False positives jsou balvany (kruhové) a road fragmenty. Per-shape filter: Building = obdélníkový (aspect_ratio compactness), balvan = kruhový → reject. 527 Settlement / 528 OOB sdílí priority s 526 → disambiguation v2 je nerozliší, nutný shape-based classifier.
- [ ] **Disambiguation performance** — `_disambiguate_component` dělá per-component full-image AND se VŠEMI priority maskami. Slovanka BLACK: 448 komp × 19 masek × 6.5 Mpx = desítky sekund. Omezit overlap na bbox komponenty (crop masku na bbox před AND).
- [x] **Template-aware symbol codes v detektorech** (sezení 8) — `resolve_brown_line_codes` v `brown_line_v1` + `resolve_default_area_code` v `area_v1`. Caller resolvuje exact kódy z library a předá. Slovanka: 101.0/102.0, default 403.0/406.1/526.0. → DONE.
- [x] **YELLOW disambiguation over-detection 403.1** (sezení 8) — **nebyla to over-detection, ale mislabeling.** 403.0≡403.1 a 401.0≡401.1 mají identickou RGB, color separation je nerozliší, `deduplicate_by_rgb` zahodí jednu masku. Disambiguace lepila přeživší `.1` variantu. Fix: `build_priority_to_area_code` RGB grouping + base-variant výběr. → DONE.
- [ ] **GREEN/YELLOW area under-detection** — Slovanka: 404.0 (8/159), 407.0 (47/242), 408.1 (302/630) pod GT. Color separation slévá blízké odstíny do dominantní barvy (403.0/406.1). 407 je navíc pattern (šrafa) → pattern detektor. Per-component context nebo jemnější paleta.
- [~] **109 Erosion gully discrimination v2** — `erosion_gully_v1` (crossing + pointed cap) **odpojen**, 0/17 precision. GT je jen **2 × 109** ve forest sample. Vyžaduje pozici-based check ("leží mezi 101 sousedy" — sample sousedů perpendiculárně k tangentě segmentu). Soubor zůstává jako reference (helpery `crossing_signal`, `pointed_cap_count`). Memory: `erosion-gully-vs-index-contour`.
- [~] **103 Form line v2** — `form_line_v1` (co-linear pair heuristika) odpojeno (20/3 = 6.7× over-claim). Sparse GT pattern stejný jako 109 erosion gully. v2 vyžaduje pozici-based check (sekvence ≥ 3 co-linear dashů s pravidelnými gaps) nebo multi-sample validation. Memory: `sparse-gt-naive-detector-trap`.
- [ ] **110 Small erosion gully** — `line_width=0` + `mid_symbol` Brown tečka. 16× ve forest sample. Patří do **point/dot detectoru** (sequence clustering), ne brown line. Budoucí `brown_dot_v1`.
- [ ] **Lake/pond detector (301/302)** — solid blue area. Distinct barva (modrá), low ambiguity.
- [ ] **Pattern fill detector** — 407/409 Undergrowth (zelená šrafa), 415 Cultivated land. Vyžaduje line-density / Fourier detekci pattern fillu jako area type.

## Orientation + Stripe filter

- [ ] **Stripe filter pro rotated maps** (`area_v1._is_vertical_stripe`) — pokud `orientation_deg != 0`, transformovat bbox podle rotace a pak měřit šířku v north-aligned coord. v1 řeší jen orientation=0 case (forest sample).
- [ ] **orientation_v1 fine-tuning** — peak BIN_DEG=1.0° dává rozlišení 1°. Pro fine rotation může chtít 0.25° (s 4× větším histogramem). Plus snížit min_line_length pro mapy s krátkými north lines.
- [ ] **Multi-mapa validace orientation_v1** — currently tested only Slovanka (returns 0.0°, expected 0.0°). Najít rotovanou mapu (declination je v `.pgw`, ne v rasteru — Slovanka má raster north-up i přes deklinaci 3.75°).

## DB infrastruktura

- [ ] **`diff` verb (pic2db.py)** — implementovat porovnání dvou iter_N.json. Vyžaduje persistent ID matching přes IoU bbox + symbol_code (zatím schema-only).
- [~] **`export` verb (db2omap)** — PoC + georef + line vektorizace hotové. Hotovo:
  areas → kontury, **rigorózní georef** (sezení 9: `.pgw` + OMAP georef, pixel→coord
  bez rotace, ověřeno 4×; bbox-fit fallback pro Local CRS), **line segment-trace**
  (sezení 9: kostra jako graf, každá hrana → path, neztrácí délku). Slovanka 5968 obj,
  forest 451 obj. Co zbývá do produkční verze:
  - **Bezier fit** — OOM používá kubické Beziery, ne polyline (Schneider fit). Nahradit
    approxPolyDP polyline za Bezier segmenty s flagy v `<coords>`.
  - **Re-linking fragmentů** — vrstevnice silně fragmentované (median 16 px) kvůli
    mid-symbol/černým překryvům. Spojit co-linear sousední segmenty (fáze B re-link).
  - **L-roh merge** — segment-trace seká v 8-souvislých rozích (32 segmentů u obj 1864).
    Sloučit segmenty pokračující přímo přes deg-3 roh (straightest continuation).
  - **1:10000 vs scale=15000** — ověřit Slovanka měřítko (titulek vs OMAP georef/`.pgw`).
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

## Parser

- [ ] **CombinedSymbol parts parsing** — `_parse_combined_symbol` v `omap_parser.py` zatím vrací prázdný `parts=[]`. Doplnit dohledáním struktury v OMAP spec (`<symbol type="16">`) a parsováním sub-symbolových odkazů. V `complete map.omap` ~9 combined symbolů (železnice apod.), zatím není blocker pro detekci.

## Dokumentace

- [ ] **`docs/db_schema.md` rozšířit** — popsat fáze A vs B, claim conflict resolution (brown line vs area overlap), 16-bit PNG mask format details.

## Infrastruktura

- [ ] **`requirements.txt`** — explicitní seznam závislostí (numpy, opencv-python, scikit-image). Verze podle aktuálního pip freeze.
- [ ] **Sprint scope** — sehnat oficiální `ISSprOM_2019-2.omap` template z OOM symbol sets distribuce. Bez něj nelze pokrýt sprint mapy.
- [ ] **Test ve Slovanka palette** — Slovanka má jinou color paletu než forest sample (priority 19 = Blue vs Yellow). `color_category.py` overrides možná nejsou robustní napříč mapami. Validovat.

## Otevřené architektonické otázky

- [~] **Metrika úspěchu pro Fázi 0** — počty objektů per (category, type) implementovány. Slabost: counts jsou hrubé. Doplnit IoU / geometrickou metriku po Stage 5.
- [ ] **Detekce OMAP spec verze** — soubory neuvádějí ISOM 2000 vs 2017-2 explicitně. Heuristika: měřítko + jména barev + struktura symbolů.
- [ ] **Per-OMAP-file color palette** — priority indexy se mezi soubory liší (Slovanka 19=Blue, forest sample 19=Yellow). Detector musí parsovat colors z konkrétního OMAP, ne hardcoded.
