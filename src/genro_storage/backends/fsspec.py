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

"""Fsspec-based backend for genro-storage.

This module provides a generic backend that wraps fsspec filesystems,
allowing access to local, S3, GCS, Azure, HTTP, and other storage systems
through a unified interface.

``open`` in an ``x`` mode raises ``FileExistsError`` when the file exists, on
every fsspec filesystem. s3fs checks the exclusive create only when the file
is committed, on close, and raises ``FileExistsError`` only if the server's
412 answer names the ``If-None-Match`` condition. Servers that omit it
(RustFS 1.0.3) make s3fs raise a plain ``OSError``; ``ExclusiveCreateFile``
turns that 412 into ``FileExistsError``.

s3fs pins every binary read to the ETag found when the file is opened; if the
object is replaced before a range is fetched, the server answers 412. s3fs
raises ``FileExpired`` only when the message reads "pre-conditions", so
RustFS 1.0.3 ("preconditions") gets a plain ``OSError``. ``read_bytes``,
``read_text`` and ``local_path`` restart the read up to ``READ_ATTEMPTS``
times, so the caller receives one complete version; the last 412 raises
``StorageReadConflictError``. A file from ``open('rb')`` cannot restart data
already handed out: ``ReadConflictFile`` raises ``StorageReadConflictError``
on the read that meets the 412.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import BinaryIO, TextIO
from pathlib import PurePosixPath
import errno
import fsspec

from .base import StorageBackend
from ..capabilities import BackendCapabilities
from ..exceptions import StorageReadConflictError

READ_ATTEMPTS = 3


class ExclusiveCreateFile:
    """File object for an ``x`` mode open that reports a failed exclusive create as FileExistsError.

    Attribute access is delegated to the underlying fsspec file object.
    """

    def __init__(self, file, path: str):
        self._file = file
        self._path = path

    def __getattr__(self, name: str):
        return getattr(self._file, name)

    def __iter__(self):
        return iter(self._file)

    def __enter__(self) -> ExclusiveCreateFile:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        """Close the file; a 412 PreconditionFailed from the commit becomes FileExistsError."""
        try:
            self._file.close()
        except FileExistsError:
            raise
        except OSError as exc:
            response = getattr(exc.__cause__, "response", None) or {}
            if response.get("Error", {}).get("Code") != "PreconditionFailed":
                raise
            raise FileExistsError(errno.EEXIST, "File already exists", self._path) from exc


class ReadConflictFile:
    """File object for an ``rb`` open that reports a replaced object as StorageReadConflictError.

    Attribute access is delegated to the underlying fsspec file object.
    """

    def __init__(self, file, path: str, backend: FsspecBackend):
        self._file = file
        self._path = path
        self.backend = backend

    def __getattr__(self, name: str):
        return getattr(self._file, name)

    def __enter__(self) -> ReadConflictFile:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._file.close()

    def __iter__(self) -> ReadConflictFile:
        return self

    def __next__(self) -> bytes:
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def read(self, *args) -> bytes:
        with self.backend.read_conflict_as_storage_error(self._path):
            return self._file.read(*args)

    def readinto(self, buffer) -> int:
        with self.backend.read_conflict_as_storage_error(self._path):
            return self._file.readinto(buffer)

    def readline(self, *args) -> bytes:
        with self.backend.read_conflict_as_storage_error(self._path):
            return self._file.readline(*args)

    def readlines(self, *args) -> list[bytes]:
        with self.backend.read_conflict_as_storage_error(self._path):
            return self._file.readlines(*args)


class FsspecBackend(StorageBackend):
    """Generic backend that wraps any fsspec filesystem.

    This backend provides a unified interface to any fsspec-compatible
    filesystem, including:
    - Local filesystem (file://)
    - Amazon S3 (s3://)
    - Google Cloud Storage (gcs://)
    - Azure Blob Storage (az://)
    - HTTP/HTTPS (http://, https://)
    - In-memory (memory://)
    - And many more...

    Args:
        protocol: Fsspec protocol (e.g., 'file', 's3', 'gcs', 'memory')
        base_path: Base path within the filesystem (optional)
        **kwargs: Additional arguments passed to fsspec.filesystem()

    Examples:
        >>> # Local filesystem
        >>> backend = FsspecBackend('file', base_path='/home/user')
        >>>
        >>> # S3
        >>> backend = FsspecBackend('s3', base_path='my-bucket/uploads',
        ...                         anon=False, region='eu-west-1')
        >>>
        >>> # Memory (for testing)
        >>> backend = FsspecBackend('memory', base_path='/test')
    """

    def __init__(self, protocol: str, base_path: str = "", **kwargs):
        """Initialize FsspecBackend.

        Args:
            protocol: Fsspec protocol name
            base_path: Base path prefix for all operations
            **kwargs: Additional arguments for fsspec.filesystem()
        """
        self.protocol = protocol
        self.base_path = base_path.rstrip("/")
        self.fs_kwargs = kwargs

        # For S3, enable version awareness to support versioning
        if protocol == "s3":
            kwargs.setdefault("version_aware", True)

        # Create fsspec filesystem instance
        self.fs = fsspec.filesystem(protocol, **kwargs)

    def _full_path(self, path: str) -> str:
        """Combine base_path with relative path.

        Args:
            path: Relative path

        Returns:
            str: Full path including base_path
        """
        if not path:
            return self.base_path or "/"

        if self.base_path:
            # Normalize path separators
            clean_path = path.lstrip("/")
            return f"{self.base_path}/{clean_path}"

        return path

    @property
    def capabilities(self) -> BackendCapabilities:
        """Return capabilities based on fsspec protocol.

        Different protocols have different capabilities. This method returns
        the appropriate capabilities for each protocol type.

        Returns:
            BackendCapabilities: Capabilities specific to this protocol
        """
        protocol = self.protocol.lower()

        # S3 capabilities
        if protocol == "s3":
            # Check if versioning is available
            has_versioning = self._check_s3_versioning()

            return BackendCapabilities(
                read=True,
                write=True,
                delete=True,
                mkdir=True,
                list_dir=True,
                # Versioning (if enabled on bucket)
                versioning=has_versioning,
                version_listing=has_versioning,
                version_access=has_versioning,
                # S3 metadata
                metadata=True,
                # S3 URLs
                presigned_urls=True,
                public_urls=True,
                # Advanced
                atomic_operations=True,  # S3 PUT is atomic
                symbolic_links=False,
                copy_optimization=True,  # Server-side copy
                hash_on_metadata=True,  # ETag = MD5
                # Performance
                append_mode=False,  # S3 doesn't support append
                seek_support=True,
                readonly=False,
                temporary=False,
            )

        # GCS capabilities
        elif protocol in ("gcs", "gs"):
            return BackendCapabilities(
                read=True,
                write=True,
                delete=True,
                mkdir=True,
                list_dir=True,
                # GCS has different versioning model
                versioning=False,
                version_listing=False,
                version_access=False,
                metadata=True,
                presigned_urls=True,
                public_urls=True,
                atomic_operations=True,
                symbolic_links=False,
                copy_optimization=True,
                hash_on_metadata=True,  # GCS provides MD5
                append_mode=False,
                seek_support=True,
                readonly=False,
                temporary=False,
            )

        # Azure Blob Storage
        elif protocol in ("az", "abfs", "azure"):
            return BackendCapabilities(
                read=True,
                write=True,
                delete=True,
                mkdir=True,
                list_dir=True,
                versioning=False,
                metadata=True,
                presigned_urls=True,
                public_urls=True,
                atomic_operations=True,
                symbolic_links=False,
                copy_optimization=True,
                hash_on_metadata=True,
                append_mode=True,  # Azure supports append blobs
                seek_support=True,
                readonly=False,
                temporary=False,
            )

        # HTTP/HTTPS (read-only)
        elif protocol in ("http", "https"):
            return BackendCapabilities(
                read=True,
                write=False,
                delete=False,
                mkdir=False,
                list_dir=False,
                versioning=False,
                metadata=False,
                presigned_urls=False,
                public_urls=True,
                atomic_operations=False,
                symbolic_links=False,
                copy_optimization=False,
                hash_on_metadata=False,
                append_mode=False,
                seek_support=True,  # Via range requests
                readonly=True,
                temporary=False,
            )

        # FTP/SFTP
        elif protocol in ("ftp", "sftp"):
            return BackendCapabilities(
                read=True,
                write=True,
                delete=True,
                mkdir=True,
                list_dir=True,
                versioning=False,
                metadata=False,
                presigned_urls=False,
                public_urls=False,
                atomic_operations=False,
                symbolic_links=False,
                copy_optimization=False,
                hash_on_metadata=False,
                append_mode=True,
                seek_support=True,
                readonly=False,
                temporary=False,
            )

        # SMB/CIFS
        elif protocol == "smb":
            return BackendCapabilities(
                read=True,
                write=True,
                delete=True,
                mkdir=True,
                list_dir=True,
                versioning=False,
                metadata=False,
                presigned_urls=False,
                public_urls=False,
                atomic_operations=False,
                symbolic_links=False,
                copy_optimization=False,
                hash_on_metadata=False,
                append_mode=True,
                seek_support=True,
                readonly=False,
                temporary=False,
            )

        # ZIP archives
        elif protocol == "zip":
            return BackendCapabilities(
                read=True,
                write=True,  # ZIP supports write/append
                delete=True,
                mkdir=True,
                list_dir=True,
                versioning=False,
                metadata=False,
                presigned_urls=False,
                public_urls=False,
                atomic_operations=False,
                symbolic_links=False,
                copy_optimization=False,
                hash_on_metadata=False,
                append_mode=False,  # Must rewrite entire archive
                seek_support=True,
                readonly=False,
                temporary=False,
            )

        # TAR archives
        elif protocol == "tar":
            return BackendCapabilities(
                read=True,
                write=False,  # TAR is read-only in fsspec
                delete=False,
                mkdir=False,
                list_dir=True,
                versioning=False,
                metadata=False,
                presigned_urls=False,
                public_urls=False,
                atomic_operations=False,
                symbolic_links=False,
                copy_optimization=False,
                hash_on_metadata=False,
                append_mode=False,
                seek_support=True,
                readonly=True,  # TAR is read-only
                temporary=False,
            )

        # Memory filesystem (testing)
        elif protocol == "memory":
            return BackendCapabilities(
                read=True,
                write=True,
                delete=True,
                mkdir=True,
                list_dir=True,
                versioning=False,
                metadata=False,
                presigned_urls=False,
                public_urls=False,
                atomic_operations=True,
                symbolic_links=False,
                copy_optimization=True,
                hash_on_metadata=False,
                append_mode=True,
                seek_support=True,
                readonly=False,
                temporary=True,  # Ephemeral!
            )

        # Git local repositories (read-only)
        elif protocol == "git":
            return BackendCapabilities(
                read=True,
                write=False,  # Git is read-only
                delete=False,
                mkdir=False,
                list_dir=True,
                versioning=True,  # Access any commit/tag/branch
                version_listing=False,  # Can't list all versions
                version_access=True,  # Can access specific versions via ref
                metadata=False,
                presigned_urls=False,
                public_urls=False,
                atomic_operations=False,
                symbolic_links=False,
                copy_optimization=False,
                hash_on_metadata=False,
                append_mode=False,
                seek_support=True,
                readonly=True,
                temporary=False,
            )

        # GitHub repositories (read-only, remote)
        elif protocol == "github":
            return BackendCapabilities(
                read=True,
                write=False,  # GitHub is read-only via API
                delete=False,
                mkdir=False,
                list_dir=True,
                versioning=True,  # Access any commit/tag/branch
                version_listing=False,
                version_access=True,  # Can access specific versions via sha
                metadata=False,
                presigned_urls=False,
                public_urls=True,  # GitHub URLs are public
                atomic_operations=False,
                symbolic_links=False,
                copy_optimization=False,
                hash_on_metadata=False,
                append_mode=False,
                seek_support=True,
                readonly=True,
                temporary=False,
            )

        # WebDAV (Nextcloud, ownCloud, SharePoint)
        elif protocol == "webdav":
            return BackendCapabilities(
                read=True,
                write=True,
                delete=True,
                mkdir=True,
                list_dir=True,
                versioning=False,  # Depends on server
                metadata=False,
                presigned_urls=False,
                public_urls=False,
                atomic_operations=False,
                symbolic_links=False,
                copy_optimization=False,
                hash_on_metadata=False,
                append_mode=True,
                seek_support=True,
                readonly=False,
                temporary=False,
            )

        # LibArchive (universal archive support: 7z, rar, iso, etc.)
        elif protocol == "libarchive":
            return BackendCapabilities(
                read=True,
                write=False,  # LibArchive is read-only
                delete=False,
                mkdir=False,
                list_dir=True,
                versioning=False,
                metadata=False,
                presigned_urls=False,
                public_urls=False,
                atomic_operations=False,
                symbolic_links=False,
                copy_optimization=False,
                hash_on_metadata=False,
                append_mode=False,
                seek_support=True,
                readonly=True,
                temporary=False,
            )

        # Default for unknown protocols (conservative)
        else:
            return BackendCapabilities(
                read=True,
                write=True,
                delete=True,
                mkdir=True,
                list_dir=True,
                versioning=False,
                metadata=False,
                presigned_urls=False,
                public_urls=False,
                atomic_operations=True,
                symbolic_links=False,
                copy_optimization=False,
                hash_on_metadata=False,
                append_mode=True,
                seek_support=True,
                readonly=False,
                temporary=False,
            )

    def _check_s3_versioning(self) -> bool:
        """Check if S3 bucket has versioning enabled.

        Returns:
            bool: True if versioning is available
        """
        try:
            # Check if s3fs supports versioning methods and the mount enables them
            return hasattr(self.fs, "object_version_info") and self.fs.version_aware
        except Exception:
            return False

    def exists(self, path: str) -> bool:
        """Check if file or directory exists."""
        full_path = self._full_path(path)
        return self.fs.exists(full_path)

    def is_file(self, path: str) -> bool:
        """Check if path points to a file."""
        full_path = self._full_path(path)
        try:
            info = self.fs.info(full_path)
            return info["type"] == "file"
        except FileNotFoundError:
            return False

    def is_dir(self, path: str) -> bool:
        """Check if path points to a directory."""
        full_path = self._full_path(path)
        try:
            info = self.fs.info(full_path)
            return info["type"] == "directory"
        except FileNotFoundError:
            return False

    def size(self, path: str) -> int:
        """Get file size in bytes."""
        full_path = self._full_path(path)

        info = self.fs.info(full_path)

        if info["type"] != "file":
            raise ValueError(f"Path is a directory, not a file: {path}")

        return info.get("size", 0)

    def mtime(self, path: str) -> float:
        """Get last modification time."""
        full_path = self._full_path(path)

        info = self.fs.info(full_path)

        return self._mtime_from_info(info)

    @staticmethod
    def _mtime_from_info(info: dict) -> float:
        # fsspec may return 'mtime' or 'LastModified' depending on backend
        if "mtime" in info:
            return info["mtime"]
        elif "LastModified" in info:
            # S3-style timestamp
            import datetime

            dt = info["LastModified"]
            if isinstance(dt, datetime.datetime):
                return dt.timestamp()

        # Fallback: return current time
        import time

        return time.time()

    def ext_attributes(self, path: str) -> tuple[float | None, int | None, bool]:
        """Read one metadata snapshot, without retaining a new client cache."""
        try:
            info = self.fs.info(self._full_path(path))
        except FileNotFoundError:
            return None, None, False
        is_directory = info["type"] == "directory"
        # An S3 prefix has no modification timestamp. Match the legacy tuple
        # instead of manufacturing a different timestamp on every call.
        mtime = None if self.protocol == "s3" and is_directory else self._mtime_from_info(info)
        size = None if is_directory else info.get("size", 0)
        return mtime, size, is_directory

    def open(self, path: str, mode: str = "rb") -> BinaryIO | TextIO:
        """Open file and return file-like object."""
        full_path = self._full_path(path)
        file = self.fs.open(full_path, mode)
        if "x" in mode:
            return ExclusiveCreateFile(file, path)
        if "r" in mode and "b" in mode:
            return ReadConflictFile(file, path, self)
        return file

    def read_bytes(self, path: str) -> bytes:
        """Read entire file as bytes."""
        return self._read_with_restart(path, "rb", lambda f: f.read())

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        """Read entire file as text."""
        return self._read_with_restart(path, "r", lambda f: f.read(), encoding=encoding)

    def _read_with_restart(self, path: str, mode: str, consume, **open_kwargs):
        """Open path and return consume(file), restarting when the object is replaced.

        The first READ_ATTEMPTS - 1 replacements restart the read from the new
        version; the last one raises StorageReadConflictError.
        """
        full_path = self._full_path(path)
        for _ in range(READ_ATTEMPTS - 1):
            try:
                with self.fs.open(full_path, mode, **open_kwargs) as f:
                    return consume(f)
            except OSError as exc:
                if not self._is_precondition_failed(exc):
                    raise
        with self.read_conflict_as_storage_error(path):
            with self.fs.open(full_path, mode, **open_kwargs) as f:
                return consume(f)

    @contextmanager
    def read_conflict_as_storage_error(self, path: str):
        """Raise StorageReadConflictError for a 412 PreconditionFailed met inside the block."""
        try:
            yield
        except OSError as exc:
            if not self._is_precondition_failed(exc):
                raise
            raise StorageReadConflictError(f"Object replaced during the read: {path}") from exc

    def _is_precondition_failed(self, exc: OSError) -> bool:
        """True when exc comes from a 412 PreconditionFailed answer of the server."""
        cause = exc.__cause__
        while cause is not None:
            response = getattr(cause, "response", None)
            if response is not None:
                return response.get("Error", {}).get("Code") == "PreconditionFailed"
            cause = cause.__cause__
        return False

    def write_bytes(self, path: str, data: bytes) -> None:
        """Write bytes to file."""
        full_path = self._full_path(path)

        with self.fs.open(full_path, "wb") as f:
            f.write(data)

    def write_text(self, path: str, text: str, encoding: str = "utf-8") -> None:
        """Write text to file."""
        full_path = self._full_path(path)

        with self.fs.open(full_path, "w", encoding=encoding) as f:
            f.write(text)

    def delete(self, path: str, recursive: bool = False) -> None:
        """Delete file or directory."""
        full_path = self._full_path(path)

        if not self.fs.exists(full_path):
            # Idempotent
            return

        # fsspec's rm handles both files and directories
        self.fs.rm(full_path, recursive=recursive)

    def list_dir(self, path: str) -> list[str]:
        """List directory contents."""
        full_path = self._full_path(path)

        # Get all items in directory
        items = self.fs.ls(full_path, detail=False)

        # Extract just the names (not full paths)
        base = full_path.rstrip("/") + "/"
        names = []
        for item in items:
            if item.startswith(base):
                name = item[len(base) :]
                # Only direct children (no nested paths)
                if "/" not in name:
                    names.append(name)
            else:
                # Fallback: use basename
                names.append(item.split("/")[-1])

        return names

    def mkdir(self, path: str, parents: bool = False, exist_ok: bool = False) -> None:
        """Create directory."""
        full_path = self._full_path(path)

        if self.fs.exists(full_path):
            if not exist_ok:
                raise FileExistsError(f"Directory already exists: {path}")
            return

        # fsspec's makedirs handles parent creation
        if parents:
            self.fs.makedirs(full_path, exist_ok=True)
        else:
            # Check parent exists. The mount root is not a directory entry on
            # every backend (memory has none), so it is never validated here.
            parent = str(PurePosixPath(full_path).parent)
            if parent not in ("", ".", "/") and not self.fs.exists(parent):
                raise FileNotFoundError(f"Parent directory does not exist: {parent}")

            self.fs.mkdir(full_path)

    def copy(self, src_path: str, dest_backend: StorageBackend, dest_path: str) -> str | None:
        """Copy file/directory to another backend."""
        src_full = self._full_path(src_path)

        # Check if both are fsspec backends
        if isinstance(dest_backend, FsspecBackend):
            dest_full = dest_backend._full_path(dest_path)

            # Use fsspec's copy if same filesystem
            if self.fs == dest_backend.fs:
                self.fs.copy(src_full, dest_full, recursive=True)
                return None

        # Fallback: copy via read/write
        info = self.fs.info(src_full)

        if info["type"] == "file":
            # Copy single file
            data = self.read_bytes(src_path)
            result = dest_backend.write_bytes(dest_path, data)
            return result  # Return new path if dest backend changed it

        elif info["type"] == "directory":
            # Copy directory recursively
            dest_backend.mkdir(dest_path, parents=True, exist_ok=True)

            for item in self.fs.ls(src_full, detail=True):
                item_name = item["name"].split("/")[-1]

                if item["type"] == "file":
                    src_item = f"{src_path}/{item_name}" if src_path else item_name
                    dest_item = f"{dest_path}/{item_name}" if dest_path else item_name
                    self.copy(src_item, dest_backend, dest_item)
                elif item["type"] == "directory":
                    src_item = f"{src_path}/{item_name}" if src_path else item_name
                    dest_item = f"{dest_path}/{item_name}" if dest_path else item_name
                    self.copy(src_item, dest_backend, dest_item)

    def get_versions(self, path: str) -> list[dict]:
        """Get list of available versions for a file.

        Returns version history for versioned storage (S3 with versioning enabled).
        For non-versioned storage, returns empty list.

        Args:
            path: Relative path to file

        Returns:
            list[dict]: List of version info dicts with keys:
                - version_id: Version identifier
                - is_latest: True if this is the current version
                - last_modified: Modification timestamp
                - size: File size in bytes

        Examples:
            >>> versions = backend.get_versions('document.pdf')
            >>> for v in versions:
            ...     print(f"Version {v['version_id']}: {v['last_modified']}")

        Notes:
            - Only S3 with versioning enabled returns versions
            - GCS and Azure have different versioning models
            - Empty list if versioning not enabled or not supported
        """
        full_path = self._full_path(path)

        # S3: Get version history
        if self.protocol == "s3":
            if hasattr(self.fs, "object_version_info"):
                try:
                    versions_info = self.fs.object_version_info(full_path)
                    # Convert to normalized format
                    versions_list = [
                        {
                            "version_id": v.get("VersionId"),
                            "is_latest": v.get("IsLatest", False),
                            "last_modified": v.get("LastModified"),
                            "size": v.get("Size", 0),
                            "etag": v.get("ETag", "").strip(
                                '"'
                            ),  # S3 ETag (MD5 for simple uploads)
                        }
                        for v in versions_info
                    ]
                    # Sort by timestamp (oldest first) for Python-style negative indexing
                    # where -1 = latest version, -len = oldest version
                    versions_list.sort(key=lambda v: v["last_modified"])
                    return versions_list
                except Exception:
                    # Versioning not enabled or error
                    return []
            else:
                return []

        # Other protocols: no versioning
        return []

    def open_version(self, path: str, version_id: str, mode: str = "rb"):
        """Open a specific version of a file.

        Opens a historical version of a file from versioned storage.
        Only works with S3 when versioning is enabled.

        Args:
            path: Relative path to file
            version_id: Version identifier to open
            mode: Open mode (read modes only)

        Returns:
            File-like object

        Raises:
            ValueError: If mode is not read-only
            PermissionError: If versioning not supported
            FileNotFoundError: If version doesn't exist

        Examples:
            >>> # Open specific version
            >>> with backend.open_version('file.txt', 'xyz123') as f:
            ...     old_content = f.read()
        """
        if "w" in mode or "a" in mode or "+" in mode:
            raise ValueError("Cannot write to historical versions (read-only)")

        full_path = self._full_path(path)

        # S3: Open specific version
        if self.protocol == "s3":
            if hasattr(self.fs, "open"):
                return self.fs.open(full_path, mode, version_id=version_id)
            else:
                raise PermissionError("S3 versioning not available")

        # Other protocols: not supported
        raise PermissionError(f"{self.protocol} backend does not support versioning")

    def delete_version(self, path: str, version_id: str) -> None:
        """Delete a specific version of a file.

        Removes a specific version from S3 versioned storage. The current version
        and other versions remain unaffected.

        Args:
            path: Relative path to file
            version_id: Version identifier to delete

        Raises:
            PermissionError: If versioning not supported
            FileNotFoundError: If version doesn't exist
            Exception: If S3 deletion fails

        Examples:
            >>> # Delete a specific version
            >>> backend.delete_version('file.txt', 'abc123xyz')
        """
        full_path = self._full_path(path)

        # S3: Delete specific version
        if self.protocol == "s3":
            try:
                # Create a synchronous boto3 client from stored configuration
                import boto3

                # Extract bucket and key from full_path (format: bucket/key)
                parts = full_path.split("/", 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 else ""

                # Build boto3 client kwargs from stored fs_kwargs
                client_kwargs = {}

                # Map s3fs parameter names to boto3 parameter names
                if "key" in self.fs_kwargs:
                    client_kwargs["aws_access_key_id"] = self.fs_kwargs["key"]
                if "secret" in self.fs_kwargs:
                    client_kwargs["aws_secret_access_key"] = self.fs_kwargs["secret"]
                if "token" in self.fs_kwargs:
                    client_kwargs["aws_session_token"] = self.fs_kwargs["token"]
                if "endpoint_url" in self.fs_kwargs:
                    client_kwargs["endpoint_url"] = self.fs_kwargs["endpoint_url"]
                if "region_name" in self.fs_kwargs:
                    client_kwargs["region_name"] = self.fs_kwargs["region_name"]

                # Create sync boto3 client
                s3_client = boto3.client("s3", **client_kwargs)

                # Delete the specific version
                s3_client.delete_object(Bucket=bucket, Key=key, VersionId=version_id)
            except Exception as e:
                # Re-raise with more context if it's a known error type
                error_str = str(e)
                if "NoSuchKey" in error_str or "NoSuchVersion" in error_str:
                    raise FileNotFoundError(f"Version {version_id} not found for {path}") from e
                raise

        # Other protocols: not supported
        else:
            raise PermissionError(f"{self.protocol} backend does not support version deletion")

    def get_hash(self, path: str) -> str | None:
        """Get MD5 hash from filesystem metadata if available.

        For S3/MinIO: Uses ETag which is the MD5 hash
        For GCS: Also uses ETag
        For Azure: Uses content_md5
        For local/memory: Returns None (must compute)

        Args:
            path: Relative path to file

        Returns:
            str | None: MD5 hash as hexadecimal string, or None if not in metadata
        """
        full_path = self._full_path(path)

        try:
            info = self.fs.info(full_path)
        except FileNotFoundError:
            return None

        # S3/MinIO/GCS: ETag is MD5 (wrapped in quotes)
        if "ETag" in info:
            return info["ETag"].strip('"')

        # Azure Blob Storage: content_md5
        if "content_md5" in info:
            return info["content_md5"]

        # No hash available in metadata
        return None

    def get_metadata(self, path: str) -> dict[str, str]:
        """Get custom metadata for a file.

        Retrieves user-defined metadata from cloud storage. Different storage
        backends store metadata in different ways:
        - S3: Uses 'Metadata' field
        - GCS: Uses 'metadata' field
        - Azure: Uses 'metadata' field

        Args:
            path: Relative path to file

        Returns:
            dict[str, str]: Metadata key-value pairs

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        full_path = self._full_path(path)

        try:
            info = self.fs.info(full_path)
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {path}")

        # Extract metadata based on protocol
        if self.protocol == "s3":
            # S3: metadata in 'Metadata' field (case-sensitive)
            return info.get("Metadata", {})
        elif self.protocol in ("gcs", "gs"):
            # GCS: metadata in 'metadata' field
            return info.get("metadata", {})
        elif self.protocol in ("azure", "az", "adl"):
            # Azure: metadata in 'metadata' field
            return info.get("metadata", {})
        else:
            # Other protocols: no metadata support
            return {}

    def set_metadata(self, path: str, metadata: dict[str, str]) -> None:
        """Set custom metadata for a file.

        Stores user-defined metadata with the file in cloud storage.

        Args:
            path: Relative path to file
            metadata: Metadata key-value pairs to set

        Raises:
            FileNotFoundError: If file doesn't exist
            PermissionError: If backend doesn't support metadata
            ValueError: If metadata keys/values are invalid

        Notes:
            - For S3: Replaces all existing metadata
            - For GCS/Azure: Similar behavior
            - Some backends have key/value restrictions
        """
        full_path = self._full_path(path)

        # Check file exists
        if not self.fs.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")

        # Validate metadata
        if not isinstance(metadata, dict):
            raise ValueError("Metadata must be a dictionary")

        for key, value in metadata.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("Metadata keys and values must be strings")

        # Set metadata based on protocol
        if self.protocol == "s3":
            # S3: Use setxattr or update_metadata if available
            if hasattr(self.fs, "setxattr"):
                for key, value in metadata.items():
                    self.fs.setxattr(full_path, key, value)
            else:
                raise PermissionError(
                    "S3 metadata update not available in this fsspec version. "
                    "Consider using boto3 directly for metadata operations."
                )

        elif self.protocol in ("gcs", "gs"):
            # GCS: Use setxattr if available
            if hasattr(self.fs, "setxattr"):
                for key, value in metadata.items():
                    self.fs.setxattr(full_path, key, value)
            else:
                raise PermissionError("GCS metadata update not available")

        elif self.protocol in ("azure", "az", "adl"):
            # Azure: Use setxattr if available
            if hasattr(self.fs, "setxattr"):
                for key, value in metadata.items():
                    self.fs.setxattr(full_path, key, value)
            else:
                raise PermissionError("Azure metadata update not available")

        else:
            # Other protocols don't support metadata
            raise PermissionError(f"{self.protocol} backend does not support metadata operations")

    def url(self, path: str, expires_in: int = 3600, **kwargs) -> str | None:
        """Generate public URL for file access.

        For S3: Generates presigned URL
        For GCS: Generates signed URL
        For HTTP: Returns direct URL
        For others: Returns None

        Args:
            path: Relative path to file
            expires_in: URL expiration time in seconds
            **kwargs: Backend-specific options

        Returns:
            str | None: Public URL or None if not supported
        """
        full_path = self._full_path(path)

        # S3: Generate presigned URL
        if self.protocol == "s3":
            if hasattr(self.fs, "sign"):
                # s3fs supports signing
                return self.fs.sign(full_path, expiration=expires_in)
            else:
                # Fallback: no presigned URL support
                return None

        # HTTP: Return direct URL
        elif self.protocol in ("http", "https"):
            # For HTTP, the path IS the URL
            return full_path

        # GCS: Generate signed URL
        elif self.protocol in ("gcs", "gs"):
            if hasattr(self.fs, "sign"):
                return self.fs.sign(full_path, expiration=expires_in)
            else:
                return None

        # Other protocols: no URL support
        else:
            return None

    def internal_url(self, path: str, nocache: bool = False) -> str | None:
        """Generate internal/relative URL for file access.

        This is a simplified version that returns a path-based URL.
        Applications should override this with their own URL generation logic.

        Args:
            path: Relative path to file
            nocache: If True, append mtime as query parameter

        Returns:
            str | None: Internal URL or None
        """
        # For cloud storage, we don't have an "internal" URL concept
        # Applications would typically use their own URL routing
        # Return None by default
        return None

    def local_path(self, path: str, mode: str = "r"):
        """Get local filesystem path for remote file.

        Downloads the file to a temporary location, yields the local path,
        and uploads changes back on exit if the file was modified.

        This allows external tools (ffmpeg, imagemagick, etc.) to work
        with remote files transparently.

        Args:
            path: Relative path to file
            mode: Access mode - 'r' (read), 'w' (write), 'rw' (read-write)

        Returns:
            Context manager yielding str (local temp file path)

        Examples:
            >>> # Process remote S3 file with ffmpeg
            >>> with backend.local_path('video.mp4', mode='r') as local_path:
            ...     subprocess.run(['ffmpeg', '-i', local_path, 'output.mp4'])
            >>>
            >>> # Modify remote file in place
            >>> with backend.local_path('image.jpg', mode='rw') as local_path:
            ...     subprocess.run(['convert', local_path, '-resize', '800', local_path])
            >>> # Changes uploaded automatically
        """
        import tempfile
        import os
        from contextlib import contextmanager

        @contextmanager
        def _local_path():
            full_path = self._full_path(path)

            # Create temporary file
            suffix = os.path.splitext(path)[1]  # Preserve extension
            with tempfile.NamedTemporaryFile(mode="w+b", suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name

            try:
                # Download file if reading
                if mode in ("r", "rw"):
                    if self.fs.exists(full_path):
                        # Download from remote to temp; a restart rewrites the temp file
                        def download(remote_file):
                            with open(tmp_path, "wb") as local_file:
                                # Stream in chunks to handle large files
                                chunk_size = 8 * 1024 * 1024  # 8MB chunks
                                while True:
                                    chunk = remote_file.read(chunk_size)
                                    if not chunk:
                                        break
                                    local_file.write(chunk)

                        self._read_with_restart(path, "rb", download)
                    elif mode == "rw":
                        # File doesn't exist but mode is rw - create empty
                        pass

                # Yield temp path for user to work with
                yield tmp_path

                # Upload file if writing
                if mode in ("w", "rw"):
                    # Upload from temp to remote
                    if os.path.exists(tmp_path):
                        # Ensure parent directory exists
                        parent = str(PurePosixPath(full_path).parent)
                        if parent and parent != ".":
                            self.fs.makedirs(parent, exist_ok=True)

                        # Upload
                        with open(tmp_path, "rb") as local_file:
                            with self.fs.open(full_path, "wb") as remote_file:
                                # Stream in chunks
                                chunk_size = 8 * 1024 * 1024  # 8MB chunks
                                while True:
                                    chunk = local_file.read(chunk_size)
                                    if not chunk:
                                        break
                                    remote_file.write(chunk)

            finally:
                # Always cleanup temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        return _local_path()

    def close(self) -> None:
        """Close filesystem connection if needed."""
        # Most fsspec filesystems don't need explicit closing
        # but S3 and others might have session cleanup
        if hasattr(self.fs, "close"):
            self.fs.close()

    def __repr__(self) -> str:
        """String representation."""
        return f"FsspecBackend(protocol='{self.protocol}', base_path='{self.base_path}')"
