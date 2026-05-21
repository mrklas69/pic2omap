"""
train — U-Net trénink segmentace ploch (komponenta #3-4 ML pilotu).

Čte dataset z `build_dataset.py` (manifest.json + dlaždice 512×512) a trénuje
`segmentation-models-pytorch` U-Net (encoder resnet34, ImageNet pretrained) na
8 tříd ColorCategory úrovně (0=pozadí .. 7=purple, viz omap_mask.CATEGORY_TO_CLASS).

Bez Lightning (rozhodnutí sezení 12): čistá train/val smyčka, checkpoint nejlepšího
val mIoU. Augmentace albumentations on-the-fly (mírná — val/test jsou rendery, ne
skeny, domain gap se v pilotu netestuje; agresivní balík připraven zakomentovaný).
Loss = Dice + CrossEntropy (snáší silnou nerovnováhu tříd: gray ~1e3 px vs yellow ~1e7).

HW dělba (sezení 12): vývoj + smoke-test tady na CPU, plný trénink na GPU "mrkla".
Device se volí automaticky. ML balíčky: viz requirements-ml.txt.

Použití:
    python train.py --smoke                 # rychlé ověření pipeline na CPU (8/4 dlaždice, 2 epochy)
    python train.py --epochs 40 --batch 8   # plný trénink (na "mrkla")
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

import albumentations as A
import segmentation_models_pytorch as smp
from albumentations.pytorch import ToTensorV2

from cli_utils import force_utf8_console
from omap_mask import NUM_CLASSES

# ImageNet normalizace — encoder je pretrained na ImageNet, vstup musí sedět.
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


# --- Augmentace ---------------------------------------------------------------

def build_train_aug() -> A.Compose:
    """
    Mírná augmentace (volba sezení 13). Geometrické symetrie + drobný scale/posun +
    lehký jas/kontrast. Maska se interpoluje nearest (zachová class indexy).

    Pilot val/test jsou rendery z .omap (ne degradované skeny), takže domain gap
    render→sken se tu NEvaliduje — agresivní fotometrická augmentace by jen mohla
    srazit within-domain IoU. Pro pozdější trénink na REÁLNÝ vstup odkomentuj
    domain-gap blok níže (šum, blur, JPEG, papír, blednutí).
    """
    return A.Compose([
        A.HorizontalFlip(p=0.5),
        A.VerticalFlip(p=0.5),
        A.RandomRotate90(p=0.5),
        A.Affine(scale=(0.9, 1.1), translate_percent=0.05, rotate=0, p=0.5),
        A.RandomBrightnessContrast(brightness_limit=0.1, contrast_limit=0.1, p=0.3),
        # --- domain-gap balík (pro reálné skeny, ZÁMĚRNĚ vypnutý pro pilot) ---
        # A.GaussNoise(p=0.3),
        # A.MotionBlur(blur_limit=5, p=0.2),
        # A.ImageCompression(quality_range=(40, 90), p=0.3),
        # A.RandomGamma(p=0.2),
        # A.GridDistortion(p=0.2),
        A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ToTensorV2(),
    ])


def build_eval_aug() -> A.Compose:
    """Eval: jen normalizace (žádná náhoda — deterministické val/test metriky)."""
    return A.Compose([
        A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ToTensorV2(),
    ])


# --- Dataset ------------------------------------------------------------------

class SegDataset(Dataset):
    """Čte dlaždice jednoho splitu z manifest.json. Vrací (image CHW float, mask HW long)."""

    def __init__(self, manifest_path: Path, split: str, transform: A.Compose, limit: int | None = None):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.root = manifest_path.parent
        self.tiles = [t for t in manifest["tiles"] if t["split"] == split]
        if limit is not None:
            self.tiles = self.tiles[:limit]
        self.transform = transform

    def __len__(self) -> int:
        return len(self.tiles)

    def __getitem__(self, i: int):
        t = self.tiles[i]
        bgr = cv2.imread(str(self.root / t["image"]))           # cv2 čte BGR
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        mask = cv2.imread(str(self.root / t["mask"]), cv2.IMREAD_GRAYSCALE)  # class indexy 0..7
        out = self.transform(image=rgb, mask=mask)
        return out["image"], out["mask"].long()


# --- Model + loss -------------------------------------------------------------

def build_model(encoder: str) -> nn.Module:
    return smp.Unet(
        encoder_name=encoder,
        encoder_weights="imagenet",
        in_channels=3,
        classes=NUM_CLASSES,
        activation=None,            # syrové logity (loss/metriky si poradí)
    )


class DiceCELoss(nn.Module):
    """Dice + CrossEntropy. Dice tlumí imbalance (per-class překryv), CE drží stabilní gradient."""

    def __init__(self):
        super().__init__()
        self.dice = smp.losses.DiceLoss(mode="multiclass")
        self.ce = nn.CrossEntropyLoss()

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        return self.dice(logits, target) + self.ce(logits, target)


# --- Metrika (per-class IoU) --------------------------------------------------

@torch.no_grad()
def evaluate(model: nn.Module, loader: DataLoader, device: str) -> tuple[float, dict[int, float]]:
    """Vrátí (mean IoU přes třídy přítomné v GT, per-class IoU). Akumuluje tp/fp/fn/tn přes batche."""
    model.eval()
    tp = fp = fn = tn = None
    for img, mask in loader:
        logits = model(img.to(device))
        preds = logits.argmax(dim=1).cpu()                       # [B,H,W] class indexy
        b_tp, b_fp, b_fn, b_tn = smp.metrics.get_stats(
            preds, mask, mode="multiclass", num_classes=NUM_CLASSES)
        b = [s.sum(dim=0) for s in (b_tp, b_fp, b_fn, b_tn)]     # [C] součet přes batch
        if tp is None:
            tp, fp, fn, tn = b
        else:
            tp, fp, fn, tn = (acc + cur for acc, cur in zip((tp, fp, fn, tn), b))

    iou = smp.metrics.iou_score(tp, fp, fn, tn, reduction=None)  # [C]
    present = (tp + fn) > 0                                       # třída je v GT
    per_class = {c: float(iou[c]) for c in range(NUM_CLASSES) if bool(present[c])}
    mean_iou = float(np.mean(list(per_class.values()))) if per_class else 0.0
    return mean_iou, per_class


# --- Train --------------------------------------------------------------------

def train_one_epoch(model, loader, loss_fn, optimizer, device) -> float:
    model.train()
    total = 0.0
    for img, mask in loader:
        optimizer.zero_grad()
        logits = model(img.to(device))
        loss = loss_fn(logits, mask.to(device))
        loss.backward()
        optimizer.step()
        total += loss.item()
    return total / max(len(loader), 1)


def set_seed(seed: int) -> None:
    """Fixuje RNG (python/numpy/torch) pro reprodukovatelný trénink — init vah,
    augmentace i shuffle. CUDA seed pokrývá i GPU běh na „mrkla"."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def fit(args) -> None:
    set_seed(args.seed)
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    manifest_path = Path(args.dataset) / "manifest.json"
    class_names = {int(k): v for k, v in
                   json.loads(manifest_path.read_text(encoding="utf-8"))["class_names"].items()}

    limit = 8 if args.smoke else None
    val_limit = 4 if args.smoke else None
    train_ds = SegDataset(manifest_path, "train", build_train_aug(), limit)
    val_ds = SegDataset(manifest_path, "val", build_eval_aug(), val_limit)
    # Generator se seedem → reprodukovatelné pořadí shuffle napříč běhy.
    loader_gen = torch.Generator().manual_seed(args.seed)
    train_loader = DataLoader(train_ds, batch_size=args.batch, shuffle=True,
                              num_workers=args.workers, generator=loader_gen)
    val_loader = DataLoader(val_ds, batch_size=args.batch, shuffle=False, num_workers=args.workers)

    model = build_model(args.encoder).to(device)
    loss_fn = DiceCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "best.pt"

    print(f"=== train: device={device} encoder={args.encoder} "
          f"train={len(train_ds)} val={len(val_ds)} epochs={args.epochs} batch={args.batch} ===")

    best_miou = -1.0
    for epoch in range(1, args.epochs + 1):
        train_loss = train_one_epoch(model, train_loader, loss_fn, optimizer, device)
        miou, per_class = evaluate(model, val_loader, device)
        flag = ""
        if miou > best_miou:
            best_miou = miou
            torch.save({"model": model.state_dict(), "epoch": epoch, "val_miou": miou,
                        "encoder": args.encoder, "num_classes": NUM_CLASSES}, ckpt_path)
            flag = "  ← best (uloženo)"
        per_class_str = " ".join(f"{class_names.get(c, c)}={v:.2f}" for c, v in per_class.items())
        print(f"  epoch {epoch:3}/{args.epochs}  loss={train_loss:.4f}  val_mIoU={miou:.3f}  "
              f"[{per_class_str}]{flag}")

    print(f"\n  nejlepší val mIoU: {best_miou:.3f}  → {ckpt_path}")


def main() -> None:
    force_utf8_console()
    ap = argparse.ArgumentParser(description="U-Net trénink segmentace ploch (ML pilot).")
    ap.add_argument("--dataset", default="output/dataset", help="adresář s manifest.json")
    ap.add_argument("--out", default="output/checkpoints", help="kam ukládat checkpoint")
    ap.add_argument("--encoder", default="resnet34", help="smp encoder (resnet34, resnet18, ...)")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--workers", type=int, default=0, help="DataLoader workers (0 = bezpečné na Windows)")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed pro reprodukovatelnost")
    ap.add_argument("--device", default=None, help="cuda/cpu (default auto)")
    ap.add_argument("--smoke", action="store_true",
                    help="rychlý smoke-test: 8 train / 4 val dlaždice, 2 epochy, malý batch")
    args = ap.parse_args()

    if args.smoke:
        args.epochs = 2
        args.batch = min(args.batch, 2)

    fit(args)


if __name__ == "__main__":
    main()
