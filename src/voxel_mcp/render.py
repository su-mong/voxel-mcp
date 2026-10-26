"""Six unlit orthographic surface projections with explicit camera orientations."""

from io import BytesIO
from typing import Annotated

import numpy as np
from PIL import Image
from pydantic import Field, StrictInt, TypeAdapter

from .config import Settings
from .errors import VoxelError
from .models import VoxelAsset

Scale = Annotated[StrictInt, Field(ge=1, le=16)]
Padding = Annotated[StrictInt, Field(ge=0, le=64)]

# Camera side; image right/up directions in world coordinates.
VIEWS = {
    "front": {"camera": "-Y", "right": "+X", "up": "+Z"},
    "back": {"camera": "+Y", "right": "-X", "up": "+Z"},
    "left": {"camera": "-X", "right": "-Y", "up": "+Z"},
    "right": {"camera": "+X", "right": "+Y", "up": "+Z"},
    "top": {"camera": "+Z", "right": "+X", "up": "+Y"},
    "bottom": {"camera": "-Z", "right": "+X", "up": "-Y"},
}


def render_six(asset: VoxelAsset, settings: Settings, scale: int = 8, padding: int = 0) -> dict:
    scale = TypeAdapter(Scale).validate_python(scale)
    padding = TypeAdapter(Padding).validate_python(padding)
    sx, sy, sz = asset.size
    dimensions = ((sx, sz), (sx, sz), (sy, sz), (sy, sz), (sx, sy), (sx, sy))
    pixels = sum((w * scale + 2 * padding) * (h * scale + 2 * padding) for w, h in dimensions)
    if pixels > settings.max_png_pixels:
        raise VoxelError(
            "Six-view output exceeds max_png_pixels; reduce scale/padding.", "resource_limit"
        )
    grid = asset.grid
    rays = {
        "front": grid.transpose(1, 2, 0)[:, ::-1, :],
        "back": grid.transpose(1, 2, 0)[::-1, ::-1, ::-1],
        "left": grid.transpose(0, 2, 1)[:, ::-1, ::-1],
        "right": grid.transpose(0, 2, 1)[::-1, ::-1, :],
        "top": grid.transpose(2, 1, 0)[::-1, ::-1, :],
        "bottom": grid.transpose(2, 1, 0),
    }
    palette = np.array(asset.palette, dtype=np.uint8)
    output = {}
    for name, ray in rays.items():
        occupied = ray != 0
        nearest = occupied.argmax(axis=0)
        surface = np.take_along_axis(ray, nearest[None, ...], axis=0)[0]
        surface[~occupied.any(axis=0)] = 0
        image = Image.fromarray(palette[surface])
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
        if padding:
            padded = Image.new("RGBA", (image.width + 2 * padding, image.height + 2 * padding))
            padded.paste(image, (padding, padding))
            image = padded
        stream = BytesIO()
        image.save(stream, format="PNG")
        output[name] = {
            "data": stream.getvalue(),
            "width": image.width,
            "height": image.height,
            **VIEWS[name],
        }
    return output
