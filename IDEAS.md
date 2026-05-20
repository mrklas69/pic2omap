# IDEAS — pic2omap

Raw brainstorming. Konkrétní úkoly migrují do `TODO.md` (až vznikne).
Externí zdroje a existující řešení → viz `RESEARCH.md`.

## Koncept

`pic2omap`: konverze raster mapy (PNG/JPG) → vektorová `.omap` (OpenOrienteering Mapper).

- **Vstup**: orienťácká mapa jako rastr (scan papíru, render z OOM, screenshot).
- **Výstup**: `.omap` soubor s vektorovými objekty napojenými na ISOM / ISSprOM symbol set.
- **Použití**: buď přímo, nebo jako template pro doladění v OOM.

## Architektura pic2db / db2omap (Sezení 5 — aktuální koncept)

> **Datový model a CLI verby**: kanonický zdroj je `docs/db_schema.md`. Tato sekce drží high-level přehled.

Refrejming původního 8-stage pohledu. Hlavní změna: **DB jako mezivrstva**.

```
PNG → pic2db → db.json → db2omap → OMAP
```

- **pic2db**: rozpoznávání symbolů do strukturované DB. Iterativní.
- **db.json**: zdroj pravdy o detekovaném obsahu. Editovatelný, diff-able.
- **db2omap**: serializace DB → OMAP XML. Není detekce, jen mapování.

### Fáze A — strip overlays (one-pass per layer)

Cíl: očistit rastr od non-map elementů. Výstup: clean raster + DB záznamy typu `non_map_element` (db2omap může chtít zachovat trať jako template).

1. **Texty a písmena** — OCR (Tesseract?) nebo blob-based detekce kompaktních non-category shapes.
2. **Loga, jiná grafika** — sponzoři, popisky kontrol. Detekce: barvy mimo ISOM paletu / velké souvislé bloky.
3. **PurplePen (trať)** — fialová vrstva, **auto-detect**: pokud rastr obsahuje fialové pixely → strip; bez fialové se krok přeskočí.

Stop: každá vrstva one-pass, žádná iterace.

### Fáze B — content recognition (iterativní, anotativní claiming)

Každý pixel získá claim `{symbol_id, confidence}`. Další pass pracuje pouze s unclaimed pixely. Pořadí **lowest-confusion first**:

4. **Plochy (areas)** — velké souvislé regiony, nejmíň ambiguous.
5. **Linie (lines)** — skeleton-based, vnitřní ambiguity (vrstevnice vs cesta vs plot).
6. **Body (points)** — nejmenší, nejvíc šum-podobné. Záměrně až po liniích.
7. **Re-linie (reconnect)** — kritický krok: 418/536 přerušuje vrstevnici. Po claim odstranění bodů zkus napojit přerušené linie.

Stop iterace fáze B (kterékoli první):
- **Konvergence**: nových claimů < 1 % objektů mezi iter N a N+1.
- **Cap**: max 3 iterace (víc = signál na bug v claim logice).

### Klíčové designové volby

- **Anotativní claiming**, ne destruktivní. Iterace = update claimů, ne vymazání pixelů. Reverzibilní, debug-friendly.
- **DB formát = JSON** (`output/<sample>/db/iter_N.json`). Dataclasses + `to_dict`/`from_dict`. Diff mezi iteracemi je grep-friendly. Při škálování na velké mapy lze přejít na Parquet/SQLite — pro forest sample (~540 objektů) JSON stačí.
- **PurplePen presence = auto-detect** (existence fialových pixelů). Fáze A není povinná pro každý vstup.

## Pipeline (8 stages) — historický rozklad

Původní pohled ze Sezení 1, dnes nahrazený pic2db/db2omap architekturou (výše).
Aktuální stav stages: viz `README.md` (kanonický zdroj). Historicky:

`PNG → [1] preprocess → [2] color separation → [3] per-color raster ops → [4] symbol recognition → [5] vektorizace → [6] topology fix → [7] georef → [8] OMAP serializace`

**Pozn.**: Stage 2 přepsán z původního K-means na palette-based separation. Důvod: máme fixní paletu z library (22 barev pro ISOM, 39 pro complete map). Nejbližší barva v LAB prostoru = deterministické, žádný unsupervised clustering, žádné K-tuning.

## Klíčové problémy

- **Sémantika ≠ barva.** Černá = cesta + plot + balvan + budova + číslo kontroly + text.
  Hnědá = vrstevnice + suchý příkop + jáma + erozní rýha. Tvarem velmi podobné.
