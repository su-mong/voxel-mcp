"""Headless six-camera model captures: common framing, square canvases, contact sheet."""

from io import BytesIO
from typing import Annotated

import numpy as np
from PIL import Image, ImageDraw
from pydantic import Field, StrictInt, TypeAdapter

from .config import Settings
from .errors import VoxelError
from .models import VoxelAsset
from .palette import Byte
from .render import VIEWS, surface_images

CaptureSize = Annotated[StrictInt, Field(ge=64, le=2048)]
CapturePadding = Annotated[StrictInt, Field(ge=0, le=256)]
Background = Annotated[list[Byte], Field(min_length=4, max_length=4)]
LABEL_HEIGHT = 24
SHEET_BACKGROUND = (32, 36, 44, 255)


def png_bytes(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def capture_six(
    asset: VoxelAsset,
    settings: Settings,
    image_size: int = 512,
    padding: int = 24,
    background: list[int] | None = None,
) -> dict:
    image_size = TypeAdapter(CaptureSize).validate_python(image_size)
    padding = TypeAdapter(CapturePadding).validate_python(padding)
    background = TypeAdapter(Background).validate_python(
        [0, 0, 0, 0] if background is None else background
    )
    available = image_size - 2 * padding
    if available < 1:
        raise VoxelError("Capture padding must leave at least one content pixel per axis.")
    pixels = 6 * image_size**2 + (3 * image_size) * (2 * (image_size + LABEL_HEIGHT))
    if pixels > settings.max_png_pixels:
        raise VoxelError(
            "Six captures plus contact sheet exceed max_png_pixels; reduce image_size.",
            "resource_limit",
        )

    # Use one world-space crop and one scale for all six views, preserving relative proportions.
    points = np.argwhere(asset.grid != 0)
    if len(points):
        lo, hi = points.min(axis=0), points.max(axis=0)
        bounds = {"min": lo.tolist(), "max": hi.tolist()}
        grid = asset.grid[tuple(slice(int(a), int(b) + 1) for a, b in zip(lo, hi, strict=True))]
    else:
        bounds = None
        grid = asset.grid[:1, :1, :1]
    cropped = VoxelAsset(asset.asset_name, grid, asset.palette, asset.revision)
    longest = max(cropped.size)
    sheet = Image.new("RGBA", (3 * image_size, 2 * (image_size + LABEL_HEIGHT)), SHEET_BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    views = {}
    for index, (name, surface) in enumerate(surface_images(cropped)):
        width = max(1, surface.width * available // longest)
        height = max(1, surface.height * available // longest)
        surface = surface.resize((width, height), Image.Resampling.NEAREST)
        x, y = (image_size - width) // 2, (image_size - height) // 2
        # Background composition is intentional; surface selection remains nearest occupied voxel.
        canvas = Image.new("RGBA", (image_size, image_size), tuple(background))
        canvas.alpha_composite(surface, (x, y))
        views[name] = {
            "data": png_bytes(canvas),
            "width": image_size,
            "height": image_size,
            "content_rect": {"x": x, "y": y, "width": width, "height": height},
            **VIEWS[name],
        }
        sheet_x = (index % 3) * image_size
        sheet_y = (index // 3) * (image_size + LABEL_HEIGHT)
        draw.text((sheet_x + 8, sheet_y + 6), name.upper(), fill=(240, 243, 248, 255))
        sheet.alpha_composite(canvas, (sheet_x, sheet_y + LABEL_HEIGHT))

    return {
        "views": views,
        "contact_sheet": {
            "data": png_bytes(sheet),
            "width": sheet.width,
            "height": sheet.height,
            "columns": 3,
            "rows": 2,
            "order": list(VIEWS),
            "label_height": LABEL_HEIGHT,
            "background": list(SHEET_BACKGROUND),
        },
        "source_size": list(asset.size),
        "model_bounds": bounds,
        "cropped_size": list(cropped.size),
        "image_size": image_size,
        "padding": padding,
        "background": background,
        "pixels_per_voxel": available / longest,
        "empty": bounds is None,
    }
