# RESEARCH — pic2omap

Externí rešerše: existující nástroje, akademické práce, formáty, komunitní zdroje.
Žije souběžně s `IDEAS.md` — sem patří **co je venku**, do `IDEAS.md` **co bychom mohli udělat my**.

**Poslední aktualizace**: 2026-05-19 (sezení 2)

---

## Existující nástroje

### CoVe (Contour Vectorizer)

- **Repo**: https://github.com/lpechacek/cove
- **Manuál**: https://www.openorienteering.org/mapper-manual/pages/cove.html
- **Typ**: OSS (GPL-3.0), **integrovaný přímo v OpenOrienteering Mapper** + standalone CLI
- **Co dělá**: Color-classified line vectorization z raster template. Pipeline: cleanup → color classification (typicky 15–20 barev u scanu) → morfologie (erode / dilate / thin / prune) → vektorizace. Navzdory názvu **není omezeno na vrstevnice**.
- **Vstup → výstup**: JPG / PNG / TIFF → vektorové linie přímo v OOM mapě (integrovaná verze), nebo OCAD 6 soubor se symbolem 990.0 (standalone).
- **Stav**: Standalone repo 11 commitů, žádné release. Integrovaná verze je živá součást OOM.
- **Mezery vůči pic2omap**:
  - Pouze linie (žádné plochy, žádné bodové symboly).
  - Žádné automatické napojení na ISOM / ISSprOM symboly.
  - Ruční výběr barev per třída.
- **Relevance**: **VYSOKÁ** — nejbližší existující řešení. pic2omap by měl stavět **nad CoVe**, ne reinvent.

### OCAD (komerční)

- **URL**: https://www.ocad.com
- **Wiki**: https://www.ocad.com/wiki/ocad/en/index.php?title=Drawing_Orienteering_Maps_in_OCAD
- **Co dělá**: Profesionální mapový software. **Nemá** native auto-vektorizaci raster scanu. Má:
  - **CRT (Cross Reference Table)** — mapování již existujících vector formátů (SHP / DXF / GeoPackage) na OCAD symboly při importu.
  - **DEM Wizard** — z LiDARu generuje contours / vegetation density.
- **Relevance**: **NÍZKÁ** — neřeší vstupní problém (raster).
- **Poznámka**: Tímto se opravuje původní předpoklad v `IDEAS.md`, že OCAD má auto-vektorizaci scanu.

### Karttapullautin

- **Repo**: https://github.com/karttapullautin/karttapullautin (Rust rewrite)
- **Co dělá**: LiDAR point cloud → automatická orienťácká mapa (contours, cliffs, vegetation density). Deployed na národní úrovni (Mapant Spain, Mapant Norge).
- **Vstup → výstup**: `.las` / `.laz` → PNG raster + vector contours / cliffs (OCAD / DXF).
- **Stav**: Aktivně vyvíjený.
- **Relevance**: **NÍZKÁ** — jiný vstup (LiDAR ≠ raster mapa). Užitečný jako reference pipeline architektury.

### NYPL map-vectorizer

- **Repo**: https://github.com/nypl-spacetime/map-vectorizer (MIT)
- **Co dělá**: Vektorizace historických insurance atlasů (Sanborn maps) — polygony budov, dot patterns.
- **Vstup → výstup**: GeoTIFF (WGS84) → Shapefile / GeoJSON.
- **Stav**: Archivní (~220 commitů, neaktivní).
- **Relevance**: **NÍZKÁ** — jiná doména (budovy, ne přírodní symboly), ale OpenCV pipeline jako inspirace.

### Generické vector tracers

