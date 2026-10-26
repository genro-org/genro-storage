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

"""Exception classes for genro-storage.

All exceptions inherit from StorageError base class for easy catching.
Exceptions also inherit from standard Python exceptions where appropriate
to maintain compatibility with existing code.
"""


class StorageError(Exception):
    """Base exception for all storage-related errors.

    This is the base class that all genro-storage exceptions inherit from.
    You can catch this to handle any storage-related error.

    Examples:
        >>> try:
        ...     node.read_bytes()
        ... except StorageError as e:
        ...     print(f"Storage error occurred: {e}")
    """

    pass


class StorageNotFoundError(StorageError, FileNotFoundError):
    """Raised when a file, directory, or mount point is not found.

    This exception inherits from both StorageError and FileNotFoundError,
    so it can be caught by either exception type.

    Common causes:
        - Attempting to access a mount point that hasn't been configured
        - Reading a file that doesn't exist
        - Accessing a path in a non-existent directory

    Examples:
        >>> try:
        ...     node = storage.node('missing_mount:file.txt')
        ... except StorageNotFoundError:
        ...     print("Mount or file not found")
    """

    pass


class StoragePermissionError(StorageError, PermissionError):
    """Raised when a permission-related error occurs.

    This exception inherits from both StorageError and PermissionError,
    so it can be caught by either exception type.

    Common causes:
        - Insufficient permissions to read/write a file
        - Insufficient AWS/GCS/Azure credentials or permissions
        - Attempting to write to a read-only storage backend (e.g., HTTP)

    Examples:
        >>> try:
        ...     node.write_bytes(b'data')
        ... except StoragePermissionError:
        ...     print("Permission denied")
    """

    pass


class StorageReadConflictError(StorageError, OSError):
    """Raised when an object is replaced while it is being read.

    A new read returns the new version. ``read_bytes``, ``read_text`` and
    ``local_path`` restart on their own and raise this only when the object
    keeps changing; a file opened with ``open('rb')`` raises it on the read
    that follows the replacement. It inherits from OSError, so code that
    catches OSError keeps working.

    Examples:
        >>> try:
        ...     data = node.read_bytes()
        ... except StorageReadConflictError:
        ...     print("Object kept changing during the read")
    """

    pass


class StorageConfigError(StorageError, ValueError):
    """Raised when configuration is invalid.

    This exception inherits from both StorageError and ValueError,
    so it can be caught by either exception type.

    Common causes:
        - Invalid configuration format (missing required fields)
        - Unsupported storage backend type
        - Invalid path format
        - Malformed YAML/JSON configuration file

    Examples:
        >>> try:
        ...     storage.configure([{'name': 'test'}])  # missing 'type'
        ... except StorageConfigError as e:
        ...     print(f"Configuration error: {e}")
    """

    pass
