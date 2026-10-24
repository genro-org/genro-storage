# Copyright (c) 2025 Softwell Srl, Milano, Italy
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Local filesystem backend for genro-storage.

This module implements the local filesystem storage backend using
Python's standard pathlib and file operations.

Writes that replace a file (``write_bytes``, ``write_text``, ``open`` in a
``w`` mode) are atomic for readers: data goes to a uniquely named temporary
file in the destination directory, is fsync'ed, then ``os.replace`` moves it
onto the destination. A reader sees the complete old or the complete new
content. An existing destination keeps its permission bits; a new one gets
the umask default. If the ``with`` block of ``open`` raises, the temporary
file is removed and the destination is untouched. Modes ``a``, ``x`` and
``r+`` write in place, as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, TextIO, Callable, Union
import os
import shutil
import stat
import sys
import uuid

from .base import StorageBackend
from ..capabilities import capability


class AtomicWriteFile:
    """File object that writes to a temporary file and replaces the destination on close.

    Attribute access is delegated to the underlying temporary file object.
    """

    def __init__(self, temp_file, temp_path: Path, destination: Path):
        self._temp_file = temp_file
        self._temp_path = temp_path
        self._destination = destination

    def __getattr__(self, name: str):
        return getattr(self._temp_file, name)

    def __iter__(self):
        return iter(self._temp_file)

    def __enter__(self) -> AtomicWriteFile:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.close()
        else:
            self.discard()

    def close(self) -> None:
        """Flush, fsync and close the temporary file, then move it onto the destination."""
        if self._temp_file.closed:
            return
        try:
            self._temp_file.flush()
            os.fsync(self._temp_file.fileno())
            self._temp_file.close()
            os.replace(self._temp_path, self._destination)
        except BaseException:
            self.discard()
            raise

    def discard(self) -> None:
        """Close and remove the temporary file, leaving the destination untouched."""
        self._temp_file.close()
        self._temp_path.unlink(missing_ok=True)


