# TODO — pic2omap

Pracovní úkoly. Hotové migrují do `DONE.md`. Brainstorming nápadů → `IDEAS.md`.

## Stage 3 — Per-color raster ops

Vstup: per-category masky z `output/<image>/category/*.png`.
Cíl: připravit binární masky k vektorizaci (Stage 5).

- [ ] **Morfologie** — `morphology.py`: opening/closing pro odstranění šumu (1px artefakty z anti-aliasing po color separation). Per-category nastavení (vrstevnice tolerantnější, plochy agresivnější).
- [ ] **Connected components** — pro každou category masku rozdělit komponenty na **linky** (poměr stran), **plochy** (kompaktní, velká plocha), **body** (malé, kruhové). Heuristika přes `cv2.connectedComponentsWithStats`.
- [ ] **Skeletonizace** — pro linky: `skimage.morphology.skeletonize` → 1px středovky. Připravka pro vektorizaci.

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
