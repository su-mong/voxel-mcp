"""Disk-authoritative state, inter-process locking, path policy, atomic replacement."""

import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import portalocker
from pydantic import TypeAdapter

from .config import Settings
from .errors import VoxelError
from .models import AssetRecord, Revision, VoxelAsset, asset_name, decode_grid, validate_size
from .operations import execute
from .palette import make_palette


def reject_links(path: Path, root: Path):
    if not path.is_relative_to(root):
        raise VoxelError("Path escapes the allowed root.", "unsafe_path")
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise VoxelError(
                "Symlinks and junctions are not allowed in asset paths.", "unsafe_path"
            )
        if item == root:
            break
    if not path.resolve().is_relative_to(root):
        raise VoxelError("Resolved path escapes the allowed root.", "unsafe_path")


class AssetStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.workspace.absolute()
        # The configured workspace itself must not redirect via a link/junction.
        reject_links(self.root, Path(self.root.anchor))
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self._thread_lock = threading.RLock()
        for folder in ("assets", ".state"):
            self.path(folder).mkdir(exist_ok=True)

    def path(self, *parts: str) -> Path:
        path = self.root.joinpath(*parts)
        reject_links(path, self.root)
        return path

    @contextmanager
    def locked(self):
        with self._thread_lock:
            try:
                with portalocker.Lock(self.path(".state", "store.lock"), timeout=10):
                    yield
            except portalocker.exceptions.LockException as exc:
                raise VoxelError("Workspace is busy; retry the request.", "workspace_busy") from exc

    def atomic_write(self, path: Path, data: bytes):
        reject_links(path, self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".voxel-", delete=False
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            reject_links(path, self.root)
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _state_path(self, name: str) -> Path:
        return self.path(".state", asset_name(name) + ".json")

    def _read(self, name: str) -> tuple[VoxelAsset, list[str]]:
        path = self._state_path(name)
        if not path.exists():
            raise VoxelError(
                f"Asset '{asset_name(name)}' does not exist; create or load it first.", "not_found"
            )
        limit = (
            4096
            + (self.settings.history_limit + 1) * 4 * ((self.settings.max_voxels + 2) // 3)
            + 32768
        )
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
        if len(data) > limit:
            raise VoxelError("Asset state exceeds configured size limit.", "resource_limit")
        record = AssetRecord.model_validate_json(data)
        size = validate_size(record.size, self.settings)
        if (
            record.asset_name != asset_name(name)
            or len(record.history) > self.settings.history_limit
        ):
            raise VoxelError("Corrupt asset state metadata.")
        return VoxelAsset(
            record.asset_name,
            decode_grid(record.grid, size),
            make_palette(record.palette),
            record.revision,
            record.saved_vox_sha256,
        ), record.history

    def _write(self, asset: VoxelAsset, history: list[str]):
        self.atomic_write(
            self._state_path(asset.asset_name), asset.record(history).model_dump_json().encode()
        )

    @staticmethod
    def check_revision(asset: VoxelAsset, expected_revision: int | None):
        if expected_revision is not None:
            TypeAdapter(Revision).validate_python(expected_revision)
            if expected_revision != asset.revision:
                raise VoxelError(
                    f"Revision conflict: expected {expected_revision}, current {asset.revision}. Refresh get_asset_info.",
                    "revision_conflict",
                )

    def _check_new(self, name: str):
        if self._state_path(name).exists():
            raise VoxelError(f"Asset '{asset_name(name)}' already exists.", "already_exists")
        if sum(1 for _ in self.path(".state").glob("*.json")) >= self.settings.max_assets:
            raise VoxelError("Workspace has reached max_assets.", "resource_limit")

    def create(self, name: str, size, palette=None) -> dict:
        asset = VoxelAsset.create(name, size, palette, self.settings)
        with self.locked():
            self._check_new(asset.asset_name)
            self._write(asset, [])
        return asset.info()

    def get(self, name: str) -> VoxelAsset:
        with self.locked():
            return self._read(name)[0]

    def list(self, prefix: str = "") -> list[dict]:
        if prefix:
            prefix = asset_name(prefix)
        with self.locked():
            return [
                self._read(p.stem)[0].info()
                for p in sorted(self.path(".state").glob("*.json"))
                if p.stem.startswith(prefix)
            ]

    def edit(self, name: str, operations: list, expected_revision: int | None = None) -> dict:
        with self.locked():
            asset, history = self._read(name)
            self.check_revision(asset, expected_revision)
            grid, affected = execute(asset, operations, self.settings)
            history = (
                (history + [asset.encode_grid()])[-self.settings.history_limit :]
                if self.settings.history_limit
                else []
            )
            asset.grid = grid
            asset.revision += 1
            self._write(asset, history)
            return {
                "ok": True,
                "asset_name": asset.asset_name,
                "revision": asset.revision,
                "affected_voxels": affected,
                "warnings": [],
            }

    def source_path(self, source_path: str) -> Path:
        if "\x00" in source_path or ".." in Path(source_path).parts:
            raise VoxelError("Invalid source path.", "unsafe_path")
        path = Path(source_path)
        if not path.is_absolute():
            path = self.root / path
        roots = (self.root, *(p.absolute().resolve() for p in self.settings.read_roots))
        for root in roots:
            if path.is_relative_to(root):
                reject_links(path, root)
                if path.suffix.lower() != ".vox" or not path.is_file():
                    raise VoxelError("source_path must name an existing .vox file.")
                return path
        raise VoxelError(
            "source_path is outside workspace and configured read_roots.", "unsafe_path"
        )

    def undo(self, name: str, expected_revision: int | None = None) -> dict:
        with self.locked():
            asset, history = self._read(name)
            self.check_revision(asset, expected_revision)
            if not history:
                raise VoxelError("No edit history to undo.", "empty_history")
            restored = decode_grid(history[-1], asset.size)
            affected = int((restored != asset.grid).sum())
            asset.grid = restored
            asset.revision += 1
            self._write(asset, history[:-1])
            return {
                "ok": True,
                "asset_name": asset.asset_name,
                "revision": asset.revision,
                "affected_voxels": affected,
                "warnings": [],
            }
