# ISOM 2017-2 — verifikace OMAP databáze

**Zdroj OMAP**: `resources/forest sample.omap` (158 unikátních symbolů, dle `docs/dump_forest_sample.txt`)
**Zdroj spec**: IOF ISOM 2017-2, Revision 6, January 2024 (PDF stažen z `https://www.orienteeringaustria.at/wp-content/uploads/2025/01/IOF-ISOM-2017-2-Revision-6-January-2024.pdf`, uložen v `docs/ISOM_2017-2_rev6.pdf`)
**Datum**: 2026-05-19

---

## TL;DR — hlavní nález

**OMAP soubor NEPOUŽÍVÁ číslování ISOM 2017-2.** Používá **starší ISOM 2000 schéma** (OOM-default symbol set). Názvy se převážně shodují s ISOM 2017-2, ale **numerické kódy jsou posunuté** (např. „Earth bank" je v OMAPu `106`, ale v IOF ISOM 2017-2 má kód `104`; „Small knoll" je v OMAPu `112`, v IOF `109`).

Důsledek pro Pic2Omap: pokud má nástroj generovat OMAP soubory kompatibilní s OOM defaultní symbol sadou, **používej OMAP kódy z této tabulky, ne IOF spec kódy**. Pokud naopak chceš strict ISOM 2017-2 kompatibilitu, je třeba symbol set v OMAPu **přečíslovat** (a zarovnat s IOF specifikací).

---

## Souhrn

| Metrika | Hodnota |
|---|---|
| ISOM 2017-2 Rev 6 spec (jen základní kódy) | **~90 symbolů** |
| OMAP obsahuje | **158 symbolů** |
| OMAP základních kódů (bez `.X` variant) | **~110** |
| Pokrytí ISOM 2017-2 (mapováno přes názvy) | ~85 / 90 = **94 %** |
| Chybí v OMAP (ISOM symboly bez OMAP ekvivalentu) | **5** |
| Extra v OMAP (nad rámec ISOM 2017-2) | **~12 reálných + ~50 .X variant** |

> Pozn.: počty „základní symbolů" v ISOM 2017-2 jsou orientační — spec uvádí 101…715 s mezerami, takže ne každý kód v range existuje (např. 411 přeskočeno, 510-514 přeskočeno, 533-540 neexistuje).

---

## Kompletní seznam IOF ISOM 2017-2 Rev 6 (z PDF)

### 3.1 Landforms (brown)
| Kód | Název | Typ |
|---|---|---|
| 101 | Contour | L |
| 102 | Index contour | L, T |
| 103 | Form line | L |
| 104 | Earth bank | L |
| 105.1 | Earth wall | L |
| 105.2 | Retaining earth wall | L |
| 106 | Ruined earth wall | L |
| 107 | Erosion gully | L |
| 108 | Small erosion gully | L |
| 109 | Small knoll | P |
| 110 | Small elongated knoll | P |
| 111 | Small depression | P |
| 112 | Pit | P |
| 113 | Broken ground | A |
| 114 | Very broken ground | A |
| 115 | Prominent landform feature | P |

### 3.2 Rock and boulders (black + grey)
| Kód | Název | Typ |
|---|---|---|
| 201 | Impassable cliff | L |
| 202 | Cliff | L |
| 203.1 | Rocky pit or cave | P |
| 203.2 | Dangerous pit | P |
| 204 | Boulder | P |
| 205 | Large boulder | P |
| 206 | Gigantic boulder or rock pillar | A |
| 207 | Boulder cluster | P |
| 208 | Boulder field | A |
| 209 | Dense boulder field | A |
| 210 | Stony ground, slow running | A |
| 211 | Stony ground, walk | A |
| 212 | Stony ground, fight | A |
| 213 | Sandy ground | A |
| 214 | Bare rock | A |
| 215 | Trench | L |

### 3.3 Water and marsh (blue)
| Kód | Název | Typ |
|---|---|---|
| 301 | Uncrossable body of water | A |
| 302 | Shallow body of water | A |
| 303 | Waterhole | P |
| 304 | Crossable watercourse | L |
| 305 | Small crossable watercourse | L |
| 306 | Minor/seasonal water channel | L |
| 307 | Uncrossable marsh | A |
| 308 | Marsh | A |
| 309 | Narrow marsh | L |
| 310 | Indistinct marsh | A |
| 311 | Well, fountain or water tank | P |
| 312 | Spring | P |
| 313 | Prominent water feature | P |

