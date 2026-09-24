Architecture Deep Dive
======================

This document provides a detailed look at genro-storage's internal architecture, design decisions, and implementation patterns.

.. contents:: Table of Contents
   :local:
   :depth: 2

Introduction
------------

genro-storage is built on a layered architecture that separates concerns clearly:

1. **User API Layer** - Simple, intuitive interface for developers
2. **Backend Layer** - Storage-specific implementations
3. **Provider Layer** - Async architecture with registry pattern
4. **Capabilities System** - Runtime feature detection

This design enables:

- Support for 15+ storage backends through a unified API
- Both synchronous and asynchronous operations
- Dynamic backend selection and configuration
- Feature detection without hardcoded assumptions

---

Architecture Overview
---------------------

.. mermaid::

   graph TB
       subgraph UserAPI[User API Layer]
           SM[StorageManager]
           SN[StorageNode]
           SC[StorageConfig grammar]
       end

       subgraph BackendLayer[Backend Layer]
           SB[StorageBackend Abstract]
           LOCAL[LocalStorage]
           FSSPEC[FsspecBackend]
           B64[Base64Backend]
           REL[RelativeMountBackend]
       end

       subgraph ProviderLayer[Provider Layer]
           PR[ProviderRegistry]
           BASE[BaseProvider]
           CUSTOM[CustomProvider]
           FS[FsspecProvider]
       end

       subgraph Capabilities[Capabilities System]
           CAP[BackendCapabilities]
           DEC[@capability decorator]
       end

       SM --> SN
       SM --> SB
       SN --> SB

       ASM --> ASN
       ASM --> PR
       ASN --> BASE

       SB --> LOCAL
       SB --> FSSPEC
       SB --> B64
       SB --> REL

       FSSPEC -.supports.-> CAP
       LOCAL -.supports.-> CAP

       PR --> BASE
       BASE --> CUSTOM
       BASE --> FS

       style SM fill:#4051b5,color:#fff
       style ASM fill:#4051b5,color:#fff
       style FSSPEC fill:#f39c12,color:#fff
       style PR fill:#27ae60,color:#fff

The architecture consists of three main layers:

**Key Points**:

1. **User API Layer** serves sync and async callers through the same classes:
   every I/O method carries ``@smartasync``, so it is awaitable from async code
2. **Backend Layer** implements storage-specific operations for different protocols
3. **Capabilities System** allows runtime feature detection and backend selection

---

Configuration and Setup Flow
-----------------------------

.. mermaid::

   sequenceDiagram
       participant User
       participant StorageManager
       participant BackendFactory
       participant Backend

       User->>StorageManager: configure(config_list)
       Note over StorageManager: Parse configuration

       loop For each mount
           StorageManager->>BackendFactory: create_backend(type, config)
           BackendFactory->>Backend: __init__(config params)
           Backend-->>BackendFactory: backend instance
           BackendFactory-->>StorageManager: configured backend
           StorageManager->>StorageManager: register mount
       end

       Note over StorageManager: All mounts configured

       User->>StorageManager: node('mount:path')
       StorageManager->>Backend: resolve mount
       StorageManager-->>User: StorageNode instance

**Configuration Process**:

1. **Parse Configuration** - Load from list, YAML, or JSON
2. **Validate Mounts** - Check required fields (name, type)
3. **Create Backends** - Instantiate appropriate backend class
4. **Register Mounts** - Store in mount registry
5. **Ready for Use** - node() method resolves to configured backends

**Key Features**:

- Configuration is sync (happens at startup)
- Mount names are unique identifiers
- Backends are lazy-loaded (created only when needed)
- Configuration can be updated at runtime

---

File Operation Flow
-------------------

.. mermaid::

   sequenceDiagram
       participant User
       participant StorageNode
       participant Backend
       participant Storage

       User->>StorageNode: node.read()
       StorageNode->>Backend: exists()
       Backend->>Storage: check file
       Storage-->>Backend: True
       Backend-->>StorageNode: True

       StorageNode->>Backend: read_bytes()
       Backend->>Storage: open file
       Storage-->>Backend: file handle
       Backend->>Storage: read content
       Storage-->>Backend: bytes
       Backend-->>StorageNode: bytes
       StorageNode-->>User: content

       Note over StorageNode,Backend: Properties cached for efficiency

