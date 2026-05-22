# TODO — pic2omap

Pracovní úkoly. Hotové migrují do `DONE.md`. Brainstorming nápadů → `IDEAS.md`.

## Krok 4 fokus — review-driven detekce (Sezení 11)

> **Milník v1 = "lesní core"**: vrstevnice (101/102) + plochy (green/yellow/black) +
> budovy přesně (ratio ~1×, správné kódy). Bodové/pattern symboly až potom.
> Export (krok 7) zamražen. Detail: `IDEAS.md` "Milník v1".

- [ ] **Per-objekt matching GT↔DB** — zkoušeno (sezení 11), odloženo. Nearest-centroid
  produkoval >90 % falešných párů: forest nemá přesný georef (bbox-fit), Garching `.pgw`
  je jen ~5mm přesný (jen 15 % budov sedí do své velikosti). Potřebuje (a) přesný georef,
  (b) odfiltrovat legendu z `.omap` GT, (c) možná IoU overlap místo centroidu. Bez něj
  se GT (coord) a naše (raster) pozice 1:1 neslícují.
- [ ] **Brown-line precision audit (138 vs 66 GT)** — proč 2,1× over. Mix mislabeled
  hnědých bodů (115/116/112/113 nemají point detektor) + over-segmentace vrstevnic.
  Po review identifikovat, kolik je čeho.
- [ ] **Point detektor v2 — redukce over-claim** — v1 over-claimuje 7–34× (forest brown
  235 vs GT 7, black 58 vs 4, green 147 vs 21): point bucket plný fragmentů linií. Potřebuje:
  (a) **izolovanost** — komponenta sousedící s line/area claim_mask = odříznutý fragment,
  ne bod; (b) **tvarová disambiguace** per symbol (115 oblouk / 116 plný / 112 tečka);
  (c) per-objekt GT matching pro kalibraci prahů (= přesný georef). Memory `sparse-gt-naive-detector-trap`.
- [ ] **Point disambiguace + odebrat body z brown-line** — default jeden kód per kategorie
  (115/536/418) → 419/116/532/540 vždy MISSING. Per-tvar klasifikace. Plus brown-line
  bere body do 101/102 (138 vs 66 GT) — odebrat point pixely z line claimů.
- [ ] **template_point_v1 — produkční tvarový detektor** (PoC hotový sezení 11) — render
  tvaru symbolu z OMAP geometrie + diskriminativní match (foreground + forbidden prstenec),
  vrací top-N kandidátů se skóre. Pro tvarové symboly (536 tower, 537 cross, knolly), kde
  bucket selhává. PoC: oba posedy top-3 z 226 fragmentů. Generalizovat z `point_template_poc.py`:
  area/point elementy (zatím jen line), rotace (rotatable symboly), per-symbol konfig.
  Memory `template-match-point-detection`.
- [ ] **Vision-ověření kandidátů (hybrid cv2+vision)** — diskriminativní match zúží na ~6
  kandidátů (100 % recall), ale poslední false positives (roh budovy = lokální T) cv2
  neodliší. Claude vision (API) ověří zúžené kandidáty dle kontextu — jako bráška. Strop
  čistého cv2 ~33 % precision na top kandidátech.

## ML pilot — segmentace ploch (Sezení 12)

> **Cíl pilotu (go/no-go):** naučí se U-Net segmentovat plochy z reálného obrázku,
> když masku vezmeme z `.omap` geometrie? Metrika = IoU per třída na held-out mapě.
> Rozhodne, jestli investovat do procedurálního generátoru + rendereru pro scale.
> Vstup cílově = degradované reálné skeny → domain gap = hlavní bitva (agresivní
> augmentace). Trénink na GPU stroji "mrkla", vývoj tady. Detail: `IDEAS.md` "ML pilot".

- [x] **Komponenta #1 — mask generator** (sezení 12) — `omap_mask.py`: area objekty
  z `.omap` → coord→pixel transform (re-use db2omap georef, obrácený směr) → fillPoly →
  uint8 maska class indexů (ColorCategory úroveň, 8 tříd). Bezier tessellation + holes +
  priority řazení. Solid fill jen (inner_color != -1; pattern-only overlaye jako severky
  601 přeskočeny — jinak přemažou plochy pod sebou). Overlay reality-check: Garching +
  Slovanka **alignment OK**, ~5mm georef na úrovni ploch nevadí. → DONE.
