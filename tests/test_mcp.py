import asyncio
import os
import sys
from pathlib import Path

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from voxel_mcp.config import Settings
from voxel_mcp.server import create_server

CORE_TOOLS = {
    "create_voxel_asset",
    "get_asset_info",
    "execute_voxel_operations",
    "save_vox",
    "load_vox",
    "list_assets",
}


async def workflow(client):
    tools = (await client.list_tools()).tools
    assert CORE_TOOLS <= {tool.name for tool in tools}
    batch_tool = next(t for t in tools if t.name == "execute_voxel_operations")
    schema = batch_tool.input_schema
    assert schema["properties"]["operations"]["items"]["discriminator"]["propertyName"] == "op"
    assert "grid[x,y,z]" in client.instructions

    async def call(name, **arguments):
        result = await client.call_tool(name, arguments)
        assert not result.is_error, result.content
        return result.structured_content

    created = await call(
        "create_voxel_asset",
        asset_name="slime",
        size=[32, 32, 32],
        palette=[[0, 0, 0, 0], [10, 10, 10, 255], [50, 200, 70, 255]],
    )
    assert created["revision"] == 0
    edited = await call(
        "execute_voxel_operations",
        asset_name="slime",
        expected_revision=0,
        operations=[
            {"op": "fill_ellipsoid", "center": [16, 16, 12], "radius": [12, 10, 11], "color": 2},
            {"op": "fill_box", "min": [11, 6, 13], "max": [12, 8, 15], "color": 1},
            {"op": "fill_box", "min": [20, 6, 13], "max": [21, 8, 15], "color": 1},
        ],
    )
    assert edited["revision"] == 1 and edited["affected_voxels"] > 100
    saved = await call("save_vox", asset_name="slime", expected_revision=1)
    assert Path(saved["path"]).is_file()
    loaded = await call(
        "load_vox", asset_name="slime", source_path=saved["path"], expected_revision=1
    )
    assert loaded["revision"] == 2
    await call(
        "execute_voxel_operations",
        asset_name="slime",
        expected_revision=2,
        operations=[{"op": "set_voxel", "point": [11, 6, 16], "color": 1}],
    )
    await call("save_vox", asset_name="slime", expected_revision=3)
    exported = await call("export_six_views", asset_name="slime", scale=4, expected_revision=3)
    assert len(exported["views"]) == 6
    assert all(Path(v["path"]).is_file() for v in exported["views"].values())
    result = await client.call_tool(
        "execute_voxel_operations",
        {
            "asset_name": "slime",
            "expected_revision": 0,
            "operations": [{"op": "remove_voxel", "point": [0, 0, 0]}],
        },
    )
    assert result.is_error and "revision_conflict" in str(result.content)
    result = await client.call_tool(
        "execute_voxel_operations", {"asset_name": "slime", "operations": [{"op": "hack"}]}
    )
    assert result.is_error
    result = await client.call_tool(
        "create_voxel_asset", {"asset_name": "../escape", "size": [1, 1, 1]}
    )
    assert result.is_error and "validation_error" in str(result.content)
    assert (await call("get_asset_info", asset_name="slime"))["revision"] == 3
    assert len((await call("list_assets"))["assets"]) == 1
    undone = await call("undo_voxel_operations", asset_name="slime", expected_revision=3)
    assert undone["revision"] == 4
    disabled = await client.call_tool("open_in_magicavoxel", {"asset_name": "slime"})
    assert disabled.is_error and "launcher_disabled" in str(disabled.content)


def test_in_memory_mcp(tmp_path):
    async def run():
        async with Client(create_server(Settings(workspace=tmp_path))) as client:
            await workflow(client)

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_real_stdio_tools_list_and_e2e(tmp_path, mode):
    async def run():
        env = dict(
            os.environ,
            VOXEL_WORKSPACE=str(tmp_path),
            PYTHONPATH=str(Path(__file__).parents[1] / "src"),
            PYTHONUTF8="1",
        )
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "voxel_mcp.server"], env=env
        )
        async with Client(params, mode=mode, read_timeout_seconds=20) as client:
            await workflow(client)

    asyncio.run(run())