class LocalStorage(StorageBackend):
    """Local filesystem storage backend.

    This backend provides access to files on the local filesystem.
    All paths are relative to a configured base directory.

    The base_path can be either a string or a callable that returns a string.
    When a callable is provided, it will be evaluated each time the base_path
    property is accessed, allowing for dynamic paths (e.g., user-specific directories).

    Args:
        path: Absolute path to the base directory, or callable returning path

    Raises:
        ValueError: If resolved path is not absolute or not a directory
        FileNotFoundError: If resolved path doesn't exist

    Examples:
        >>> # Static path
        >>> backend = LocalStorage('/home/user')
        >>>
        >>> # Dynamic path with context-based callable (no parameters)
        >>> def get_user_dir():
        ...     user_id = get_current_user()
        ...     return f'/data/users/{user_id}'
        >>> backend = LocalStorage(get_user_dir)
        >>>
        >>> # Switched mount: callable with prefix parameter
        >>> # Single mount behaves like multiple mounts based on first path component
        >>> def resource_resolver(prefix):
        ...     # prefix = 'sys', 'adm', 'gnr', etc.
        ...     return f'/path/to/{prefix}-package'
        >>> backend = LocalStorage(resource_resolver)
        >>> # Accessing 'sys/folder/file.txt' routes to '/path/to/sys-package/folder/file.txt'
        >>> # Accessing 'adm/folder/file.txt' routes to '/path/to/adm-package/folder/file.txt'
        >>>
        >>> # Access files relative to base
        >>> data = backend.read_bytes('documents/report.pdf')

    Note:
        **Switched Mounts**: When the callable accepts a parameter, it receives the
        first path component (prefix) and should return the base directory for that prefix.
        The backend then appends the remaining path. This allows a single mount to route
        to different base directories based on the prefix.
    """

    # Default protocol name for this backend
    _default_protocol = "local"

    def __init__(self, path: Union[str, Callable[[], str]], base_url: str | None = None):
        """Initialize LocalStorage backend.

        Args:
            path: Absolute path or callable returning absolute path
            base_url: Optional base URL for generating file URLs (e.g., '/static')

        Raises:
            ValueError: If path (string only) is not absolute or not a directory
            FileNotFoundError: If path (string only) doesn't exist

        Note:
            When path is a callable, validation is deferred until first access.
            This allows configuration before the context (e.g., current user) is available.
        """
        self._path_or_callable = path
        self._base_url = base_url

        # Validate immediately only if path is a string (not callable)
        if not callable(path):
            resolved = Path(path).resolve()
            if not Path(path).is_absolute():
                raise ValueError(f"base_path must be absolute, got: {path}")

            if not resolved.exists():
                raise FileNotFoundError(f"Base path does not exist: {path}")

            if not resolved.is_dir():
                raise ValueError(f"Base path must be a directory: {path}")

    def _resolve_base_path(self, requested_path: str = "") -> Path:
        """Resolve base path (evaluating callable if necessary).

        Args:
            requested_path: The path being accessed (passed to callable if it accepts parameters)

        Returns:
            Resolved base path as Path object

        Note:
            If path is a callable:
            - Tries to call with requested_path parameter first
            - Falls back to calling without parameters for backward compatibility
            - This allows callables to dynamically determine base path based on the requested path
        """
        if callable(self._path_or_callable):
            # Try calling with path parameter first (new behavior)
            import inspect

            sig = inspect.signature(self._path_or_callable)

            if len(sig.parameters) > 0:
                # Callable accepts parameters - pass the requested path
                path_str = self._path_or_callable(requested_path)
            else:
                # Callable takes no parameters - backward compatibility
                path_str = self._path_or_callable()
        else:
            path_str = self._path_or_callable

        return Path(path_str).resolve()

    @property
    def base_path(self) -> Path:
        """Get current base path (evaluates callable if needed).

        Returns:
            Current base path as Path object
        """
        return self._resolve_base_path()

    @classmethod
    def get_json_info(cls) -> dict:
        """Return complete backend information in JSON format.

        Returns:
            dict: Backend information with schema, capabilities, and description.
        """
        # Get base capabilities from parent class (auto-derived from @capability decorators)
        info = super().get_json_info()

        # Override description and schema with LocalStorage-specific information
        info["description"] = "Local filesystem storage with full read/write capabilities"
        info["schema"] = {
            "fields": [
                {
                    "name": "path",
                    "type": "text",
                    "label": "Local Path",
                    "required": True,
                    "placeholder": "/path/to/directory",
                    "help": "Absolute path to local directory",
                }
            ]
        }

        # Add platform-specific capability (symbolic_links only on Unix)
        is_unix = sys.platform != "win32"
        info["capabilities"]["symbolic_links"] = is_unix

        return info

    def _resolve_path(self, path: str) -> Path:
        """Resolve a relative path to absolute filesystem path.

        Args:
            path: Relative path within this storage

        Returns:
            Path: Absolute filesystem path

        Raises:
            ValueError: If path tries to escape base_path
        """
        if not path:
            return self._resolve_base_path()

        # Check if callable accepts parameters (routing mode)
        if callable(self._path_or_callable):
            import inspect

            sig = inspect.signature(self._path_or_callable)
            has_parameters = len(sig.parameters) > 0
        else:
            has_parameters = False

        if has_parameters:
            # Routing mode: extract first component (prefix)
            # Example: 'sys/folder/file.txt' -> prefix='sys', rest='folder/file.txt'
            if "/" in path:
                prefix, rest = path.split("/", 1)
            else:
                prefix = path
                rest = ""

            # Pass only the prefix to base_path resolution (for callable routing)
            base = self._resolve_base_path(prefix)

            # Append the rest of the path
            if rest:
                full_path = (base / rest).resolve()
            else:
                full_path = base.resolve()
        else:
            # Context mode: pass whole path to base resolution
            base = self._resolve_base_path()
            full_path = (base / path).resolve()

        # Security check: ensure path doesn't escape base_path
        try:
            full_path.relative_to(base)
        except ValueError:
            raise ValueError(
                f"Path escapes base directory: {path} " f"(resolved to {full_path}, base is {base})"
            )

        return full_path

    def exists(self, path: str) -> bool:
        """Check if file or directory exists."""
        return self._resolve_path(path).exists()

    def is_file(self, path: str) -> bool:
        """Check if path points to a file."""
        return self._resolve_path(path).is_file()

    def is_dir(self, path: str) -> bool:
        """Check if path points to a directory."""
        return self._resolve_path(path).is_dir()

    def size(self, path: str) -> int:
        """Get file size in bytes."""
        full_path = self._resolve_path(path)

        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if full_path.is_dir():
            raise ValueError(f"Path is a directory, not a file: {path}")

        return full_path.stat().st_size

    def mtime(self, path: str) -> float:
        """Get last modification time."""
        full_path = self._resolve_path(path)

        if not full_path.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        return full_path.stat().st_mtime

    @capability("read", "write", "append_mode", "seek_support", "atomic_operations")
    def open(self, path: str, mode: str = "rb") -> BinaryIO | TextIO:
        """Open file and return file-like object."""
        full_path = self._resolve_path(path)

        if "w" in mode:
            return self._open_atomic_write(full_path, mode)

        # Ensure parent directory exists for write modes
        if any(m in mode for m in ["a", "x"]):
            full_path.parent.mkdir(parents=True, exist_ok=True)

        return open(full_path, mode)

    def _open_atomic_write(
        self, full_path: Path, mode: str, encoding: str | None = None
    ) -> AtomicWriteFile:
        """Open a temporary file beside full_path that replaces it on close."""
        full_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = full_path.with_name(f".{full_path.name}.{uuid.uuid4().hex}.tmp")
        temp_file = open(temp_path, mode.replace("w", "x"), encoding=encoding)
        if full_path.exists():
            os.chmod(temp_path, stat.S_IMODE(full_path.stat().st_mode))
        return AtomicWriteFile(temp_file, temp_path, full_path)

    @capability("read")
    def read_bytes(self, path: str) -> bytes:
        """Read entire file as bytes."""
        full_path = self._resolve_path(path)

        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        return full_path.read_bytes()

    @capability("read")
    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        """Read entire file as text."""
        full_path = self._resolve_path(path)

        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        return full_path.read_text(encoding=encoding)

    @capability("write", "atomic_operations")
    def write_bytes(self, path: str, data: bytes) -> None:
        """Write bytes to file, replacing it atomically."""
        with self._open_atomic_write(self._resolve_path(path), "wb") as f:
            f.write(data)

    @capability("write", "atomic_operations")
    def write_text(self, path: str, text: str, encoding: str = "utf-8") -> None:
        """Write text to file, replacing it atomically."""
        with self._open_atomic_write(self._resolve_path(path), "w", encoding=encoding) as f:
            f.write(text)

    @capability("delete")
    def delete(self, path: str, recursive: bool = False) -> None:
        """Delete file or directory."""
        full_path = self._resolve_path(path)

        if not full_path.exists():
            # Idempotent - no error if doesn't exist
            return

        if full_path.is_file():
            full_path.unlink()
        elif full_path.is_dir():
            if recursive:
                shutil.rmtree(full_path)
            else:
                # Check if directory is empty
                if any(full_path.iterdir()):
                    raise ValueError(
                        f"Directory is not empty: {path}. "
                        f"Use recursive=True to delete recursively."
                    )
                full_path.rmdir()

    @capability("list_dir")
    def list_dir(self, path: str) -> list[str]:
        """List directory contents."""
        full_path = self._resolve_path(path)

        if not full_path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")

        if not full_path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

        return [item.name for item in full_path.iterdir()]

    @capability("mkdir")
    def mkdir(self, path: str, parents: bool = False, exist_ok: bool = False) -> None:
        """Create directory."""
        full_path = self._resolve_path(path)

        if full_path.exists() and not exist_ok:
            raise FileExistsError(f"Directory already exists: {path}")

        full_path.mkdir(parents=parents, exist_ok=exist_ok)

    @capability("copy_optimization")
    def copy(self, src_path: str, dest_backend: StorageBackend, dest_path: str) -> None:
        """Copy file/directory to another backend.

        For local-to-local copies, uses efficient filesystem operations.
        For copies to other backends, streams the data.
        """
        src_full = self._resolve_path(src_path)

        if not src_full.exists():
            raise FileNotFoundError(f"Source not found: {src_path}")

        if src_full.is_file():
            # Copy single file
            if isinstance(dest_backend, LocalStorage):
                # Local-to-local: use shutil for efficiency
                dest_full = dest_backend._resolve_path(dest_path)
                dest_full.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_full, dest_full)
            else:
                # To other backend: stream via read/write
                data = self.read_bytes(src_path)
                dest_backend.write_bytes(dest_path, data)

        elif src_full.is_dir():
            # Copy directory recursively
            dest_backend.mkdir(dest_path, parents=True, exist_ok=True)

            for item in src_full.iterdir():
                item_rel_path = f"{src_path}/{item.name}" if src_path else item.name
                dest_item_path = f"{dest_path}/{item.name}" if dest_path else item.name
                self.copy(item_rel_path, dest_backend, dest_item_path)

    def url(self, path: str, expires_in: int = 3600, **kwargs) -> str | None:
        """Generate URL for file access.

        Returns a URL based on the configured base_url. If no base_url was
        configured, returns None.

        Args:
            path: Relative path to file
            expires_in: Ignored for local storage (no expiration)
            **kwargs: Ignored for local storage

        Returns:
            str | None: URL string if base_url configured, None otherwise

        Examples:
            >>> # With base_url='/static'
            >>> backend = LocalStorage('/var/www/static', base_url='/static')
            >>> url = backend.url('css/style.css')
            >>> print(url)
            '/static/css/style.css'
            >>>
            >>> # Without base_url
            >>> backend = LocalStorage('/var/www/static')
            >>> url = backend.url('css/style.css')
            >>> print(url)
            None
        """
        if self._base_url is None:
            return None

        # Normalize base_url (ensure no trailing slash)
        base = self._base_url.rstrip("/")

        # Normalize path (ensure leading slash removed)
        normalized_path = path.lstrip("/")

        # Combine with /
        return f"{base}/{normalized_path}"

    def resolved_path(self, path: str) -> str:
        """Get resolved absolute filesystem path.

        Returns the absolute filesystem path for the given relative path.

        Args:
            path: Relative path within this storage

        Returns:
            str: Absolute filesystem path

        Examples:
            >>> backend = LocalStorage('/var/www/static')
            >>> abs_path = backend.resolved_path('css/style.css')
            >>> print(abs_path)
            '/var/www/static/css/style.css'

        Notes:
            - Path may not exist yet (e.g., for write operations)
            - Always returns a string (never None) for local storage
            - Handles callable paths and routing correctly
        """
        resolved = self._resolve_path(path)
        return str(resolved)

    def local_path(self, path: str, mode: str = "r"):
        """Get local filesystem path (returns the actual path).

        For local storage, this simply returns the actual filesystem path
        since the file is already local. No temporary copy is needed.

        Args:
            path: Relative path to file
            mode: Access mode (ignored for local storage)

        Returns:
            Context manager yielding str (the actual filesystem path)

        Examples:
            >>> with backend.local_path('video.mp4') as local_path:
            ...     subprocess.run(['ffmpeg', '-i', local_path, 'out.mp4'])
        """
        from contextlib import contextmanager

        @contextmanager
        def _local_path():
            full_path = self._resolve_path(path)
            yield str(full_path)

        return _local_path()

    def __repr__(self) -> str:
        """String representation."""
        return f"LocalStorage('{self.base_path}')"
