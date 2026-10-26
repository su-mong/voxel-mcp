import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from voxel_mcp.config import Settings
from voxel_mcp.errors import VoxelError
from voxel_mcp.launcher import open_file


def test_settings_environment(monkeypatch, tmp_path):
    for key in Settings.model_fields:
        monkeypatch.delenv("VOXEL_" + key.upper(), raising=False)
    monkeypatch.setenv("VOXEL_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("VOXEL_MAX_AXIS", "64")
    monkeypatch.setenv(
        "VOXEL_READ_ROOTS", str(tmp_path / "a") + __import__("os").pathsep + str(tmp_path / "b")
    )
    monkeypatch.setenv("MAGICAVOXEL_EXE", str(tmp_path / "MagicaVoxel.exe"))
    settings = Settings.from_env()
    assert settings.workspace == tmp_path and settings.max_axis == 64
    assert settings.read_roots == (tmp_path / "a", tmp_path / "b")
    assert settings.magicavoxel_exe == tmp_path / "MagicaVoxel.exe"
    monkeypatch.setenv("VOXEL_MAX_AXIS", "257")
    with pytest.raises(ValidationError):
        Settings.from_env()


def test_launcher_uses_argument_array_without_shell(tmp_path, monkeypatch):
    executable = tmp_path / "Magica Voxel.exe"
    executable.write_bytes(b"fixture only, not executed")
    source = tmp_path / "asset with spaces.vox"
    source.write_bytes(b"fixture")
    called = {}

    def launch(args, **kwargs):
        called.update(args=args, kwargs=kwargs)
        return SimpleNamespace(pid=123)

    monkeypatch.setattr(subprocess, "Popen", launch)
    result = open_file(executable, source)
    assert result["started"] and result["pid"] == 123
    assert called["args"] == [str(executable.resolve()), str(source)]
    assert called["kwargs"]["shell"] is False
    assert called["kwargs"]["cwd"] == executable.parent
    assert called["kwargs"]["stdout"] == subprocess.DEVNULL
    for exe in (None, Path("missing.exe"), source):
        with pytest.raises(VoxelError):
            open_file(exe, source)
