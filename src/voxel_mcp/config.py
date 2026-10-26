import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace: Path = Path("workspace")
    read_roots: tuple[Path, ...] = ()
    max_axis: int = Field(default=126, ge=1, le=256)
    max_voxels: int = Field(default=2_000_376, ge=1, le=256**3)
    max_operations: int = Field(default=1000, ge=1, le=10000)
    max_processed_cells: int = Field(default=20_000_000, ge=1)
    max_file_bytes: int = Field(default=64 * 1024**2, ge=2048)
    max_assets: int = Field(default=128, ge=1)
    history_limit: int = Field(default=8, ge=0, le=32)
    max_png_pixels: int = Field(default=16_000_000, ge=1)
    magicavoxel_exe: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        values = {}
        for key in cls.model_fields:
            value = os.environ.get("VOXEL_" + key.upper())
            if value is not None:
                values[key] = (
                    tuple(Path(p) for p in value.split(os.pathsep) if p)
                    if key == "read_roots"
                    else value
                )
        if os.environ.get("MAGICAVOXEL_EXE"):
            values["magicavoxel_exe"] = os.environ["MAGICAVOXEL_EXE"]
        return cls(**values)