**Read Operation Flow**:

1. **Existence Check** - Verify file exists before reading
2. **Backend Resolution** - Find appropriate backend for mount
3. **Open File** - Backend-specific file opening
4. **Read Content** - Stream or buffer based on size
5. **Return Data** - Convert encoding if needed

**Write Operation Flow**:

1. **Validate Path** - Check path security (no parent traversal)
2. **Ensure Directory** - Create parent dirs if needed
3. **Open for Write** - Backend-specific write mode
4. **Write Content** - Handle encoding conversion
5. **Close and Sync** - Ensure data is persisted

---

Copy Operation with Skip Strategies
------------------------------------

.. mermaid::

   sequenceDiagram
       participant User
       participant SourceNode
       participant DestNode
       participant SkipStrategy

       User->>SourceNode: copy_to(dest, skip='hash')
       SourceNode->>SourceNode: exists check

       SourceNode->>DestNode: exists()
       DestNode-->>SourceNode: True

       SourceNode->>SkipStrategy: should_skip(src, dest, strategy='hash')
       SkipStrategy->>SourceNode: get_hash()
       SkipStrategy->>DestNode: get_hash()
       Note over SkipStrategy: Compare MD5/ETag
       SkipStrategy-->>SourceNode: skip=True (hashes match)

       SourceNode->>User: on_skip callback
       Note over User: File skipped, no copy

       Note over SourceNode: For different hash, would proceed with copy

**Skip Strategy Process**:

1. **Check Existence** - If dest doesn't exist, always copy
2. **Apply Strategy**:

   - ``never``: Always copy
   - ``exists``: Skip if dest exists
   - ``size``: Compare file sizes
   - ``hash``: Compare MD5/ETag (smart for S3)
   - ``custom``: User-provided function

3. **Perform Copy** - If not skipped, execute copy operation
4. **Callbacks** - Invoke on_file or on_skip as appropriate

**Optimization for Cloud**:

- S3 ETag used for hash comparison (no download needed)
- Batch operations reduce API calls
- Parallel copies with async mode

---

Class Relationships
-------------------

.. mermaid::

   classDiagram
       class StorageManager {
           -dict _mounts
           -dict _backend_classes
           +configure(config)
           +node(path) StorageNode
           +has_mount(name) bool
           +get_mount_names() list
       }

       class StorageNode {
           -StorageBackend _backend
           -str _path
           -str _mount
           +read() str
           +write(content)
           +exists bool
           +size int
           +copy_to(dest)
           +delete()
       }

       class StorageBackend {
           <<abstract>>
           +read_bytes(path) bytes
           +write_bytes(path, data)
           +exists(path) bool
           +delete(path)
           +list_dir(path) list
           +capabilities() BackendCapabilities
       }

       class LocalStorage {
           -Path _root
           +read_bytes(path)
           +write_bytes(path, data)
       }

       class FsspecBackend {
           -AbstractFileSystem _fs
           -str _protocol
           +read_bytes(path)
           +write_bytes(path, data)
           +presigned_url(path, expires)
           +get_metadata(path)
       }

       class BackendCapabilities {
           +bool read
           +bool write
           +bool delete
           +bool versioning
           +bool metadata
           +bool presigned_urls
       }

       StorageManager "1" --> "*" StorageBackend : manages
       StorageManager --> "*" StorageNode : creates
       StorageNode "*" --> "1" StorageBackend : uses
       StorageBackend <|-- LocalStorage : implements
       StorageBackend <|-- FsspecBackend : implements
       StorageBackend --> "1" BackendCapabilities : provides

**Class Responsibilities**:

- **StorageManager**: Configuration, mount registry, node creation
- **StorageNode**: High-level file operations, path handling, API convenience
- **StorageBackend**: Low-level storage operations, protocol-specific code
- **BackendCapabilities**: Feature discovery, backend selection criteria

---

Module Structure
----------------

File Organization
~~~~~~~~~~~~~~~~~

