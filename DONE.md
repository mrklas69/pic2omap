# DONE — pic2omap

Hotové úkoly. Migrují z `TODO.md` po dokončení. Detail v `DIARY.md` / `docs/diary/`.

## %AUDIT:CODE + opravy (sezení 14)

- [x] **%AUDIT:CODE — hloubkový audit** — 7 paralelních agentů přečetlo všech 8223 LOC,
  konsolidované nálezy (kritické/doporučené/kosmetické). Jediný „kritický" (priority↔index)
  vyvrácen ověřením 3 reálných `.omap` (invariant `priority==index` drží). [2026-05-21 sezení 14]
- [x] **Dávka A — kosmetika + docstringy + ML seed** — nepoužité `import sys` (3×), f-string
  bez interpolace, nadbytečné závorky, tempfile leak (db_model smoke), `_CLASS_NAME`→`CLASS_NAMES`
  (veřejné), dvojí `val_frac` default → konstanty, zastaralé docstringy (pic2db export, db2omap
  georef, build_dataset split, morphology closing). `train.py --seed` + `set_seed` + DataLoader
  generator (reprodukovatelnost). [2026-05-21 sezení 14]
- [x] **Dávka C — sdílené helpery** — `imread_unicode` v `cli_utils` (UTF-8-safe loader, 6 míst);
  `omap_tag` (veřejné z `_tag`) + `iter_map_objects` (phantom-fix XPath) v omap_parser, smazány
  3 lokální kopie `_tag`/`OMAP_NS` + 3 XPath duplikáty; **`georef.py` extrakce** (6 georef funkcí
  z „zamraženého" db2omap → samostatný modul, importují db2omap/omap_mask/compare_to_omap).
  Ověřeno: detect 722, export bbox-fit, omap_mask rigorózní georef. [2026-05-21 sezení 14]
- [x] **Dávka B — DRY/izomorfismus detektorů** — `cmd_detect` area sekce: 8 proměnných + 4 kopie
  bloků → `area_config` tabulka + smyčka; `_merge_claim` helper (6 inline kopií → 1); point
  `default_code` (nová `resolve_default_point_code`, izomorfní s area — body dostanou template-aware
  kód). **722 invariant ověřen** (behavior-preserving). D2 (sdílená kostra area↔point) vědomě
  vynechána — KISS (area_v1 řádově složitější, callbacky > čitelnost). [2026-05-21 sezení 14]
- [x] **Dávka D — smazání mrtvého kódu** — `erosion_gully_v1.py` + `form_line_v1.py` (0 importů,
  helpery nikdo nevolá, v2 vyžaduje jiný přístup; lessons v memory + git). 4 nástroje ponechány
  v rootu (přesun by rozbil root importy, malý přínos). Net sezení: −609 ř. [2026-05-21 sezení 14]

## ML pilot segmentace ploch — komponenta #3+4 (sezení 13)

- [x] **`train.py` — U-Net trénink (komponenta #3+4)** — `SegDataset` (čte `manifest.json`,
  BGR→RGB, mask = class indexy 0–7), `build_train_aug`/`build_eval_aug` (albumentations, **mírná**:
  flip + rotate90 + drobný scale/posun + lehký jas — domain gap se v pilotu nevaliduje, val/test
  jsou rendery; agresivní balík zakomentovaný pro reálné skeny), `build_model` (smp.Unet resnet34/
  ImageNet, 8 tříd, logity), `DiceCELoss` (řeší imbalance ~11000×), `evaluate` (per-class IoU přes
  `smp.metrics`, mean jen přes třídy přítomné v GT), `fit` (Adam, checkpoint best val mIoU, bez
  Lightning). CLI `--smoke`/`--epochs`/`--batch`/`--lr`/`--encoder`/`--device`/`--workers`.
  `force_utf8_console` (Windows cp1250 šipka). Smoke-test CPU OK (pipeline ověřena); **CPU sanity
  5 epoch prokázal učení**: val mIoU 0.61, bg/green/yellow ~0.9, black 0→0.65, blue 0→0.23 (brown
  127k px za 5 epoch CPU nezachycena). Plný trénink (40 epoch) na „mrkla". [2026-05-20 sezení 13]
- [x] **`requirements-ml.txt`** — torch/segmentation-models-pytorch/albumentations oddělené od
  `requirements.txt` (cv2 dev stack zůstává lehký). CPU instalace tady (smoke), CUDA na „mrkla"
  (plný trénink). Pokyny v hlavičce souboru. [2026-05-20 sezení 13]

## ML pilot segmentace ploch — komponenty #1 + #2 (sezení 12)

- [x] **Prostředí (`.venv` + `requirements.txt`)** — nový stroj (první klon), chyběl numpy/cv2.
  `.venv` (Python 3.12.3), `requirements.txt` (numpy/opencv/scikit-image; ML balíčky vědomě jen
  na GPU stroji "mrkla"). Vyřešen starý TODO. Windows git "dubious ownership" fix. [2026-05-20 sezení 12]
- [x] **`omap_mask.py` — mask generator (komponenta #1)** — area objekty z `.omap` → per-pixel
  sémantická maska class indexů (úroveň `ColorCategory`, 8 tříd). `build_area_mask` (parse objektů,
  priority řazení, fillPoly + holes), `_coords_to_rings` (Bezier tessellation flag 1, hole split
  flag 16), `_symbol_class` (jen inner_color = solid fill; pattern-only jako severky 601 přeskočeny —
  jinak přemažou plochy pod sebou, bug 43 % falešná modrá opraven), `_coord_to_pixel_matrix`
  (re-use db2omap georef parsery, obrácený směr coord→pixel + ratio škálování), `overlay_on_image`.
  **Maska z autoritativní .omap geometrie, NE z barev PNG** (jinak nulová ML hodnota). Reality-check:
  Garching + Slovanka alignment OK, ~5mm georef na úrovni ploch nevadí. Memory `ml-pilot-segmentace-ploch`,
  `oom-095-no-headless-render`. [2026-05-20 sezení 12]
- [x] **`build_dataset.py` — dataset builder (komponenta #2)** — tiling (PNG, .omap) párů →
  dlaždice 512×512 + `manifest.json`. `_tile_split` (spatial train/gap/val per y → within-domain
  čistý go/no-go signál), `_ink_fraction` filtr (>5 % ne-bílých = uvnitř mapy), `_class_px`.
  Augmentace VĚDOMĚ ne v datasetu (patří na trénink, on-the-fly). Split po celých mapách (leakage).
  Slovanka spatial: train 234 / val 62 dlaždic (within-domain, podobná class distrib.), Garching
  test 22 (cross-domain). [2026-05-20 sezení 12]

## Template matching point detektor — PoC (sezení 11)

- [~] **`point_template_poc.py` — diskriminativní template matching** — převzato od jiného Clauda ("bráška" našel 2 posedy 536 vizuálně). Render tvaru symbolu z OMAP geometrie (T = coords čar) + diskriminativní kernel (foreground T kde MÁ být černá, + forbidden prstenec kde MÁ být bílá → penalizuje 537 kříž nad vodorovnou + budovy po stranách), `filter2D`, self-kalibrace měřítka. **Oba posedy spolehlivě top-3 (skóre 0.88/0.84) z 226 bucket fragmentů** → 6 kandidátů, 100 % recall. Strop: roh budovy v písčině (skóre 0.86) se neodliší (izolovanost selže — posed na srázu = velká komponenta). Bráškova vision to zvládla, plain cv2 ne. Zachováno jako PoC/reference. Memory `template-match-point-detection`. [2026-05-20 sezení 11]

## Point detektor v1 (sezení 11)

- [~] **`point_v1.py` — detektor bodových symbolů** — mirror `area_v1`, `detect(category)` na `cat_<cat>_point.png`, `geometry_type="point"`. Filtr velikostní okno (MIN/MAX_AREA per kategorie) + aspect (vyřadí fragmenty linií). Default brown→115 (depression), black→536 (tower), green→418 (special veg). Záměrně NEfiltruje agresivně tvarem (115 depression je obrys/nízký fill, 116 pit plný). Zapojen v `pic2db.cmd_detect` (po area/line, claimuje jen unclaimed — IDEAS fáze B). Forest: 440 bodů (brown 235, black 58, green 147). **Over-claim 7–34× vs GT (7/4/21)** — point bucket plný fragmentů linií, v1 = odrazový můstek pro ladění (memory `sparse-gt-naive-detector-trap`). Tím se naplnil chybějící třetí Point obrázek (`mark --by-type`). [2026-05-20 sezení 11]

## Review nástroj + georef zjištění (sezení 11)

- [x] **`mark` review overlay** — `cmd_mark` (byl funkční stub) rozšířen: `--by-type` (3 obrázky per geometry_type point/line/area na ztlumeném originálu, `_render_mark_overlay` helper), `--scale N` (upscale + úměrný font pro čitelnost ID na malých renderech — forest 631px nečitelný při font 0.2). ID v centroidu, barva per symbol_code, `--symbols` filtr. [2026-05-20 sezení 11]
- [x] **`compare_to_omap --db` per-symbol tabulka** — GT (z OMAP) vs DB counts per ISOM kód: `kód | název | GT | DB | ratio | status` (OK/OVER/UNDER/MISSING/EXTRA). Stálá DB↔OMAP metrika kroku 4, ne koncový krok. Forest: OK=3 OVER=2 (101 2.2×, 102 1.7×) UNDER=4 MISSING=28 z 37 symbolů. [2026-05-20 sezení 11]
- [x] **`--csv-dir` review CSV export** — `review_suma.csv` (per kód), `review_gt.csv` (všech 539 GT objektů z OMAP s pozicí, coord systém), `review_detail.csv` (naše detekce, raster systém). encoding utf-8-sig (Excel diakritika), xLoc/yLoc 0-10 origin vlevo-dole. [2026-05-20 sezení 11]
- [~] **Per-objekt matching GT↔DB (zkoušeno, odloženo)** — nearest-centroid v OMAP coord. Odhalil, že georef je nepřesný: forest bbox-fit hrubý, Garching `.pgw` ~5mm (jen 15 % budov sedí do své velikosti, 90 %+ falešných párů). NENÍ y-flip (unáhlený závěr opraven — coord zrcadlení byla náhoda, budovy kolem coord y=0). Matching odstraněn, → TODO (potřebuje přesný georef + legenda filtr). Memory `verify-domain-claims-against-source`. [2026-05-20 sezení 11]

## Gray budovy + ISSprOM combined kódy (sezení 11)

- [x] **GRAY area detektor (budovy)** — `area_v1` rozšířen o `ColorCategory.GRAY` (4 per-category dicty: MIN_AREA_PX=80, stripe filter off, default "526", ISOM prefix "5"), `pic2db.cmd_detect` GRAY blok (4. kopie vzoru, per-priority disambiguace izomorfní s BLACK). Garching: **241 budov** (gray fill color 6 "Black 50-65%"), median 1297 px = velké plochy. Recall ~241/273 GT = 88 %. MIN_AREA=80 odfiltroval anti-alias lemy kolem černých prvků. Forest/Slovanka: 0 gray ploch (no-op, žádná regrese). Memory: `verify-domain-claims-against-source`. [2026-05-20 sezení 11]
- [x] **ISSprOM combined/hierarchické kódy (resolver)** — CombinedSymbol parts parsing v `omap_parser._parse_combined_symbol` (`<combined_symbol><part symbol="ID"/>` → `list[int]`; 526.1 → [112,113]). `_promote_to_combined` v `area_v1` povýší area helper → rodičovský combined (526.1.1 → 526.1 = fill+outline, jak OOM kreslí budovy). `resolve_default_area_code` pattern `?`→`*` (víceúrovňové suffixy) + `category_map` filtr. Export: **220× `symbol="111"`** (combined budova), 0× helper. Memory: `omap-xml-gotchas`, `template-aware-symbol-codes`. [2026-05-20 sezení 11]
- [x] **BLACK regrese fix (category filtr v resolveru)** — `resolve_default_area_code` bral AreaSymboly bez ohledu na barvu → v ISSprOM by BLACK default povýšil na 526.1 (budova je tam GRAY, ne black) a nalepil ji na černé fragmenty. Fix: `category_map` filtr — default kategorie musí být symbol té barvy. BLACK Garching → "526" (zahodí se, správně), 154 černých fragmentů NEpovýšeno na budovy. Memory: `verify-domain-claims-against-source`. [2026-05-20 sezení 11]
- [x] **Mislabeling "154 budov" vyvrácen** — diář Sezení 10 tvrdil "154 budov přeskočeno". Empirie: těch 154 objektů s kódem "526" má median 26 px = drobné černé fragmenty, NE budovy (budovy jsou gray, median 1297 px). Jejich zahození je správné. Past z memory `verify-domain-claims-against-source`. [2026-05-20 sezení 11]

## L-roh merge + georef robustnost + třetí pár Garching (sezení 10)

- [x] **L-roh merge** — `_merge_segments` v `db2omap.py` (post-trace, před approxPolyDP). Segment-trace láme linii v každém deg≠2 uzlu; 89 % z nich jsou "staircase" pixely 8-souvislé Zhang-Suen kostry (zalomení/diagonála, ne větvení — `lcorner_probe` na Slovance: 573 staircase / 68 junction). Merge spáruje ve sdíleném uzlu segmenty se směry "ven" pod prahem (ohyb < 40°, směr z k=4 px) a sřetězí je. Pravé větvení (dotyk vrstevnice s valem/kamenem) zůstane dělené. Slovanka 3018→2471 segmentů (−18 %), forest 332→236 (−29 %), obj 1864 32→15. **Invariant pixel-set zachován u 0 objektů** (merge jen přeskupuje, neztrácí délku). Export Slovanka 5968→5421, forest 451→355. Memory: `skeleton-median-misleads`. [2026-05-20 sezení 10]
- [x] **N↔S flip fix (bbox-fit `_make_transform`)** — forest export byl vertikálně překlopený. Příčina: mylný předpoklad "OMAP y roste nahoru". Zdroják Mapperu `georeferencing.cpp::updateTransformation` dokazuje opak: `scale(scale, -scale)` flipuje y až na rozhraní map↔projected (kompenzace UTM north-up), paper-space je top-down (y dolů jako pixel y). Fix: `my = min_y + (py/H)·span_y` bez flipu. Rigorózní Slovanka byla správně (skládá pravý Mapper vzorec). Validace Sezení 9 byla slepá k flipu (mapa má obsah všude). Memory: `georef-paper-space-not-world`, `verify-domain-claims-against-source`. [2026-05-20 sezení 10]
- [x] **Georef parsing fix (`_parse_georef`)** — bral první `<ref_point>` v souboru → u Garchingu chybně map ref (10,35) místo projected UTM. Fix: projected ref cíleně z `<projected_crs>` bloku, map ref z root-level `<ref_point>` (default 0,0), `auxiliary_scale_factor` (default 1.0). `_build_map_to_proj` odečítá map_ref a násobí aux. Slovanka beze změny (žádná regrese). Memory: `omap-xml-gotchas`. [2026-05-20 sezení 10]
- [x] **Třetí testovací pár Garching (ISSprOM sprint 1:4000)** — uživatel dodal čistý map-only raster + `.pgw` (původně poster s legendou). End-to-end pipeline: Stage 2 (39 barev ISSprOM ✓, nová `gray` kategorie), detect 1774 obj, **rigorózní `.pgw` export 5470 obj — bbox = GT bbox přesně**. Georef fix ověřen na 3 párech. Odhalil díry: gray detektor chybí, ISSprOM combined kódy (→ TODO). [2026-05-20 sezení 10]

## Template-aware symbol codes + area RGB-collision fix (sezení 8)

- [x] **Template-aware symbol codes** — `resolve_brown_line_codes(library)` v `brown_line_v1` (regex `^101(\.\d+)?$`, fallback default) + `resolve_default_area_code(library, category)` v `area_v1`. Caller (`pic2db.cmd_detect`) parsuje library jednou, resolvuje a předá kódy jako stringy (detektor nezná omap_model). Slovanka: 101.0/102.0, default 403.0/406.1/526.0. Forest sample beze změny (holé kódy). Blokátor db2omap exportu odstraněn. Memory: `template-aware-symbol-codes`. [2026-05-20 sezení 8]
- [x] **YELLOW 403.1 "over-detection" = mislabeling** — diagnostika odhalila, že NEjde o over-detection. OMAP má páry s identickou RGB (403.0≡403.1, 401.0≡401.1), color separation je nerozliší, `deduplicate_by_rgb` zahodí jednu priority masku, disambiguace lepila přeživší `.1` variantu (vzácná OOM-custom "upraveno") na vše. Důkaz: 1019 det / 945 GT (403.0+403.1) = 1.08×. Memory: `verify-domain-claims-against-source`, `omap-rgb-collision-variants`. [2026-05-20 sezení 8]
- [x] **`build_priority_to_area_code` RGB grouping** — seskupuje area symboly podle resolved RGB (`_priority_to_rgb`), ne podle priority indexu. Vybírá základní variantu (`_base_variant` = nejnižší ISOM kód). Ambiguous skupina (víc base shodné barvy) → nejnižší base, ne fallback na cizí barvu. Slovanka: priority 27→403.0 (bylo 403.1), 24→401.0. [2026-05-20 sezení 8]
- [x] **`area_v1.detect()` + `default_code` param** — template-aware default fallback. Forest sample zlepšení bez regrese: 401 nově rozlišeno (4/6 GT), 406 přesnější (49 vs GT 45, bylo 55). [2026-05-20 sezení 8]

## db2omap rigorózní georef + line vektorizace (sezení 9)

- [x] **Rigorózní georef přes `.pgw` + OMAP georeferencing** — `build_georef_transform` v `db2omap.py` skládá afinní matice `pixel --[.pgw]--> UTM --[projectedToMap]--> OMAP coord`. Klíč: OMAP coord je paper-space, pixel→coord je scale+translace+y-flip BEZ rotace (rotace grivation se ve složení vyruší). Znaménko ověřeno empiricky: `MapToProj = proj_ref + scale·1e-6·R(-grivation)·diag(1,-1)·map`. Helpery `_parse_pgw`, `_parse_georef`, `_build_map_to_proj`. Škáluje mask px → full px (detekce na downscale). Ověřeno 4×: 100 % GT coords uvnitř PNG (y vyplní výšku), 92.9 % centroidů na ne-bílém pixelu, export bbox ≈ GT bbox (99 %), vizuální overlay sedí na struktury mapy. Memory: `georef-paper-space-not-world`, `png-dpi-pitfalls`. [2026-05-20 sezení 9]
- [x] **`export()` + `--pgw`/`--pgw-width`** — `pgw_path`/`pgw_width` param, volba georef vs bbox-fit fallback (Local CRS / chybí `.pgw` → bbox-fit). `pic2db export` CLI argumenty. Forest sample zůstává na bbox-fit (PNG kontaminovaný Paint.NET). [2026-05-20 sezení 9]
- [x] **Line vektorizace segment-trace** — `_trace_skeleton` přepsán: kostra jako graf (uzly = deg≠2, hrany = řetězy deg-2 pixelů), každá hrana → samostatný OMAP path. Neztrácí délku ani u větvených/slitých objektů (greedy walk bral jen 1. větev — u obj 1864 prošel 7 bodů z 2093 px; segment-trace 111 bodů / 32 segmentů). `_object_coords_xml` → `_object_coords_list` (line → víc `<coords>`, area beze změny). Topologie: 94 % jednoduché křivky, 6 % junction = 15 % délky. Limitace v1: L-rohy sekají segment v ohybu (délka zachována). Memory: `skeleton-median-misleads`. [2026-05-20 sezení 9]
- [x] **Skok objektů** — Slovanka small 3759→5968, forest sample 188→451 (degenerátní 1209→95 / 94→25). Segment-trace + min 2 body zachytil krátké linie, které findContours zahazoval jako degenerátní zdvojené smyčky. [2026-05-20 sezení 9]

## db2omap PoC export (sezení 8)

- [~] **`db2omap.py` + `pic2db export` verb** — PoC: areas → kontury (`findContours` + `approxPolyDP`), lines → kontura skeletonu, georef = lineární bbox-fit (pixel→OMAP coord, y-flip), symbols/colors/georef z template OMAP (regex injekce `<objects>`). Forest sample: 188/282 obj zapsáno (94 degenerátních), 0 neznámých symbolů (template-aware se vyplatil), validní OMAP (správný namespace). Produkční verze vyžaduje přesnou georef + line path-tracing + Bezier — viz TODO. [2026-05-20 sezení 8]

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
