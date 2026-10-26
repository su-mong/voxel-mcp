import hashlib
import os
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from voxel_mcp.capture import LABEL_HEIGHT, capture_six
from voxel_mcp.config import Settings
from voxel_mcp.errors import VoxelError
from voxel_mcp.models import VoxelAsset
from voxel_mcp.service import AssetService


def decode(view):
    return Image.open(BytesIO(view["data"]))


def test_auto_crop_six_orientations_common_scale_and_center():
    asset = VoxelAsset.create("a", [12, 15, 13], None, Settings())
    for point, color in [((2, 4, 1), 1), ((4, 8, 6), 2), ((3, 4, 4), 3), ((3, 8, 4), 4)]:
        asset.grid[point] = color
    before = asset.grid.copy()
    capture = capture_six(asset, Settings(), image_size=64, padding=8)
    assert capture["model_bounds"] == {"min": [2, 4, 1], "max": [4, 8, 6]}
    assert capture["source_size"] == [12, 15, 13] and capture["cropped_size"] == [3, 5, 6]
    assert capture["pixels_per_voxel"] == 8 and not capture["empty"]
    cameras = {
        "front": (3, 6, lambda u, v: [(2 + u, y, 6 - v) for y in range(4, 9)]),
        "back": (3, 6, lambda u, v: [(4 - u, y, 6 - v) for y in range(8, 3, -1)]),
        "left": (5, 6, lambda u, v: [(x, 8 - u, 6 - v) for x in range(2, 5)]),
        "right": (5, 6, lambda u, v: [(x, 4 + u, 6 - v) for x in range(4, 1, -1)]),
        "top": (3, 5, lambda u, v: [(2 + u, 8 - v, z) for z in range(6, 0, -1)]),
        "bottom": (3, 5, lambda u, v: [(2 + u, 4 + v, z) for z in range(1, 7)]),
    }
    for name, (width, height, ray) in cameras.items():
        view = capture["views"][name]
        image = decode(view)
        assert image.size == (64, 64) and image.mode == "RGBA"
        rect = view["content_rect"]
        assert rect == {
            "x": (64 - width * 8) // 2,
            "y": (64 - height * 8) // 2,
            "width": width * 8,
            "height": height * 8,
        }
        for u in range(width):
            for v in range(height):
                index = next((int(asset.grid[p]) for p in ray(u, v) if asset.grid[p]), 0)
                assert (
                    image.getpixel((rect["x"] + u * 8 + 4, rect["y"] + v * 8 + 4))
                    == asset.palette[index]
                )
        assert image.getpixel((0, 0)) == (0, 0, 0, 0)
    sheet = decode(capture["contact_sheet"])
    assert sheet.size == (192, 2 * (64 + LABEL_HEIGHT))
    assert sheet.getextrema()[3] == (255, 255)
    np.testing.assert_array_equal(asset.grid, before)
    assert asset.revision == 0


def test_background_composition_and_transparent_default():
    asset = VoxelAsset.create("a", [1, 1, 1], [[0, 0, 0, 0], [200, 100, 50, 128]], Settings())
    asset.grid[0, 0, 0] = 1
    transparent = capture_six(asset, Settings(), 64, 8)
    solid = capture_six(asset, Settings(), 64, 8, [20, 30, 40, 255])
    for view in transparent["views"].values():
        assert decode(view).getpixel((32, 32)) == (200, 100, 50, 128)
    for view in solid["views"].values():
        assert decode(view).getpixel((32, 32)) == (110, 65, 45, 255)
        assert decode(view).getpixel((0, 0)) == (20, 30, 40, 255)


def test_empty_capture_and_background():
    asset = VoxelAsset.create("empty", [32, 32, 32], None, Settings())
    capture = capture_six(asset, Settings(), 64, 0)
    assert capture["empty"] and capture["model_bounds"] is None
    assert capture["cropped_size"] == [1, 1, 1]
    assert all(decode(view).getbbox() is None for view in capture["views"].values())


@pytest.mark.parametrize(
    "options",
    [
        {"image_size": 63},
        {"image_size": 2049},
        {"image_size": True},
        {"image_size": 64.0},
        {"padding": -1},
        {"padding": 257},
        {"padding": False},
        {"background": [0, 0, 0]},
        {"background": [0, 0, 0, 256]},
        {"background": [0, 0, 0, True]},
    ],
)
def test_strict_capture_validation(options):
    asset = VoxelAsset.create("a", [1, 1, 1], None, Settings())
    with pytest.raises(ValidationError):
        capture_six(asset, Settings(), **options)


