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
- [ ] **Ground truth comparison** — skript `compare_to_omap.py`: načte `forest sample.omap`, spočítá objekty per category (vrstevnice = Brown linie 101/102/103) a porovná s pipeline výstupem (kolik connected components v brown mask).

## Symbol layer 2 (pro Stage 4)

- [ ] **SymbolProfile** — `symbol_profile.py`: per-symbol key features (line width v px po georef, dashed Y/N, dash period, point shape signature, area pattern fingerprint). Builder ze SymbolLibrary.

## Infrastruktura

- [ ] **`requirements.txt`** — explicitní seznam závislostí (numpy, opencv-python, scikit-image). Verze podle aktuálního pip freeze.
- [ ] **Sprint scope** — sehnat oficiální `ISSprOM_2019-2.omap` template z OOM symbol sets distribuce. Bez něj nelze pokrýt sprint mapy (aktuální OMAP soubory jsou všechny ISOM 2000-based).

## Otevřené architektonické otázky

- [ ] **Metrika úspěchu pro Fázi 0** — co je "MVP funguje"? IoU per category? Počet vrstevnic detect vs OMAP? Pixel accuracy v overview? Vázáno na definici scope.
- [ ] **Detekce OMAP spec verze** — soubory neuvádějí ISOM 2000 vs 2017-2. Heuristika: měřítko + jména barev + struktura symbolů. Nutné pro pic2omap → výstup s konzistentními kódy.
