"""Strict, little-endian VOX 150/200 single-model reader; deterministic VOX 150 writer.

All unknown chunks are rejected, even if ignoring them would produce a plausible model.
This prevents silently dropping scene transforms, materials, layers and animation.
"""

import struct

import numpy as np

from .config import Settings
from .errors import VoxelError
from .models import VoxelAsset, asset_name, validate_size
from .palette import default_palette, make_palette


def chunk(kind: bytes, content: bytes = b"", children: bytes = b"") -> bytes:
    return struct.pack("<4sII", kind, len(content), len(children)) + content + children


def dumps(asset: VoxelAsset, settings: Settings | None = None) -> bytes:
    settings = settings or Settings()
    validate_size(asset.size, settings)
    if asset.grid.dtype != np.uint8:
        raise VoxelError("VOX grid must have dtype uint8.")
    palette = make_palette(asset.palette)
    positions = np.argwhere(asset.grid != 0)
    records = np.empty((len(positions), 4), dtype=np.uint8)
    if len(positions):
        records[:, :3] = positions
        records[:, 3] = asset.grid[tuple(positions.T)]
    children = chunk(b"SIZE", struct.pack("<3I", *asset.size))
    children += chunk(b"XYZI", struct.pack("<I", len(records)) + records.tobytes())
    # 255 usable RGBA entries, followed by the unused 256th record.
    children += chunk(b"RGBA", bytes(v for rgba in palette[1:] for v in rgba) + bytes(4))
    data = b"VOX " + struct.pack("<I", 150) + chunk(b"MAIN", children=children)
    if len(data) > settings.max_file_bytes:
        raise VoxelError("VOX output exceeds max_file_bytes.", "resource_limit")
    return data


def loads(data: bytes, name: str, settings: Settings | None = None) -> VoxelAsset:
    settings = settings or Settings()
    if len(data) > settings.max_file_bytes:
        raise VoxelError("VOX input exceeds max_file_bytes.", "resource_limit")
    if len(data) < 20 or data[:4] != b"VOX ":
        raise VoxelError("Invalid or truncated VOX header.", "invalid_vox")
    version = struct.unpack_from("<I", data, 4)[0]
    if version not in (150, 200):
        raise VoxelError(f"Unsupported VOX version {version}.", "unsupported_vox")
    kind, content_size, children_size = struct.unpack_from("<4sII", data, 8)
    if kind != b"MAIN" or content_size != 0 or children_size != len(data) - 20:
        raise VoxelError("Invalid MAIN chunk or file boundary.", "invalid_vox")
    pos = 20
    size = None
    grid = None
    palette = default_palette()
    seen = set()
    while pos < len(data):
        if len(data) - pos < 12:
            raise VoxelError("Truncated VOX chunk header.", "invalid_vox")
        kind, count, children = struct.unpack_from("<4sII", data, pos)
        pos += 12
        if count > len(data) - pos or children > len(data) - pos - count:
            raise VoxelError("VOX chunk exceeds its parent boundary.", "invalid_vox")
        if kind not in (b"SIZE", b"XYZI", b"RGBA"):
            raise VoxelError(
                f"Unsupported VOX chunk {kind.decode('ascii', errors='replace')}; scene/multi-model/material data cannot be preserved. Export a basic single model.",
                "unsupported_vox",
            )
        if children or kind in seen:
            raise VoxelError(
                "Nested or duplicate model/palette chunks are unsupported.", "unsupported_vox"
            )
        seen.add(kind)
        content = memoryview(data)[pos : pos + count]
        if kind == b"SIZE":
            if count != 12 or grid is not None or b"RGBA" in seen:
                raise VoxelError("Invalid SIZE chunk length or order.", "invalid_vox")
            size = validate_size(struct.unpack_from("<3I", content), settings)
        elif kind == b"XYZI":
            if size is None or count < 4 or b"RGBA" in seen:
                raise VoxelError(
                    "XYZI requires a preceding SIZE and at least four bytes.", "invalid_vox"
                )
            n = struct.unpack_from("<I", content)[0]
            if n > int(np.prod(size)) or count != 4 + n * 4:
                raise VoxelError("Invalid XYZI voxel count/length.", "invalid_vox")
            records = np.frombuffer(content[4:], dtype=np.uint8).reshape(n, 4)
            if n and (np.any(records[:, :3] >= np.array(size)) or np.any(records[:, 3] == 0)):
                raise VoxelError(
                    "XYZI contains an out-of-bounds coordinate or empty color index 0.",
                    "invalid_vox",
                )
            # Linear addresses make duplicates detectable without allocating a huge list of tuples.
            positions = records[:, :3].astype(np.int64)
            linear = (positions[:, 0] * size[1] + positions[:, 1]) * size[2] + positions[:, 2]
            if len(np.unique(linear)) != n:
                raise VoxelError("XYZI contains duplicate coordinates.", "invalid_vox")
            grid = np.zeros(size, dtype=np.uint8)
            if n:
                grid[tuple(positions.T)] = records[:, 3]
        elif kind == b"RGBA":
            if count != 1024 or grid is None:
                raise VoxelError(
                    "RGBA must follow XYZI and contain exactly 1024 bytes.", "invalid_vox"
                )
            palette = [(0, 0, 0, 0)] + [tuple(content[i : i + 4]) for i in range(0, 1020, 4)]
        pos += count
    if grid is None:
        raise VoxelError("VOX requires exactly one SIZE/XYZI pair.", "invalid_vox")
    return VoxelAsset(asset_name(name), grid, palette)
