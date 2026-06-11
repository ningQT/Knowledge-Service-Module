"""File storage backend abstract interface."""

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Abstract file storage backend for KSM.

    Phase 1: LocalStorageBackend (local filesystem)
    Phase 2: S3StorageBackend / WebDAVStorageBackend
    """

    @abstractmethod
    def read_file(self, path: str) -> str:
        """Read file content as string."""
        ...

    @abstractmethod
    def write_file(self, path: str, content: str) -> None:
        """Write string content to file."""
        ...

    @abstractmethod
    def list_files(self, directory: str, pattern: str = "*.md") -> list[str]:
        """List files matching pattern in directory."""
        ...

    @abstractmethod
    def delete_file(self, path: str) -> None:
        """Delete a file."""
        ...

    @abstractmethod
    def create_directory(self, path: str) -> None:
        """Create directory (and parents)."""
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if path exists."""
        ...

    @abstractmethod
    def join_path(self, *parts: str) -> str:
        """Join path components."""
        ...
