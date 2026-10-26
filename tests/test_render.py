from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from voxel_mcp.config import Settings
from voxel_mcp.errors import VoxelError
from voxel_mcp.models import VoxelAsset
from voxel_mcp.render import render_six
from voxel_mcp.service import AssetService


def test_six_views_orientation_occlusion_and_palette_against_scalar_rays():
    asset = VoxelAsset.create(
        "a", [3, 5, 7], [[0, 0, 0, 0], [255, 10, 20, 255], [20, 255, 30, 128]], Settings()
    )
    for point, color in [
        ((0, 0, 0), 1),
        ((2, 4, 6), 2),
        ((1, 0, 3), 1),
        ((1, 4, 3), 2),
        ((0, 2, 4), 1),
        ((2, 2, 4), 2),
    ]:
        asset.grid[point] = color
    views = render_six(asset, Settings(), scale=1)
    # Independent camera equations: (u,v) in pixels, depth list nearest first.
    cameras = {
        "front": (3, 7, lambda u, v: [(u, y, 6 - v) for y in range(5)]),
        "back": (3, 7, lambda u, v: [(2 - u, y, 6 - v) for y in range(4, -1, -1)]),
        "left": (5, 7, lambda u, v: [(x, 4 - u, 6 - v) for x in range(3)]),
        "right": (5, 7, lambda u, v: [(x, u, 6 - v) for x in range(2, -1, -1)]),
        "top": (3, 5, lambda u, v: [(u, 4 - v, z) for z in range(6, -1, -1)]),
        "bottom": (3, 5, lambda u, v: [(u, v, z) for z in range(7)]),
    }
    for name, (width, height, ray) in cameras.items():
        image = Image.open(BytesIO(views[name]["data"]))
        assert image.size == (width, height) and image.mode == "RGBA"
        for v in range(height):
            for u in range(width):
                color = next((int(asset.grid[p]) for p in ray(u, v) if asset.grid[p]), 0)
                assert image.getpixel((u, v)) == asset.palette[color], (name, u, v)


def test_empty_transparent_scale_and_padding():
    asset = VoxelAsset.create("empty", [2, 3, 4], None, Settings())
    views = render_six(asset, Settings(), 3, 2)
    for _name, view in views.items():
        image = Image.open(BytesIO(view["data"]))
        assert image.getbbox() is None
    assert Image.open(BytesIO(views["front"]["data"])).size == (10, 16)
    asset.grid[0, 0, 0] = 1
    image = Image.open(BytesIO(render_six(asset, Settings(), 3, 2)["front"]["data"]))
    assert image.getpixel((2, 11)) == asset.palette[1]
    assert image.getpixel((1, 11)) == (0, 0, 0, 0)


@pytest.mark.parametrize("scale,padding", [(0, 0), (17, 0), (True, 0), (1, -1), (1, 65)])
def test_export_validation(scale, padding):
    asset = VoxelAsset.create("a", [2, 2, 2], None, Settings())
    with pytest.raises(ValidationError):
        render_six(asset, Settings(), scale, padding)


def test_pixel_budget():
    asset = VoxelAsset.create("a", [4, 4, 4], None, Settings())
    with pytest.raises(VoxelError, match="max_png_pixels"):
        render_six(asset, Settings(max_png_pixels=95), 1)


def test_atomic_bundle_determinism_and_modified_file_conflict(store, monkeypatch):
    store.create("a", [3, 5, 7])
    service = AssetService(store)
    first = service.export_six_views("a", 2, 1, 0)
    assert service.export_six_views("a", 2, 1, 0) == first
    assert len(first["views"]) == 6 and Path(first["manifest_path"]).is_file()
    before = {name: Path(info["path"]).read_bytes() for name, info in first["views"].items()}
    store.edit("a", [{"op": "set_voxel", "point": [1, 2, 3], "color": 1}], 0)
    original_write = store.atomic_write

    def fail_on_second_png(path, data):
        if path.name == "back.png":
            raise OSError("simulated disk full")
        original_write(path, data)

    with monkeypatch.context() as scoped:
        scoped.setattr(store, "atomic_write", fail_on_second_png)
        with pytest.raises(OSError):
            service.export_six_views("a", 2, 1, 1)
    parent = Path(first["manifest_path"]).parent.parent
    assert len(list(parent.iterdir())) == 1
    assert not list(parent.glob(".voxel-views-*"))
    for name, info in first["views"].items():
        assert Path(info["path"]).read_bytes() == before[name]
    second = service.export_six_views("a", 2, 1, 1)
    assert second["manifest_path"] != first["manifest_path"]
    Path(second["views"]["front"]["path"]).write_bytes(b"changed")
    with pytest.raises(VoxelError, match="modified"):
        service.export_six_views("a", 2, 1, 1)