- [x] **Komponenta #2 — dataset builder** (sezení 12) — `build_dataset.py`: tiling 512×512 +
  `manifest.json`. Split po CELÝCH mapách (leakage); pilot = spatial split Slovanky (train 234 /
  val 62 dlaždic within-domain) + Garching test 22 (cross-domain). `_ink_fraction` filtr (mimo
  mapu). Augmentace VĚDOMĚ ne tady — patří na trénink (#3). → DONE.
- [x] **Komponenta #3+4 — `train.py` + U-Net trénink** (sezení 13) — `train.py`: `SegDataset`
  (manifest.json, BGR→RGB), smp U-Net resnet34/ImageNet, **mírná** augmentace albumentations (volba:
  domain gap se v pilotu nevaliduje, val/test jsou rendery; agresivní balík zakomentovaný), Dice+CE
  loss, per-class IoU (smp.metrics), checkpoint best mIoU, bez Lightning. `requirements-ml.txt`
  (torch/smp/albumentations zvlášť, CPU/CUDA pokyny). Smoke-test CPU OK; **CPU sanity 5 epoch
  prokázal učení** (val mIoU 0.61, bg/green/yellow ~0.9). → DONE.
- [ ] **Plný trénink na „mrkla" (GPU) — RUNBOOK** (self-contained: mrkla je jiný stroj
  s vlastní/prázdnou memory, tahle poznámka nesmí spoléhat na memory tohoto klonu).
  - **Přenos dat:** `output/dataset.zip` (~57 MB, 1081 dlaždic, sezení 17) **nebo** regenerovat:
    `python build_dataset.py` (deterministické; `DATASET_MAPS` = Slovanka spatial + Bedrichovka +
    Blatna train + Garching test). Rozbalit do `output/dataset/`.
  - **Prostředí:** `pip install -r requirements-ml.txt` s **CUDA** torch buildem (viz hlavička
    souboru — `--index-url` pro CUDA wheel). Torch NENÍ v `requirements.txt` (cv2 dev stack).
  - **Trénink:** `python train.py --epochs 40 --batch 16 --seed 42 --workers 4` →
    `output/checkpoints/best.pt` (best-mIoU checkpoint). GPU ~10–30 min/40 epoch.
  - **Re-eval:** `python eval.py --split test` (cross-domain Garching) + `--split val`
    (within-domain Slovanka). Triptych overlay foto|GT|predikce.
  - **Baseline k porovnání** (15-epoch běh, JEN Slovanka v trainu, PO georef fixu — sezení 14/16):
    within-domain val mIoU **0,666** (bg/green/yellow 0,91–0,95, blue 0,45, black 0,74, brown 0,00→0,25);
    cross-domain test (Garching) mIoU **0,340**, green **0,875**, ale **gray/black/brown = 0,00**.
  - **Co od tohoto běhu čekat (hypotéza sezení 17):** train teď má 3 mapy (997 dlaždic vs 234) a
    **obsahuje gray 0,8 / brown 0,7 / black 0,9 %** (z Bedřichovky) — dřív ≈0. Garching test je
    brown 33 % + gray 23 %, dřív nebylo čím trefit → tyhle třídy by měly z nuly vyrůst. **brown**
    vzácná třída chytá až ~e11 (15-epoch běh 0→0,25); 40 epoch by mělo dotáhnout, jinak class
    weight / oversample. Pozn.: gray v Bedřichovce = skála (ISOM), Garching gray = budovy (ISSprOM)
    — stejná maska-třída, jiný kontext; jestli to pomůže cross-domain, je otevřená otázka.
  - **Kontext z memory tohoto klonu** (mrkla ho jinak nemá): georef byl rozbitý jednotkovým bugem
    `map_ref` (mm vs 1/1000 mm) → opraveno sezení 16, proto je cross-domain baseline teď 0,340 a ne
    0,106; nízké gray/black/brown = reálný ISOM↔ISSprOM class gap (1 sprint mapa jen v testu), NE
    georef. Detail: `docs/diary/2026-05-21.md` sezení 14–17.

## ML scale track — až po go/no-go pilotu

- [ ] **Synthetic render pipeline** — procedurálně generovaný `.omap` → render →
  `(obrázek, pixel-perfect maska)`. Neomezená diverzita + odemkne per-objekt eval cv2.
  **Renderer NELZE přes OOM 0.9.5** (ověřeno sezení 12: GUI-only, žádný headless export/
  konverze — argument = soubor k otevření). Cesty: vlastní renderer (máme `omap_parser` +
  geometrii z template PoC; věrný render = vrstvy + anti-alias + pattern fill = práce),
  nebo ověřit novější OOM (0.9.6+ / fork dg0yt). Pozn.: pro degradované skeny je výhoda
  věrného renderu menší (gap render→sken stejně řeší augmentace).
- [ ] **ML detekce bodů** (po segmentaci) — YOLOv11/RT-DETR, řeší tvarovou disambiguaci
  bodů (536 vs 537) systematicky. Class imbalance vzácných symbolů → přesytit v synthetic.

