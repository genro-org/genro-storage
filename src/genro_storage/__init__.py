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

"""genro-storage - Unified storage abstraction for the Genropy framework.

This package provides a clean, consistent API for accessing files across
different storage backends (local, S3, GCS, Azure, HTTP, etc.) using a
mount-point abstraction inspired by Unix filesystems.

Main Components:
    - StorageManager: Configure and manage storage backends
    - StorageNode: Interact with files and directories (sync/async via @smartasync)
    - Exceptions: Storage-specific exception hierarchy

Quick Start (Sync):
    >>> from genro_storage import StorageManager
    >>>
    >>> # Setup
    >>> storage = StorageManager()
    >>> storage.configure([
    ...     {'name': 'home', 'protocol': 'local', 'base_path': '/home/user'},
    ...     {'name': 'uploads', 'protocol': 's3', 'bucket': 'my-bucket'}
    ... ])
    >>>
    >>> # Access files
    >>> node = storage.node('home:documents/report.pdf')
    >>> content = node.read_text()
    >>>
    >>> # Copy across backends
    >>> node.copy_to(storage.node('uploads:backup/report.pdf'))

Quick Start (Async):
    >>> import asyncio
    >>> from genro_storage import StorageManager
    >>>
    >>> async def main():
    ...     storage = StorageManager()
    ...     storage.configure([
    ...         {'name': 's3', 'protocol': 's3', 'bucket': 'my-bucket'}
    ...     ])
    ...     node = storage.node('s3:file.txt')
    ...     # Methods work in async context via @smartasync
    ...     data = await node.read_bytes()
    ...     await node.write_bytes(b'new data')
    >>>
    >>> asyncio.run(main())

For more information, see the documentation at:
https://genro-storage.readthedocs.io
"""

__version__ = "0.8.5"

from .manager import StorageManager
from .node import StorageNode, SkipStrategy
from .exceptions import (
    StorageError,
    StorageNotFoundError,
    StoragePermissionError,
    StorageReadConflictError,
    StorageConfigError,
)
from .storage_grammar import StorageConfig

__all__ = [
    # Version
    "__version__",
    # Main classes
    "StorageManager",
    "StorageNode",
    "SkipStrategy",
    # Configuration grammar (the mixin stays reachable as StorageManager.grammar)
    "StorageConfig",
    # Exceptions
    "StorageError",
    "StorageNotFoundError",
    "StoragePermissionError",
    "StorageReadConflictError",
    "StorageConfigError",
]
