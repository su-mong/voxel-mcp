"""MCP SDK v2 stdio adapter. stdout belongs exclusively to the protocol."""

import logging
from functools import wraps
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import StrictStr

from . import __version__
from .asset_store import AssetStore
from .capture import Background, CapturePadding, CaptureSize
from .config import Settings
from .errors import VoxelError
from .models import Point, Revision
from .operations import Operation
from .palette import PaletteInput
from .render import Padding, Scale
from .service import AssetService

INSTRUCTIONS = """Create/edit local voxel assets, save MagicaVoxel-compatible .vox files, and export six PNG views.
grid[x,y,z]; +X right, +Y back, +Z up. Index 0 is empty; colors 1..255 are occupied.
Workflow: create/load -> get_asset_info -> execute_voxel_operations with expected_revision -> save_vox.
Batches are atomic, bounds are inclusive, out-of-bounds writes fail without clipping.
Pass the latest revision to edits/saves/undo; reloading an existing name requires it.
Only basic single-model VOX files are supported. Scene/layer/material/unknown chunks are rejected.
Asset names are normalized to lowercase. Files stay in the configured workspace. Relative import paths
are relative to workspace; external imports require configured read_roots. No uploads or LLM calls.
save_vox detects external changes; explicitly load them before overwriting.
Use capture_six_views for model-only, auto-framed square PNGs and a six-view contact sheet.
Use export_six_views for the original voxel-scale, full-grid PNGs. Neither requires an app window.
"""