::

    genro_storage/
    ├── __init__.py                  # Public API exports
    ├── manager.py                   # StorageManager
    ├── node.py                      # StorageNode
    ├── storage_grammar.py           # StorageConfig / StorageGrammar
    ├── backends/
    │   ├── __init__.py
    │   ├── base.py                  # StorageBackend abstract class
    │   ├── local.py                 # Local filesystem backend
    │   ├── fsspec.py                # Generic fsspec wrapper (15+ protocols)
    │   ├── base64.py                # In-memory base64 backend
    │   └── relative.py              # Permission wrapper backend
    ├── capabilities.py              # BackendCapabilities dataclass
    └── exceptions.py                # Custom exceptions

**Key Modules**:

- **manager.py**: Entry point, configuration, mount management, encryption keys
- **node.py**: Core file operations, copy strategies, virtual nodes
- **storage_grammar.py**: The builder grammar accepted by ``configure()``
- **backends/fsspec.py**: Wraps fsspec for 15+ protocols (S3, GCS, Azure, HTTP, etc.)

---

Component Responsibilities
--------------------------

StorageManager
~~~~~~~~~~~~~~

**Purpose**: Central configuration and entry point

**Responsibilities**:

- Parse and validate configuration (YAML, JSON, Python dicts)
- Manage mount registry (add, remove, list mounts)
- Create StorageNode instances
- Backend factory pattern (create appropriate backend for type)

**Example**:

.. code-block:: python

    storage = StorageManager()
    storage.configure([
        {'name': 'home', 'protocol': 'local', 'path': '/home/user'},
        {'name': 's3', 'protocol': 's3', 'bucket': 'my-bucket'}
    ])
    node = storage.node('s3:file.txt')

StorageNode
~~~~~~~~~~~

**Purpose**: High-level file abstraction

**Responsibilities**:

- File I/O operations (read, write, open)
- Directory operations (mkdir, list, delete)
- Path manipulation (parent, child, stem, suffix)
- Copy/move with skip strategies
- Virtual nodes (iternode, diffnode, zip)
- Versioning support (S3 version access)

**Design Pattern**: Facade pattern (simplifies backend complexity)

StorageBackend
~~~~~~~~~~~~~~

**Purpose**: Abstract interface for storage protocols

**Responsibilities**:

- Low-level storage operations
- Protocol-specific implementations
- Capability reporting
- Error handling and normalization

**Key Backends**:

- **LocalStorage**: Direct filesystem access
- **FsspecBackend**: Wraps fsspec for cloud/remote protocols
- **Base64Backend**: In-memory data URIs
- **RelativeMountBackend**: Permission wrapper and nested mounts

BackendCapabilities
~~~~~~~~~~~~~~~~~~~

**Purpose**: Runtime feature detection

**Capabilities**:

- ``read``, ``write``, ``delete`` - Basic operations
- ``versioning`` - Historical versions (S3)
- ``metadata`` - Custom metadata (S3, GCS, Azure)
- ``presigned_urls`` - Temporary signed URLs (S3, GCS)
- ``copy_optimization`` - Server-side copy (S3)
- ``hash_on_metadata`` - Fast hashing via ETag (S3)

**Usage**:

.. code-block:: python

    node = storage.node('s3:file.txt')
    caps = node.capabilities

    if caps.versioning:
        versions = node.versions

    if caps.presigned_urls:
        url = node.url(expires_in=3600)

---

Key Design Decisions
--------------------

Decision 1: One API for Sync and Async
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Supporting both sync and async without complexity

**Solution**: One set of classes. I/O methods carry ``@smartasync`` (from
genro-toolbox), which detects the calling context: the same call returns a
value from sync code and is awaitable from async code. Earlier versions
shipped separate ``AsyncStorageManager``/``AsyncStorageNode`` classes; they
were removed when the public API became synchronous-first.

**Benefits**:

- One class to learn, one to document, no duplicated implementation
- A store contract written once works for both kinds of caller

**Trade-off**: the awaitable-or-not duality lives inside the decorator rather
than in the type signature

Decision 2: Mount Point System
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Managing multiple storage backends elegantly

**Solution**: Unix-like mount point abstraction (``mount:path`` format)

**Benefits**:

