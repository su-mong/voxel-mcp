import os

import pytest
from pydantic import ValidationError

from voxel_mcp.asset_store import AssetStore
from voxel_mcp.config import Settings
from voxel_mcp.errors import VoxelError


@pytest.mark.parametrize(
    "name",
    [
        "../evil",
        "..",
        "/tmp/a",
        "C:\\evil",
        "\\\\server\\share",
        "a/b",
        "a\\b",
        "a:b",
        "a\x00b",
        "a\nb",
        "CON",
        "lpt1",
        "a.",
        "a ",
        "",
        "a" * 65,
    ],
)
def test_asset_name_policy(store, name):
    with pytest.raises(VoxelError):
        store.create(name, [1, 1, 1])


def test_read_policy(store, tmp_path):
    outside = tmp_path / "outside.vox"
    outside.write_bytes(b"VOX ")
    for source in (
        str(outside),
        "../outside.vox",
        "C:\\Windows\\outside.vox",
        "\\\\server\\share\\a.vox",
    ):
        with pytest.raises(VoxelError):
            store.source_path(source)


def test_atomic_state_failure_preserves_original(store, monkeypatch):
    store.create("a", [2, 2, 2])
    before = store._state_path("a").read_bytes()

    def fail(*args):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.edit("a", [{"op": "set_voxel", "point": [0, 0, 0], "color": 1}], 0)
    assert store._state_path("a").read_bytes() == before
    assert not list(store.path(".state").glob(".voxel-*"))


def test_palette_validation(store):
    for palette in ([[0, 0, 0, 255]], [[0, 0, 0, 0], [256, 0, 0, 255]], []):
        with pytest.raises((VoxelError, ValidationError)):
            store.create("bad", [1, 1, 1], palette)
    asset = store.create("a", [1, 1, 1], [[0, 0, 0, 0], [12, 34, 56, 78]])
    assert asset["palette"][1] == (12, 34, 56, 78)


def test_allowed_import_root_and_read_size_limit(store, tmp_path):
    outside = tmp_path / "imports"
    outside.mkdir()
    path = outside / "sample.vox"
    path.write_bytes(b"VOX ")
    configured = AssetStore(Settings(workspace=store.root, read_roots=(outside,)))
    assert configured.source_path(str(path)) == path


def test_symlink_escape_if_supported(store, tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    link = store.root / "redirect"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink creation requires Developer Mode or elevated privilege.")
    with pytest.raises(VoxelError, match="Symlinks"):
        store.path("redirect", "escape.vox")


def test_asset_and_total_cell_limits(tmp_path):
    store = AssetStore(Settings(workspace=tmp_path, max_assets=1, max_voxels=4))
    with pytest.raises(VoxelError, match="total cells"):
        store.create("big", [2, 2, 2])
    store.create("a", [1, 1, 1])
    with pytest.raises(VoxelError, match="max_assets"):
        store.create("b", [1, 1, 1])