def test_padding_and_pixel_budget_including_contact_sheet():
    asset = VoxelAsset.create("a", [1, 1, 1], None, Settings())
    with pytest.raises(VoxelError, match="padding"):
        capture_six(asset, Settings(), 64, 32)
    budget = 6 * 64**2 + 192 * (2 * (64 + LABEL_HEIGHT))
    capture_six(asset, Settings(max_png_pixels=budget), 64, 8)
    with pytest.raises(VoxelError, match="max_png_pixels"):
        capture_six(asset, Settings(max_png_pixels=budget - 1), 64, 8)


def test_capture_atomicity_idempotency_and_revision(store, monkeypatch):
    store.create("a", [5, 6, 7])
    store.edit("a", [{"op": "set_voxel", "point": [2, 3, 4], "color": 1}], 0)
    service = AssetService(store)
    vox = Path(service.save_vox("a", 1)["path"])
    vox_before = vox.read_bytes()
    state_before = store._state_path("a").read_bytes()
    first = service.capture_six_views("a", 64, 8, expected_revision=1)
    assert first == service.capture_six_views("a", 64, 8, expected_revision=1)
    assert len(first["views"]) == 6
    for view in [*first["views"].values(), first["contact_sheet"]]:
        assert hashlib.sha256(Path(view["path"]).read_bytes()).hexdigest() == view["sha256"]
    parent = Path(first["manifest_path"]).parent.parent
    original = store.atomic_write

    def fail(path, data):
        if path.name == "contact_sheet.png":
            raise OSError("simulated capture disk failure")
        original(path, data)

    with monkeypatch.context() as scoped:
        scoped.setattr(store, "atomic_write", fail)
        with pytest.raises(OSError):
            service.capture_six_views("a", 64, 9, expected_revision=1)
    assert list(parent.iterdir()) == [Path(first["manifest_path"]).parent]
    assert store._state_path("a").read_bytes() == state_before and vox.read_bytes() == vox_before
    with pytest.raises(VoxelError, match="Revision conflict"):
        service.capture_six_views("a", 64, 8, expected_revision=0)
    Path(first["contact_sheet"]["path"]).write_bytes(b"external change")
    with pytest.raises(VoxelError, match="modified"):
        service.capture_six_views("a", 64, 8, expected_revision=1)


def test_slim_model_noninteger_scale_and_downsampling():
    asset = VoxelAsset.create("a", [126, 1, 1], None, Settings())
    asset.grid[:] = 1
    capture = capture_six(asset, Settings(), 64, 8)
    rect = capture["views"]["front"]["content_rect"]
    assert rect["width"] == 48 and rect["height"] == 1
    assert decode(capture["views"]["front"]).getbbox() == (8, 31, 56, 32)


def test_fully_occluded_background_settings_do_not_conflict(store):
    store.create("cube", [1, 1, 1])
    store.edit("cube", [{"op": "set_voxel", "point": [0, 0, 0], "color": 1}], 0)
    service = AssetService(store)
    first = service.capture_six_views("cube", 64, 0, [0, 0, 0, 0], 1)
    second = service.capture_six_views("cube", 64, 0, [255, 0, 0, 255], 1)
    assert first["views"]["front"]["sha256"] == second["views"]["front"]["sha256"]
    assert first["manifest_path"] != second["manifest_path"]


@pytest.mark.parametrize("failures", [2, 5])
def test_directory_publish_transient_lock_and_permanent_failure(store, monkeypatch, failures):
    store.create("a", [1, 1, 1])
    service = AssetService(store)
    original = os.replace
    attempts = []

    def replace(source, destination):
        if Path(source).is_dir():
            attempts.append(destination)
            if len(attempts) <= failures:
                raise PermissionError("simulated Windows directory lock")
        return original(source, destination)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr("voxel_mcp.service.time.sleep", lambda _: None)
    if failures == 2:
        result = service.capture_six_views("a", 64, 8)
        assert Path(result["manifest_path"]).is_file() and len(attempts) == 3
    else:
        with pytest.raises(PermissionError):
            service.capture_six_views("a", 64, 8)
        assert len(attempts) == 5
        assert not list(store.path("assets", "a", "captures").iterdir())
