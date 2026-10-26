"""Internal palette index 0 is empty; VOX RGBA record 0 corresponds to index 1."""

from itertools import product
from typing import Annotated

from pydantic import Field, StrictInt, TypeAdapter

from .errors import VoxelError

Byte = Annotated[StrictInt, Field(ge=0, le=255)]
RGBA = tuple[Byte, Byte, Byte, Byte]
PaletteInput = Annotated[list[RGBA], Field(min_length=1, max_length=256)]
_palette_adapter = TypeAdapter(PaletteInput)


def default_palette() -> list[RGBA]:
    # Original author's default_palette, represented as RGBA bytes (not host-endian ints).
    levels = (255, 204, 153, 102, 51, 0)
    colors = [(r, g, b, 255) for r, g, b in product(levels, repeat=3) if (r, g, b) != (0, 0, 0)]
    ramp = (238, 221, 187, 170, 136, 119, 85, 68, 34, 17)
    colors += [(v, 0, 0, 255) for v in ramp]
    colors += [(0, v, 0, 255) for v in ramp]
    colors += [(0, 0, v, 255) for v in ramp]
    colors += [(v, v, v, 255) for v in ramp]
    return [(0, 0, 0, 0), *colors]


def make_palette(value: PaletteInput | None = None) -> list[RGBA]:
    palette = default_palette()
    if value is not None:
        supplied = _palette_adapter.validate_python(value)
        if supplied[0] != (0, 0, 0, 0):
            raise VoxelError("Palette index 0 must be [0,0,0,0] (empty).")
        palette[: len(supplied)] = supplied
    return palette