- **Anti-aliasing rozhazuje podobné barvy.** Vyřešeno [Sezení 2]: `ColorCategory` vrstva slučuje podobné barvy do sémantických rodin (BROWN family = Brown + Brown 50% + OpenOrienteering Orange) podle HSV hue klasifikace. Anti-aliased pixely na hraně Brown/Orange teď spadnou do BROWN.
- **Pattern fills.** Žlutá s tečkami (otevřeno s rozptýlenými stromy), zelená šrafa svisle vs. vodorovně (pasečina vs. nepřístupné) → Fourier / autokorelační analýza.
- **Překryvy.** Černá cesta přes hnědou vrstevnici "ukousne" vrstevnici → musí se rekonstruovat průchodem.
- **Bezier fitting.** OOM používá kubické Beziery, ne polyline. Naivní fitting produkuje křivky s 10× víc kontrolních bodů než člověk → performance + editovatelnost trpí.
- **Symbol set version.** ISOM 2000 vs ISOM 2017-2 vs ISSprOM 2019-2 (sprint) — odlišné ID, odlišné kódy. Musí být datově parametrizovatelné (YAML mapping), ne hardcoded.

## Alternativní přístupy

### A) Full pipeline (heuristický)

Ruční klasifikátor per symbol. 6–12 měsíců práce. Křehké, ale deterministické a debugovatelné.

### B) ML-first (CNN segmentace)

U-Net / DeepLab segmentace per-pixel → symbol class.
- Trénink na **syntetických datech**: existující `.omap` → render → degradace (rotace, šum, blur, paper texture) → spárované `(image, mask)` pairs.
- (+) Škálovatelné, žádné hand-tuning klasifikátory.
- (−) Potřebuje GPU, training pipeline; dataset se ale generuje sám z OOM.

### C) Semi-auto / assist (KISS)

**Nepokoušet se o plnou automatizaci.** Místo toho nástroje **akcelerující ruční kreslení** v OOM:
- Color separator → 7 barevných PNG vrstev jako template (uživatel vidí jen "hnědou vrstvu").
- "Trace this stroke" — uživatel klikne, nástroj odsleduje křivku, navrhne symbol.
- Auto-suggest contours (jen hnědá, jen plynulé čáry, vysoká hustota) → uživatel potvrdí.
- **MVP za týdny, ne měsíce.** Reálná hodnota pro uživatele.

### D) Build on CoVe (preferované)

**CoVe** (Contour Vectorizer, `github.com/lpechacek/cove`) je už integrovaný v OOM a dělá color-classified line vectorization. Detaily v `RESEARCH.md`.
- Použít CoVe jako základ liniové vektorizace → ušetří měsíce práce na stage 2+3+5.
- Dodělat to, co CoVe **neumí**: plochy (area symbols), bodové symboly, automatické napojení na ISOM.
- **MVP za týdny.** Smysluplná produkční hodnota.
- Alternativa "wrap" cesty (Inkscape Trace Bitmap → SVG → OMAP) byla zvažována, ale CoVe je lepší startovní bod.

## Rizika a neznámé

1. **Quality ceiling**: I s plnou pipeline bude výstup horší než manuál. *O kolik* neznáme dokud nezkusíme.
2. **Rozlišení vstupu**: reálná hranice použitelnosti ~150 DPI scanu A4. `resources/u_bonexu.png` (600 px na šířku) je drasticky málo.
3. **Bezier fitting**: produkuje křivky vypadající správně, ale přebobtnalé kontrolními body.
4. **Symbol set drift**: 200+ symbolů → DRY vyžaduje datovou tabulku (YAML), ne hardcoded switch.
5. **Existující práce** (rešerše hotova, viz `RESEARCH.md`): end-to-end raster→OMAP neexistuje. **CoVe** (integrovaný v OOM) řeší color line vectorization. OCAD **nemá** auto-vektorizaci raster scanu (jen LiDAR DEM Wizard a vector→vector CRT). Symbol recognition raster→ISOM nikdo neudělal — díra v trhu.
6. **OMAP formát** je **veřejně dokumentován**: https://www.openorienteering.org/api-docs/mapper/file_format.html. XML namespace, lze generovat čistě z Pythonu, žádný reverse engineering nepotřeba.

## Doporučený směr (fáze)

- **Fáze 0** (1 den, KISS): Definovat **scope**. Jeden typ vstupu (např. OOM rendered PNG ≥ 300 DPI, ISOM 2017-2). Jedna metrika úspěchu.
- **Fáze 1** (1–2 týdny): MVP = D + kus C. **Postavit nad CoVe** (linie už máme) + Python OMAP writer + ruční mapování barva→ISOM symbol. Cíl: vznikne *něco* otevíratelného v OOM, ne "pavučina", ale aproximace mapy.
- **Fáze 2**: Symbol recognition pro **jeden** dominantní typ — vrstevnice (hnědá, plynulé čáry, vysoká hustota).
- **Fáze 3**: ML přístup (B) jen pokud Fáze 2 narazí na strop heuristik.

