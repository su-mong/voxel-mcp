"""Application workflows, independent of MCP transport."""

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from . import vox_io
from .asset_store import AssetStore, reject_links
from .capture import capture_six
from .errors import VoxelError
from .launcher import open_file
from .render import render_six


class AssetService:
    def __init__(self, store: AssetStore):
        self.store = store

    def save_vox(self, name: str, expected_revision: int | None = None) -> dict:
        with self.store.locked():
            asset, history = self.store._read(name)
            self.store.check_revision(asset, expected_revision)
            path = self.store.path("assets", asset.asset_name + ".vox")
            data = vox_io.dumps(asset, self.store.settings)
            digest = hashlib.sha256(data).hexdigest()
            if path.exists():
                current = self._read_bytes(path)
                current_digest = hashlib.sha256(current).hexdigest()
                if current_digest not in (asset.saved_vox_sha256, digest):
                    raise VoxelError(
                        "Output .vox was changed externally or belongs to another asset state. Load it explicitly before saving, or choose a new asset name.",
                        "file_conflict",
                    )
            self.store.atomic_write(path, data)
            asset.saved_vox_sha256 = digest
            warnings = []
            try:
                self.store._write(asset, history)
            except OSError:
                # The export itself has committed. Do not report it as a failed file write;
                # a retry with identical bytes can safely recover the fingerprint.
                warnings.append(
                    "VOX was saved, but its fingerprint could not be persisted. Retry save_vox before further edits."
                )
            return {
                "ok": True,
                "asset_name": asset.asset_name,
                "path": str(path),
                "revision": asset.revision,
                "sha256": digest,
                "warnings": warnings,
            }

    def _read_bytes(self, path):
        with path.open("rb") as handle:
            data = handle.read(self.store.settings.max_file_bytes + 1)
        if len(data) > self.store.settings.max_file_bytes:
            raise VoxelError("File exceeds max_file_bytes.", "resource_limit")
        return data

    def load_vox(self, name: str, source_path: str, expected_revision: int | None = None) -> dict:
        with self.store.locked():
            path = self.store.source_path(source_path)
            data = self._read_bytes(path)
            asset = vox_io.loads(data, name, self.store.settings)
            state = self.store._state_path(asset.asset_name)
            if state.exists():
                old, _ = self.store._read(asset.asset_name)
                if expected_revision is None:
                    raise VoxelError(
                        "Replacing an existing asset with load_vox requires expected_revision.",
                        "revision_conflict",
                    )
                self.store.check_revision(old, expected_revision)
                asset.revision = old.revision + 1
                asset.saved_vox_sha256 = old.saved_vox_sha256
            else:
                self.store._check_new(asset.asset_name)
                if expected_revision is not None:
                    self.store.check_revision(asset, expected_revision)
            if path == self.store.path("assets", asset.asset_name + ".vox"):
                asset.saved_vox_sha256 = hashlib.sha256(data).hexdigest()
            self.store._write(asset, [])
            return {
                **asset.info(),
                "ok": True,
                "support": "single_model_SIZE_XYZI_RGBA",
                "warnings": [
                    "Import replaces the undo history; scene/material/layer chunks are rejected."
                ],
            }

    def export_six_views(
        self, name: str, scale: int = 8, padding: int = 0, expected_revision: int | None = None
    ) -> dict:
        with self.store.locked():
            asset, _ = self.store._read(name)
            self.store.check_revision(asset, expected_revision)
            views = render_six(asset, self.store.settings, scale, padding)
            digest = hashlib.sha256(b"".join(view["data"] for view in views.values())).hexdigest()
            parent = self.store.path("assets", asset.asset_name, "views")
            parent.mkdir(parents=True, exist_ok=True)
            folder = self.store.path(
                "assets",
                asset.asset_name,
                "views",
                f"r{asset.revision:06d}_s{scale}_p{padding}_{digest[:16]}",
            )
            manifest = {
                "ok": True,
                "asset_name": asset.asset_name,
                "revision": asset.revision,
                "projection": "orthographic_nearest_occupied_surface",
                "scale": scale,
                "padding": padding,
                "views": {},
                "warnings": [],
            }
            for view_name, view in views.items():
                manifest["views"][view_name] = {k: v for k, v in view.items() if k != "data"}
                manifest["views"][view_name].update(
                    path=str(folder / f"{view_name}.png"),
                    sha256=hashlib.sha256(view["data"]).hexdigest(),
                )
            manifest["manifest_path"] = str(folder / "manifest.json")
            manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
            files = {f"{name}.png": view["data"] for name, view in views.items()}
            files["manifest.json"] = manifest_bytes
            self._publish_images(folder, files)
            return manifest

    def _publish_images(self, folder: Path, files: dict[str, bytes]):
        """Publish a complete immutable image bundle or leave all previous bundles intact."""
        reject_links(folder, self.store.root)
        if folder.exists():
            for filename, data in files.items():
                path = folder / filename
                reject_links(path, self.store.root)
                if (
                    not path.is_file()
                    or path.stat().st_size != len(data)
                    or path.read_bytes() != data
                ):
                    raise VoxelError(
                        "Existing PNG bundle was modified; use different capture settings or revision.",
                        "file_conflict",
                    )
            return
        stage = Path(tempfile.mkdtemp(prefix=".voxel-views-", dir=folder.parent))
        try:
            for filename, data in files.items():
                self.store.atomic_write(stage / filename, data)
            for attempt in range(5):
                reject_links(folder, self.store.root)
                try:
                    os.replace(stage, folder)
                    break
                except PermissionError:
                    # Windows thumbnailers/AV can briefly hold new image directories.
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            if stage.exists():
                reject_links(stage, self.store.root)
                shutil.rmtree(stage)

    def capture_six_views(
        self,
        name: str,
        image_size: int = 512,
        padding: int = 24,
        background: list[int] | None = None,
        expected_revision: int | None = None,
    ) -> dict:
        with self.store.locked():
            asset, _ = self.store._read(name)
            self.store.check_revision(asset, expected_revision)
            capture = capture_six(asset, self.store.settings, image_size, padding, background)
            views = capture.pop("views")
            sheet = capture.pop("contact_sheet")
            digest = hashlib.sha256(
                json.dumps({"capture_format_version": 1, **capture}, sort_keys=True).encode("utf-8")
                + b"".join(view["data"] for view in views.values())
                + sheet["data"]
            ).hexdigest()
            parent = self.store.path("assets", asset.asset_name, "captures")
            parent.mkdir(parents=True, exist_ok=True)
            folder = self.store.path(
                "assets",
                asset.asset_name,
                "captures",
                f"r{asset.revision:06d}_{image_size}px_p{padding}_{digest[:16]}",
            )
            manifest = {
                "ok": True,
                "asset_name": asset.asset_name,
                "revision": asset.revision,
                "format_version": 1,
                "capture_method": "headless_model_orthographic",
                "projection": "orthographic_nearest_occupied_surface",
                **capture,
                "views": {},
                "warnings": [],
            }
            files = {}
            for name, view in [*views.items(), ("contact_sheet", sheet)]:
                data = view["data"]
                metadata = {k: v for k, v in view.items() if k != "data"}
                metadata.update(
                    path=str(folder / f"{name}.png"), sha256=hashlib.sha256(data).hexdigest()
                )
                if name == "contact_sheet":
                    manifest["contact_sheet"] = metadata
                else:
                    manifest["views"][name] = metadata
                files[f"{name}.png"] = data
            manifest["manifest_path"] = str(folder / "manifest.json")
            files["manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=False).encode(
                "utf-8"
            )
            self._publish_images(folder, files)
            return manifest

    def open_in_magicavoxel(self, name: str, expected_revision: int | None = None) -> dict:
        if self.store.settings.magicavoxel_exe is None:
            raise VoxelError(
                "Set MAGICAVOXEL_EXE to enable the optional launcher.", "launcher_disabled"
            )
        saved = self.save_vox(name, expected_revision)
        return open_file(self.store.settings.magicavoxel_exe, Path(saved["path"]))
