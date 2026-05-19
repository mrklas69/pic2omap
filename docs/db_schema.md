# DB Schema — pic2db / db2omap

**Status**: návrh (Sezení 5, 2026-05-19). Před implementací odsouhlaseno s userem.
**Zdroj pravdy**: tento soubor. IDEAS.md odkazuje sem, kód implementuje sem.

Mezivrstva mezi rasterem a OMAP XML. `pic2db` plní DB, `db2omap` ji serializuje.

```
PNG → pic2db → output/<sample>/db/ → db2omap → OMAP
```

## Datový model

Python `@dataclass` s `to_dict()` / `from_dict()` pro JSON round-trip.

### `MapObject`

Jeden detekovaný mapový objekt (vrstevnice, balvan, plocha lesa, ...).

```python
@dataclass
class MapObject:
    # Identita
    id: int                          # persistent napříč iteracemi (viz "Persistent IDs")
    symbol_code: str                 # "101", "204"... string kvůli OMAP konzistenci
    geometry_type: Literal["point", "line", "area"]
    category: ColorCategory          # brown / black / blue / yellow / green / purple

    # Lokalizace
    bbox: tuple[int, int, int, int]  # (x0, y0, x1, y1) v pixelech rasteru
    pixel_count: int                 # informativní; rychlý filter pro mark/list

    # Geometrie
    pixel_blob_id: int               # odkaz do claim_mask_iter_N.png
                                     # (16-bit PNG, hodnota pixelu = MapObject.id)
                                     # Polyline/polygon doplníme až Stage 5 vektorizace.

    # Diagnostika
    confidence: float                # 0.0–1.0
    detected_in_iter: int            # iter_N, kde objekt vznikl
    detection_method: str            # "thickness_v1", "shape_match_v1", ...
```

**Proč `pixel_blob_id` místo polyline**: vektorizace (Schneider Bezier) je Stage 5,
zatím nemáme. Start s pixel-level reprezentací → db2omap může produkovat raw polygon
OMAP objekty (špatné, ale funkční). Až přijde Stage 5, přidáme `polyline: list[(x,y)]`
volitelně vedle `pixel_blob_id` (oba zůstanou — pixel pro debug, polyline pro produkční OMAP).

### `NonMapElement`

Výstup fáze A (strip overlays). Texty, loga, PurplePen tratě.

```python
@dataclass
class NonMapElement:
    id: int
    kind: Literal["text", "logo", "purplepen"]
    bbox: tuple[int, int, int, int]
    metadata: dict                   # např. {"ocr_text": "21", "dominant_color": "purple"}
```

**Proč držet ve stejné DB**: db2omap se může rozhodnout zachovat PurplePen jako
template layer v OMAP (ne ji mazat). Texty bývají popisky kontrol → mapový kontext.

### `DBSnapshot`

Jeden `iter_N.json` soubor. Container.

```python
@dataclass
class DBSnapshot:
    iteration: int
    source_image: str                # relativní cesta k zdrojovému rasteru
    image_shape: tuple[int, int]     # (height, width)
    objects: list[MapObject]
    non_map_elements: list[NonMapElement]
    unclaimed_pixel_count: int       # pro stop-konvergenci fáze B
```

## Disk layout

```
output/<sample>/db/
  iter_0.json                       # po fázi A (před recognition)
  iter_1.json                       # po prvním passu fáze B (areas + lines + points)
  iter_2.json                       # po druhém passu (re-lines apod.)
  claim_mask_iter_1.png             # 16-bit grayscale, pixel = MapObject.id, 0 = unclaimed
  claim_mask_iter_2.png
  latest.txt                        # text s číslem poslední iter (Windows: žádný symlink)
```

**Proč mask jako PNG, ne JSON**: pro 631×478 raster je to 300k záznamů. PNG s 16-bit
grayscale (uint16 = max 65535 objektů per iter — dost) je 1–2× menší než ekvivalentní
gzipped JSON a load přes `cv2.imread(..., IMREAD_UNCHANGED)` je instantní.

**Proč 16-bit**: 8-bit (max 255 objektů) je málo (`forest sample` má 539 objektů).
32-bit zbytečné, 16-bit pokrývá realistické mapy.

## CLI nástroje — subcommand router

Single entry point `pic2db.py` se subcommands. Sdílené args (`--symbols`, `--out-dir`)
žijí na top-level parseru.

```bash
# Detekce — produkuje novou iteraci
python pic2db.py detect "resources/forest sample.png" --symbols 101,102 --iter 1

# Výpis objektů (text dump)
python pic2db.py list "output/forest sample" --symbols 204,205

# Vizualizace — overlay přes background
python pic2db.py mark "output/forest sample" --symbols 204 \
    --background "resources/forest sample.png"

# Totéž s ID popisky (font_scale=0.2)
python pic2db.py mark "output/forest sample" --symbols 204 \
    --background "resources/forest sample.png" --with-ids

# Diff mezi iteracemi
python pic2db.py diff "output/forest sample" --from 1 --to 2

# Export do OMAP (= db2omap entry point)
python pic2db.py export "output/forest sample" --to omap --out forest.omap
```

`--symbols` filter ve **všech** verbach. Bez něj = všechny detekované symboly.

### Vztah ke stávajícím skriptům

`peak_visualizer.py`, `border_overlay.py`, `thickness_probe.py`, `border_probe.py` jsou
rozpoznávací experimenty pre-DB éry. Zůstávají jako legacy (referenční implementace pro
brown line classifier). Až bude `pic2db.py detect` produkční, transformují se na
jeden ze symbol detectorů uvnitř (`detectors/brown_line_v1.py`).

## Persistent IDs napříč iteracemi

Objekt #42 detekovaný v iter 1 zůstává #42 i v iter 3, pokud je matchnut. Důvod:
`diff` verb má smysl jen tehdy, když IDs mají kontinuitu.

**Matching pravidlo (návrh, dotunit při implementaci)**:
- Stejný `symbol_code` + IoU(bbox_old, bbox_new) > 0.5 → re-use ID.
- Jinak nový ID (`max_existing_id + 1`).

Globální counter žije v `db/latest.txt` nebo separátním `id_counter.txt`.

## Stop kritéria iterace fáze B

Iterace končí když **kterékoli** nastane:
- **Konvergence**: |objects_iter_N+1 − objects_iter_N| / objects_iter_N < 0.01 (méně než
  1 % nových/odebraných objektů). Měříme přes ID matching, ne přes count diff.
- **Cap**: iter > 3 → stop a hlasitě warn (signál na bug v detector logice).

## Otevřené body (řeší se při implementaci)

- IoU threshold pro persistent ID matching — 0.5 je odhad, kalibrovat na forest sample.
- Co s objektem, který v iter N+1 zmizí? Hard delete vs soft (`deleted_in_iter`)?
  Návrh: hard delete, historii drží předchozí `iter_N.json`.
- `confidence` agregace per category vs per object — zatím per object, agregát počítáme on-demand.
- OCR strategie pro NonMapElement.text — Tesseract vs blob-based bez OCR (jen "tady je text"). Druhé je MVP.
