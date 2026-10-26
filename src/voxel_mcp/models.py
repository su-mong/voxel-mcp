import base64
import math
import re
from dataclasses import dataclass
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter

from .config import Settings
from .errors import VoxelError
from .palette import PaletteInput, make_palette

Point = tuple[StrictInt, StrictInt, StrictInt]
Color = Annotated[StrictInt, Field(ge=1, le=255)]
Index = Annotated[StrictInt, Field(ge=0, le=255)]
Revision = Annotated[StrictInt, Field(ge=0)]
_point_adapter = TypeAdapter(Point)
_reserved = {"con", "prn", "aux", "nul", *(f"{p}{i}" for p in ("com", "lpt") for i in range(1, 10))}


def asset_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise VoxelError(
            "asset_name must be 1..64 ASCII letters, digits, underscores or hyphens, starting with a letter or digit."
        )
    name = value.lower()
    if name in _reserved:
        raise VoxelError("Windows reserved device names are not allowed.")
    return name


def validate_size(value: Point, settings: Settings) -> Point:
    size = _point_adapter.validate_python(value)
    if any(v < 1 or v > settings.max_axis for v in size) or math.prod(size) > settings.max_voxels:
        raise VoxelError(
            f"Size must be within 1..{settings.max_axis} per axis and {settings.max_voxels} total cells."
        )
    return size


class AssetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    asset_name: str
    size: Point
    palette: PaletteInput
    revision: Revision
    grid: str
    history: list[str] = Field(default_factory=list)
    saved_vox_sha256: str | None = None


@dataclass
class VoxelAsset:
    asset_name: str
    grid: np.ndarray
    palette: list
    revision: int = 0
    saved_vox_sha256: str | None = None

    @property
    def size(self) -> Point:
        return tuple(self.grid.shape)

    @classmethod
    def create(cls, name: str, size: Point, palette: PaletteInput | None, settings: Settings):
        return cls(
            asset_name(name),
            np.zeros(validate_size(size, settings), dtype=np.uint8),
            make_palette(palette),
        )

    def info(self) -> dict:
        occupied = np.argwhere(self.grid != 0)
        bounds = (
            {"min": occupied.min(axis=0).tolist(), "max": occupied.max(axis=0).tolist()}
            if len(occupied)
            else None
        )
        return {
            "asset_name": self.asset_name,
            "size": list(self.size),
            "palette": self.palette,
            "revision": self.revision,
            "voxel_count": len(occupied),
            "bounds": bounds,
        }

    def encode_grid(self) -> str:
        return base64.b64encode(self.grid.tobytes(order="C")).decode("ascii")

    def record(self, history: list[str] | None = None) -> AssetRecord:
        return AssetRecord(
            asset_name=self.asset_name,
            size=self.size,
            palette=self.palette,
            revision=self.revision,
            grid=self.encode_grid(),
            history=history or [],
            saved_vox_sha256=self.saved_vox_sha256,
        )


def decode_grid(encoded: str, size: Point) -> np.ndarray:
    expected = math.prod(size)
    if len(encoded) != 4 * ((expected + 2) // 3):
        raise VoxelError("Corrupt asset state: grid size mismatch.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise VoxelError("Corrupt asset state: invalid grid encoding.") from exc
    if len(raw) != expected:
        raise VoxelError("Corrupt asset state: grid size mismatch.")
    return np.frombuffer(raw, dtype=np.uint8).reshape(size).copy()
