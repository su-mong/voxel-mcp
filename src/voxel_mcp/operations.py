"""Typed operations and copy-on-success batch execution."""

import math
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, TypeAdapter

from .config import Settings
from .errors import VoxelError
from .geometry import cylinder_bounds, cylinder_mask, line_points
from .models import Color, Index, Point, VoxelAsset

Number = StrictInt | StrictFloat
Positive = Annotated[Number, Field(gt=0, allow_inf_nan=False)]
Center = tuple[Number, Number, Number]
Radii = tuple[Positive, Positive, Positive]
Axis = Literal["x", "y", "z"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Region(StrictModel):
    min: Point
    max: Point


class SetVoxel(StrictModel):
    op: Literal["set_voxel"]
    point: Point
    color: Color


class RemoveVoxel(StrictModel):
    op: Literal["remove_voxel"]
    point: Point


class FillBox(Region):
    op: Literal["fill_box"]
    color: Color


class FillEllipsoid(StrictModel):
    op: Literal["fill_ellipsoid"]
    center: Center
    radius: Radii
    color: Color


class ClearRegion(Region):
    op: Literal["clear_region"]


class ReplaceColor(StrictModel):
    op: Literal["replace_color"]
    from_color: Color
    to_color: Index


class FillSphere(StrictModel):
    op: Literal["fill_sphere"]
    center: Center
    radius: Positive
    color: Color


class FillCylinder(StrictModel):
    op: Literal["fill_cylinder"]
    start: Point
    end: Point
    radius: Positive
    color: Color


class FillLine(StrictModel):
    op: Literal["fill_line"]
    start: Point
    end: Point
    color: Color


class Mirror(StrictModel):
    op: Literal["mirror"]
    axis: Axis
    region: Region | None = None
    mode: Literal["copy", "reflect"]


class Rotate90(StrictModel):
    op: Literal["rotate_90"]
    axis: Axis
    turns: Annotated[StrictInt, Field(ge=-3, le=3)] = 1
    region: Region | None = None


class Translate(StrictModel):
    op: Literal["translate"]
    delta: Point
    region: Region | None = None
    collision: Literal["error", "overwrite"] = "error"


Operation = Annotated[
    SetVoxel
    | RemoveVoxel
    | FillBox
    | FillEllipsoid
    | ClearRegion
    | ReplaceColor
    | FillSphere
    | FillCylinder
    | FillLine
    | Mirror
    | Rotate90
    | Translate,
    Field(discriminator="op"),
]


def region_slices(region: Region | None, shape: Point):
    lo, hi = (region.min, region.max) if region else ((0, 0, 0), tuple(v - 1 for v in shape))
    if any(a < 0 or b < a or b >= s for a, b, s in zip(lo, hi, shape, strict=False)):
        raise VoxelError("Region is reversed or outside the asset bounds; clipping is not allowed.")
    return tuple(slice(a, b + 1) for a, b in zip(lo, hi, strict=False))


def check_point(point: Point, shape: Point):
    if any(v < 0 or v >= s for v, s in zip(point, shape, strict=False)):
        raise VoxelError(f"Point {point} is outside asset bounds {shape}.")


class Budget:
    def __init__(self, limit: int):
        self.remaining = limit

    def charge(self, count: int):
        self.remaining -= count
        if self.remaining < 0:
            raise VoxelError(
                "Batch exceeds max_processed_cells; split it into smaller batches.",
                "resource_limit",
            )


def apply_operation(grid: np.ndarray, op, budget: Budget):
    if isinstance(op, FillSphere):
        op = FillEllipsoid(
            op="fill_ellipsoid", center=op.center, radius=(op.radius,) * 3, color=op.color
        )
    if isinstance(op, (SetVoxel, RemoveVoxel)):
        check_point(op.point, grid.shape)
        budget.charge(1)
        grid[op.point] = op.color if isinstance(op, SetVoxel) else 0
    elif isinstance(op, (FillBox, ClearRegion)):
        target = grid[region_slices(op, grid.shape)]
        budget.charge(target.size)
        target[:] = op.color if isinstance(op, FillBox) else 0
    elif isinstance(op, FillEllipsoid):
        if any(
            c - r < 0 or c + r > s - 1
            for c, r, s in zip(op.center, op.radius, grid.shape, strict=False)
        ):
            raise VoxelError("Ellipsoid extent exceeds asset bounds; clipping is not allowed.")
        lo = tuple(math.ceil(c - r) for c, r in zip(op.center, op.radius, strict=False))
        hi = tuple(math.floor(c + r) for c, r in zip(op.center, op.radius, strict=False))
        target = grid[tuple(slice(a, b + 1) for a, b in zip(lo, hi, strict=False))]
        budget.charge(target.size)
        axes = np.ogrid[tuple(slice(a, b + 1) for a, b in zip(lo, hi, strict=False))]
        distance = sum(
            ((p - c) / r) ** 2 for p, c, r in zip(axes, op.center, op.radius, strict=False)
        )
        target[distance <= 1.0 + 1e-12] = op.color
    elif isinstance(op, ReplaceColor):
        budget.charge(grid.size)
        grid[grid == op.from_color] = op.to_color
    elif isinstance(op, FillLine):
        check_point(op.start, grid.shape)
        check_point(op.end, grid.shape)
        budget.charge(max(abs(b - a) for a, b in zip(op.start, op.end, strict=False)) + 1)
        for point in line_points(op.start, op.end):
            grid[point] = op.color
    elif isinstance(op, FillCylinder):
        check_point(op.start, grid.shape)
        check_point(op.end, grid.shape)
        lo, hi, unit, length = cylinder_bounds(op.start, op.end, op.radius, grid.shape)
        target = grid[tuple(slice(a, b + 1) for a, b in zip(lo, hi, strict=False))]
        budget.charge(target.size)
        target[cylinder_mask(op.start, op.radius, lo, hi, unit, length)] = op.color
    elif isinstance(op, (Mirror, Rotate90)):
        target = grid[region_slices(op.region, grid.shape)]
        budget.charge(target.size)
        axis = "xyz".index(op.axis)
        if isinstance(op, Mirror):
            flipped = np.flip(target, axis=axis).copy()
            if op.mode == "reflect":
                target[:] = flipped
            else:
                destination = [slice(None)] * 3
                destination[axis] = slice((target.shape[axis] + 1) // 2, None)
                target[tuple(destination)] = flipped[tuple(destination)]
        else:
            axes = ((1, 2), (2, 0), (0, 1))[axis]
            if op.turns % 2 and target.shape[axes[0]] != target.shape[axes[1]]:
                raise VoxelError(
                    "Quarter turns require equal region lengths in the rotation plane; resize/select a square region."
                )
            target[:] = np.rot90(target, k=op.turns, axes=axes).copy()
    elif isinstance(op, Translate):
        slices = region_slices(op.region, grid.shape)
        target = grid[slices]
        budget.charge(target.size)
        points = np.argwhere(target != 0) + np.array([s.start for s in slices])
        # Reject enormous deltas before conversion to fixed-width integer arrays.
        if any(abs(d) >= s for d, s in zip(op.delta, grid.shape, strict=False)) and len(points):
            raise VoxelError("Translated voxels exceed asset bounds.")
        shifted = points + np.array(op.delta, dtype=object)
        if len(points):
            if np.any(shifted < 0) or np.any(shifted >= np.array(grid.shape)):
                raise VoxelError("Translated voxels exceed asset bounds.")
            shifted = shifted.astype(np.int64)
            values = grid[tuple(points.T)].copy()
            grid[tuple(points.T)] = 0
            if op.collision == "error" and np.any(grid[tuple(shifted.T)] != 0):
                raise VoxelError(
                    "Translation collides with occupied voxels outside the moved selection."
                )
            grid[tuple(shifted.T)] = values
    else:
        raise VoxelError("Unsupported operation.")


def execute(asset: VoxelAsset, operations: list, settings: Settings) -> tuple[np.ndarray, int]:
    if not isinstance(operations, list) or not 1 <= len(operations) <= settings.max_operations:
        raise VoxelError(f"Batch must contain 1..{settings.max_operations} operations.")
    parsed = TypeAdapter(list[Operation]).validate_python(operations)
    grid = asset.grid.copy()
    budget = Budget(settings.max_processed_cells)
    for operation in parsed:
        apply_operation(grid, operation, budget)
    return grid, int(np.count_nonzero(grid != asset.grid))