## Milník v1 + review-driven detekce (Sezení 11)

Strategický obrat. Sezení 8-10 stavěla export / georef / gray budovy (= kroky 5-7),
ale empirie z forest sample odhalila slabý **základ v kroku 4 (rozpoznání)**:

- vrstevnice 101+102 detekováno **138×** vs GT **66×** (2,1× over);
- **žádný bodový detektor** (`geometry_type` jen area/line) → hnědé body 112/113/115/116
  padají do brown-line bucketu a vycházejí jako falešné vrstevnice;
- pokryto ~9 kódů z ~30 forest symbolů.

Betonovali jsme střechu na nedodělaných základech (porušení *first things first*).

### Rozhodnutí

- **Milník v1 = "lesní core"**: vrstevnice (101/102) + plochy (green/yellow/black) +
  budovy — PŘESNĚ (ratio ~1×, správné kódy). Bodové a pattern symboly až potom.
  (Zodpovídá dříve otevřenou Fázi 0 "definovat scope".)
- **Export (krok 7) zamražen**; count-only metrika (krok 8) povýšena na stálou
  **per-symbol DB↔OMAP validaci**. OMAP = správné řešení k PNG; ověřovat VŽDY.
- **Mapař v smyčce jako oponent**: review nástroj (3 obrázky point/line/area s ID +
  per-symbol tabulka GT vs detekováno) → uživatel oponuje per-objekt → iterace detekce.
  Forma: 3 obrázky per `geometry_type` + `--symbols` filtr pro hustá místa.

## ML rozpoznávání symbolů + synthetic data (Sezení 11 THINK)

Prohloubení alternativy "B) ML-first". Branže vektorizaci rastrových map deep
learningem **dělá** (historické/topografické mapy, ECCV 2024 + 2024-25 práce:
CNN segmentace silnic/mokřadů/vrstevnic; CNN vektorizace bodových symbolů;
trénink na **automaticky generovaných datech rekonstrukcí symbolů**). Orienťácky-
specifický model **neexistuje** (díra). Viz `RESEARCH.md` pro zdroje.

### Není to jedna úloha — tři CV problémy

- **Plochy** → *semantic segmentation* (per-pixel třída). Nejvyzrálejší, ML zvládá výborně.
- **Linie** → segmentation + vektorizace (skeletonizace — už máme).
- **Body** → *object/instance detection* (instance + tvar). Řeší bráškův problém ML
  cestou (model se naučí 536 T vs 537 kříž sám).

### SOTA modely (k 2025/26)

- Segmentace: **U-Net** (baseline), **SegFormer** (transformer, efektivní),
  **Mask2Former** (universal semantic+instance).
- Detekce bodů: **YOLOv11** (Ultralytics), **RT-DETR**.
- Foundation: **SAM 2** (Meta, promptable) — ale třídně-agnostický, potřebuje klasif. hlavu.

### Killer výhoda — synthetic data z OMAP

Důvod, proč to NENÍ bez šance. ML obvykle umírá na nedostatek labeled dat; my
generujeme **neomezeně**: `.omap` → render → `(obrázek, per-pixel maska symbolů)`,
ground truth zadarmo a dokonalý. Augmentace (šum, blur, rotace, papír, JPEG,
vyblednutí) napodobí scany. Doménové výhody (konečná paleta, množina symbolů,
předepsané rozměry, pořadí vrstev) render věrně reprodukuje.

**Dvojí hodnota:** synthetic render dá **pixel-perfect alignment obrázek↔maska** →
vyřeší i náš current evaluační blokátor (per-objekt GT matching ztroskotal na ~5mm
georef nepřesnosti, viz [[gt-db-matching-needs-georef]]). Takže pipeline má hodnotu
**i bez ML** — přesná evaluace cv2 detektorů.

### Rizika

- **Domain gap render→scan** (největší). Augmentace pomáhá, negarantuje.
- **Renderer** — kdo věrně vykreslí `.omap` → obrázek (vrstvy, anti-alias, pattern fill)?
  OOM CLI export? Vlastní renderer (máme parser + geometrii symbolů, ale věrný render je práce).
- **Vektorizace masek → DB** zůstává (Stage 5).
- **Infra** — GPU trénink, serving, MLOps. Velká investice vs cv2.
- **Class imbalance** — vzácné symboly podreprezentované; v synthetic lze cíleně přesytit.

