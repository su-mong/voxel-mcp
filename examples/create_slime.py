"""Run the complete creation/reload/edit/export workflow through a real MCP stdio client.

python examples/create_slime.py [--workspace PATH] [--name green_slime]
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters


async def create_slime(workspace: Path, name: str) -> dict:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "voxel_mcp.server"],
        env=dict(os.environ, VOXEL_WORKSPACE=str(workspace), PYTHONUTF8="1"),
    )
    async with Client(params, mode="legacy", read_timeout_seconds=30) as client:

        async def call(tool, **arguments):
            result = await client.call_tool(tool, arguments)
            if result.is_error:
                raise RuntimeError(str(result.content))
            return result.structured_content

        palette = [
            [0, 0, 0, 0],
            [16, 24, 22, 255],
            [61, 189, 82, 255],
            [119, 231, 120, 255],
            [255, 255, 255, 255],
        ]
        await call("create_voxel_asset", asset_name=name, size=[32, 32, 32], palette=palette)
        await call(
            "execute_voxel_operations",
            asset_name=name,
            expected_revision=0,
            operations=[
                {
                    "op": "fill_ellipsoid",
                    "center": [15.5, 16, 12],
                    "radius": [12.5, 11, 11],
                    "color": 2,
                },
                {"op": "fill_ellipsoid", "center": [12, 11, 19], "radius": [3, 3, 2], "color": 3},
                {"op": "fill_box", "min": [10, 5, 13], "max": [12, 8, 16], "color": 1},
                {"op": "fill_box", "min": [19, 5, 13], "max": [21, 8, 16], "color": 1},
                {"op": "set_voxel", "point": [11, 5, 16], "color": 4},
                {"op": "set_voxel", "point": [20, 5, 16], "color": 4},
            ],
        )
        saved = await call("save_vox", asset_name=name, expected_revision=1)
        await call("load_vox", asset_name=name, source_path=saved["path"], expected_revision=1)
        await call(
            "execute_voxel_operations",
            asset_name=name,
            expected_revision=2,
            operations=[
                {"op": "fill_box", "min": [10, 5, 13], "max": [12, 8, 16], "color": 2},
                {"op": "fill_box", "min": [19, 5, 13], "max": [21, 8, 16], "color": 2},
                {"op": "fill_box", "min": [10, 5, 14], "max": [12, 8, 17], "color": 1},
                {"op": "fill_box", "min": [19, 5, 14], "max": [21, 8, 17], "color": 1},
                {"op": "set_voxel", "point": [11, 5, 17], "color": 4},
                {"op": "set_voxel", "point": [20, 5, 17], "color": 4},
            ],
        )
        saved = await call("save_vox", asset_name=name, expected_revision=3)
        exported = await call(
            "export_six_views", asset_name=name, scale=8, padding=8, expected_revision=3
        )
        info = await call("get_asset_info", asset_name=name)
        return {
            "asset_name": name,
            "revision": info["revision"],
            "voxel_count": info["voxel_count"],
            "vox": saved["path"],
            "views": exported["views"],
            "manifest": exported["manifest_path"],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--name", default="green_slime")
    args = parser.parse_args()
    result = asyncio.run(create_slime(args.workspace.resolve(), args.name))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