- Intuitive for developers (familiar Unix concepts)
- Easy to switch backends (change config, not code)
- Supports nesting and permission wrapping
- Clear separation between backend and path

**Example**:

.. code-block:: python

    # Same code works with different backends
    node = storage.node('uploads:user/123/avatar.jpg')

    # uploads can be local, S3, GCS, or any backend

Decision 3: Fsspec Foundation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Supporting many storage protocols without reinventing wheels

**Solution**: Build on fsspec, add convenience layer

**Benefits**:

- 20+ protocols supported immediately (S3, GCS, Azure, HTTP, SFTP, etc.)
- Battle-tested implementations
- Community-maintained backends
- Focus on API design, not protocol details

**Value Add**: Mount points, unified errors, capabilities, convenience methods

Decision 4: Copy Skip Strategies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Efficient incremental backups and sync operations

**Solution**: Pluggable skip strategies (never, exists, size, hash, custom)

**Benefits**:

- Avoid unnecessary data transfer
- Smart use of cloud metadata (S3 ETag)
- Flexible for different use cases
- Progress tracking built-in

**Optimization**: Hash comparison uses ETag on S3 (no download)

Decision 5: Virtual Nodes
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Common operations like concat, diff, zip require temporary files

**Solution**: Virtual nodes (iternode, diffnode) with lazy evaluation

**Benefits**:

- No temporary file management
- Memory efficient (streaming)
- Clean API (same as regular nodes)
- Composable operations

**Use Cases**: Log aggregation, version comparison, archive creation

---

Performance Characteristics
---------------------------

Operation Costs
~~~~~~~~~~~~~~~

+-------------------------+------------------+------------------------+
| Operation               | Local Storage    | Cloud Storage (S3)     |
+=========================+==================+========================+
| Read file metadata      | ~1ms             | ~50-100ms (API call)   |
+-------------------------+------------------+------------------------+
| Read small file (<1MB)  | ~5ms             | ~100-200ms             |
+-------------------------+------------------+------------------------+
| Read large file (100MB) | ~500ms           | ~2-5s (network bound)  |
+-------------------------+------------------+------------------------+
| Write small file        | ~10ms            | ~150-300ms             |
+-------------------------+------------------+------------------------+
| List directory (100)    | ~20ms            | ~200-500ms             |
+-------------------------+------------------+------------------------+
| Copy (skip='hash')      | ~30ms            | ~100ms (ETag check)    |
+-------------------------+------------------+------------------------+
| Delete file             | ~2ms             | ~50ms                  |
+-------------------------+------------------+------------------------+

**Optimization Strategies**:

1. **Caching**: Node properties cached (size, mtime)
2. **Batch Operations**: list() returns all at once
3. **Smart Hashing**: S3 ETag used instead of downloading
4. **Async Mode**: Parallel operations for multiple files
5. **Skip Strategies**: Avoid unnecessary transfers

Memory Usage
~~~~~~~~~~~~

- **StorageNode**: ~500 bytes per instance
- **Cached Properties**: ~200 bytes per node
- **Backend Instance**: ~1-2 KB per backend
- **Large File Read**: Streaming (no memory penalty)

**Recommendation**: For 100,000 files, expect ~70MB memory overhead

---

Thread Safety Considerations
-----------------------------

Thread-Safe Components
~~~~~~~~~~~~~~~~~~~~~~

- **StorageManager**: Safe for concurrent node() calls
- **Backend Instances**: Thread-safe (fsspec backends are thread-safe)
- **Read Operations**: Safe for concurrent reads

Not Thread-Safe
~~~~~~~~~~~~~~~~

- **Write Operations**: No locking, concurrent writes may conflict
- **Configuration Changes**: configure() not safe during operation
- **Node State**: StorageNode instances not thread-safe

**Recommendation**:

- Use one StorageManager per application
- Create new StorageNode per thread if modifying
- For concurrent writes, use external locking or async mode

---

Extension Points
----------------

Adding Custom Backends
~~~~~~~~~~~~~~~~~~~~~~~

Extend ``StorageBackend`` abstract class:

