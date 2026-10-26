import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from voxel_mcp.asset_store import AssetStore
from voxel_mcp.errors import VoxelError


def test_independent_stores_competing_revision(store):
    store.create("shared", [2, 2, 2])
    barrier = threading.Barrier(4)

    def edit(index):
        other = AssetStore(store.settings)
        barrier.wait(timeout=10)
        try:
            return other.edit(
                "shared", [{"op": "set_voxel", "point": [0, 0, 0], "color": index + 1}], 0
            )["ok"]
        except VoxelError as error:
            assert error.code == "revision_conflict"
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(edit, range(4)))
    assert results.count(True) == 1 and store.get("shared").revision == 1


def test_two_processes_share_durable_state(store):
    store.create("shared", [2, 2, 2])
    source = """
from pathlib import Path
import sys
from voxel_mcp.asset_store import AssetStore
from voxel_mcp.config import Settings
from voxel_mcp.errors import VoxelError
store = AssetStore(Settings(workspace=Path(sys.argv[1])))
try:
    store.edit('shared', [{'op':'set_voxel','point':[1,1,1],'color':2}], 0)
    print('edited')
except VoxelError as error:
    print(error.code)
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "src"))
    commands = [
        subprocess.Popen(
            [sys.executable, "-c", source, str(store.root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for _ in range(2)
    ]
    outputs = []
    for process in commands:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr
        outputs.append(stdout.strip())
    assert sorted(outputs) == ["edited", "revision_conflict"]
    assert store.get("shared").grid[1, 1, 1] == 2
