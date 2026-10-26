"""Capture an existing asset through the real MCP stdio server, with no application UI."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters


async def capture_asset(workspace, asset_name, image_size, padding, background):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "voxel_mcp.server"],
        env=dict(os.environ, VOXEL_WORKSPACE=str(workspace), PYTHONUTF8="1"),
    )
    async with Client(params, mode="legacy", read_timeout_seconds=30) as client:
        info = await client.call_tool("get_asset_info", {"asset_name": asset_name})
        if info.is_error:
            raise RuntimeError(str(info.content))
        result = await client.call_tool(
            "capture_six_views",
            {
                "asset_name": asset_name,
                "expected_revision": info.structured_content["revision"],
                "image_size": image_size,
                "padding": padding,
                "background": background,
            },
        )
        if result.is_error:
            raise RuntimeError(str(result.content))
        return result.structured_content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_name")
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--image-size", type=int, default=512)
    parser.add_argument("--padding", type=int, default=24)
    parser.add_argument("--background", type=int, nargs=4, metavar=("R", "G", "B", "A"))
    args = parser.parse_args()
    result = asyncio.run(
        capture_asset(
            args.workspace.resolve(),
            args.asset_name,
            args.image_size,
            args.padding,
            args.background,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
