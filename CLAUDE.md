# CLAUDE.md — pic2omap (projektový overlay)

Rozšiřuje globální `~/.claude/CLAUDE.md`, nepřevažuje. Makra %BEGIN/%END:
viz `docs/PROMPTS.md`. Stav/architektura projektu: README.md (ne sem).

## Doménové pracovní zásady
- **Verify-against-source, nevěř agregátům.** `.omap` XML / zdroj je
  pravda; než uvěříš count ratiu, koukni do geometrie. (Zachránilo nález
  5×: 109 erosion, 403.1 „iluze", 154 „budov", N↔S flip, georef posun.)
- **Ověř premisu empiricky PŘED kódem** — hypotézu detektoru/fixu doložit
  daty z `.omap`, ne domněnkou.
- **Baseline-driven regrese** — před zásahem do detekčního toku zachyť
  baseline detect (forest sample iter_1 = 722 objektů invariant); DRY/
  refaktor musí být behavior-preserving.
- **Mapař v smyčce** — uživatel je doménový expert (orienťák); detekci
  oponuje per-objekt přes review nástroj.

## %THINK — doménové rozšíření
U detekce/ML zvaž: ISOM↔ISSprOM spec rozdíly (stejný kód = jiný symbol),
paper-space vs world georef, limity color separation (RGB-identické páry
.0/.1), sparse-GT past (vzácný symbol v zašuměném bucketu → naivní
detektor vždy over-claim).

## Klíčové soubory (orientace; plný rozpis README „Repository layout")
- Vstupní body: `pic2db.py` (detect/list/mark/export), `db2omap.py`,
  `omap_mask.py`/`build_dataset.py`/`train.py`/`eval.py` (ML pilot).
- Sdílené jádro: `georef.py` (pixel↔coord, sdílí 3 moduly — pozor na
  regrese), `omap_parser.py`/`omap_model.py` (symbol DB), `cli_utils.py`.
- Dva paralelní tracky: cv2 review-driven detekce + ML pilot segmentace.
