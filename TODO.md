# TODO — pic2omap

Pracovní úkoly. Hotové migrují do `DONE.md`. Brainstorming nápadů → `IDEAS.md`.

## Stage 3 — doladění

- [ ] **AREA filtrování** — krátké tlusté fragmenty čar (density > 0.5) se schovaly v AREA. Stage 4 bude potřebovat min-size threshold nebo pattern-based filter, aby je odlišil od skutečných ploch.
- [ ] **Pattern detection (P2)** — `cat_green_area.png` obsahuje šrafu (svislé čárky 412/413). Pattern fill ≠ solid area. Vyžaduje Fourier / autokorelaci nebo line-density detektor. Patří spíš do Stage 4 (symbol recognition).
- [ ] **Per-DPI škálování thresholdů** — `MIN_AREA=4, POINT_MAX_AREA=30, AREA_MIN_DENSITY=0.5` jsou kalibrované na 631×478 forest sample. Pro jiné rozlišení/DPI škálovat lineárně (nebo přejít na fyzické mm/inch units).

## Stage 4 — Symbol recognition

- [x] **Vrstevnice (Brown) v1** — thickness peak detector (`brown_line_v1.py`). 138 objektů na forest sample (112 × 101, 26 × 102). Over-segmentace 2.09×, řeší re-link iterace.
- [~] **109 Erosion gully discrimination** — `erosion_gully_v1` (crossing + pointed cap) odpojen v cmd_detect, 0/17 precision. GT je jen **2 × 109** ve forest sample. Signály thickness/cap nestačí — vyžaduje pozici-based check ("leží mezi 101 sousedy"). Soubor zůstává jako reference. Detail: viz memory `erosion-gully-vs-index-contour`.
- [ ] **110 Small erosion gully** — line_width=0 + mid_symbol Brown tečka. 16× v forest sample. **Patří do point/dot detectoru**, ne brown_line. Bude součást budoucího `brown_dot_v1`.
- [ ] **Stage 2/3 brown skeleton contamination** — urban roads (forest sample #122, ISSprOM 529/503) padají do cat_brown_clean.png. Color separator nebo category mapping zachycuje sprint symboly jako BROWN. Vyšetřit color_category overrides nebo per-OMAP-version paletu.
- [ ] **103 Form line (dashed brown)** — dash pattern detector v skeletonu (mezi-mezera mezery). Ujme se další chunk z mid peaku.
- [ ] **Bodové symboly** — z `cat_*_point.png` rozpoznat ISOM symboly (boulder 206/207, knoll 109, pit 114) podle tvaru. Šablonové matchingem nebo signaturou (compactness, kruhovitost, dot vs X).

## Stage 2 — Doplnění

- [ ] **Map area extraction** — title "Forest map sample" je nad mapou, rozhazuje statistiku. Auto-detekce mapového obdélníku (např. najít největší kompaktní region "non-white"), nebo manuální ROI parametr.

## Ground truth — doladění (compare_to_omap.py)

- [ ] **Brown line filtering (jen vrstevnice)** — momentálně GT BROWN line=96 obsahuje i 4 Minor road, 4 Earth bank, 2+16 Erosion gully, 1 Earth wall. Pro Stage 4 vrstevnicový detektor potřebujeme přesnou metriku jen pro 101/102/103 (= 69 objektů). Přidat `--symbols 101,102,103` CLI flag.
- [ ] **IoU / geometrická metrika** — counts jsou hrubá metrika (oversegmentace skrytá ve fragmentaci). Po Stage 5 (vektorizace) přidat porovnání délek linií v mm a ploch v mm², přepočet OMAP units → pixel via georef.

## Symbol layer 2 (pro Stage 4)

- [ ] **SymbolProfile** — `symbol_profile.py`: per-symbol key features (line width v px po georef, dashed Y/N, dash period, point shape signature, area pattern fingerprint). Builder ze SymbolLibrary.

## Dokumentace (pro %AUDIT:DOCS)

- [ ] **Single source of truth pro pipeline status** — tabulka 8 stages se ☐/✓ existuje na 5+ místech (README, IDEAS, DIARY sezení 2/3/4). Drift hrozí při každé změně stavu. Návrh: README = kanonický, ostatní jen odkazují. Diary sezení drží pouze *delta* sezení, ne celkový stav. Vyřešit při příštím %AUDIT:DOCS.

## Infrastruktura

- [ ] **`requirements.txt`** — explicitní seznam závislostí (numpy, opencv-python, scikit-image). Verze podle aktuálního pip freeze.
- [ ] **Sprint scope** — sehnat oficiální `ISSprOM_2019-2.omap` template z OOM symbol sets distribuce. Bez něj nelze pokrýt sprint mapy (aktuální OMAP soubory jsou všechny ISOM 2000-based).

## Otevřené architektonické otázky

- [~] **Metrika úspěchu pro Fázi 0** — počty objektů per (category, type) implementovány (`compare_to_omap.py`). Slabost: counts jsou hrubé, oversegmentace zkresluje (BROWN line 2.26×). Doplnit IoU / geometrickou metriku po Stage 5.
- [ ] **Detekce OMAP spec verze** — soubory neuvádějí ISOM 2000 vs 2017-2. Heuristika: měřítko + jména barev + struktura symbolů. Nutné pro pic2omap → výstup s konzistentními kódy.