### Doporučené fázování (low-regret)

1. **Synthetic data/eval pipeline** (first) — `.omap` → render → `(image, mask)`. Hned na
   pixel-perfect evaluaci cv2 (odemkne ladění blokované georef). Základ pro ML.
2. **ML pilot: segmentace ploch** — nejsnazší win, ověří pipeline + domain gap.
3. **ML detekce bodů** (pokud pilot vyjde) — bráškův problém systematicky.
4. **Hybrid** — ML kde vyhrává, cv2 baseline jinde.

ML = paralelní track, ne náhrada current práce. Synthetic pipeline = nejlepší společný základ.

## ML pilot — segmentace ploch (Sezení 12, → TODO)

Konkretizace „B) ML-first" do akčního pilotu. Uživatel rozhodl jít cestou trénovaného
modelu. **Pilot-first**: levný pilot segmentace ploch jako brána před investicí do generátoru.

- **Maska z `.omap` geometrie, ne z barev PNG** — jádro architektury. Color-classify PNG by
  učil model jen color separation (umíme v cv2 = nulová ML hodnota). Autoritativní pravda = vektor.
- **Cílový vstup = degradované reálné skeny** (mapy po závodě / staré se ztraceným zdrojem) →
  domain gap = hlavní bitva, agresivní augmentace (on-the-fly při tréninku, ne v datasetu).
- **Renderer: OOM 0.9.5 GUI-only** (ověřeno) → headless render `.omap`→PNG nejde; scale track
  potřebuje vlastní renderer nebo novější OOM. Pilot ale renderer NEpotřebuje (reálné PNG už máme).
- **Komponenty:** #1 mask generator (`omap_mask.py`, hotovo — reality-check georef OK na úrovni
  ploch i přes ~5mm), #2 dataset builder (`build_dataset.py`, hotovo — spatial split), #3-4 U-Net
  trénink (smp, na „mrkla"), #5 eval IoU = go/no-go pro scale.
- **Riziko dat:** ~3-6 reálných `.omap`, 1 lesní velká (Slovanka). Pilot = spatial split jedné
  mapy (within-domain čistý signál). Generalizace přes mapy = potřebuje víc map nebo scale generátor.
- **Třídy = úroveň `ColorCategory`** (8 tříd), ne ISOM kódy (pilot granularita).

## Otevřené otázky

### Zodpovězeno

- ~~Cílový symbolset~~ (S2) → **OOM-native (ISOM 2000-based)**, ne IOF přepisování. Sprint zatím mimo scope.
- ~~Jazyk implementace~~ (S2) → **Python** (numpy + opencv + skimage).
- ~~Strategie symbolové DB~~ (S2) → **Extrahovat z OMAP parserem**, ne psát ručně z PDF. Jediný zdroj pravdy = OMAP soubor.
- ~~Metrika úspěchu pro Fázi 0~~ (S4+S6) → `compare_to_omap.py` counts per (ColorCategory, ComponentType) + per-symbol breakdown + `--symbols` filter pro per-detector validaci. IoU geometrická metrika odložena po Stage 5 (TODO).
- ~~Strategie integrace s CoVe~~ (S2 update) → vlastní palette-based separation funguje výborně, CoVe nepotřebujeme. Reconsider pokud Stage 5 (vektorizace) bude problematická.
- ~~DB jako mezivrstva~~ (S5+S6) → **Implementováno**: `pic2db` (raster → DB) / `db2omap` (DB → OMAP) split. `db_model.py` + `pic2db.py`. Kanonický zdroj: `docs/db_schema.md`.

### Otevřené

- **OCR pro text** (čísla kontrol, popisky)? Title "Forest map sample" je v rasteru, ale není mapový obsah → spíš oříznout než OCRovat. Fáze A `NonMapElement` schema připraveno (`db_schema.md`), implementace neproběhla.
- **Fialová barva** (kurz, kontroly) — vždy ignorovat, nebo nabídnout volbu? Forest sample 0 fialových pixelů, irrelevantní. `IDEAS.md` Fáze A "auto-detect PurplePen" navržen.
- **Detekce spec verze OMAP** — soubory neuvádějí explicitně ISOM 2000 vs 2017-2 vs ISSprOM 2019-2. Heuristika: měřítko + jména barev + struktura. Vazba na TODO.md.
- **Anotovaný dataset pro ML přístup (B)** — vyrobit syntetický z OOM renderů, nebo manuálně anotovat reálné mapy? Sekundární — heuristiky možná vystačí.
