"""Local filesystem storage backend implementation."""

import shutil
from pathlib import Path

from app.storage.filesystem import StorageBackend
from app.storage.path_utils import UnsafePathError


class LocalStorageBackend(StorageBackend):
    """Local filesystem implementation of StorageBackend."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def read_file(self, path: str) -> str:
        full_path = self._resolve(path)
        return full_path.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        full_path = self._resolve(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def list_files(self, directory: str, pattern: str = "*.md") -> list[str]:
        full_path = self._resolve(directory)
        if not full_path.exists():
            return []
        return sorted(str(p.relative_to(self.base_dir)) for p in full_path.rglob(pattern))

    def delete_file(self, path: str) -> None:
        full_path = self._resolve(path)
        if full_path.exists():
            full_path.unlink()

    def create_directory(self, path: str) -> None:
        full_path = self._resolve(path)
        full_path.mkdir(parents=True, exist_ok=True)

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def join_path(self, *parts: str) -> str:
        return str(Path(*parts))

    def _resolve(self, path: str) -> Path:
        """Resolve path under base_dir."""
        p = Path(path)
        base = self.base_dir.resolve()
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (base / p).resolve()
        if resolved == base or resolved.is_relative_to(base):
            return resolved
        raise UnsafePathError("Resolved path is outside the storage base directory")
