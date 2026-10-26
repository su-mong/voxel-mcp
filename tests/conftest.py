import pytest

from voxel_mcp.asset_store import AssetStore
from voxel_mcp.config import Settings


@pytest.fixture
def store(tmp_path):
    return AssetStore(Settings(workspace=tmp_path / "workspace"))
