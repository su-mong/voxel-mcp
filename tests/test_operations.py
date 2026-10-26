import numpy as np
import pytest
from pydantic import ValidationError

from voxel_mcp.asset_store import AssetStore
from voxel_mcp.config import Settings
from voxel_mcp.errors import VoxelError


def test_asymmetric_axis_revision_serialization(store):
    store.create("Asymmetric", [3, 5, 7])
    result = store.edit("asymmetric", [{"op": "set_voxel", "point": [2, 3, 6], "color": 255}], 0)
    assert result == dict(
        ok=True, asset_name="asymmetric", revision=1, affected_voxels=1, warnings=[]
    )
    asset = AssetStore(store.settings).get("asymmetric")
    assert asset.size == (3, 5, 7) and asset.grid.dtype == np.uint8
    assert asset.grid[2, 3, 6] == 255 and np.count_nonzero(asset.grid) == 1
    assert asset.info()["bounds"] == {"min": [2, 3, 6], "max": [2, 3, 6]}


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "set_voxel", "point": [-1, 0, 0], "color": 1},
        {"op": "set_voxel", "point": [3, 0, 0], "color": 1},
        {"op": "set_voxel", "point": [0, 0, 0], "color": 0},
        {"op": "set_voxel", "point": [0, 0, 0], "color": 256},
        {"op": "set_voxel", "point": [0.1, 0, 0], "color": 1},
        {"op": "set_voxel", "point": [True, 0, 0], "color": 1},
        {"op": "fill_box", "min": [2, 0, 0], "max": [1, 1, 1], "color": 1},
        {"op": "fill_box", "min": [0, 0, 0], "max": [3, 2, 2], "color": 1},
        {"op": "fill_ellipsoid", "center": [1, 1, 1], "radius": [0, 1, 1], "color": 1},
        {"op": "fill_ellipsoid", "center": [0, 1, 1], "radius": [1, 1, 1], "color": 1},
        {"op": "unknown"},
        {"op": "remove_voxel", "point": [0, 0, 0], "unexpected": 1},
    ],
)
def test_invalid_batch_rolls_back(store, operation):
    store.create("a", [3, 3, 3])
    with pytest.raises((VoxelError, ValidationError)):
        store.edit("a", [{"op": "set_voxel", "point": [1, 1, 1], "color": 2}, operation], 0)
    asset = store.get("a")
    assert asset.revision == 0 and not asset.grid.any()


def test_six_core_operations(store):
    store.create("a", [7, 7, 7])
    store.edit(
        "a", [{"op": "fill_ellipsoid", "center": [3, 3, 3], "radius": [2, 1, 1], "color": 5}]
    )
    grid = store.get("a").grid
    expected = np.zeros_like(grid)
    for x, y, z in np.ndindex(grid.shape):
        if ((x - 3) / 2) ** 2 + (y - 3) ** 2 + (z - 3) ** 2 <= 1:
            expected[x, y, z] = 5
    np.testing.assert_array_equal(grid, expected)
    store.edit(
        "a",
        [
            {"op": "fill_box", "min": [0, 0, 0], "max": [1, 1, 1], "color": 2},
            {"op": "clear_region", "min": [0, 0, 0], "max": [0, 1, 1]},
            {"op": "replace_color", "from_color": 2, "to_color": 3},
            {"op": "remove_voxel", "point": [1, 0, 0]},
        ],
        1,
    )
    grid = store.get("a").grid
    assert (grid == 3).sum() == 3 and (grid == 5).sum() == (expected == 5).sum()


def test_revision_conflict_and_duplicate_create(store):
    store.create("a", [2, 2, 2])
    store.edit("a", [{"op": "set_voxel", "point": [0, 0, 0], "color": 1}], 0)
    with pytest.raises(VoxelError, match="Revision conflict"):
        store.edit("a", [{"op": "remove_voxel", "point": [0, 0, 0]}], 0)
    with pytest.raises(VoxelError, match="already exists"):
        store.create("A", [2, 2, 2])


@pytest.mark.parametrize("size", [[0, 1, 1], [127, 1, 1], [True, 1, 1], [1, 1]])
def test_invalid_size(store, size):
    with pytest.raises((VoxelError, ValidationError)):
        store.create("a", size)


def test_budget_and_operation_count(tmp_path):
    store = AssetStore(Settings(workspace=tmp_path, max_operations=1, max_processed_cells=2))
    store.create("a", [3, 3, 3])
    with pytest.raises(VoxelError, match="max_processed_cells"):
        store.edit("a", [{"op": "replace_color", "from_color": 1, "to_color": 2}])
    for operations in ([], [{"op": "remove_voxel", "point": [0, 0, 0]}] * 2):
        with pytest.raises(VoxelError, match="Batch must contain"):
            store.edit("a", operations)
    assert store.get("a").revision == 0
