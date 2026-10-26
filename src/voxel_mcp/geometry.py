"""Deterministic integer lines and flat-capped cylinder geometry."""

import math

import numpy as np

from .errors import VoxelError


def line_points(start, end):
    """Dominant-axis DDA; nearest integer with ties away from the starting point."""
    delta = tuple(b - a for a, b in zip(start, end, strict=False))
    steps = max(map(abs, delta))
    if steps == 0:
        return [start]
    return [
        tuple(
            a + (1 if d >= 0 else -1) * ((2 * i * abs(d) + steps) // (2 * steps))
            for a, d in zip(start, delta, strict=False)
        )
        for i in range(steps + 1)
    ]


def cylinder_bounds(start, end, radius, shape):
    direction = np.array(end, dtype=float) - start
    length = float(np.linalg.norm(direction))
    if length == 0:
        raise VoxelError("Cylinder start and end must differ.")
    unit = direction / length
    extent = radius * np.sqrt(np.maximum(0, 1 - unit**2))
    lower = np.minimum(start, end) - extent
    upper = np.maximum(start, end) + extent
    if np.any(lower < -1e-12) or np.any(upper > np.array(shape) - 1 + 1e-12):
        raise VoxelError("Cylinder extent exceeds asset bounds; clipping is not allowed.")
    return (
        tuple(math.ceil(v - 1e-12) for v in lower),
        tuple(math.floor(v + 1e-12) for v in upper),
        unit,
        length,
    )


def cylinder_mask(start, radius, lo, hi, unit, length):
    axes = np.ogrid[tuple(slice(a, b + 1) for a, b in zip(lo, hi, strict=False))]
    relative = [a - s for a, s in zip(axes, start, strict=False)]
    projection = sum(a * u for a, u in zip(relative, unit, strict=False))
    distance_sq = sum(a**2 for a in relative) - projection**2
    return (
        (projection >= -1e-12) & (projection <= length + 1e-12) & (distance_sq <= radius**2 + 1e-12)
    )
