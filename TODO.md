# TODO — pic2omap

Pracovní úkoly. Hotové migrují do `DONE.md`. Brainstorming nápadů → `IDEAS.md`.

## Stage 3 — doladění

- [ ] **AREA filtrování** — krátké tlusté fragmenty čar (density > 0.5) se schovaly v AREA. Stage 4 bude potřebovat min-size threshold nebo pattern-based filter, aby je odlišil od skutečných ploch.
- [ ] **Pattern detection (P2)** — `cat_green_area.png` obsahuje šrafu (svislé čárky 412/413). Pattern fill ≠ solid area. Vyžaduje Fourier / autokorelaci nebo line-density detektor. Patří spíš do Stage 4 (symbol recognition).
- [ ] **Per-DPI škálování thresholdů** — `MIN_AREA=4, POINT_MAX_AREA=30, AREA_MIN_DENSITY=0.5` jsou kalibrované na 631×478 forest sample. Pro jiné rozlišení/DPI škálovat lineárně (nebo přejít na fyzické mm/inch units).

## Stage 4 — Symbol recognition

- [ ] **Vrstevnice (Brown)** — první symbol detector. Vstup: `cat_brown_skeleton.png` (1px středovky). Cíl: rozdělit na 101 Index contour / 102 Contour / 103 Form line podle tloušťky původní čáry a stylu (form line je čárkovaná).
- [ ] **Bodové symboly** — z `cat_*_point.png` rozpoznat ISOM symboly (boulder 206/207, knoll 109, pit 114) podle tvaru. Šablonové matchingem nebo signaturou (compactness, kruhovitost, dot vs X).

## Stage 2 — Doplnění

- [ ] **Map area extraction** — title "Forest map sample" je nad mapou, rozhazuje statistiku. Auto-detekce mapového obdélníku (např. najít největší kompaktní region "non-white"), nebo manuální ROI parametr.

## Ground truth — doladění (compare_to_omap.py)

- [ ] **No-color symbol resolution** — symboly s `inner_color="-1"` a `patterns_count > 0` (Undergrowth 407/409, Distinct vegetation boundary 416, Small erosion gully 110, Small depression 115, …) se přeskakují. V `forest sample.omap` je takových 156 objektů — náš GT je podhodnocený. Rozšířit `symbol_to_color_ref` o čtení barvy z prvního `<pattern>` child elementu, nebo extended parser, který zaznamená pattern barvy do AreaSymbol/LineSymbol.
- [ ] **Brown line filtering (jen vrstevnice)** — momentálně GT BROWN line=80 obsahuje i 4 Minor road, 4 Earth bank, 2 Erosion gully, 1 Earth wall. Pro Stage 4 vrstevnicový detektor potřebujeme přesnou metriku jen pro 101/102/103 (= 69 objektů). Přidat `--symbols 101,102,103` CLI flag.
- [ ] **IoU / geometrická metrika** — counts jsou hrubá metrika (oversegmentace skrytá ve fragmentaci). Po Stage 5 (vektorizace) přidat porovnání délek linií v mm a ploch v mm², přepočet OMAP units → pixel via georef.

## Symbol layer 2 (pro Stage 4)

- [ ] **SymbolProfile** — `symbol_profile.py`: per-symbol key features (line width v px po georef, dashed Y/N, dash period, point shape signature, area pattern fingerprint). Builder ze SymbolLibrary.

## Infrastruktura

- [ ] **`requirements.txt`** — explicitní seznam závislostí (numpy, opencv-python, scikit-image). Verze podle aktuálního pip freeze.
- [ ] **Sprint scope** — sehnat oficiální `ISSprOM_2019-2.omap` template z OOM symbol sets distribuce. Bez něj nelze pokrýt sprint mapy (aktuální OMAP soubory jsou všechny ISOM 2000-based).

## Otevřené architektonické otázky

- [~] **Metrika úspěchu pro Fázi 0** — počty objektů per (category, type) implementovány (`compare_to_omap.py`). Slabost: counts jsou hrubé, oversegmentace zkresluje (BROWN line 2.26×). Doplnit IoU / geometrickou metriku po Stage 5.
- [ ] **Detekce OMAP spec verze** — soubory neuvádějí ISOM 2000 vs 2017-2. Heuristika: měřítko + jména barev + struktura symbolů. Nutné pro pic2omap → výstup s konzistentními kódy.
