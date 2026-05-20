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
- [2026-05-20](docs/diary/2026-05-20.md#2026-05-20--sezení-9) — Sezení 9: db2omap rigorózní georef (.pgw + OMAP georef, pixel→coord bez rotace, ověřeno 4×), line vektorizace segment-trace (kostra jako graf, neztrácí délku). Slovanka 3759→5968 obj, forest 188→451
- [2026-05-20](docs/diary/2026-05-20.md#2026-05-20--sezení-10) — Sezení 10: L-roh merge (post-trace `_merge_segments`, 89 % deg≥3 = staircase, Slovanka −18 % segmentů), N↔S flip fix (OMAP y-down ze zdrojáku Mapperu), georef parsing fix (map vs projected ref_point + map_ref + aux_scale), třetí pár Garching (ISSprOM sprint) end-to-end — bbox = GT bbox
- [2026-05-20](docs/diary/2026-05-20.md#2026-05-20--sezení-11) — Sezení 11: GRAY detektor budov (241 budov Garching, median 1297 px), ISSprOM combined resolver (`_promote_to_combined` 526.1.1 → 526.1, parts parsing, 220× combined export), BLACK regrese fix (category filtr), "154 budov" vyvráceno (fragmenty median 26 px). %THINK obrat: fokus na krok 4 (rozpoznání), milník v1 "lesní core", export zamražen
- [2026-05-20](docs/diary/2026-05-20.md#2026-05-20--sezení-12) — Sezení 12: **obrat na ML** (vytrénovat rozpoznávač místo ladění cv2). Nový stroj (první klon). Pilot segmentace ploch: komponenta #1 `omap_mask.py` (maska z .omap geometrie, ne barev PNG; reality-check georef OK na úrovni ploch), #2 `build_dataset.py` (tiling 512, spatial split Slovanky 234/62 + Garching test). OOM 0.9.5 = GUI-only (žádný headless render). Prostředí `.venv` + `requirements.txt`
