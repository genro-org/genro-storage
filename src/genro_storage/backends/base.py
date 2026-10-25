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

"""Base backend interface for genro-storage.

This module defines the abstract base class that all storage backends
must implement. It provides the contract for file operations across
different storage systems.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO, TextIO

from ..capabilities import BackendCapabilities


class StorageBackend(ABC):
    """Abstract base class for storage backends.

    All storage backend implementations (Local, S3, GCS, Azure, HTTP, etc.)
    must inherit from this class and implement all abstract methods.

    This ensures a consistent interface across all storage types and makes
    it easy to add new backends in the future.

    Note:
        Backend implementations should not be instantiated directly by users.
        They are created internally by StorageManager based on configuration.

    Capability System:
        Capabilities are automatically derived from methods decorated with @capability.
        The decorator populates the _capabilities set during class definition,
        and __init_subclass__ ensures proper inheritance.
    """

    # Class variable: maps protocol → set of capabilities
    # Populated automatically by @capability decorator or declared manually
    PROTOCOL_CAPABILITIES: dict[str, set[str]] = {}

    def __init_subclass__(cls, **kwargs):
        """Automatically collect and inherit capabilities when subclass is created.

        This method is called when a subclass of StorageBackend is defined.
        It collects PROTOCOL_CAPABILITIES from parent classes and merges them.
        """
        super().__init_subclass__(**kwargs)

        # Collect capabilities from all parent classes
        inherited_caps = {}
        for base in cls.__mro__[1:]:  # Skip cls itself
            if hasattr(base, "PROTOCOL_CAPABILITIES"):
                for protocol, caps in base.PROTOCOL_CAPABILITIES.items():
                    if protocol not in inherited_caps:
                        inherited_caps[protocol] = set()
                    inherited_caps[protocol].update(caps)

        # Get capabilities defined in this class (added by @capability decorator)
        own_caps = cls.__dict__.get("PROTOCOL_CAPABILITIES", {})

        # Merge inherited and own capabilities
        all_caps = inherited_caps.copy()
        for protocol, caps in own_caps.items():
            if protocol not in all_caps:
                all_caps[protocol] = set()
            all_caps[protocol].update(caps)

        cls.PROTOCOL_CAPABILITIES = all_caps

    @classmethod
    def get_capabilities(cls, protocol: str | None = None) -> set[str]:
        """Get capability set for a given protocol.

        For single-protocol backends (LocalStorage, Base64Backend), protocol
        parameter is optional and defaults to the backend's only protocol.
        For multi-protocol backends (FsspecBackend), protocol must be specified.

        Args:
            protocol: Protocol name (e.g., 's3', 'gcs', 'local', 'base64')
                     If None, returns capabilities for the only available protocol

        Returns:
            set: Set of capability names

        Examples:
            >>> # Single-protocol backend
            >>> LocalStorage.get_capabilities()  # protocol auto-detected
            {'read', 'write', 'delete', 'mkdir', ...}

            >>> # Multi-protocol backend
            >>> FsspecBackend.get_capabilities('s3')
            {'read', 'write', 'metadata', 'presigned_urls', ...}
        """
        if protocol is None:
            # Auto-detect for single-protocol backends
            if len(cls.PROTOCOL_CAPABILITIES) == 1:
                protocol = list(cls.PROTOCOL_CAPABILITIES.keys())[0]
            else:
                raise ValueError(
                    f"{cls.__name__} supports multiple protocols. "
                    f"Please specify protocol parameter. "
                    f"Available: {list(cls.PROTOCOL_CAPABILITIES.keys())}"
                )

        if protocol not in cls.PROTOCOL_CAPABILITIES:
            raise ValueError(
                f"Unknown protocol '{protocol}' for {cls.__name__}. "
                f"Available: {list(cls.PROTOCOL_CAPABILITIES.keys())}"
            )

        return cls.PROTOCOL_CAPABILITIES[protocol]

    @property
    def capabilities(self) -> BackendCapabilities:
        """Return the capabilities of this backend instance.

        For single-protocol backends, automatically uses the only protocol.
        For multi-protocol backends (FsspecBackend), uses self.protocol.

        Returns:
            BackendCapabilities: Object describing supported features

        Examples:
            >>> backend = LocalStorage('/tmp')
            >>> caps = backend.capabilities
            >>> if caps.versioning:
            ...     versions = backend.get_versions('file.txt')
        """
        # For multi-protocol backends, get protocol from instance
        protocol = getattr(self, "protocol", None)
        caps_set = self.get_capabilities(protocol)

        # Build kwargs dict for BackendCapabilities from the capability set
        kwargs = {}
        for field in BackendCapabilities.__dataclass_fields__:
            kwargs[field] = field in caps_set

        return BackendCapabilities(**kwargs)

    @classmethod
    def get_json_info(cls, protocol: str | None = None) -> dict:
        """Return complete backend information in JSON format.

        This classmethod can be overridden by backend subclasses to provide
        complete information including configuration schema, capabilities,
        and description. This is useful for UI generation and documentation.

        The default implementation returns capabilities derived from @capability
        decorators, but no schema information.

        Args:
            protocol: Protocol name for multi-protocol backends (optional for single-protocol)

        Returns:
            dict: Backend information with schema, capabilities, and description

        Examples:
            >>> # Single-protocol backend
            >>> info = LocalStorage.get_json_info()
            >>> print(info['schema']['fields'])
            [{'name': 'path', 'type': 'text', 'required': True}]

            >>> # Multi-protocol backend
            >>> info = FsspecBackend.get_json_info('s3')
            >>> print(info['capabilities']['metadata'])
            True
        """
        # Get capabilities for the protocol
        caps_set = cls.get_capabilities(protocol)

        # Build capabilities dict from set
        caps_dict = {}
        for field in BackendCapabilities.__dataclass_fields__:
            caps_dict[field] = field in caps_set

        # Determine backend name from protocol or class name
        if protocol:
            backend_name = protocol
        elif len(cls.PROTOCOL_CAPABILITIES) == 1:
            backend_name = list(cls.PROTOCOL_CAPABILITIES.keys())[0]
        else:
            backend_name = cls.__name__.lower().replace("backend", "").replace("storage", "")

        return {
            "backend": backend_name,
            "schema": {"fields": []},
            "capabilities": caps_dict,
            "description": "No description available",
        }

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if a file or directory exists.

        Args:
            path: Relative path within this storage backend

        Returns:
            bool: True if file or directory exists

        Examples:
            >>> exists = backend.exists('documents/report.pdf')
        """
        pass

    @abstractmethod
    def is_file(self, path: str) -> bool:
        """Check if path points to a file.

        Args:
            path: Relative path within this storage backend

        Returns:
            bool: True if path is a file, False otherwise

        Examples:
            >>> if backend.is_file('documents/report.pdf'):
            ...     print("It's a file")
        """
        pass

    @abstractmethod
    def is_dir(self, path: str) -> bool:
        """Check if path points to a directory.

        Args:
            path: Relative path within this storage backend

        Returns:
            bool: True if path is a directory, False otherwise

        Examples:
            >>> if backend.is_dir('documents'):
            ...     print("It's a directory")
        """
        pass

    @abstractmethod
    def size(self, path: str) -> int:
        """Get file size in bytes.

        Args:
            path: Relative path to file

        Returns:
            int: File size in bytes

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If path is a directory

        Examples:
            >>> size = backend.size('documents/report.pdf')
            >>> print(f"File is {size} bytes")
        """
        pass

    @abstractmethod
    def mtime(self, path: str) -> float:
        """Get last modification time.

        Args:
            path: Relative path to file or directory

        Returns:
            float: Unix timestamp of last modification

        Raises:
            FileNotFoundError: If path doesn't exist

        Examples:
            >>> from datetime import datetime
            >>> timestamp = backend.mtime('documents/report.pdf')
            >>> mod_time = datetime.fromtimestamp(timestamp)
        """
        pass

    def ext_attributes(self, path: str) -> tuple[float | None, int | None, bool]:
        """Return modification time, file size and directory status together.

        Backends may override this to fetch one metadata snapshot. The default
        preserves compatibility with backends implementing separate methods.
        """
        if not self.exists(path):
            return None, None, False
        is_directory = self.is_dir(path)
        size = None if is_directory else self.size(path)
        return self.mtime(path), size, is_directory

    @abstractmethod
    def open(self, path: str, mode: str = "rb") -> BinaryIO | TextIO:
        """Open a file and return file-like object.

        Args:
            path: Relative path to file
            mode: File mode ('r', 'rb', 'w', 'wb', 'a', 'ab', 'x', 'xb')

        Returns:
            BinaryIO | TextIO: File-like object supporting context manager

        Raises:
            FileNotFoundError: If file doesn't exist (in read mode)
            FileExistsError: If file exists (in 'x' mode); object stores
                may raise it on close, when the write is committed
            PermissionError: If insufficient permissions

        Examples:
            >>> with backend.open('file.txt', 'rb') as f:
            ...     data = f.read()
        """
        pass

    @abstractmethod
    def read_bytes(self, path: str) -> bytes:
        """Read entire file as bytes.

        Args:
            path: Relative path to file

        Returns:
            bytes: Complete file contents

        Raises:
            FileNotFoundError: If file doesn't exist

        Examples:
            >>> data = backend.read_bytes('image.jpg')
        """
        pass

    @abstractmethod
    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        """Read entire file as text.

        Args:
            path: Relative path to file
            encoding: Text encoding

        Returns:
            str: Complete file contents as string

        Raises:
            FileNotFoundError: If file doesn't exist
            UnicodeDecodeError: If encoding is incorrect

        Examples:
            >>> content = backend.read_text('document.txt')
        """
        pass

    @abstractmethod
    def write_bytes(self, path: str, data: bytes) -> None:
        """Write bytes to file.

        Args:
            path: Relative path to file
            data: Bytes to write

        Raises:
            PermissionError: If insufficient permissions
            FileNotFoundError: If parent directory doesn't exist

        Examples:
            >>> backend.write_bytes('file.bin', b'Hello')
        """
        pass

    @abstractmethod
    def write_text(self, path: str, text: str, encoding: str = "utf-8") -> None:
        """Write text to file.

        Args:
            path: Relative path to file
            text: String to write
            encoding: Text encoding

        Raises:
            PermissionError: If insufficient permissions
            FileNotFoundError: If parent directory doesn't exist

        Examples:
            >>> backend.write_text('file.txt', 'Hello World')
        """
        pass

    @abstractmethod
    def delete(self, path: str, recursive: bool = False) -> None:
        """Delete file or directory.

        Args:
            path: Relative path to delete
            recursive: If True, delete directories recursively

        Raises:
            FileNotFoundError: If path doesn't exist (implementation may choose to be idempotent)
            ValueError: If path is non-empty directory and recursive=False

        Examples:
            >>> backend.delete('file.txt')
            >>> backend.delete('folder', recursive=True)
        """
        pass

    @abstractmethod
    def list_dir(self, path: str) -> list[str]:
        """List directory contents.

        Args:
            path: Relative path to directory

        Returns:
            list[str]: List of names (not full paths) in the directory

        Raises:
            FileNotFoundError: If directory doesn't exist
            ValueError: If path is not a directory

        Examples:
            >>> names = backend.list_dir('documents')
            >>> for name in names:
            ...     print(name)  # Just 'report.pdf', not 'documents/report.pdf'
        """
        pass

    @abstractmethod
    def mkdir(self, path: str, parents: bool = False, exist_ok: bool = False) -> None:
        """Create directory.

        Args:
            path: Relative path to create
            parents: If True, create parent directories as needed
            exist_ok: If True, don't error if directory exists

        Raises:
            FileExistsError: If exists and exist_ok=False
            FileNotFoundError: If parent doesn't exist and parents=False

        Examples:
            >>> backend.mkdir('new_folder')
            >>> backend.mkdir('a/b/c', parents=True)
        """
        pass

    @abstractmethod
    def copy(self, src_path: str, dest_backend: "StorageBackend", dest_path: str) -> str | None:
        """Copy file/directory to another backend.

        This method handles cross-backend copying efficiently, streaming
        data when possible to avoid loading large files in memory.

        Args:
            src_path: Source path in this backend
            dest_backend: Destination backend (may be different type)
            dest_path: Destination path in dest_backend

        Returns:
            str | None: New destination path if destination backend changes it
                       (e.g., base64 backend), or None if path unchanged

        Raises:
            FileNotFoundError: If source doesn't exist
            PermissionError: If insufficient permissions

        Examples:
            >>> # Copy within same backend
            >>> backend.copy('file.txt', backend, 'backup/file.txt')
            >>>
            >>> # Copy to different backend
            >>> backend.copy('file.txt', other_backend, 'file.txt')
        """
        pass

    def get_hash(self, path: str) -> str | None:
        """Get MD5 hash from filesystem metadata if available.

        This method attempts to retrieve the MD5 hash from the storage
        backend's metadata without reading the file content. For cloud
        storage like S3, this uses the ETag. For local storage, this
        returns None and the hash must be computed by reading the file.

        Args:
            path: Relative path to file

        Returns:
            str | None: MD5 hash as hexadecimal string, or None if not available

        Examples:
            >>> hash_value = backend.get_hash('file.txt')
            >>> if hash_value:
            ...     print(f"MD5: {hash_value}")
        """
        return None  # Default: no metadata hash available

    def get_metadata(self, path: str) -> dict[str, str]:
        """Get custom metadata for a file.

        Returns user-defined metadata attached to the file. For cloud storage
        (S3, GCS, Azure), this retrieves custom metadata stored with the file.
        For local storage, this typically returns an empty dict or uses
        extended attributes if supported.

        Args:
            path: Relative path to file

        Returns:
            dict[str, str]: Metadata key-value pairs

        Examples:
            >>> metadata = backend.get_metadata('document.pdf')
            >>> print(metadata.get('Content-Type'))
            'application/pdf'

        Notes:
            - Keys and values are strings
            - Cloud storage may have restrictions on key names (e.g., lowercase only)
            - Returns empty dict if no metadata or not supported
        """
        return {}  # Default: no metadata support

    def set_metadata(self, path: str, metadata: dict[str, str]) -> None:
        """Set custom metadata for a file.

        Attaches user-defined metadata to the file. For cloud storage
        (S3, GCS, Azure), this sets custom metadata that persists with the file.
        For local storage, this may use extended attributes if supported,
        or raise PermissionError if not supported.

        Args:
            path: Relative path to file
            metadata: Metadata key-value pairs to set

        Raises:
            FileNotFoundError: If file doesn't exist
            PermissionError: If backend doesn't support metadata

        Examples:
            >>> backend.set_metadata('document.pdf', {
            ...     'Content-Type': 'application/pdf',
            ...     'Author': 'John Doe',
            ...     'Version': '1.0'
            ... })

        Notes:
            - Keys and values must be strings
            - Cloud storage may have restrictions (e.g., max metadata size)
            - This typically replaces all metadata (not merge)
        """
        raise PermissionError(f"{self.__class__.__name__} does not support metadata operations")

    def get_versions(self, path: str) -> list[dict]:
        """Get list of available versions for a file.

        Returns version history for versioned storage. Default implementation
        returns empty list (no versioning support).

        Args:
            path: Relative path to file

        Returns:
            list[dict]: List of version info dicts

        Notes:
            - Override in subclasses that support versioning
            - S3 with versioning enabled can implement this
        """
        return []  # Default: no versioning

    def open_version(self, path: str, version_id: str, mode: str = "rb"):
        """Open a specific version of a file.

        Default implementation raises PermissionError. Override in subclasses
        that support versioning (e.g., S3).

        Args:
            path: Relative path to file
            version_id: Version identifier
            mode: Open mode (read-only)

        Raises:
            PermissionError: Always (base implementation)
        """
        raise PermissionError(f"{self.__class__.__name__} does not support versioning")

    def delete_version(self, path: str, version_id: str) -> None:
        """Delete a specific version of a file.

        Removes a specific version from versioned storage. The current version
        and other versions remain unaffected. This is useful for cleaning up
        duplicate or unwanted versions.

        Default implementation raises PermissionError. Override in subclasses
        that support versioning (e.g., S3).

        Args:
            path: Relative path to file
            version_id: Version identifier to delete

        Raises:
            PermissionError: If backend doesn't support versioning
            FileNotFoundError: If version doesn't exist
            ValueError: If attempting to delete the only remaining version

        Examples:
            >>> # Delete a specific version
            >>> backend.delete_version('file.txt', 'abc123')

        Notes:
            - Cannot delete the current version if it's the only version
            - Some backends may have restrictions on version deletion
            - This operation is typically irreversible
        """
        raise PermissionError(f"{self.__class__.__name__} does not support version deletion")

    def url(self, path: str, expires_in: int = 3600, **kwargs) -> str | None:
        """Generate public URL for file access.

        Returns a URL that can be used to access the file directly.
        For cloud storage (S3, GCS, Azure), this generates a presigned URL.
        For local storage, this returns None or a local file path URL.

        Args:
            path: Relative path to file
            expires_in: URL expiration time in seconds (default: 3600 = 1 hour)
            **kwargs: Backend-specific options

        Returns:
            str | None: Public URL or None if not supported

        Examples:
            >>> # S3 presigned URL (expires in 1 hour)
            >>> url = backend.url('documents/report.pdf')
            >>> print(url)
            'https://bucket.s3.amazonaws.com/documents/report.pdf?X-Amz-...'
            >>>
            >>> # Custom expiration (24 hours)
            >>> url = backend.url('video.mp4', expires_in=86400)

        Notes:
            - Cloud storage URLs are temporary and expire
            - Local storage typically returns None
            - HTTP storage returns the direct URL
        """
        return None  # Default: no URL generation

    def internal_url(self, path: str, nocache: bool = False) -> str | None:
        """Generate internal/relative URL for file access.

        Returns a URL suitable for internal application use, typically
        relative to the application's base URL. Optionally includes
        cache busting parameters.

        Args:
            path: Relative path to file
            nocache: If True, append mtime as query parameter for cache busting

        Returns:
            str | None: Internal URL or None if not supported

        Examples:
            >>> # Simple internal URL
            >>> url = backend.internal_url('images/logo.png')
            >>> print(url)
            '/storage/home/images/logo.png'
            >>>
            >>> # With cache busting
            >>> url = backend.internal_url('app.js', nocache=True)
            >>> print(url)
            '/storage/home/app.js?mtime=1234567890'

        Notes:
            - Useful for web applications
            - Cache busting helps with CDN/browser caching
            - Format depends on application configuration
        """
        return None  # Default: no internal URL

    def resolved_path(self, path: str) -> str | None:
        """Get resolved absolute filesystem path.

        Returns the absolute filesystem path for local storage backends.
        For remote storage (S3, GCS, Azure, HTTP), returns None.

        This is useful for:
        - Passing paths to external tools and commands
        - Integrating with legacy code expecting file paths
        - Using with Python standard library functions

        Args:
            path: Relative path within the storage

        Returns:
            str | None: Absolute filesystem path for local storage, None for remote

        Examples:
            >>> # Local storage
            >>> backend = LocalStorage('/var/www/static')
            >>> abs_path = backend.resolved_path('css/style.css')
            >>> print(abs_path)
            '/var/www/static/css/style.css'
            >>>
            >>> # Remote storage (S3, etc.)
            >>> backend = S3Backend('bucket-name')
            >>> abs_path = backend.resolved_path('file.txt')
            >>> print(abs_path)
            None

        Notes:
            - Only local filesystem backends return a path
            - Remote backends return None (use local_path() for temp access)
            - The path may not exist yet (e.g., for write operations)
        """
        return None  # Default: not supported for remote storage

    def local_path(self, path: str, mode: str = "r"):
        """Get a local filesystem path for the file.

        Returns a context manager that provides a local filesystem path
        to the file. For local storage, this returns the actual path.
        For remote storage (S3, GCS, etc.), this downloads the file to
        a temporary location, yields the temp path, and uploads changes
        back on exit if the file was modified.

        This is essential for integrating with external tools that only
        work with local filesystem paths (ffmpeg, ImageMagick, etc.).

        Args:
            path: Relative path to file
            mode: Access mode - 'r' (read-only), 'w' (write-only), 'rw' (read-write)

        Returns:
            Context manager yielding str (local filesystem path)

        Examples:
            >>> # Process remote file with external tool
            >>> with backend.local_path('video.mp4', mode='r') as local_path:
            ...     subprocess.run(['ffmpeg', '-i', local_path, 'output.mp4'])
            >>>
            >>> # Modify remote file in place
            >>> with backend.local_path('image.jpg', mode='rw') as local_path:
            ...     subprocess.run(['convert', local_path, '-resize', '800x600', local_path])
            >>> # Changes automatically uploaded on exit

        Notes:
            - For read mode ('r'), the file is downloaded but not uploaded
            - For write mode ('w'), the file is uploaded on exit
            - For read-write mode ('rw'), both download and upload occur
            - Temporary files are automatically cleaned up on exit
            - For local storage, returns the original path (no copy)
        """
        from contextlib import contextmanager

        @contextmanager
        def _local_path():
            yield self._get_local_path(path, mode)

        return _local_path()

    def _get_local_path(self, path: str, mode: str) -> str:
        """Implementation detail for local_path. Override in subclasses if needed."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement _get_local_path")

    def close(self) -> None:
        """Close backend and release resources.

        This method is called when the backend is no longer needed.
        Implementations should close any open connections, file handles, etc.

        The default implementation does nothing. Backends that manage
        resources should override this method.

        Examples:
            >>> backend.close()
        """
        pass