- **Potrace** (https://potrace.sourceforge.net/) — pouze B/W, GPL.
- **AutoTrace, color_trace** (https://github.com/migvel/color_trace) — multi-color přes color quantization + per-channel Potrace.
- **Inkscape Trace Bitmap** — interní wrapper okolo Potrace.
- **Relevance**: **NÍZKÁ** — žádná sémantika (neumí rozlišit "hnědá vrstevnice" vs "hnědá tečka").

---

## Komunita / odmítnuté pokusy

### Issue #833 v OpenOrienteering/mapper

- **URL**: https://github.com/OpenOrienteering/mapper/issues/833
- **Co**: Návrh (2017) na integraci CoVe kódu přímo do Mapperu. Closed bez PR a milestonu.
- **Relevance**: **STŘEDNÍ** — komunita uvažovala o end-to-end řešení, ale nedotáhla.

### Fóra (attackpoint, oringa, mapyo, oklub)

- Diskuse o scanování, georeferencování, rubbersheeting starých map.
- **Žádný end-to-end raster → vector nástroj** se neobjevil.
- Standardní postup: OOM / OCAD ručně přes raster jako template.

### Orienteering NZ Wiki — automated mapping

- LiDAR pipelines, **ne raster vectorization**.

---

## Akademické práce

Žádný paper není **sport-map specific**. Obecné historical-map approaches jsou aplikovatelné.

| Paper | URL | Co řeší |
|-------|-----|---------|
| Raster Map Line Element Extraction Based on Improved U-Net (MDPI 2022) | https://www.mdpi.com/2220-9964/11/8/439 | U-Net pro extrakci liniových prvků z raster map |
| Deep learning road extraction from historical maps (ScienceDirect 2022) | — | Symbol reconstruction pro training data |
| ACPV-Net (arXiv 2024) | https://arxiv.org/ | Polygonal vectorization z aerial imagery, vertex heatmaps |
| Semantic Segmentation for Sequential Historical Maps | https://arxiv.org/abs/2501.01845 | Časové řady historických map |
| Evaluating AI-Driven Automated Map Digitization in QGIS | https://arxiv.org/abs/2504.18777 | QGIS + AI digitization eval |
| Esri / ArcGIS Pro AI digitization | Living Atlas pretrained models | Komerční ecosystem |

**Aplikovatelnost**: U-Net + multi-class segmentation pro orienťácké barvy / symboly je přímo aplikovatelný přístup. **Chybí annotated dataset** — bylo by nutné vyrobit.

---

## OMAP formát

- **Specifikace**: https://www.openorienteering.org/api-docs/mapper/file_format.html
- **XML namespace**: `http://openorienteering.org/apps/mapper/xml/v2`
- `.omap` = minifikované XML, `.xmap` = pretty-printed (stejné schéma)
- **Veřejně dokumentovaný** — žádný reverse engineering nepotřeba.
- Lze generovat čistě z Pythonu, bez závislosti na OOM C++ kódu.
- **Poznámka**: Tímto se opravuje původní předpoklad v `IDEAS.md`, že je nutný reverse engineering.
- **Symboly uloženy v souboru**: každý OMAP soubor obsahuje plnou definici všech použitých symbolů (id, code, name, type, color refs, geometrie, dash patterns, …). Tj. **každý OMAP je sebepopisující** — pro symbol DB stačí parsovat OMAP, není nutné mít separátní symbol set file.

---

## IOF Specifikace (lokálně + URL)

### ISOM 2017-2 (Foot orienteering, lesní)

- **URL**: https://www.orienteeringaustria.at/wp-content/uploads/2025/01/IOF-ISOM-2017-2-Revision-6-January-2024.pdf
- **Revision**: 6 (leden 2024)
- **Lokálně**: `docs/ISOM_2017-2_rev6.pdf` (11.7 MB, gitignored)
- **Symbolů**: ~90 základních (101-715, s mezerami)
- **Nové v Rev 6**: 105.2 Retaining earth wall, 203.2 Dangerous pit, 715 Continuing point after map exchange

### ISSprOM 2019-2 (Sprint orienteering)

- **URL**: https://www.orienteeringaustria.at/wp-content/uploads/2025/01/IOF-ISSprOM-2019-2-Revision-6-January-2024.pdf
- **Revision**: 6 (leden 2024)
- **Lokálně**: `docs/ISSprOM_2019-2_rev6.pdf` (10 MB, gitignored)
- **Symbolů**: 104 (101-715)

### Klíčové zjištění (Sezení 2): OMAP vs IOF schéma

**OMAP soubory typicky NEpoužívají aktuální IOF kódy.** Default OOM symbol set používá **ISOM 2000** numbering, který se liší od ISOM 2017-2 o 1-3 pozice (některé kódy prohozené):

- OMAP `106` Earth bank = IOF `104`
- OMAP `112` Small knoll = IOF `109`
- OMAP `309` Uncrossable marsh = IOF `307` (prohozeno s `308 Marsh`)
- OMAP `415` Cultivated land = IOF `412` (prohozeno s `412-415`)
- OMAP `515` Railway = IOF `509`
- OMAP `702` Control point = IOF `703`

**Stejný kód = úplně jiný symbol** napříč spec verzemi:

| Kód | ISOM 2000 (OOM-default) | ISOM 2017-2 | ISSprOM 2019-2 |
|---|---|---|---|
| 501 | Paved area (OMAP 529) | Paved area | Paved area |
| 515 | Railway | Footpath | Uncrossable wall |
| 516 | Power line | Small footpath | Passable fence |
| 521 | High stone wall | Building (grey) | Building |
| 526 | Building | Cairn | Cairn |

**`.X.Y` notace v OMAP** (např. `106.0.1`, `203.1.1`) jsou **OOM rendering varianty** (minimum size, no tags, …), ne IOF kódy.

**Detailní mapování OMAP ↔ IOF** v:
- `docs/spec_check_ISOM-2017-2.md` (388 řádků)
- `docs/spec_check_ISSprOM-2019-2.md` (246 řádků)

**Dopad na pic2omap**: nikdy nepředpokládat, že "kód X" znamená totéž — kód je nespolehlivý identifikátor bez znalosti spec verze. Pic2omap pracuje **OOM-native** (ne IOF přepisování).

---

## Souhrn

- **End-to-end raster → OMAP**: **neexistuje**.
- **Nejbližší řešení**: CoVe (linie, integrované v OOM) + Karttapullautin (LiDAR, jiný vstup) + obecné U-Net papery na historical maps.
- **Díra v trhu**: symbol recognition raster → ISOM. CoVe to nedělá, akademika to pro sport maps neřešila.
- **Stavět pic2omap má smysl**, ale **nad CoVe**, nikoli místo něj.
