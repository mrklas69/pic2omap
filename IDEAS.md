# IDEAS — pic2omap

Raw brainstorming. Konkrétní úkoly migrují do `TODO.md` (až vznikne).
Externí zdroje a existující řešení → viz `RESEARCH.md`.

## Koncept

`pic2omap`: konverze raster mapy (PNG/JPG) → vektorová `.omap` (OpenOrienteering Mapper).

- **Vstup**: orienťácká mapa jako rastr (scan papíru, render z OOM, screenshot).
- **Výstup**: `.omap` soubor s vektorovými objekty napojenými na ISOM / ISSprOM symbol set.
- **Použití**: buď přímo, nebo jako template pro doladění v OOM.

## Pipeline (8 stages)

`PNG → [1] preprocess → [2] color separation → [3] per-color raster ops → [4] symbol recognition → [5] vektorizace → [6] topology fix → [7] georef → [8] OMAP serializace`

| # | Stage | Obtížnost | Stav |
|---|-------|-----------|------|
| 1 | Preprocess (deskew, denoise, normalizace barev) | nízká | ☐ |
| 2 | Color separation (palette-based, LAB nearest) | střední | **✓** |
| 3 | Per-color ops (connected components, skeletonizace, pattern detection) | střední | **✓** (pattern detection odložen do Stage 4) |
| 4 | **Symbol recognition** (cesta / plot / vrstevnice / balvan / text) | **vysoká** | ☐ |
| 5 | Vektorizace (skeleton → polyline → Bezier — Schneider 1990) | střední | ☐ |
| 6 | Topology fix (snap endpoints, close polygons, T-junctions) | střední | ☐ |
| 7 | Georeferencing (scale, origin, rotace — bez metadat nutný user input) | nízká | ☐ |
| 8 | OMAP XML serializace + mapování na konkrétní symbol set | nízká | ☐ |

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

## Otevřené otázky

### Zodpovězeno (Sezení 2)

- ~~Cílový symbolset~~ → **OOM-native (ISOM 2000-based, jak je v OMAP)**, ne IOF přepisování. Sprint zatím mimo scope (nemáme ISSprOM template).
- ~~Jazyk implementace~~ → **Python** (potvrzeno; numpy 2.4 + opencv 4.13 + skimage 0.26).
- ~~Strategie symbolové DB~~ → **Extrahovat z OMAP parserem**, ne psát ručně z PDF. Jediný zdroj pravdy = `complete map.omap` (resp. další OMAP soubory v `resources/`).

### Otevřené

- Co s textem (čísla kontrol, popisky)? OCR (Tesseract?) nebo ignorovat? Title "Forest map sample" je v rasteru, ale není mapový obsah → spíš oříznout než OCRovat.
- Fialová barva (kurz, kontroly) — vždy ignorovat, nebo nabídnout volbu? V `forest sample.png` 0 fialových pixelů, tj. zatím irrelevantní.
- Strategie integrace s CoVe: vendoring / fork / přispět upstream / použít OOM jako headless service? **Update Sezení 2**: vlastní palette-based separation funguje výborně, CoVe možná nepotřebujeme — vrátit se k tomu, pokud Stage 5 (vektorizace) bude šlapat.
- Anotovaný dataset pro ML přístup (B) — vyrobit syntetický z OOM renderů, nebo manuálně anotovat reálné mapy? Sekundární otázka — heuristiky možná vystačí.
- **Nové (Sezení 2)**: jak detekovat spec verzi OMAP souboru? Měřítko + barvy + jména symbolů jsou indicie, ale nedostačující — soubory neuvádějí explicitně ISOM 2000 vs 2017-2 vs ISSprOM 2019-2. Hrozí miscoding při OMAP exportu.
- **Nové (Sezení 2)**: jaká je správná metrika úspěchu pro pic2omap? Counts (počet vrstevnic detect vs OMAP) / IoU per category mask / pixel accuracy quantization? Vázáno na Fázi 0 scope definici.