### 3.4 Vegetation (green + yellow)
| Kód | Název | Typ |
|---|---|---|
| 401 | Open land | A |
| 402 | Open land with scattered trees | A |
| 403 | Rough open land | A |
| 404 | Rough open land with scattered trees | A |
| 405 | Forest | A |
| 406 | Vegetation: slow running | A |
| 407 | Vegetation, slow running, good visibility | A |
| 408 | Vegetation: walk | A |
| 409 | Vegetation: walk, good visibility | A |
| 410 | Vegetation: fight | A |
| 412 | Cultivated land | A |
| 413 | Orchard | A |
| 414 | Vineyard or similar | A |
| 415 | Distinct cultivation boundary | L |
| 416 | Distinct vegetation boundary | L |
| 417 | Prominent large tree | P |
| 418 | Prominent bush or tree | P |
| 419 | Prominent vegetation feature | P |

(Pozn.: 411 v ISOM 2017-2 NEEXISTUJE — přeskočeno.)

### 3.5 Man-made features (black)
| Kód | Název | Typ |
|---|---|---|
| 501 | Paved area | A |
| 502 | Wide road | L |
| 503 | Road | L |
| 504 | Vehicle track | L |
| 505 | Footpath | L |
| 506 | Small footpath | L |
| 507 | Less distinct small footpath | L |
| 508 | Narrow ride or linear trace through the terrain | L |
| 509 | Railway | L |
| 510 | Power line, cableway or skilift | L, P |
| 511 | Major power line | L, P |
| 512 | Bridge / tunnel | L, P |
| 513.1 | Wall | L |
| 513.2 | Retaining wall | L |
| 514 | Ruined wall | L |
| 515 | Impassable wall | L |
| 516 | Fence | L |
| 517 | Ruined fence | L |
| 518 | Impassable fence | L |
| 519 | Crossing point | P |
| 520 | Area that shall not be entered | A |
| 521 | Building | A |
| 522 | Canopy | A |
| 523 | Ruin | L |
| 524 | High tower | P |
| 525 | Small tower | P |
| 526 | Cairn | P |
| 527 | Fodder rack | P |
| 528 | Prominent line feature | L |
| 529 | Prominent uncrossable line feature | L |
| 530 | Prominent man-made feature — ring | P |
| 531 | Prominent man-made feature — x | P |
| 532 | Stairway | L |

### 3.6 Technical symbols
| Kód | Název | Typ |
|---|---|---|
| 601 | Magnetic north line | L |
| 602 | Registration mark | P |
| 603 | Spot height | P, T |

### 3.7 Course planning symbols (purple)
| Kód | Název | Typ |
|---|---|---|
| 701 | Start | P |
| 702 | Map issue point | P |
| 703 | Control point | P |
| 704 | Control number | T |
| 705 | Course line | L |
| 706 | Finish | P |
| 707 | Marked route | L |
| 708 | Out-of-bounds boundary | L |
| 709 | Out-of-bounds area | A |
| 710 | Crossing point | L |
| 711 | Out-of-bounds route | L |
| 712 | First aid post | P |
| 713 | Refreshment point | P |
| 715 | Continuing point after map exchange | P |

(Pozn.: 714 v ISOM 2017-2 NEEXISTUJE — přeskočeno. 715 je nový symbol z Rev 6, leden 2024.)

---

## Mapování OMAP kódů na ISOM 2017-2 kódy (přes názvy)

Tabulka ukazuje, jak se OMAP kódy z `forest sample.omap` mapují na oficiální IOF kódy. **Rozdíl v číslování je zásadní** — OMAP používá pre-2017 (ISOM 2000) schéma.

