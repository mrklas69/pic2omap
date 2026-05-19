"""
pic2db — entry point pro detekci a manipulaci s DB mezivrstvou.

Subcommands:
  detect  — spustí detekci symbolů, zapíše iter_N.json
  list    — vypíše objekty v DB (filtrovatelné --symbols)
  mark    — overlay objektů přes background (--with-ids pro popisky)  [NOT IMPLEMENTED]
  diff    — porovnání dvou iterací                                    [NOT IMPLEMENTED]
  export  — db2omap serializace do OMAP XML                           [NOT IMPLEMENTED]

Kanonický popis viz docs/db_schema.md.

Stav: skeleton router. `detect` produkuje prázdný snapshot, `list` ho přečte.
Reálné detektory přijdou v dalším kroku.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from db_model import DBSnapshot


def _parse_symbols(s: str | None) -> set[str] | None:
    """
    '101,102,103' → {'101', '102', '103'}. None nebo prázdné → None (= bez filtru).
    Vrácený set se používá v `if code in symbols_filter` — O(1) lookup.
    """
    if not s:
        return None
    return {code.strip() for code in s.split(",") if code.strip()}


def _resolve_db_path(out_dir: Path, iteration: int | None) -> Path:
    """
    Najde cestu k iter_N.json. Pokud iteration je None, použije latest.txt.
    Pokud i ten chybí, scan db/ adresáře a vezme nejvyšší existující iter.
    """
    db_dir = out_dir / "db"
    if iteration is not None:
        return db_dir / f"iter_{iteration}.json"

    # Auto-detect: latest.txt drží číslo poslední iterace (na Win nemáme rozumný symlink).
    latest_file = db_dir / "latest.txt"
    if latest_file.exists():
        n = int(latest_file.read_text().strip())
        return db_dir / f"iter_{n}.json"

    # Fallback: scan adresáře. sorted() na ['iter_1.json', 'iter_10.json'] dá
    # špatné pořadí (lexikograficky 10 < 2), ale pro malá čísla iterací OK.
    candidates = sorted((db_dir).glob("iter_*.json"))
    if not candidates:
        raise SystemExit(f"V {db_dir} žádné iter_*.json — spusť `detect` první.")
    return candidates[-1]


# --- Verb: detect ---

def cmd_detect(args: argparse.Namespace) -> int:
    """
    Spustí detektory podle --symbols filtru, výsledek do iter_<N>.json + claim mask.

    V1 detektory:
        - brown_line_v1: 101 Contour, 102 Index contour (thickness peak)

    Bez --symbols filtru spouští všechny dostupné detektory. S filtrem jen ty,
    které produkují alespoň jeden z požadovaných symbol_codes.
    """
    img_path: Path = args.image
    if not img_path.exists():
        print(f"Vstupní obrázek neexistuje: {img_path}", file=sys.stderr)
        return 1

    # Sample name = basename bez extension (konzistentní s peak_visualizer.py).
    sample_name = img_path.stem
    out_dir = args.out_dir if args.out_dir else Path("output") / sample_name
    db_dir = out_dir / "db"

    # Late import cv2 + numpy — list/diff verby je nepotřebují.
    import cv2
    import numpy as np

    img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    if img is None:
        print(f"Nelze načíst obrázek: {img_path}", file=sys.stderr)
        return 1
    h, w = img.shape[:2]

    symbols_filter = _parse_symbols(args.symbols)

    # Akumulátor přes všechny detektory v této iteraci.
    all_objects: list = []
    # uint16 claim mask, 0 = unclaimed, jinak MapObject.id.
    claim_mask = np.zeros((h, w), dtype=np.uint16)
    # Persistent ID counter — pokračuje napříč detektory v rámci iter.
    # Pro multi-iter persistent IDs napříč iteracemi přijde matching v cmd diff.
    next_id = 1

    # --- Brown line detector v1 ---
    # Aktivuje se pokud filter chybí, nebo obsahuje 101/102.
    if symbols_filter is None or symbols_filter & {"101", "102"}:
        from brown_line_v1 import detect as detect_brown_line
        brown_objs, brown_mask = detect_brown_line(
            out_dir=out_dir,
            image_shape=(h, w),
            starting_id=next_id,
            iteration=args.iter,
        )
        # Merge claim mask: kde detector claimed (nonzero), zapsat do globální mask.
        # Pro v1 nejsou kolize (jen 1 detektor), do budoucna bude potřeba conflict resolution.
        nonzero = brown_mask > 0
        claim_mask[nonzero] = brown_mask[nonzero]
        all_objects.extend(brown_objs)
        next_id += len(brown_objs)
        print(f"  brown_line_v1:    {len(brown_objs):>4} objektů "
              f"({sum(1 for o in brown_objs if o.symbol_code == '101'):>3} × 101, "
              f"{sum(1 for o in brown_objs if o.symbol_code == '102'):>3} × 102)")

    # Post-filter na --symbols (KISS — detector spustí vše, filter až po).
    # Důvod: detektory budou produkovat víc symbol_codes (101 + 102 z jednoho běhu),
    # filtrovat per-detector dělá API složitější. Filter na konci je 1 řádek.
    if symbols_filter is not None:
        before = len(all_objects)
        all_objects = [o for o in all_objects if o.symbol_code in symbols_filter]
        # Claim mask čistíme: pixely nepatřící filtru → 0 (unclaimed).
        kept_ids = {o.id for o in all_objects}
        # np.isin vrátí bool mask: pixel je v kept_ids? Pixely false → 0.
        filter_mask = np.isin(claim_mask, list(kept_ids) + [0])
        claim_mask[~filter_mask] = 0
        if before != len(all_objects):
            print(f"  --symbols filter:  {before} → {len(all_objects)} objektů")

    # Unclaimed = pixely s hodnotou 0 v claim mask.
    unclaimed = int((claim_mask == 0).sum())

    snap = DBSnapshot(
        iteration=args.iter,
        source_image=str(img_path),
        image_shape=(h, w),
        objects=all_objects,
        non_map_elements=[],   # fáze A přijde později
        unclaimed_pixel_count=unclaimed,
    )

    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / f"iter_{args.iter}.json"
    snap.save(db_path)

    # Claim mask jako 16-bit PNG. cv2.imwrite respektuje dtype (uint16 → 16-bit PNG).
    mask_path = db_dir / f"claim_mask_iter_{args.iter}.png"
    cv2.imwrite(str(mask_path), claim_mask)

    # latest.txt = ukazatel na nejnovější iter (na Win nemáme rozumný symlink).
    (db_dir / "latest.txt").write_text(str(args.iter))

    print()
    print(f"DB: {db_dir}")
    print(f"  {db_path.name}")
    print(f"  {mask_path.name} (16-bit, hodnota = MapObject.id)")
    print(f"  iterace:           {snap.iteration}")
    print(f"  rozměry:           {h} × {w} = {h * w} px celkem")
    print(f"  objekty:           {len(snap.objects)}")
    print(f"  unclaimed pixelů:  {unclaimed} ({100 * unclaimed / (h * w):.1f} %)")

    return 0


# --- Verb: list ---

def cmd_list(args: argparse.Namespace) -> int:
    """Načte DBSnapshot, vypíše objekty (volitelně filtrované --symbols)."""
    db_path = _resolve_db_path(args.out_dir, args.iter)
    if not db_path.exists():
        print(f"DB neexistuje: {db_path}", file=sys.stderr)
        return 1

    snap = DBSnapshot.load(db_path)
    symbols_filter = _parse_symbols(args.symbols)

    print(f"=== DB list: {db_path} ===")
    print(f"Iterace: {snap.iteration}")
    print(f"Source:  {snap.source_image}")
    print(f"Image:   {snap.image_shape[0]} × {snap.image_shape[1]}")
    if symbols_filter:
        print(f"Filter:  --symbols {','.join(sorted(symbols_filter))}")
    print()

    # Filter aplikujeme na objects (NonMapElement nemá symbol_code).
    objs = snap.objects
    if symbols_filter:
        objs = [o for o in objs if o.symbol_code in symbols_filter]

    print(f"Objekty ({len(objs)}):")
    if not objs:
        print("  (žádné)")
    else:
        # Hlavička tabulky.
        print(f"  {'ID':>4}  {'Symbol':<8}  {'Typ':<6}  {'Cat':<8}  {'BBox':<22}  {'Conf':>6}  Method")
        for o in objs:
            bbox_str = f"({o.bbox[0]},{o.bbox[1]})-({o.bbox[2]},{o.bbox[3]})"
            print(
                f"  {o.id:>4}  {o.symbol_code:<8}  {o.geometry_type:<6}  "
                f"{o.category.value:<8}  {bbox_str:<22}  {o.confidence:>6.2f}  {o.detection_method}"
            )

    print()
    print(f"Non-map elements ({len(snap.non_map_elements)}):")
    if not snap.non_map_elements:
        print("  (žádné)")
    else:
        for e in snap.non_map_elements:
            print(f"  {e.id} {e.kind} bbox={e.bbox} metadata={e.metadata}")

    print()
    print(f"Unclaimed pixels: {snap.unclaimed_pixel_count}")

    return 0


# --- Verb stuby: mark / diff / export ---
# Implementace přijde až bude reálný detektor produkovat objekty do DB.

def cmd_mark(args: argparse.Namespace) -> int:
    """
    Vykreslí detekované objekty jako barevný overlay přes background.

    Postup:
      1. Načte iter_N.json + claim_mask_iter_N.png (pixel = MapObject.id).
      2. Filtruje objekty dle --symbols (a claim mask se omezí na jejich IDs).
      3. Per symbol_code přiřadí stabilní barvu z palety.
      4. Dilatuje claim mask pro vizibilitu (skeleton je 1px, neviditelný).
      5. Alpha-blend přes background.
      6. --with-ids: přidá popisky ID v centroidech (reuse annotate_with_ids
         z peak_visualizer.py, font_scale=0.2).

    Výstup: output/<sample>/marks/mark_iter_<N>[_<filter>][_ids].png
    """
    import cv2
    import numpy as np

    from peak_visualizer import annotate_with_ids, dilate_for_visibility

    # --- Načtení DB ---
    db_path = _resolve_db_path(args.out_dir, args.iter)
    if not db_path.exists():
        print(f"DB neexistuje: {db_path}", file=sys.stderr)
        return 1

    snap = DBSnapshot.load(db_path)
    iteration = snap.iteration

    mask_path = args.out_dir / "db" / f"claim_mask_iter_{iteration}.png"
    if not mask_path.exists():
        print(f"Claim mask neexistuje: {mask_path}", file=sys.stderr)
        return 1

    # IMREAD_UNCHANGED zachová 16-bit dtype (default IMREAD_COLOR by ho zahodil).
    claim_mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
    if claim_mask.dtype != np.uint16:
        # Backward-compat: kdyby starý 8-bit mask přežíval, povýšit.
        claim_mask = claim_mask.astype(np.uint16)

    # --- Filter na --symbols ---
    symbols_filter = _parse_symbols(args.symbols)
    objs = snap.objects
    if symbols_filter:
        objs = [o for o in objs if o.symbol_code in symbols_filter]

    if not objs:
        print(f"Žádné objekty k vykreslení (DB obsahuje {len(snap.objects)}, "
              f"po filtru {len(objs)}).", file=sys.stderr)
        return 1

    # --- Background ---
    h, w = snap.image_shape
    if args.background is not None:
        background = cv2.imread(str(args.background), cv2.IMREAD_COLOR)
        if background is None:
            print(f"Nelze načíst background: {args.background}", file=sys.stderr)
            return 1
        if background.shape[:2] != (h, w):
            print(f"Background dimenze {background.shape[:2]} ≠ DB {(h, w)}.",
                  file=sys.stderr)
            return 1
    else:
        # Bílá plocha — pro debug bez originálu.
        background = np.ones((h, w, 3), dtype=np.uint8) * 255

    # --- Barvy per symbol_code ---
    # Stabilní mapping: každý unikátní symbol_code → index do palety v pořadí
    # prvního výskytu v objs. Pro reproducible výstup.
    palette = [
        (0, 0, 255),       # BGR red
        (0, 255, 0),       # green
        (255, 0, 0),       # blue
        (0, 255, 255),     # yellow
        (255, 0, 255),     # magenta
        (255, 255, 0),     # cyan
        (0, 128, 255),     # orange
        (128, 0, 255),     # purple-ish
    ]
    symbol_to_color: dict[str, tuple[int, int, int]] = {}
    for o in objs:
        if o.symbol_code not in symbol_to_color:
            # Cyklicky přes paletu, kdyby symbol_codes > len(palette).
            symbol_to_color[o.symbol_code] = palette[len(symbol_to_color) % len(palette)]

    # --- Render overlay ---
    out = background.copy()
    alpha = 0.85

    # Set kept IDs pro rychlý check.
    kept_ids = {o.id for o in objs}
    # Restrict claim_mask jen na kept_ids — ostatní budou ignorovány.
    # Pro každý symbol_code samostatně, ať můžeme dilatovat skupinu a barvit jednotnou barvou.
    by_symbol: dict[str, list[int]] = {}
    for o in objs:
        by_symbol.setdefault(o.symbol_code, []).append(o.id)

    for symbol_code, ids in by_symbol.items():
        # Bool mask všech pixelů patřících tomuto symbol_code.
        # np.isin je vektorizovaná — rychlejší než smyčka pro velký claim_mask.
        symbol_mask = np.isin(claim_mask, ids).astype(np.uint8) * 255
        # Skeleton je 1px → bez dilatace špatně vidět. dilate_for_visibility = 3×3 kernel.
        dilated = dilate_for_visibility(symbol_mask)
        bool_mask = dilated > 0
        color = np.array(symbol_to_color[symbol_code], dtype=np.float32)
        # Alpha blend: new = (1-α)·orig + α·color
        out[bool_mask] = ((1 - alpha) * out[bool_mask] + alpha * color).astype(np.uint8)

    # --- ID popisky ---
    if args.with_ids:
        # annotate_with_ids potřebuje labels image (int) + list label IDs.
        # claim_mask má pixel = MapObject.id; přesně to chceme.
        # Cast na int32 (annotate používá np.where pro centroidy, int dtype požaduje).
        labels_int32 = claim_mask.astype(np.int32)
        out = annotate_with_ids(out, labels_int32, [o.id for o in objs])

    # --- Output path ---
    # Schema: mark_iter_<N>[_<sorted-symbols>][_ids].png
    parts = [f"mark_iter_{iteration}"]
    if symbols_filter:
        parts.append("_".join(sorted(symbols_filter)))
    if args.with_ids:
        parts.append("ids")
    output_name = "_".join(parts) + ".png"

    marks_dir = args.out_dir / "marks"
    marks_dir.mkdir(parents=True, exist_ok=True)
    output_path = marks_dir / output_name
    cv2.imwrite(str(output_path), out)

    # --- Report ---
    print(f"=== Mark: {output_path} ===")
    print(f"Iter: {iteration}, objektů: {len(objs)}")
    print()
    print("Barvy per symbol_code (BGR):")
    for code, color in symbol_to_color.items():
        count = sum(1 for o in objs if o.symbol_code == code)
        print(f"  {code:<6}  BGR{color}  ({count} objektů)")

    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    print("`diff` zatím není implementováno — vyžaduje 2+ iterace s reálnými objekty.",
          file=sys.stderr)
    return 1


def cmd_export(args: argparse.Namespace) -> int:
    print("`export` (db2omap) zatím není implementováno — přijde po prvním kompletním pic2db průchodu.",
          file=sys.stderr)
    return 1


# --- Argparse setup ---

def build_parser() -> argparse.ArgumentParser:
    """
    Top-level parser s subcommands. Sdílené argumenty (--symbols, --iter)
    žijí na subcommand level, protože ne každý verb je má (např. `diff`
    používá --from/--to místo --iter).
    """
    parser = argparse.ArgumentParser(
        prog="pic2db",
        description="Detekce a manipulace s DB mezivrstvou (pic2db / db2omap). Viz docs/db_schema.md.",
    )
    sub = parser.add_subparsers(dest="verb", required=True, metavar="VERB")

    # --- detect ---
    p_detect = sub.add_parser(
        "detect",
        help="Spustí detekci, zapíše iter_N.json (skeleton: prázdný snapshot).",
    )
    p_detect.add_argument("image", type=Path, help="Vstupní raster (PNG).")
    p_detect.add_argument("--iter", type=int, default=0,
                          help="Číslo iterace (default 0 = po fázi A).")
    p_detect.add_argument("--out-dir", type=Path, default=None,
                          help="Výstupní adresář (default output/<image-stem>/).")
    p_detect.add_argument("--symbols", type=str, default=None,
                          help="Omezení detekce na symboly (např. 101,102,103). Skeleton ignoruje.")
    p_detect.set_defaults(func=cmd_detect)

    # --- list ---
    p_list = sub.add_parser("list", help="Vypíše objekty v DB.")
    p_list.add_argument("out_dir", type=Path, help="Adresář s db/ podadresářem.")
    p_list.add_argument("--iter", type=int, default=None,
                        help="Číslo iterace (default = latest dle db/latest.txt).")
    p_list.add_argument("--symbols", type=str, default=None,
                        help="Filtr na symboly (např. 204,205).")
    p_list.set_defaults(func=cmd_list)

    # --- mark (stub) ---
    p_mark = sub.add_parser("mark", help="Overlay objektů přes background [NOT IMPLEMENTED].")
    p_mark.add_argument("out_dir", type=Path)
    p_mark.add_argument("--iter", type=int, default=None)
    p_mark.add_argument("--symbols", type=str, default=None)
    p_mark.add_argument("--background", type=Path, default=None)
    p_mark.add_argument("--with-ids", action="store_true",
                        help="Přidá ID popisky (font_scale=0.2).")
    p_mark.set_defaults(func=cmd_mark)

    # --- diff (stub) ---
    p_diff = sub.add_parser("diff", help="Porovnání dvou iterací [NOT IMPLEMENTED].")
    p_diff.add_argument("out_dir", type=Path)
    p_diff.add_argument("--from", dest="from_iter", type=int, required=True)
    p_diff.add_argument("--to", dest="to_iter", type=int, required=True)
    p_diff.set_defaults(func=cmd_diff)

    # --- export (stub) ---
    p_export = sub.add_parser("export", help="db2omap serializace [NOT IMPLEMENTED].")
    p_export.add_argument("out_dir", type=Path)
    p_export.add_argument("--to", choices=["omap"], required=True)
    p_export.add_argument("--out", type=Path, required=True)
    p_export.add_argument("--iter", type=int, default=None)
    p_export.set_defaults(func=cmd_export)

    return parser


def main() -> int:
    # Windows konzole: vynutíme UTF-8 pro stdout/stderr, jinak české znaky padají.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()
    # set_defaults(func=...) zaregistroval handler per subcommand, dispatch je 1 řádek.
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