## Stage 4 — Detektory (priority pro další sezení)

- [ ] **Per-priority area disambiguation v3** — v2 (`area_v1` + `--omap` flag, sezení 7) zlepšil per-symbol klasifikaci 8 % (4× 408 + 3× 404). Limitace: component-level majority threshold (50 %) je moc přísný pro fragmentovanou Stage 3, 410 Opaque Green stále nedetekováno, 408 hodně pod GT. v3: per-pixel priority assignment + split komponenty na sub-areas per dominantní priority. Vyžaduje rework Stage 3 connected components.
- [ ] **Black area per-shape filter** — `area_v1` BLACK detekuje 59/50 GT (1.18× over) ve forest sample. False positives jsou balvany (kruhové) a road fragmenty. Per-shape filter: Building = obdélníkový (aspect_ratio compactness), balvan = kruhový → reject. 527 Settlement / 528 OOB sdílí priority s 526 → disambiguation v2 je nerozliší, nutný shape-based classifier.
- [ ] **Disambiguation performance** — `_disambiguate_component` dělá per-component full-image AND se VŠEMI priority maskami. Slovanka BLACK: 448 komp × 19 masek × 6.5 Mpx = desítky sekund. Omezit overlap na bbox komponenty (crop masku na bbox před AND).
- [ ] **GREEN/YELLOW area under-detection** — Slovanka: 404.0 (8/159), 407.0 (47/242), 408.1 (302/630) pod GT. Color separation slévá blízké odstíny do dominantní barvy (403.0/406.1). 407 je navíc pattern (šrafa) → pattern detektor. Per-component context nebo jemnější paleta.
- [ ] **109 Erosion gully discrimination v2** — `erosion_gully_v1` byl odpojen (0/17 precision,
  GT jen 2× 109) a **smazán (sezení 14)**. v2 vyžaduje pozici-based check ("leží mezi 101 sousedy" —
  sample sousedů perpendiculárně k tangentě). Helper logika (`crossing_signal`, `pointed_cap_count`)
  v git historii; lessons v memory `erosion-gully-vs-index-contour`.
- [ ] **103 Form line v2** — `form_line_v1` odpojeno (20/3 = 6.7× over-claim) a **smazáno (sezení 14)**.
  Sparse GT pattern stejný jako 109. v2 vyžaduje pozici-based check (sekvence ≥ 3 co-linear dashů
  s pravidelnými gaps) nebo multi-sample validaci. Git historie + memory `sparse-gt-naive-detector-trap`.
- [ ] **110 Small erosion gully** — `line_width=0` + `mid_symbol` Brown tečka. 16× ve forest sample. Patří do **point/dot detectoru** (sequence clustering), ne brown line. Budoucí `brown_dot_v1`.
- [ ] **Lake/pond detector (301/302)** — solid blue area. Distinct barva (modrá), low ambiguity.
- [ ] **Pattern fill detector** — 407/409 Undergrowth (zelená šrafa), 415 Cultivated land. Vyžaduje line-density / Fourier detekci pattern fillu jako area type.

## Orientation + Stripe filter

- [ ] **Stripe filter pro rotated maps** (`area_v1._is_vertical_stripe`) — pokud `orientation_deg != 0`, transformovat bbox podle rotace a pak měřit šířku v north-aligned coord. v1 řeší jen orientation=0 case (forest sample).
- [ ] **orientation_v1 fine-tuning** — peak BIN_DEG=1.0° dává rozlišení 1°. Pro fine rotation může chtít 0.25° (s 4× větším histogramem). Plus snížit min_line_length pro mapy s krátkými north lines.
- [ ] **Multi-mapa validace orientation_v1** — currently tested only Slovanka (returns 0.0°, expected 0.0°). Najít rotovanou mapu (declination je v `.pgw`, ne v rasteru — Slovanka má raster north-up i přes deklinaci 3.75°).

## DB infrastruktura

- [ ] **`diff` verb (pic2db.py)** — implementovat porovnání dvou iter_N.json. Vyžaduje persistent ID matching přes IoU bbox + symbol_code (zatím schema-only).
- [~] **`export` verb (db2omap)** — PoC + georef + line vektorizace + L-roh merge hotové.
  Hotovo: areas → kontury, **rigorózní georef** (sezení 9: `.pgw` + OMAP georef,
  pixel→coord bez rotace; bbox-fit fallback pro Local CRS; **sezení 10**: y-down fix
  + map/projected ref_point + map_ref subtrakce + auxiliary_scale_factor — ověřeno na
  3 párech), **line segment-trace** (sezení 9: kostra jako graf, neztrácí délku),
  **L-roh merge** (sezení 10: post-trace `_merge_segments`, slévá staircase + slité
  vrstevnice rovně přes uzel, ohyb < 40°; Slovanka −18 % segmentů, invariant pixel-set
  zachován). Slovanka 5421 obj, forest 355 obj, Garching 5470 obj. Co zbývá:
  - **Bezier fit** — OOM používá kubické Beziery, ne polyline (Schneider fit). Nahradit
    approxPolyDP polyline za Bezier segmenty s flagy v `<coords>`.
  - **Re-linking fragmentů** — vrstevnice silně fragmentované (median 16 px) kvůli
    mid-symbol/černým překryvům. Spojit co-linear sousední segmenty (fáze B re-link).
    (L-roh merge spojuje jen segmenty SDÍLEJÍCÍ uzel; re-link řeší MEZERY = proximity.)
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