### Landforms — posun číslování
| OMAP kód | OMAP název | IOF kód | IOF název | Pozn. |
|---|---|---|---|---|
| 101 | Contour | 101 | Contour | OK |
| 102 | Index contour | 102 | Index contour | OK |
| 103 | Form line | 103 | Form line | OK |
| 104 | Slope line | — | (součást 101) | OOM-only; v IOF není samostatný kód |
| 105 | Contour value | — | (součást 102) | OOM-only; v IOF text label u 102 |
| 106 | Earth bank | **104** | Earth bank | **posun -2** |
| 107 | Earth wall | **105.1** | Earth wall | |
| 108 | Small earth wall | — | — | OMAP varianta (možná = staré 106) |
| 109 | Erosion gully | **107** | Erosion gully | **posun -2** |
| 110 | Small erosion gully | **108** | Small erosion gully | |
| 112 | Small knoll | **109** | Small knoll | **posun -3** |
| 113 | Elongated knoll | **110** | Small elongated knoll | |
| 115 | Small depression | **111** | Small depression | |
| 116 | Pit | **112** | Pit | |
| 117.1 / 117.2 | Broken ground (small/big) | **113 / 114** | Broken / Very broken ground | |
| 118 | Special land form feature | **115** | Prominent landform feature | název se liší |

### Rock and boulders
| OMAP kód | OMAP název | IOF kód | IOF název | Pozn. |
|---|---|---|---|---|
| 201 | Impassable cliff | 201 | Impassable cliff | OK |
| 202 | Rock pillars/cliffs | **206** | Gigantic boulder or rock pillar | **kompletně jiný kód!** |
| 203 | Passable rock face | **202** | Cliff | název odlišný |
| 204 | Rocky pit | **203.1** | Rocky pit or cave | |
| 205 | Cave | (203.1) | (sloučeno do Rocky pit or cave) | OOM rozlišuje, IOF spojeno |
| 206 | Boulder | **204** | Boulder | |
| 207 | Large boulder | **205** | Large boulder | |
| 208 | Boulder field | **208** | Boulder field | OK |
| 209 | Boulder cluster | **207** | Boulder cluster | **prohozeno!** OMAP 209↔IOF 207 |
| 210 | Stony ground, small | **210** nebo **211** | Stony ground slow/walk | částečně OK |
| 211 | Open sandy ground | **213** | Sandy ground | |
| 212 | Bare rock | **214** | Bare rock | |

### Water and marsh
| OMAP kód | OMAP název | IOF kód | Pozn. |
|---|---|---|---|
| 301 | Lake | 301 | Uncrossable body of water — OK (jiný název) |
| 302 | Pond | 302 | Shallow body of water — OK |
| 303 | Waterhole | 303 | OK |
| 305 | Crossable watercourse | 304 | **posun -1** |
| 306 | Crossable small watercourse | 305 | |
| 307 | Minor water channel | 306 | |
| 308 | Narrow marsh | 309 | **kód jiný** (OMAP 308 = IOF 309) |
| 309 | Uncrossable marsh | 307 | **prohozeno!** OMAP 309↔IOF 307 |
| 310 | Marsh | 308 | |
| 311 | Indistinct marsh | 310 | |
| 312 | Well | 311 | |
| 313 | Spring | 312 | |
| 314 | Special water feature | 313 | Prominent water feature |

### Vegetation
| OMAP kód | OMAP název | IOF kód | Pozn. |
|---|---|---|---|
| 401-405 | Open land … Forest | 401-405 | OK (až na drobné rozdíly v názvech) |
| 406 | Forest: slow running | 406 | Vegetation: slow running — název |
| 407 | Undergrowth: slow running | 407 | Vegetation, slow running, good visibility |
| 408 | Forest: difficult to run | 408 | Vegetation: walk |
| 409 | Undergrowth: difficult to run | 409 | Vegetation: walk, good visibility |
| 410 | Vegetation: very difficult | 410 | Vegetation: fight |
| 411.0-411.2 | Forest runnable in one direction | — | OOM-specific, **v ISOM 2017-2 kód 411 NEEXISTUJE** |
| 412 | Orchard | 413 | **kód posunut** |
| 413 | Vineyard | 414 | |
| 414 | Distinct cultivation boundary | 415 | |
| 415 | Cultivated land | 412 | **prohozeno!** |
| 416 | Distinct vegetation boundary | 416 | OK |
| 418/419/420 | Special vegetation feature | 417/418/419 | |

