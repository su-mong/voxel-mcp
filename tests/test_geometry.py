import numpy as np
import pytest

from voxel_mcp.errors import VoxelError
from voxel_mcp.geometry import line_points


def test_sphere_and_flat_cylinder(store):
    store.create("a", [9, 9, 9])
    store.edit("a", [{"op": "fill_sphere", "center": [4, 4, 4], "radius": 2, "color": 1}])
    grid = store.get("a").grid
    assert (grid != 0).sum() == 33
    store.edit(
        "a",
        [
            {"op": "clear_region", "min": [0, 0, 0], "max": [8, 8, 8]},
            {"op": "fill_cylinder", "start": [4, 4, 2], "end": [4, 4, 6], "radius": 2, "color": 2},
        ],
    )
    grid = store.get("a").grid
    for x, y, z in np.ndindex(grid.shape):
        assert bool(grid[x, y, z]) == (2 <= z <= 6 and (x - 4) ** 2 + (y - 4) ** 2 <= 4)


def test_diagonal_cylinder_against_scalar_reference(store):
    store.create("a", [11, 11, 11])
    start, end, radius = np.array([3, 3, 3]), np.array([7, 6, 7]), 1.5
    store.edit(
        "a",
        [
            {
                "op": "fill_cylinder",
                "start": start.tolist(),
                "end": end.tolist(),
                "radius": radius,
                "color": 2,
            }
        ],
    )
    grid = store.get("a").grid
    direction = end - start
    for point in np.ndindex(grid.shape):
        relative = np.array(point) - start
        t = np.dot(relative, direction) / np.dot(direction, direction)
        radial = np.linalg.norm(relative - t * direction)
        assert bool(grid[point]) == (0 <= t <= 1 and radial <= radius + 1e-12)


@pytest.mark.parametrize("end", [(6, 4, 2), (2, 6, 4), (4, 2, 6), (0, 0, 0), (3, 3, 3)])
def test_line_connected_endpoints_and_determinism(store, end):
    start = (3, 3, 3)
    points = line_points(start, end)
    assert points == line_points(start, end) and points[0] == start and points[-1] == end
    assert all(
        max(abs(a - b) for a, b in zip(p, q, strict=False)) == 1
        for p, q in zip(points, points[1:], strict=False)
    )
    store.create("a", [7, 7, 7])
    store.edit("a", [{"op": "fill_line", "start": start, "end": end, "color": 3}])
    assert (store.get("a").grid != 0).sum() == len(points)


def test_mirror_copy_and_reflect_overwrite(store):
    store.create("a", [5, 3, 3])
    store.edit(
        "a",
        [
            {"op": "set_voxel", "point": [0, 1, 2], "color": 1},
            {"op": "set_voxel", "point": [3, 0, 0], "color": 2},
            {"op": "mirror", "axis": "x", "mode": "copy"},
        ],
    )
    grid = store.get("a").grid
    assert grid[4, 1, 2] == 1 and grid[0, 1, 2] == 1 and grid[3, 0, 0] == 0
    store.edit("a", [{"op": "mirror", "axis": "z", "mode": "reflect"}])
    assert store.get("a").grid[4, 1, 0] == 1


@pytest.mark.parametrize(
    "axis,source,destination",
    [("x", [1, 0, 1], [1, 3, 0]), ("y", [1, 2, 0], [0, 2, 3]), ("z", [1, 0, 2], [4, 1, 2])],
)
def test_rotate_right_hand_and_inverse(store, axis, source, destination):
    store.create("a", [5, 5, 5])
    store.edit(
        "a", [{"op": "set_voxel", "point": source, "color": 1}, {"op": "rotate_90", "axis": axis}]
    )
    assert store.get("a").grid[tuple(destination)] == 1
    store.edit("a", [{"op": "rotate_90", "axis": axis, "turns": -1}])
    assert store.get("a").grid[tuple(source)] == 1


def test_translation_collision_overlap_and_rollback(store):
    store.create("a", [5, 3, 3])
    store.edit("a", [{"op": "fill_box", "min": [0, 0, 0], "max": [2, 0, 0], "color": 1}])
    store.edit("a", [{"op": "translate", "delta": [1, 0, 0]}])
    assert list(store.get("a").grid[:, 0, 0]) == [0, 1, 1, 1, 0]
    region = {"min": [1, 0, 0], "max": [1, 0, 0]}
    before = store.get("a").grid
    with pytest.raises(VoxelError, match="collides"):
        store.edit("a", [{"op": "translate", "delta": [1, 0, 0], "region": region}], 2)
    np.testing.assert_array_equal(store.get("a").grid, before)
    store.edit(
        "a",
        [{"op": "translate", "delta": [1, 0, 0], "region": region, "collision": "overwrite"}],
        2,
    )
    with pytest.raises(VoxelError, match="bounds"):
        store.edit("a", [{"op": "translate", "delta": [4, 0, 0]}])


def test_undo_monotonic_revision_and_restart(store):
    store.create("a", [2, 2, 2])
    store.edit("a", [{"op": "set_voxel", "point": [1, 1, 1], "color": 3}], 0)
    assert store.undo("a", 1)["revision"] == 2
    assert not store.get("a").grid.any()
    with pytest.raises(VoxelError, match="No edit history"):
        store.undo("a", 2)
    with pytest.raises(VoxelError, match="Revision conflict"):
        store.edit("a", [{"op": "remove_voxel", "point": [0, 0, 0]}], 0)


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "fill_cylinder", "start": [2, 2, 2], "end": [2, 2, 2], "radius": 1, "color": 1},
        {"op": "fill_cylinder", "start": [0, 0, 0], "end": [3, 0, 0], "radius": 1, "color": 1},
        {"op": "rotate_90", "axis": "z"},
        {
            "op": "mirror",
            "axis": "x",
            "mode": "copy",
            "region": {"min": [0, 0, 0], "max": [4, 5, 6]},
        },
    ],
)
def test_transform_errors_are_atomic(store, operation):
    store.create("a", [4, 5, 6])
    with pytest.raises(VoxelError):
        store.edit("a", [{"op": "set_voxel", "point": [1, 1, 1], "color": 2}, operation], 0)
    assert store.get("a").revision == 0 and not store.get("a").grid.any()


def test_subregion_rotation_and_half_turn_rectangle(store):
    store.create("a", [4, 5, 6])
    store.edit(
        "a",
        [
            {"op": "set_voxel", "point": [1, 2, 3], "color": 1},
            {"op": "rotate_90", "axis": "z", "region": {"min": [1, 1, 2], "max": [3, 3, 4]}},
        ],
    )
    assert store.get("a").grid[2, 1, 3] == 1
    store.edit("a", [{"op": "rotate_90", "axis": "z", "turns": 2}])
    assert store.get("a").grid[1, 3, 3] == 1
