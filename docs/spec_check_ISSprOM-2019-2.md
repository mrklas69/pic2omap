# ISSprOM 2019-2 - verifikace OMAP databáze

**Zdroj OMAP**: `resources/complete map.omap` (182 symbolů, měřítko 1:4000, 39 barev)
**Zdroj spec**: [IOF ISSprOM 2019-2, Revision 6, January 2024](https://www.orienteeringaustria.at/wp-content/uploads/2025/01/IOF-ISSprOM-2019-2-Revision-6-January-2024.pdf) (lokální kopie: `docs/ISSprOM_2019-2_rev6.pdf`)
**Datum**: 2026-05-19

## Hlavní zjištění (TL;DR)

**OMAP soubor `complete map.omap` nepoužívá ISSprOM 2019-2 kódy, ale ISOM 2017-2 kódy.**

Pokud je tato OMAP databáze základem pro `pic2omap`, vstup do sprintové mapy ji nelze použít beze změn -- výsledný `.omap` by sice fungoval v OOM, ale **kódy symbolů by neodpovídaly oficiální specifikaci** a takovou mapu by IOF/CoVe nemohl akceptovat jako ISSprOM-compliant.

Konkrétní rozdíly:
- ISSprOM má `501` Paved area (brown/blackbrown screen), ISOM má `501` Asphalt - úplně jiné krytí.
- ISSprOM přečíslovala silnice/cesty na `505`-`509.2`, ISOM má `506`-`509`, `515`-`519` se zcela jinou granularitou.
- ISSprOM nemá `304` (lake), `420` (cultivation), `526` (cairn jako 526), nemá `534`-`540` (passable/uncrossable wall, fence, crossing point) -- má vlastní `513.1`/`513.2`/`515`/`516`/`518`/`519`.
- ISSprOM `516`, `518` = passable / uncrossable fence; v ISOM jsou tyto kódy úplně jiné objekty (small footpath, narrow ride).

## Souhrn

| Metrika | Hodnota |
|---|---|
| ISSprOM 2019-2 spec symbolů | **104** (101-715, bez 800-series textů) |
| OMAP obsahuje symbolů | **182** |
| Pokrytí ISSprOM kódů v OMAP | **~32 / 104 (~31%)** -- jen kódy, které se náhodou shodují |
| Chybí v OMAP (ISSprOM kódy bez ekvivalentu) | **~72** |
| Extra v OMAP (nad rámec spec / ISOM kódy) | **~150** |

**Pozn.**: Mnoho ISOM kódů v OMAP _funkčně_ odpovídá nějakému ISSprOM symbolu, jen pod jiným kódem. Tabulky níže rozlišují:
1. **Kódy v ISSprOM bez protějšku v OMAP** (sekce "Chybí")
2. **Kódy v OMAP bez protějšku v ISSprOM** (sekce "Extra" -- většinou ISOM-only)

## Chybí v OMAP (ISSprOM kódy bez protějšku)

### Landforms (4.1)
| Kód | Název | Pozn. |
|---|---|---|
| 105.1 | Small earth wall | OMAP má `108.1` (ISOM Small earth wall) -- funkčně OK, jiný kód |
| 105.2 | Retaining earth wall seen only from one side | nový symbol v rev. 6 (2024-02-01) |
| 107 | Erosion gully | OMAP má `109` (ISOM Erosion gully) -- jiný kód |
| 108 | Small erosion gully | OMAP má `110` (ISOM Small erosion gully) -- jiný kód |
| 109 | Small knoll | OMAP má `112` (ISOM Small knoll) -- jiný kód |
| 110 | Small elongated knoll | OMAP má `113` (ISOM Elongated knoll) -- jiný kód |
| 111 | Small depression | OMAP má `115` (ISOM Small depression) -- jiný kód |
| 112 | Pit or hole | OMAP má `116` (ISOM Pit) -- jiný kód |
| 113 | Broken ground | OMAP má `117.1`, `117.2` (ISOM Broken ground) -- jiný kód |
| 115 | Prominent landform feature | OMAP má `118` (ISOM Prominent landform feature) -- jiný kód |

### Rock and boulders (4.2)
| Kód | Název | Pozn. |
|---|---|---|
| 203 | Rocky pit or cave | OMAP má `206`, `207` (ISOM Rocky pit, Cave) |
| 204 | Boulder | OMAP má `210.1` (ISOM Boulder) -- jiný kód |
| 205 | Large boulder | OMAP má `210.2` (ISOM Large boulder) -- jiný kód |
| 206 | Gigantic boulder or rock pillar | OMAP má `202` (ISOM Gigantic boulder) -- jiný kód |
| 207 | Boulder cluster | OMAP má `203`, `203.1`, `203.2` (ISOM Boulder cluster + varianty) |
| 208 | Boulder field | OMAP má `204`, `205` (ISOM Boulder field) |
| 210 | Stony ground | OMAP má `208`, `208.1` (ISOM Stony ground) |
| 213 | Open sandy ground | OMAP má `211` (ISOM Sandy ground) -- jiný kód |
| 214 | Bare rock | OMAP má `212` (ISOM Bare rock) -- jiný kód |

### Water and marsh (4.3)
| Kód | Název | Pozn. |
|---|---|---|
| 302 | Shallow body of water | OMAP má `305.0.1`, `305.0.2`, `305.1` (ISOM Shallow water) |
| 305 | Small crossable watercourse | OMAP má `304.1`, `304.1.1` (ISOM Crossable watercourse) |
| 306 | Minor / seasonal watercourse | OMAP má `304.2` (ISOM Minor watercourse) |
| 307 | Uncrossable marsh | OMAP má `308`, `309`, `309.0.1`, `309.0.2` -- ISSprOM 307 vs ISOM 308: konflikt! |
| 309 | Narrow marsh | OMAP má `311`, `311.1` (ISOM Narrow marsh) |
| 311 | Small fountain or well | OMAP má `313` (ISOM Well) -- jiný kód |
| 312 | Spring | OMAP má `314` (ISOM Spring) -- jiný kód |
| 313 | Prominent water feature | chybí úplně |

### Vegetation (4.4)
| Kód | Název | Pozn. |
|---|---|---|
| 411 | Uncrossable vegetation | OMAP má `421` (ISOM Impassable vegetation) -- jiný kód |
| 412 | Cultivated land | OMAP má `412` (shoda!), ale ISOM 412 = Orchard -- **konflikt!** |
| 413 | Orchard | OMAP má `413` (shoda!), ale ISOM 413 = Vineyard -- **konflikt!** |
| 414 | Vineyard or similar | OMAP má `414` (shoda!), ale ISOM 414 = Distinct cultivation boundary -- **konflikt!** |
| 415 | Distinct cultivation boundary | OMAP má `415` (shoda!), ale ISOM 415 = Cultivation boundary -- prib. OK |
| 416 | Distinct vegetation boundary | OMAP má `416` (shoda!), prib. OK |
| 417 | Prominent large tree | OMAP má `418` (ISOM Prominent large tree) -- jiný kód |
| 418 | Prominent bush or small tree | OMAP má `419` (ISOM Prominent bush) -- jiný kód |
| 419 | Prominent vegetation feature | OMAP má `420` (ISOM Prominent vegetation feature) -- jiný kód |

### Man-made (4.5)
| Kód | Název | Pozn. |
|---|---|---|
| 501 | Paved area | OMAP má `501` (shoda kódu), ale ISOM 501 = Road -- **konflikt definice!** |
| 501.1 | Step or edge of paved area | OMAP nemá ekvivalent |
| 501.2 | Step or edge of paved area at lower level | OMAP nemá |
| 501.3 | Paved area with scattered trees | OMAP nemá |
| 505 | Unpaved footpath or track | OMAP má `508`, `509` -- jiný systém |
| 506 | Small unpaved footpath or track | OMAP má `506.1.1`-`506.1.4` (ISOM Paved area varianty) -- **konflikt!** |
| 507 | Less distinct small path | OMAP má `507` (shoda kódu), ale ISOM 507 = Paved area heavy -- **konflikt!** |
| 508 | Narrow ride | OMAP má `508` (ISOM Road) -- **konflikt!** |
| 509.1 | Railway | OMAP má `509` (ISOM Vehicle track) -- **konflikt!** |
| 509.2 | Tramway | OMAP nemá |
| 510 | Power line, cableway or ski lift | OMAP nemá `510` přímo |
| 511 | Major power line | OMAP nemá |
| 512.1 | Bridge or tunnel entrance | OMAP má `512.1.1`, `512.1.2` (varianty) |
| 512.2 | Underpass or tunnel | OMAP nemá přímo |
| 512.3 | Area runnable at lower level | OMAP nemá |
| 513.1 | Passable wall | OMAP má `533` (ISOM Permanent fence) -- jiný kód |
| 513.2 | Passable retaining wall | OMAP nemá |
| 515 | Uncrossable wall | OMAP má `515.1`, `515.2` -- ale ISOM 515 = Footpath -- **konflikt!** |
| 516 | Passable fence or railing | OMAP má `516` (shoda kódu), ale ISOM 516 = Small footpath -- **konflikt!** |
| 518 | Uncrossable fence or railing | OMAP má `518.1` -- ale ISOM 518 = Narrow ride -- **konflikt!** |
| 519 | Crossing point (optional) | OMAP má `519`, `519.1.1`, `519.1.2` -- ale ISOM 519 = Railway -- **konflikt!** |
| 520 | Area that shall not be entered | OMAP nemá `520` -- má jen `709` (out-of-bounds) v course planning |
| 522 | Canopy | OMAP má `522`, `522.0.1` -- ale ISOM 522 = Major power line -- **konflikt!** |
| 522.1 | Pillar | OMAP nemá |
| 526 | Cairn | OMAP má `526.1`-`526.3` (varianty) -- ale ISOM 526 = Special man-made -- **konflikt!** |
| 527 | Fodder rack | OMAP nemá |
| 530 | Prominent man-made feature - ring | OMAP nemá |
| 531 | Prominent man-made feature - x | OMAP nemá |
| 532 | Stairway | OMAP nemá v této formě (ISOM má jiný kód) |
| 533 | Area with obstacles | OMAP má `533` (shoda kódu), ale ISOM 533 = Permanent stand -- **konflikt!** |

### Course planning (4.7)
| Kód | Název | Pozn. |
|---|---|---|
| 710.1 | Crossing point (course planning) | OMAP nemá explicitně |
| 710.2 | Crossing section | OMAP nemá explicitně |
| 714 | Temporary construction or closed area | OMAP má `714` (shoda kódu) |
| 715 | Continuing point after map exchange | OMAP nemá |

## Extra v OMAP (nad rámec ISSprOM 2019-2)

Tabulka uvádí jen kódy v OMAP, které **nejsou** v ISSprOM 2019-2 vůbec definované (ani jako základ ani jako .x varianta). Většina pochází z ISOM 2017-2.

| Kód v OMAP | Pravděpodobný význam (ISOM) | Možný důvod |
|---|---|---|
| 106.0 / 106.1 / 106.2 | Earth bank, varianty | ISOM Earth bank -- v ISSprOM je `104` |
| 108.1 | Small earth wall | ISOM kód; ISSprOM má `105.1` |
| 109 | Erosion gully | ISOM kód; ISSprOM má `107` |
| 110 | Small erosion gully | ISOM kód; ISSprOM má `108` |
| 112 | Small knoll | ISOM kód; ISSprOM má `109` |
| 113 | Elongated knoll | ISOM kód; ISSprOM má `110` |
| 115 | Small depression | ISOM kód; ISSprOM má `111` |
| 116 | Pit | ISOM kód; ISSprOM má `112` |
| 117.1 / 117.2 | Broken ground varianty | ISOM kód; ISSprOM má `113` |
| 118 | Prominent landform feature | ISOM kód; ISSprOM má `115` |
| 201.0.1 / 201.1 / 201.1.1 / 201.2 | Impassable cliff varianty | shoda základu, varianty OOM-interní |
| 202 | Gigantic boulder/pillar | ISOM kód; ISSprOM má `206` |
| 203 / 203.0.1 / 203.1 / 203.1.1 / 203.2 / 203.2.1 | Boulder cluster varianty | ISOM kód; ISSprOM má `207` |
| 204 | Boulder field | ISOM kód; ISSprOM má `208` |
| 205 | Stony ground? (ISOM 205 je nĕco jiného) | ISOM kód |
| 206 / 207 | Rocky pit / cave | ISOM; ISSprOM má `203` |
| 208 / 208.1 | Stony ground | ISOM; ISSprOM má `210` |
| 210.1 / 210.2 | Boulder / large boulder | ISOM; ISSprOM má `204` / `205` |
| 211 | Sandy ground | ISOM; ISSprOM má `213` |
| 212 | Bare rock | ISOM; ISSprOM má `214` |
| 304.1 / 304.1.1 / 304.2 | Crossable watercourse | ISOM; ISSprOM má `305` / `306` |
| 304.3 / 304.4 | Uncrossable body of water (fill) | ISOM/OOM interní varianty `301` |
| 305.0.1 / 305.0.2 / 305.1 | Shallow water | ISOM; ISSprOM má `302` |
| 308 | Narrow marsh? (v ISOM je 308 Marsh) | ISOM; ISSprOM má `309` Narrow marsh |
| 309 / 309.0.1 / 309.0.2 | Impassable marsh + varianty | ISOM; ISSprOM má `307` |
| 310 / 310.1 | Marsh + varianty | ISOM; ISSprOM má `308` |
| 311 / 311.1 | Indistinct marsh? | ISOM; ISSprOM má `309` Narrow marsh / `310` Indistinct marsh |
| 313 | Well | ISOM; ISSprOM má `311` |
| 314 | Spring | ISOM; ISSprOM má `312` |
| 418 / 419 / 420 / 421 / 421.1 | Prominent vegetation varianty | ISOM; ISSprOM má `417`-`419` |
| 506.1.1 / 506.1.2 / 506.1.3 / 506.1.4 | Paved area varianty (ISOM 506) | ISOM; ISSprOM má `501` |
| 512.1.1 / 512.1.2 | Bridge varianty | OOM-interní |
| 515.1 / 515.2 | Footpath varianty (ISOM 515) | ISOM; v ISSprOM `515` = Uncrossable wall |
| 517 | Less distinct path | ISOM kód |
| 518.1 | Narrow ride varianta (ISOM 518) | ISOM |
| 519.1.1 / 519.1.2 | Railway varianty (ISOM 519) | ISOM |
| 521.1.1 / 521.1.2 | Power line varianty (ISOM 521) | ISOM; v ISSprOM `521` = Building |
| 522.0.1 | Major power line varianta (ISOM 522) | ISOM; v ISSprOM `522` = Canopy |
| 524 | High tower | ISOM kód; v ISSprOM shoda (`524` High tower) |
| 525 | Small tower | ISOM; v ISSprOM shoda (`525`) |
| 526.1 / 526.1.1 / 526.1.2 / 526.1.3 / 526.2 / 526.2.1 / 526.2.2 / 526.3 | Cairn varianty (ISOM 526) | ISOM; v ISSprOM `526` Cairn (shoda kódu, OOM varianty navíc) |
| 528.1 | Charcoal burning place varianta (ISOM 528) | ISOM; v ISSprOM `528` Prominent line feature |
| 529.0.1 .. 529.0.12 | Special man-made object varianty (ISOM 529) | OOM interní varianty; v ISSprOM `529` Prominent uncrossable line feature |
| 529.1.1 .. 529.1.4 | Special man-made varianty | OOM interní |
| 534 / 535 / 536 / 537 / 538 / 539 / 540 | Uncrossable wall / ruin / pipe / fence / crossing point | ISOM; ISSprOM má `513.1`, `513.2`, `515`, `516`, `518`, `519` |
| 601.0.1 .. 601.0.6 | Magnetic north line varianty | OOM interní; ISSprOM má jeden `601` |
| 602 | Registration mark | ISOM; v ISSprOM **neexistuje** |
| 603.0.1 / 603.0.2 | Spot height | ISOM; v ISSprOM **neexistuje** |
| 708.1 | Out-of-bounds boundary varianta | OOM interní |
| 709.1 / 709.2 | Out-of-bounds area varianty | OOM interní |
| 712 | First aid post? (ISOM 712) | ISOM; v ISSprOM **neexistuje** |
| 713 | Refreshment point? (ISOM 713) | ISOM; v ISSprOM **neexistuje** |
| 799 / 799.1 / 799.2 | Legend / map setup texts | OOM-interní (ne IOF) |
| 800 .. 800.6 | Title / subtitle / text varianty | OOM-interní (ne IOF) |
| 899.0.1 / 899.0.2 | OOM systémové | OOM-interní |
| 999 | OOM systémový (typicky "All elements") | OOM-interní |

## Poznámky

### 1. Symbolová sada v OMAP je ISOM 2017-2, ne ISSprOM 2019-2
I když má mapa sprintové měřítko (1:4000), soubor `complete map.omap` používá **číslování symbolů z ISOM 2017-2**. Mezi barvami jsou „OpenOrienteering Blue 50%", „Brown 20-50% for paved area, non-urban", „Yellow 70%" -- některé z nich naznačují hybridní / nestandardní OOM template.

Pro `pic2omap` je to zásadní:
- Pokud je cílem produkovat ISSprOM-compliant sprintové mapy, tato OMAP template **není přímo použitelná**.
- Je nutné získat samostatnou ISSprOM 2019-2 template (typicky z OOM symbol sets distribuce: `ISSprOM_2019-2.omap`) a použít ji jako zdroj pravdy pro kódy symbolů, pokud je výstupem sprintová mapa.

### 2. `.x.y` notace u kódů v OMAP
- `.0.1` typicky označuje variantu **„minimum size"** (používá se pro legendu / nejkratší reprezentaci).
- `.1` / `.2` atd. označují **size varianty** (např. „very high", „minimum length").
- `.1.1` označuje **OOM-interní sub-varianty** pro uživatele (např. „no tags").

V IOF specifikaci tyto subkódy **neexistují** -- jsou to OOM symbol set internals pro pohodlí uživatele.

### 3. ISSprOM-only symboly důležité pro sprint mapy
Následující ISSprOM symboly **musí** být přítomné v jakémkoli sprint-compatible symbol setu, ale v aktuální OMAP DB **chybí**:
- `501.1`, `501.2` - Step / edge of paved area (sprint-specifický!)
- `513.1` / `513.2` - Passable wall varianty
- `522.1` - Pillar
- `527` - Fodder rack
- `530` / `531` - Prominent man-made (ring / x)
- `715` - Continuing point after map exchange

### 4. Konflikty kódů (stejné číslo, jiný význam ISOM vs ISSprOM)
Tohle je největší hazard pro `pic2omap`. Následující kódy znamenají v obou specifikacích **úplně jiné věci**:

| Kód | ISOM 2017-2 význam | ISSprOM 2019-2 význam |
|---|---|---|
| 412 | Orchard | Cultivated land |
| 413 | Vineyard | Orchard |
| 414 | Distinct cultivation boundary | Vineyard |
| 415 | Cultivation boundary | Distinct cultivation boundary |
| 501 | Road | Paved area |
| 507 | Paved area heavy | Less distinct small path |
| 508 | Road / vehicle track | Narrow ride |
| 509 | Vehicle track | Railway (.1) / Tramway (.2) |
| 515 | Footpath | Uncrossable wall |
| 516 | Small footpath | Passable fence or railing |
| 518 | Narrow ride | Uncrossable fence or railing |
| 519 | Railway | Crossing point (optional) |
| 521 | Power line | Building |
| 522 | Major power line | Canopy |
| 526 | Special man-made point | Cairn |
| 533 | Permanent stand | Area with obstacles |

**Doporučení**: V `pic2omap` nikdy nepředpokládat, že „kód X" znamená to samé bez ohledu na spec. Před načtením OMAPu vždy zjistit, podle jaké specifikace byl vytvořen, ideálně z metadat (název souboru, měřítko, scale 1:4000 vs 1:15000), nebo si nechat uživatelem upřesnit.

### 5. Co s tím dál
Pro `pic2omap` jsou v zásadě dvě cesty:
1. **Stáhnout oficiální ISSprOM 2019-2 OMAP template** (od OOM Symbol Sets) a postavit symbolovou DB nad ním. Pak budou kódy odpovídat IOF spec.
2. **Pracovat na úrovni vyšší abstrakce** (např. názvy/typ symbolu místo číselného kódu) a mapovat na konkrétní spec až při exportu. Tím by `pic2omap` zůstal nezávislý na verzi spec.

Druhá cesta je robustnější, ale vyžaduje vlastní interní katalog symbolů s napojením na obě spec (ISOM a ISSprOM) -- to je velký kus práce.