- [~] **CombinedSymbol parts parsing** — základ HOTOV (sezení 11): `_parse_combined_symbol`
  plní `parts` z `<part symbol="ID">` (ověřeno auditem sezení 14). Zbývá: inline party
  (bez `symbol` atributu) se vědomě přeskakují — doplnit, pokud bude potřeba (zatím není blocker).

## Dokumentace

- [ ] **`docs/db_schema.md` rozšířit** — popsat fáze A vs B, claim conflict resolution (brown line vs area overlap), 16-bit PNG mask format details.

## Infrastruktura

- [ ] **imread_unicode i pro background/probes** — `pic2db.py:543`, `peak_visualizer.py:238`,
  `border_overlay.py:138` (mark `--background`) stále `cv2.imread` → selže na diakritice v cestě
  (jako Blatná). Drobné, izomorfní s fixem sezení 16 (omap_mask/build_dataset/separate_demo/detect).
- [ ] **`imwrite_unicode` v `cli_utils`** (izomorfní s `imread_unicode`) — `cv2.imwrite(str(path))`
  selže/zapíše mojibake na diakritice v cestě (odhaleno sezení 17: dataset dlaždice + scale_check
  overlay). Helper `imencode`+`write_bytes`. Pak odstranit ASCII-name workaround v `build_dataset`
  (`DATASET_MAPS` name) a opravit `build_dataset.py:146-147`. Drobné.
- [ ] **`requirements.txt`** — explicitní seznam závislostí (numpy, opencv-python, scikit-image). Verze podle aktuálního pip freeze.
- [ ] **Sprint scope** — sehnat oficiální `ISSprOM_2019-2.omap` template z OOM symbol sets distribuce. Bez něj nelze pokrýt sprint mapy.
- [ ] **Test ve Slovanka palette** — Slovanka má jinou color paletu než forest sample (priority 19 = Blue vs Yellow). `color_category.py` overrides možná nejsou robustní napříč mapami. Validovat.

## Audit follow-up (sezení 14 — zbylé nálezy %AUDIT:CODE)

> `parse_coords` kanonizace + `priority==index` assert HOTOVO (sezení 18, viz DONE).
> `compare_to_omap` split → `review_export.py` HOTOVO (sezení 19, viz DONE) — řez „co s čím
> porovnává": compare = GT vs Stage 3 masky (836→549 ř.), review_export = GT vs DB per symbol.
> „3× duplicita" byla 2+1: `georef._compute_coord_bbox` (regex přes celý `<objects>` blob =
> jiná operace, bbox-only) vědomě ponechán jako jediný regex skener — georef nedotčen.

- [ ] **Kosmetika (zbytek)** — `NAME_OVERRIDES`/HSV prahy hardcoded v generickém `color_category`
  (per-soubor paleta = souvisí s D6), CMYK→RGB fallback bez warning (`omap_parser`), lokální
  `csv`/`Counter` importy v tělech funkcí `review_export`/`compare_to_omap` → nahoru (`re` zmizel S18).

> Pozn.: per-DPI škálování thresholdů je samostatný velký bod — viz „Per-DPI škálování thresholdů"
> v sekci Stage 2/3 Cleanup. D2 (sdílená kostra area↔point) vědomě zamítnuta v sezení 14 (KISS).

## Otevřené architektonické otázky

- [~] **Metrika úspěchu pro Fázi 0** — počty objektů per (category, type) implementovány. Slabost: counts jsou hrubé. Doplnit IoU / geometrickou metriku po Stage 5.
- [ ] **Detekce OMAP spec verze** — soubory neuvádějí ISOM 2000 vs 2017-2 explicitně. Heuristika: měřítko + jména barev + struktura symbolů.
- [ ] **Per-OMAP-file color palette** — priority indexy se mezi soubory liší (Slovanka 19=Blue, forest sample 19=Yellow). Detector musí parsovat colors z konkrétního OMAP, ne hardcoded.