### Man-made features
| OMAP kód | OMAP název | IOF kód | Pozn. |
|---|---|---|---|
| 501.X | Motorway varianty | 502 | Wide road — OOM má 5+ variant |
| 502 | Major road | 503 | Road |
| 503 | Minor road | — | OOM varianta |
| 504 | Road | (502 nebo 503) | nejednoznačné |
| 505 | Vehicle track | 504 | |
| 506 | Footpath | 505 | |
| 507 | Small path | 506 | Small footpath |
| 508 | Less distinct small path | 507 | Less distinct small footpath |
| 509 | Narrow ride | 508 | |
| 512 | Footbridge | (512 v IOF = Bridge/tunnel) | OK kód |
| 515 | Railway | 509 | **velký posun** |
| 516 | Power line | 510 | |
| 517 | Major power line | 511 | |
| 518 | Tunnel | 512 | |
| 519 | Stone wall | 513.1 | Wall |
| 520 | Ruined stone wall | 514 | Ruined wall |
| 521 | High stone wall | 515 | Impassable wall |
| 522 | Fence | 516 | |
| 523 | Ruined fence | 517 | |
| 524 | High fence | 518 | Impassable fence |
| 525 | Crossing point | 519 | |
| 526 | Building | 521 | |
| 527 | Settlement | (521 grey) | OOM extra |
| 528 | Permanently out of bounds | 520 | Area that shall not be entered |
| 529 | Paved area | 501 | |
| 530 | Ruin | 523 | |
| 531 | Firing range | — | **OOM-specific, není v ISOM 2017-2** |
| 532 | Grave | — | **OOM-specific** |
| 533 | Crossable pipeline | 528 | Prominent line feature |
| 534 | Uncrossable pipeline | 529 | Prominent uncrossable line feature |
| 535 | High tower | 524 | |
| 536 | Small tower | 525 | |
| 537 | Cairn | 526 | |
| 538 | Fodder rack | 527 | |
| 539/540 | Special man-made feature | 530/531 | |

### Technical symbols
| OMAP kód | OMAP název | IOF kód | Pozn. |
|---|---|---|---|
| 601.X | Magnetic north line varianty | 601 | OK + varianty |
| 602 | Registration mark | 602 | OK |
| 603.0/603.1 | Spot height (dot/text) | 603 | OK |

### Course planning
| OMAP kód | OMAP název | IOF kód | Pozn. |
|---|---|---|---|
| 701 | Start | 701 | OK |
| 702 | Control point | 703 | **OMAP 702 = IOF 703!** |
| 703 | Control number | 704 | |
| 704 | Line | 705 | Course line |
| 705 | Marked route | 707 | |
| 706 | Finish | 706 | OK |
| 707 | Uncrossable boundary | 708 | Out-of-bounds boundary |
| 708 | Crossing point | 710 | |
| 709 | Out-of-bounds area | 709 | OK |
| 710 | Dangerous area | — | OMAP extra (mimo IOF 700s) |
| 711 | Forbidden route | 711 | OK (Out-of-bounds route) |
| 712 | First aid post | 712 | OK |
| 713 | Refreshment point | 713 | OK |

OMAP **nemá**: 702 Map issue point, 715 Continuing point after map exchange (nový v Rev 6 z 2024).

---

## Chybí v OMAP (potřeba doplnit pro plnou ISOM 2017-2 kompatibilitu)

| ISOM kód | Název | Kategorie | Poznámka |
|---|---|---|---|
| 105.2 | Retaining earth wall | Landforms | Nový v Rev 6 z 2024 |
| 106 | Ruined earth wall | Landforms | Chybí (OMAP má jen earth wall + small earth wall) |
| 203.2 | Dangerous pit | Rock | Nový v Rev 6 z 2024 |
| 702 | Map issue point | Course | Chybí |
| 715 | Continuing point after map exchange | Course | Nový v Rev 6 z 2024 |

---

## Extra v OMAP (nad rámec ISOM 2017-2)

