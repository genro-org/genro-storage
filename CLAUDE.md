# Claude Code Instructions - genro-storage

**Parent Document**: This project follows all policies from the central [genro-next-generation CLAUDE.md](https://github.com/genropy/genro-next-generation/blob/main/CLAUDE.md)

Read the parent document first for:
- Language policy (English only)
- Git commit authorship rules (no Claude co-author)
- Development status lifecycle (Pre-Alpha → Alpha → Beta)
- Temporary files policy (use temp/ directories)
- Standardization requirements
- All general project policies

## Project-Specific Context

### Current Status
- **Development Status**: Beta
- **Has Implementation Code**: Yes
- **Version**: 0.8.0
- **Python Support**: 3.11, 3.12, 3.13
- **Test Coverage**: 87% (572 tests: 565 passing, 7 skipped, with the Docker services running; 78% without them)
- **GitHub**: https://github.com/genropy/genro-storage

### Project Purpose

Universal storage abstraction for Python with pluggable backends. Provides unified interface for accessing files across local filesystems, cloud storage (S3, GCS, Azure), and remote protocols (HTTP). Built on top of fsspec with an intuitive mount-point system.

### Project Structure

```
genro-storage/
├── src/genro_storage/      # Main package
│   ├── __init__.py        # Public API exports
│   ├── manager.py         # StorageManager - main entry point, at-rest encryption
│   ├── node.py            # StorageNode - file/directory abstraction
│   ├── capabilities.py    # Backend capability system
│   ├── exceptions.py      # Custom exceptions
│   ├── storage_grammar.py # StorageConfig / StorageGrammar builder grammar
│   └── backends/          # Storage backend implementations
│       ├── base.py        # Abstract backend interface
│       ├── fsspec.py      # Unified fsspec-based backend
│       ├── local.py       # Local filesystem, with callable base_path
│       ├── base64.py      # Inline base64 data, with writable paths
│       └── relative.py    # Child mount over a parent mount
├── tests/                 # Comprehensive test suite
├── docs/                  # ReadTheDocs documentation
├── notebooks/             # Executable tutorials, run by tests/test_notebooks.py
├── doc_to_review/         # Pre-0.7.0 documents, parked and unmaintained
└── TESTING.md            # Testing instructions with MinIO
```

### Key Components

**StorageManager** (`manager.py`):
- Main entry point for the library
- Manages mount points (named storage backends)
- Factory for creating StorageNode instances
- Configuration from a `StorageConfig` grammar, a YAML/JSON path, or a list of dicts
- Owns the at-rest key material and the encrypt/decrypt boundary

**StorageNode** (`node.py`):
- Represents a file or directory
- Unified API: `read()`, `write()`, `copy_to()`, `exists()`, `children()`, `call()`, `serve()`
- Intelligent copy strategies: exists, size, hash

**Supported Backends** (15 total):
- Local filesystem, S3, GCS, Azure, HTTP
- Memory, Base64, SMB, SFTP
- ZIP, TAR, Git, GitHub, WebDAV, LibArchive

### Important Features

1. **Mount Point System**: Logical names (`home:`, `uploads:`, `s3:`) instead of full URIs
2. **Intelligent Copy**: Skip strategies for efficient backups
3. **External Tool Integration**: `call()` method for ffmpeg, imagemagick, pandoc
4. **WSGI Serving**: `serve()` method for Flask, Django, Pyramid with ETag caching
5. **Base64 Backend**: Embed data inline with writable paths
6. **Cloud Metadata**: Get/set custom metadata on S3, GCS, Azure
7. **Callable Paths**: Dynamic path resolution at runtime
8. **Async Support**: the same StorageManager is awaitable from async code via `@smartasync`
9. **Pythonic Configuration**: `StorageConfig` grammar, one typed `@element` per protocol, `BagResolver` values in place
10. **Per-file Encryption**: declared at the write site, stored as a `#GNRE1:<domain>` envelope

### Architecture Notes

- Built on fsspec for battle-tested storage backends
- Originated from Genropy framework (in production since 2006, storage since 2018)
- Type-hinted codebase with full mypy support
- Available on PyPI

### Testing Approach

**Unit Tests**: Fast, no external dependencies
```bash
pytest tests/test_local_storage.py -v
```

**Integration Tests**: Require Docker + MinIO (S3-compatible)
```bash
docker compose -f tests/docker-compose.yml up -d
pytest tests/test_s3_integration.py -v
```

**Full Test Suite**:
```bash
pytest tests/ -v --cov=genro_storage
```

### Configuration Examples

```python
from genro_storage import StorageManager

storage = StorageManager()
storage.configure([
    {'name': 'home', 'protocol': 'local', 'base_path': '/home/user'},
    {'name': 'uploads', 'protocol': 's3', 'bucket': 'my-app-uploads'},
    {'name': 'backups', 'protocol': 'gcs', 'bucket': 'my-backups'},
])

# Use mount points
node = storage.node('uploads:documents/file.pdf')
content = node.read()
```

`type` and `path` were the field names through 0.4.4; they still work but raise a
`DeprecationWarning` and go away at 1.0. The typed alternative is the grammar:

```python
from genro_storage import StorageConfig, StorageManager

class MyConfig(StorageConfig):
    def main(self, root):
        m = root.mounts()
        m.local(name='home', base_path='/home/user')
        m.s3(name='uploads', bucket='my-app-uploads')

storage = StorageManager()
storage.configure(MyConfig)
```

### Development Guidelines

**Code Quality**:
```bash
# Format
black src/genro_storage/ tests/

# Lint
ruff check src/genro_storage/ tests/

# Type check (advisory, never a gate - see the mypy config in pyproject.toml)
mypy
```

**Documentation**:
- Keep `docs/` updated for major API changes; the module docstrings carry the contracts
- Update docstrings for all public methods
- ReadTheDocs auto-builds from main branch

**Performance**:
- Use cloud metadata (S3 ETag) when available for hashing
- Implement efficient copy strategies
- Test with large files in integration tests

### Dependencies

- `fsspec>=2023.1.0` - Core backend support
- `PyYAML>=6.0` - Configuration file support
- `genro-toolbox` - `@smartasync`, for the transparent sync/async surface
- `genro-builders>=0.22.0` - the grammar machinery behind `StorageConfig`
- `genro-bag>=0.20.1` - `BagResolver`, for configuration values that come from outside
- Optional: `s3fs`, `gcsfs`, `adlfs`, `aiohttp`, `smbprotocol`, `paramiko`, `webdav4`, `libarchive-c`, `pygit2`, `requests`, `cryptography`

### Related Documentation

- [Testing Guide](https://github.com/genropy/genro-storage/blob/main/TESTING.md)
- [ReadTheDocs](https://genro-storage.readthedocs.io)
- [Jupyter Notebooks](https://github.com/genropy/genro-storage/tree/main/notebooks)

`API_DESIGN.md` is no longer at the root: 0.7.0 parked it in `doc_to_review/`
along with the other pre-src-layout documents. Nothing there is maintained —
`docs/` and the docstrings are the current specification.

---

**All general policies are inherited from the parent document: the
[genro-next-generation CLAUDE.md](https://github.com/genropy/genro-next-generation/blob/main/CLAUDE.md)**

**Last Updated**: 2026-08-04
