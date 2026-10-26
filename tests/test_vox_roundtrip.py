import os
import struct
from pathlib import Path

import numpy as np
import pytest

from voxel_mcp import vox_io
from voxel_mcp.config import Settings
from voxel_mcp.errors import VoxelError
from voxel_mcp.models import VoxelAsset
from voxel_mcp.palette import default_palette
from voxel_mcp.service import AssetService


def basic_vox(size=(3, 5, 7), records=b"\x02\x03\x06\xff", palette=None):
    # Independent reference fixture: literal little-endian headers, no production writer.
    children = b"SIZE" + struct.pack("<II3I", 12, 0, *size)
    children += b"XYZI" + struct.pack("<III", 4 + len(records), 0, len(records) // 4) + records
    if palette is not None:
        children += b"RGBA" + struct.pack("<II", len(palette), 0) + palette
    return (
        b"VOX " + struct.pack("<I", 150) + b"MAIN" + struct.pack("<II", 0, len(children)) + children
    )


def test_independent_asymmetric_fixture_and_palette_index():
    palette = bytes([12, 34, 56, 78]) + bytes(1012) + bytes([90, 80, 70, 60]) + bytes(4)
    asset = vox_io.loads(
        basic_vox(records=b"\x02\x03\x06\xff\x00\x01\x02\x01", palette=palette), "a"
    )
    assert asset.grid[2, 3, 6] == 255 and asset.grid[0, 1, 2] == 1
    assert asset.palette[1] == (12, 34, 56, 78) and asset.palette[255] == (90, 80, 70, 60)
    assert asset.palette[0] == (0, 0, 0, 0)


@pytest.mark.parametrize("size", [(1, 1, 1), (3, 5, 7), (126, 126, 126)])
@pytest.mark.parametrize("filled", [False, True])
def test_roundtrip_empty_and_max_size(size, filled):
    asset = VoxelAsset.create("a", size, None, Settings())
    if filled:
        asset.grid[-1, -1, -1] = 255
        asset.grid[0, 0, 0] = 1
    raw = vox_io.dumps(asset)
    restored = vox_io.loads(raw, "a")
    np.testing.assert_array_equal(restored.grid, asset.grid)
    assert restored.palette == asset.palette
    assert vox_io.dumps(restored) == raw


def test_default_palette_without_rgba():
    asset = vox_io.loads(basic_vox(), "a")
    assert asset.palette == default_palette() and len(asset.palette) == 256
    assert asset.palette[1] == (255, 255, 255, 255)
    assert asset.palette[2] == (255, 255, 204, 255)
    assert asset.palette[216] == (238, 0, 0, 255)
    assert asset.palette[255] == (17, 17, 17, 255)


@pytest.mark.parametrize(
    "kind", [b"PACK", b"nTRN", b"nGRP", b"nSHP", b"LAYR", b"MATL", b"MATT", b"IMAP", b"????"]
)
def test_reject_unsupported_chunks(kind):
    raw = basic_vox()
    children = raw[20:] + vox_io.chunk(kind)
    with pytest.raises(VoxelError, match="Unsupported VOX chunk"):
        vox_io.loads(raw[:8] + vox_io.chunk(b"MAIN", children=children), "a")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"VOX ",
        b"bad!" + bytes(16),
        basic_vox()[:-1],
        basic_vox() + b"junk",
        basic_vox(records=b"\x03\x00\x00\x01"),
        basic_vox(records=b"\x00\x00\x00\x00"),
        basic_vox(records=b"\x00\x00\x00\x01" * 2),
        basic_vox(palette=bytes(10)),
        b"VOX " + struct.pack("<I", 999) + vox_io.chunk(b"MAIN"),
        b"VOX "
        + struct.pack("<I", 150)
        + vox_io.chunk(b"MAIN", children=b"SIZE" + struct.pack("<II", 0xFFFFFFFF, 0)),
    ],
)
def test_malformed(raw):
    with pytest.raises(VoxelError):
        vox_io.loads(raw, "a")


def test_save_load_edit_save_and_external_conflict(store, monkeypatch):
    service = AssetService(store)
    store.create("a", [3, 5, 7])
    store.edit("a", [{"op": "set_voxel", "point": [2, 3, 6], "color": 255}], 0)
    saved = service.save_vox("a", 1)
    path = Path(saved["path"])
    before = path.read_bytes()
    with pytest.raises(VoxelError, match="requires expected_revision"):
        service.load_vox("a", str(path))
    assert service.load_vox("a", str(path), 1)["revision"] == 2
    store.edit("a", [{"op": "remove_voxel", "point": [2, 3, 6]}], 2)

    def fail(*args):
        raise OSError("simulated disk failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "replace", fail)
        with pytest.raises(OSError):
            service.save_vox("a", 3)
    assert path.read_bytes() == before
    service.save_vox("a", 3)
    assert not vox_io.loads(path.read_bytes(), "b").grid.any()
    path.write_bytes(before)
    with pytest.raises(VoxelError, match="changed externally"):
        service.save_vox("a", 3)
    assert path.read_bytes() == before
    assert service.load_vox("a", str(path), 3)["revision"] == 4
    service.save_vox("a", 4)


def test_all_bundled_magicavoxel_scene_samples_rejected():
    samples = list((Path(__file__).parents[1] / "MagicaVoxel" / "vox").glob("*.vox"))
    if not samples:
        pytest.skip("Optional local MagicaVoxel distribution is not installed.")
    for sample in samples:
        with pytest.raises(VoxelError) as error:
            vox_io.loads(sample.read_bytes(), "sample", Settings(max_axis=256, max_voxels=256**3))
        assert error.value.code == "unsupported_vox", sample.name


def test_every_palette_slot_and_rgba_order():
    palette = [(0, 0, 0, 0)] + [(i, 255 - i, (i * 17) % 256, (i * 31) % 256) for i in range(1, 256)]
    asset = VoxelAsset.create("a", [17, 15, 1], palette, Settings())
    asset.grid[:] = np.arange(1, 256, dtype=np.uint8).reshape(17, 15, 1)
    raw = vox_io.dumps(asset)
    offset = raw.index(b"RGBA") + 12
    assert raw[offset : offset + 4] == bytes(palette[1])
    assert raw[offset + 254 * 4 : offset + 255 * 4] == bytes(palette[255])
    restored = vox_io.loads(raw, "a")
    assert restored.palette == palette
    np.testing.assert_array_equal(restored.grid, asset.grid)


def test_writer_full_byte_coordinate_range():
    settings = Settings(max_axis=256, max_voxels=1536)
    asset = VoxelAsset.create("a", [256, 2, 3], None, settings)
    asset.grid[255, 1, 2] = 255
    restored = vox_io.loads(vox_io.dumps(asset, settings), "a", settings)
    assert restored.size == (256, 2, 3) and restored.grid[255, 1, 2] == 255


def test_state_fingerprint_failure_after_successful_export_is_recoverable(store, monkeypatch):
    store.create("a", [2, 2, 2])
    service = AssetService(store)

    def fail(*args):
        raise OSError("simulated state disk failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(store, "_write", fail)
        saved = service.save_vox("a", 0)
    assert saved["ok"] and saved["warnings"] and Path(saved["path"]).is_file()
    assert not service.save_vox("a", 0)["warnings"]
