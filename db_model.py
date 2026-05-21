"""
DB model pro pic2db / db2omap.

Strukturovaná mezivrstva mezi raster detekcí a OMAP XML serializací.
Kanonická specifikace: docs/db_schema.md.

Návrhové principy:
- Stdlib only (json, dataclasses) — žádné nové dependencies.
- ColorCategory enum se serializuje jako string (.value).
- Tuple → list v JSON, při loadu zpět na tuple (kvůli typové konzistenci).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from color_category import ColorCategory


# Type aliasy — Literal typy se chovají jako stringy, ale typecheckerům říkají,
# které hodnoty jsou povolené. Runtime je stále plain str.
GeometryType = Literal["point", "line", "area"]
NonMapKind = Literal["text", "logo", "purplepen"]


@dataclass
class MapObject:
    """
    Jeden detekovaný mapový objekt.

    Persistent ID napříč iteracemi — pokud objekt přežije re-recognition
    (IoU bbox match v dalším passu), drží své původní id. Viz db_schema.md.
    """
    id: int
    symbol_code: str                       # "101", "204"... string kvůli OMAP konzistenci
    geometry_type: GeometryType            # "point" | "line" | "area"
    category: ColorCategory                # brown / black / blue / ...
    bbox: tuple[int, int, int, int]        # (x0, y0, x1, y1) v px rasteru
    pixel_count: int                       # info; rychlý filter pro list/mark
    pixel_blob_id: int                     # odkaz do claim_mask_iter_N.png
    confidence: float                      # 0.0–1.0
    detected_in_iter: int                  # iterace, ve které objekt vznikl
    detection_method: str                  # "thickness_v1", "shape_match_v1", ...


@dataclass
class NonMapElement:
    """
    Výstup fáze A (strip overlays) — texty, loga, PurplePen tratě.
    Drží se v DB kvůli db2omap (může chtít zachovat trať jako template).
    """
    id: int
    kind: NonMapKind                       # "text" | "logo" | "purplepen"
    bbox: tuple[int, int, int, int]
    # default_factory=dict: každá NonMapElement instance dostane svůj vlastní
    # prázdný dict. Bez něho by všechny instance sdílely jeden dict (Python
    # mutable default argument gotcha).
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DBSnapshot:
    """
    Jeden iter_N.json soubor. Kontejner stavu DB v dané iteraci.
    """
    iteration: int
    source_image: str                      # relativní cesta ke zdrojovému rasteru
    image_shape: tuple[int, int]           # (height, width)
    objects: list[MapObject] = field(default_factory=list)
    non_map_elements: list[NonMapElement] = field(default_factory=list)
    unclaimed_pixel_count: int = 0         # pro stop-konvergenci fáze B
    # Rotace mapy ve stupních (CCW). 0 = sever nahoru (orienťácký default).
    # Detekce z paralelních north lines (601.x) — viz orientation_v1.py.
    # None = orientation_v1 nedoběhl nebo nenašel signál → fallback 0 v detektorech.
    map_orientation_deg: float | None = 0.0

    def to_dict(self) -> dict[str, Any]:
        """
        Serializace pro JSON. Explicitně, ne přes dataclasses.asdict() —
        ten neumí ColorCategory enum (json.dump by spadl). Explicit je čitelnější.
        """
        return {
            "iteration": self.iteration,
            "source_image": self.source_image,
            # tuple → list: JSON nemá tuple, list je default.
            "image_shape": list(self.image_shape),
            "objects": [
                {
                    "id": o.id,
                    "symbol_code": o.symbol_code,
                    "geometry_type": o.geometry_type,
                    # Enum → string přes .value (ColorCategory.BROWN.value == "brown").
                    "category": o.category.value,
                    "bbox": list(o.bbox),
                    "pixel_count": o.pixel_count,
                    "pixel_blob_id": o.pixel_blob_id,
                    "confidence": o.confidence,
                    "detected_in_iter": o.detected_in_iter,
                    "detection_method": o.detection_method,
                }
                for o in self.objects
            ],
            "non_map_elements": [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "bbox": list(e.bbox),
                    "metadata": e.metadata,
                }
                for e in self.non_map_elements
            ],
            "unclaimed_pixel_count": self.unclaimed_pixel_count,
            "map_orientation_deg": self.map_orientation_deg,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DBSnapshot":
        """
        Deserializace z JSON dictu. Inverzní k to_dict.
        Pozn: list → tuple konverze obnovuje typovou konzistenci.
        """
        objects = [
            MapObject(
                id=o["id"],
                symbol_code=o["symbol_code"],
                geometry_type=o["geometry_type"],
                # String → Enum přes konstruktor (ColorCategory("brown") == BROWN).
                category=ColorCategory(o["category"]),
                bbox=tuple(o["bbox"]),
                pixel_count=o["pixel_count"],
                pixel_blob_id=o["pixel_blob_id"],
                confidence=o["confidence"],
                detected_in_iter=o["detected_in_iter"],
                detection_method=o["detection_method"],
            )
            for o in data["objects"]
        ]
        non_map = [
            NonMapElement(
                id=e["id"],
                kind=e["kind"],
                bbox=tuple(e["bbox"]),
                metadata=e.get("metadata", {}),
            )
            for e in data["non_map_elements"]
        ]
        return cls(
            iteration=data["iteration"],
            source_image=data["source_image"],
            image_shape=tuple(data["image_shape"]),
            objects=objects,
            non_map_elements=non_map,
            # .get s defaultem — backward compat pro starší snapshoty bez pole.
            unclaimed_pixel_count=data.get("unclaimed_pixel_count", 0),
            map_orientation_deg=data.get("map_orientation_deg", 0.0),
        )

    def save(self, path: Path) -> None:
        """Uložit do JSON souboru. Vytvoří parent adresáře pokud chybí."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            # ensure_ascii=False → české znaky v komentářích/metadatech čitelné.
            # indent=2 → human-readable diff mezi iteracemi.
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path) -> "DBSnapshot":
        """Načíst z JSON souboru."""
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


# --- Smoke test: JSON round-trip ---
# Spuštění: `python db_model.py`. Ověří že save→load nevyrobí drift.

if __name__ == "__main__":
    import tempfile

    # Sample DBSnapshot s jedním objektem a jedním non-map elementem.
    sample = DBSnapshot(
        iteration=1,
        source_image="resources/forest sample.png",
        image_shape=(478, 631),
        objects=[
            MapObject(
                id=1, symbol_code="101", geometry_type="line",
                category=ColorCategory.BROWN, bbox=(10, 20, 100, 200),
                pixel_count=42, pixel_blob_id=1, confidence=0.95,
                detected_in_iter=1, detection_method="thickness_v1",
            ),
        ],
        non_map_elements=[
            NonMapElement(
                id=1, kind="text", bbox=(0, 0, 50, 20),
                metadata={"ocr": "21"},
            ),
        ],
        unclaimed_pixel_count=12345,
    )

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        tmp_path = Path(f.name)

    try:
        sample.save(tmp_path)
        loaded = DBSnapshot.load(tmp_path)

        # Dataclasses mají __eq__ z dataclass dekorátoru — porovnání po polích.
        assert loaded == sample, f"Round-trip mismatch!\n  orig:   {sample}\n  loaded: {loaded}"
        print("OK — JSON round-trip passed")
        print(f"   objects: {len(loaded.objects)}, non_map: {len(loaded.non_map_elements)}")
    finally:
        tmp_path.unlink(missing_ok=True)
