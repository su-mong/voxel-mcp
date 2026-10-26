"""Optional explicit MagicaVoxel launch; no UI automation or process synchronization."""

import subprocess
from pathlib import Path

from .errors import VoxelError


def open_file(executable: Path | None, source: Path) -> dict:
    if executable is None:
        raise VoxelError(
            "Set MAGICAVOXEL_EXE to enable the optional launcher.", "launcher_disabled"
        )
    executable = executable.expanduser().resolve()
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise VoxelError("MAGICAVOXEL_EXE must point to an existing .exe file.")
    process = subprocess.Popen(
        [str(executable), str(source)],
        cwd=executable.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    return {
        "ok": True,
        "started": True,
        "pid": process.pid,
        "path": str(source),
        "warnings": ["File-based review only; the running application is not synchronized."],
    }