def guarded(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except VoxelError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        except ValueError as exc:
            raise ToolError(f"validation_error: {exc}") from exc
        except OSError as exc:
            logging.getLogger(__name__).warning("Local file operation failed: %r", exc)
            raise ToolError(f"io_error: {exc.strerror or str(exc)}") from exc

    return call


def create_server(settings: Settings | None = None) -> MCPServer:
    store = AssetStore(settings or Settings.from_env())
    service = AssetService(store)
    mcp = MCPServer(
        "magica-voxel-mcp", version=__version__, instructions=INSTRUCTIONS, log_level="WARNING"
    )
    read = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
    write = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

    @mcp.tool(annotations=write)
    @guarded
    def create_voxel_asset(
        asset_name: StrictStr, size: Point, palette: PaletteInput | None = None
    ) -> dict[str, Any]:
        """Create a new empty grid[x,y,z] (default max 126 per axis), revision 0.
        Palette is an indexed RGBA list starting with [0,0,0,0]; omitted entries use the
        MagicaVoxel default palette. Existing names are rejected. 0=empty, 1..255=color.
        """
        return store.create(asset_name, size, palette)

    @mcp.tool(annotations=read)
    @guarded
    def get_asset_info(asset_name: StrictStr) -> dict[str, Any]:
        """Get size, full indexed RGBA palette, current revision, occupied count and inclusive bounds.
        +X=right, +Y=back, +Z=up. bounds=null for an empty asset.
        """
        return store.get(asset_name).info()

    @mcp.tool(annotations=write)
    @guarded
    def execute_voxel_operations(
        asset_name: StrictStr,
        operations: list[Operation],
        expected_revision: Revision | None = None,
    ) -> dict[str, Any]:
        """Apply a typed batch in order, all-or-nothing; a failure leaves grid/revision unchanged.
        Use expected_revision from get_asset_info to prevent stale edits. One successful batch
        advances revision once; affected_voxels counts distinct cells changed in the final result.
        Integer coordinates use +X=right,+Y=back,+Z=up. Box bounds include both ends.
        Ellipsoids use voxel centers and sum(((p-center)/radius)^2)<=1; radii>0.
        Shapes must fit entirely within bounds. Color 0 is only allowed as replace_color.to_color.
        fill_cylinder has flat caps at start/end; fill_line uses dominant-axis integer DDA.
        mirror reflect flips the whole region; copy copies its lower half to upper half, overwriting empties.
        rotate_90 uses right-hand positive quarter turns around region center, square plane required for odd turns.
        translate moves occupied cells, rejects bounds loss and defaults to collision=error; overwrite is explicit.
        """
        return store.edit(asset_name, operations, expected_revision)

    @mcp.tool(annotations=write)
    @guarded
    def save_vox(
        asset_name: StrictStr, expected_revision: Revision | None = None
    ) -> dict[str, Any]:
        """Atomically write workspace/assets/<name>.vox; return absolute path, revision and SHA256.
        Does not advance revision. Rejects externally modified output; explicitly load it first.
        Writes a basic single-model VOX 150 with SIZE/XYZI/RGBA for MagicaVoxel.
        """
        return service.save_vox(asset_name, expected_revision)

    @mcp.tool(annotations=write)
    @guarded
    def load_vox(
        asset_name: StrictStr, source_path: StrictStr, expected_revision: Revision | None = None
    ) -> dict[str, Any]:
        """Import a basic single-model VOX 150/200 from workspace or configured read_roots.
        Relative paths start at workspace. Unsupported scene/material/layer chunks are rejected.
        A new name starts at revision 0. Replacing an existing asset REQUIRES expected_revision,
        advances revision and resets undo history. The source file is never modified.
        """
        return service.load_vox(asset_name, source_path, expected_revision)

    @mcp.tool(annotations=read)
    @guarded
    def list_assets(prefix: StrictStr = "") -> dict[str, Any]:
        """List persisted asset metadata, optionally filtering by a safe lowercase name prefix."""
        return {"assets": store.list(prefix)}

    @mcp.tool(annotations=write)
    @guarded
    def undo_voxel_operations(
        asset_name: StrictStr, expected_revision: Revision | None = None
    ) -> dict[str, Any]:
        """Undo the latest edit batch (default last 8 available), preserving monotonically increasing revision.
        Import resets history. Undo changes the working asset; call save_vox again to update the .vox file.
        """
        return store.undo(asset_name, expected_revision)

    @mcp.tool(annotations=write)
    @guarded
    def export_six_views(
        asset_name: StrictStr,
        scale: Scale = 8,
        padding: Padding = 0,
        expected_revision: Revision | None = None,
    ) -> dict[str, Any]:
        """Export front/back/left/right/top/bottom PNGs as one atomic, versioned local bundle plus manifest.
        Transparent RGBA, unlit orthographic nearest occupied surfaces; no alpha blending or shadows.
        front=-Y/back=+Y, left=-X/right=+X, top=+Z/bottom=-Z; image orientations are in the manifest.
        Nearest-neighbor scale 1..16, transparent padding 0..64 output pixels per side.
        Returns six absolute paths, dimensions, camera axes and SHA256 hashes; revision does not change.
        """
        return service.export_six_views(asset_name, scale, padding, expected_revision)

    @mcp.tool(annotations=write)
    @guarded
    def capture_six_views(
        asset_name: StrictStr,
        image_size: CaptureSize = 512,
        padding: CapturePadding = 24,
        background: Background | None = None,
        expected_revision: Revision | None = None,
    ) -> dict[str, Any]:
        """Save six model-only square PNG captures plus a labeled 3x2 contact_sheet.png and manifest.
        Headless: no MagicaVoxel window, app UI, screen capture or executable is required.
        Automatically crop empty world margins and center the model, using one common scale across views.
        image_size=64..2048 pixels per side (default 512); padding=0..256 pixels, less than half image_size.
        background is [R,G,B,A] with bytes 0..255, default transparent. Nearest occupied surfaces,
        nearest-neighbor resizing, no lighting or shadows; partial-alpha surfaces composite over background.
        Contact sheet uses a dark opaque backdrop. Pixel budget includes all seven images.
        Front=-Y/back=+Y/left=-X/right=+X/top=+Z/bottom=-Z; axes, crop bounds, dimensions,
        SHA256 hashes and absolute file paths are in manifest. Atomic versioned output; revision unchanged.
        """
        return service.capture_six_views(
            asset_name, image_size, padding, background, expected_revision
        )

    @mcp.tool(annotations=write)
    @guarded
    def open_in_magicavoxel(
        asset_name: StrictStr, expected_revision: Revision | None = None
    ) -> dict[str, Any]:
        """Save .vox and launch the configured MAGICAVOXEL_EXE for optional manual review.
        Disabled unless the executable is configured. File-based only; no live control or synchronization.
        """
        return service.open_in_magicavoxel(asset_name, expected_revision)

    return mcp


def main():
    logging.basicConfig(level=logging.WARNING)
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