.. code-block:: python

    from genro_storage.backends.base import StorageBackend
    from genro_storage.capabilities import BackendCapabilities

    class CustomBackend(StorageBackend):
        def __init__(self, **config):
            self._config = config

        def read_bytes(self, path: str) -> bytes:
            # Implement read
            pass

        def write_bytes(self, path: str, data: bytes) -> None:
            # Implement write
            pass

        @property
        def capabilities(self) -> BackendCapabilities:
            return BackendCapabilities(
                read=True,
                write=True,
                delete=False  # Read-only example
            )

    # Register
    StorageManager._backend_classes['custom'] = CustomBackend

Adding Custom Skip Strategies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``skip='custom'`` with ``skip_fn``:

.. code-block:: python

    def skip_if_newer(src_node, dest_node):
        """Skip if destination is newer than source."""
        if not dest_node.exists:
            return False
        return dest_node.mtime > src_node.mtime

    src.copy_to(dest, skip='custom', skip_fn=skip_if_newer)

---

Design Principles Applied
--------------------------

**1. Single Responsibility Principle**

- StorageManager: Configuration only
- StorageNode: File operations only
- Backends: Protocol implementation only

**2. Open/Closed Principle**

- Backends extensible via abstract class
- Skip strategies pluggable via custom functions
- New protocols added without modifying core

**3. Liskov Substitution Principle**

- All backends interchangeable via StorageBackend interface
- Sync/Async nodes have identical APIs

**4. Interface Segregation**

- BackendCapabilities declares available features
- Nodes check capabilities before using features

**5. Dependency Inversion**

- High-level (StorageNode) depends on abstraction (StorageBackend)
- Concrete backends (LocalStorage) implement abstraction

**6. Composition Over Inheritance**

- RelativeMountBackend wraps other backends (permission layer)
- Virtual nodes compose multiple nodes (iternode)

**7. Separation of Concerns**

- API layer separate from storage layer
- Sync/Async implementations separate
- Configuration separate from execution

---

Performance Benchmarks
----------------------

Indicative orders of magnitude observed while developing the library, not
measurements produced by the test suite — there is no benchmark suite in the
repository, so treat every figure below as a rough expectation rather than a
guarantee:

**Operation Speed** (local filesystem):

- Create/configure: <1ms
- Node creation: <0.1ms
- Read 1KB file: ~1ms
- Write 1KB file: ~2ms
- Copy file: ~3ms
- List 100 files: ~15ms
- Delete file: ~1ms

**S3 Operations** (MinIO test server):

- Read with ETag check: ~80ms
- Write with metadata: ~120ms
- Copy with skip='hash': ~100ms (no download)
- List versions: ~150ms

**Memory Efficiency**:

- 10,000 nodes: ~7MB
- 100,000 nodes: ~70MB
- Large file read: O(1) memory (streaming)

---

Future Enhancements
-------------------

Planned Features
~~~~~~~~~~~~~~~~

1. **Connection Pooling**: Reuse connections for better performance
2. **Caching Layer**: Optional caching for read-heavy workloads
3. **Retry Logic**: Automatic retry with exponential backoff
4. **Compression**: Transparent compression for large files

Under Consideration
~~~~~~~~~~~~~~~~~~~

1. **Transaction Support**: Atomic multi-file operations
2. **Watch/Notify**: File change notifications
3. **Quota Management**: Per-mount storage quotas
4. **Access Control**: Fine-grained permission system

---

Conclusion
----------

genro-storage provides a clean, extensible architecture for universal storage abstraction:

- **Layered Design**: Clear separation of concerns
- **Extensible**: Easy to add new backends and features
- **Performant**: Optimized for common operations
- **Well-Tested**: 87% coverage with 572 tests
- **Production-Ready**: Based on the Genropy storage layer, in production since 2018

The architecture balances:

- **Simplicity** (easy to use)
- **Flexibility** (supports many backends)
- **Performance** (optimized operations)
- **Maintainability** (clean code, good tests)

For questions or contributions, see:

- `GitHub Repository <https://github.com/genropy/genro-storage>`_
- `Issue Tracker <https://github.com/genropy/genro-storage/issues>`_
- `Documentation <https://genro-storage.readthedocs.io/>`_
