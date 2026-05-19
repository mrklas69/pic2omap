# DIARY — pic2omap

Index pracovních sezení. Detail v `docs/diary/YYYY-MM-DD.md`.

## Sezení

- [2026-05-19](docs/diary/2026-05-19.md) — Sezení 1: založení projektu, brainstorming `pic2omap`, rešerše existujících řešení
- [2026-05-19](docs/diary/2026-05-19.md#sezení-2) — Sezení 2: symbol DB (OMAP parser + dataclass model), IOF spec verifikace, color separation (Stage 2) funguje na forest sample
- [2026-05-19](docs/diary/2026-05-19.md#sezení-3) — Sezení 3: Stage 3 (morfologie + connected components + skeletonizace) funguje, vrstevnice jako 1px středovky připravené pro Stage 5
- [2026-05-19](docs/diary/2026-05-19.md#sezení-4) — Sezení 4: ground truth comparison (`compare_to_omap.py`) — první metrika úspěchu Fáze 0, ratio 2.26× pro BROWN vrstevnice, GitHub publikace
- [2026-05-19](docs/diary/2026-05-19.md#sezení-5) — Sezení 5: GT fix (secondary_color_ref fallback + phantom objects XPath) — 156 přeskočených objektů → 0, ratiosy přesnější, %AUDIT:DOCS + opravy
- [2026-05-19](docs/diary/2026-05-19.md#sezení-6) — Sezení 6: pic2db/db2omap architektonický split, DB infrastruktura (db_model + CLI router), brown_line_v1 (138 obj), area_v1 (green/yellow), orientation_v1 (Slovanka 0.0°), erosion_gully_v1 experiment failed
- [2026-05-19](docs/diary/2026-05-19.md#sezení-7) — Sezení 7: %AUDIT:CODE+DOCS opravy, area_v1 v2 per-priority disambiguation (--omap flag), black area detector (526 Building), form_line_v1 experiment failed (sparse GT trap), Slovanka2016 generalizační test (4968 obj)
- [2026-05-20](docs/diary/2026-05-20.md) — Sezení 8: template-aware symbol codes (brown_line + area default), area RGB-collision fix (403.1 "over-detection" byl mislabeling z RGB-identických .0/.1 párů), db2omap PoC export (188 obj, validní OMAP)