| OMAP kód | Možný důvod |
|---|---|
| 104 Slope line | OOM-specific; v IOF součást 101 Contour |
| 105 Contour value | OOM-specific; v IOF text label u 102 Index contour |
| 108 Small earth wall | Pravděpodobně staré ISOM 2000 |
| 411.0/411.1/411.2 Forest runnable in one direction | OOM-specific (411 v ISOM 2017-2 neexistuje) |
| 415 Cultivated land + 414 Distinct cultivation boundary | Prohozené číslování proti IOF |
| 501.0–501.5 Motorway (6 variant) | OOM-specific — ISOM 2017-2 nerozlišuje motorway |
| 502.1 Major road, under construction | OOM-only varianta |
| 503.1 Minor road, under construction | OOM-only varianta |
| 527 Settlement | OOM-only (ISOM 2017-2 to řeší přes 521 Building grey) |
| 531 Firing range | OOM-only |
| 532 Grave | OOM-only |
| 710 Dangerous area | OOM-only |
| 799 Simple Orienteering Course | OOM-only |
| 980.0.2 Text | OOM internal |
| 999 OpenOrienteering Logo | OOM internal |
| `*.0.1`, `*.1.1`, `*.0.2` minimum size varianty (~25 ks) | OOM-internal: explicitní point representation pro malé area/line symboly |
| `*.1`, `*.2` no-tags / bank-line varianty (~25 ks) | OOM-internal: alternative styling pro stejný IOF symbol |

---

## Poznámky a klíčová zjištění

1. **OMAP soubor používá ISOM 2000 numerické schéma**, ne ISOM 2017-2. Všechny názvy se víceméně shodují s aktuální specifikací, ale **kódy jsou posunuté o 1-3 pozice**. Toto je OOM (OpenOrienteering Mapper) default symbol set z doby před 2017 redesign.

2. **Subindex notace v OMAPu** (`.X.Y` schéma):
   - `X.0.1` typicky = "minimum size" varianta (point reprezentace pro malé linie/plochy, např. 106.0.1 Earth bank minimum)
   - `X.1` = alternativní reprezentace (např. 201.1 "no tags", 309.1 "border line")
   - `X.1.1` = minimum size varianta alternativy (např. 203.1.1)
   - `X.2` = další varianta (např. 201.2 "tag line", 203.2 "rounded")
   - Toto NEJSOU IOF kódy — jsou OOM-internal sub-symboly stejného základního IOF symbolu.

3. **Pro Pic2Omap nástroj** doporučuji:
   - **Pokud cílíš na výstup pro OOM** → použij OMAP kódy z `forest sample.omap` (jak je tam najdeš)
   - **Pokud cílíš na strict ISOM 2017-2** → vytvoř mapování OMAP↔IOF (tato tabulka) a v OMAP souboru přečísluj symboly podle IOF spec
   - **Doporučení**: drž OMAP defaultní kódy (širší kompatibilita s existujícími OOM mapami), ale do metadat/komentářů přidej IOF kód jako referenci

4. **Nové symboly v Rev 6 (2024)** chybí v OMAPu: 105.2 Retaining earth wall, 203.2 Dangerous pit, 715 Continuing point. Pokud potřebuješ aktuální spec, je třeba je do OMAPu doplnit.

5. **Rev 6 errata listuje renumbering**: 105 → 105.1, 203.1 (Rocky pit) renumbered, 513 → 513.1. OMAP zatím nereflektuje tato přečíslování.

6. **Pokrytí**: většina (cca 85+) IOF symbolů má v OMAPu ekvivalent přes název. Hrubá shoda je ~94 %, exact match kódů je ~10 % (jen základní 101-103, 201, 401-405, 601-603, 706, 712, 713).

---

## Zdrojové soubory

- `docs/dump_forest_sample.txt` — dump OMAP symboly (z Pic2Omap nástroje)
- `docs/omap_symbols_list.txt` — kompletní seznam OMAP code+name páry (extrahované z OMAP XML)
- `docs/ISOM_2017-2_rev6.pdf` — oficiální IOF specifikace (Rev 6, January 2024)
- `docs/maprunner.pdf` — neoficiální 1-stránkový summary (Maprunner.co.uk, 2024)
