"""
eval — vyhodnocení natrénovaného U-Net (komponenta #5 ML pilotu).

Load checkpoint → per-class IoU na zvoleném splitu + vizuální overlay
(foto | GT maska | predikce). Cross-domain go/no-go = `--split test` (Garching);
within-domain srovnání = `--split val` (Slovanka spatial split).

Reuse train.py (SegDataset, build_model, build_eval_aug, evaluate) — eval je jen
jiný vstup (checkpoint místo tréninku) + vizualizace. DRY/izomorfní s train.

Použití:
    python eval.py                          # best.pt na test splitu (Garching, cross-domain)
    python eval.py --split val --n 8        # within-domain + 8 overlayů
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader

from cli_utils import force_utf8_console
from train import SegDataset, build_eval_aug, build_model, evaluate

# Barvy tříd pro overlay (BGR) — vizuálně blízké ColorCategory. Klíč = název třídy
# z manifestu (robustní vůči číslování class indexů).
COLOR_BY_NAME: dict[str, tuple[int, int, int]] = {
    "background": (245, 245, 245),
    "green":      (70, 160, 70),
    "yellow":     (70, 210, 240),
    "blue":       (230, 150, 40),
    "gray":       (140, 140, 140),
    "black":      (35, 35, 35),
    "brown":      (45, 90, 150),
    "purple":     (200, 70, 200),
}


def colorize(mask: np.ndarray, class_names: dict[int, str]) -> np.ndarray:
    """Class-index maska (HW) → BGR obraz pro vizuální overlay."""
    out = np.zeros((*mask.shape, 3), dtype=np.uint8)
    for idx, name in class_names.items():
        out[mask == idx] = COLOR_BY_NAME.get(name, (128, 128, 128))
    return out


def run_eval(args) -> None:
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    manifest_path = Path(args.dataset) / "manifest.json"
    class_names = {int(k): v for k, v in
                   json.loads(manifest_path.read_text(encoding="utf-8"))["class_names"].items()}

    ckpt = torch.load(args.checkpoint, map_location=device)
    model = build_model(ckpt.get("encoder", args.encoder)).to(device)
    model.load_state_dict(ckpt["model"])
    print(f"=== eval: checkpoint={args.checkpoint} (epoch {ckpt.get('epoch', '?')}, "
          f"train val_mIoU {ckpt.get('val_miou', float('nan')):.3f}) "
          f"split={args.split} device={device} ===")

    ds = SegDataset(manifest_path, args.split, build_eval_aug())
    if len(ds) == 0:
        raise SystemExit(f"Split '{args.split}' je prázdný v {manifest_path}.")
    loader = DataLoader(ds, batch_size=args.batch, shuffle=False, num_workers=args.workers)
    mean_iou, per_class = evaluate(model, loader, device)

    print(f"\n  {'třída':12} {'IoU':>6}")
    for idx in sorted(per_class):
        print(f"  {class_names.get(idx, str(idx)):12} {per_class[idx]:6.3f}")
    print(f"  {'mean IoU':12} {mean_iou:6.3f}  ({len(ds)} dlaždic, split={args.split})")

    # Vizuální overlaye: rovnoměrně rozprostřený vzorek dlaždic.
    if args.n > 0:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        tfm = build_eval_aug()
        model.eval()
        step = max(1, len(ds.tiles) // args.n)
        saved = 0
        with torch.no_grad():
            for t in ds.tiles[::step][:args.n]:
                bgr = cv2.imread(str(ds.root / t["image"]))
                gt = cv2.imread(str(ds.root / t["mask"]), cv2.IMREAD_GRAYSCALE)
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                x = tfm(image=rgb, mask=gt)["image"].unsqueeze(0).to(device)
                pred = model(x).argmax(1)[0].cpu().numpy().astype(np.uint8)
                trip = np.hstack([bgr, colorize(gt, class_names), colorize(pred, class_names)])
                cv2.imwrite(str(out_dir / f"eval_{args.split}_{Path(t['image']).stem}.png"), trip)
                saved += 1
        print(f"\n  {saved} overlayů (foto | GT | predikce) → {out_dir}")


def main() -> None:
    force_utf8_console()
    ap = argparse.ArgumentParser(description="Eval U-Net segmentace ploch (komponenta #5).")
    ap.add_argument("--checkpoint", default="output/checkpoints/best.pt")
    ap.add_argument("--dataset", default="output/dataset", help="adresář s manifest.json")
    ap.add_argument("--split", default="test", help="test (cross-domain Garching) / val (within-domain Slovanka)")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--encoder", default="resnet34", help="fallback, když checkpoint neuvádí encoder")
    ap.add_argument("--device", default=None, help="cuda/cpu (default auto)")
    ap.add_argument("--n", type=int, default=6, help="počet vizuálních overlayů (0 = žádné)")
    ap.add_argument("--out", default="output/eval", help="kam ukládat overlaye")
    args = ap.parse_args()
    run_eval(args)


if __name__ == "__main__":
    main()
