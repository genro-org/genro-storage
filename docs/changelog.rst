Changelog
=========

All notable changes to genro-storage will be documented here.

The format is based on `Keep a Changelog <https://keepachangelog.com/en/1.0.0/>`_,
and this project adheres to `Semantic Versioning <https://semver.org/spec/v2.0.0.html>`_.

Unreleased
----------

Added
~~~~~

- New optional extra ``genro-storage[github]``. fsspec's github filesystem
  imports ``requests``, which the base install never pulled in, so a GitHub
  mount failed with ``ImportError`` unless the ``gcs`` or ``azure`` extra
  happened to be installed. ``requests`` joins ``all`` as well.
- ``tests/test_async.py``: the async branch of ``@smartasync``, as real
  coroutines — reads, writes, stat, directories, cross-mount copy, delete,
  concurrent writes and an encrypted round trip.

Removed
~~~~~~~

- The ``--async-mode`` pytest flag. It wrapped each sync test body in
  ``asyncio.to_thread``, which runs it on a worker thread with no event loop:
  ``is_async_context()`` was False there, so the sync branch executed and the
  flag verified nothing about async.

Fixed (documentation)
~~~~~~~~~~~~~~~~~~~~~

- The README announced version 0.4.3, October 2025 and the **MIT** license; the
  license has been Apache-2.0 since 0.4.4. ``CONTRIBUTING.md`` and
  ``docs/contributing.rst`` carried the same MIT claim.
- Git Flow is documented as retired: ``develop`` was removed on 2026-07-30, and
  ``CONTRIBUTING.md``, ``.github/WORKFLOW.md`` and the CI triggers still
  described it. The branch protection rules now match what the GitHub API
  actually reports.
- The release process pointed at ``pyproject.toml`` for the version bump, which
  is ``dynamic``: the single source is ``__version__`` in
  ``src/genro_storage/__init__.py``.
- Dead links: ``API_DESIGN.md`` (parked in ``doc_to_review/`` at 0.7.0) and
  ``CHANGELOG.md`` at the repository root, the latter linked from every
  generated GitHub release note.
- The Binder badge was removed: no dependency file has ever existed for it, so
  the environment it launched could not import the package.
- 0.4.3 and 0.4.4 are documented below, and 0.4.1/0.4.2 are marked as the
  unreleased milestones they were.

0.8.0 - July 2026
-----------------

Added
~~~~~

- Per-node encryption: ``write_bytes()``, ``write_text()`` and ``write()`` take
  ``encrypted`` — ``True`` for the default domain, ``'<domain>'`` for an
  explicit one, ``False`` for plaintext. Encryption is now a property of the
  file, so encrypted and plain files coexist in the same directory.
- A self-describing textual envelope: an encrypted payload is the line
  ``#GNRE1:<domain>`` followed by the Fernet token. Reads are deterministic —
  header present means decrypt through that domain's keyring, header absent
  means passthrough — with a bounded 128-byte header scan. The header is
  routing metadata in cleartext and is not authenticated.
- Encoding domains: key material accepts a ``<domain>:`` prefix per key
  (``acme:<k1>,acme:<k2>,partner:<k3>``), grouping into one ``MultiFernet`` per
  domain so rotation is per domain. Unprefixed keys keep working as the default
  domain; the first entry overall sets the default write domain.
  ``encryption_domains`` lists the configured names.
- ``mount_default_encrypted(name)`` reports a mount's default.

Changed
~~~~~~~

- **Breaking**: the mount option ``encrypted`` is replaced by
  ``default_encrypted`` (``bool | str``), which is only the default of the
  per-write parameter — an explicit ``encrypted=`` at the write site wins in
  both directions. The default belongs to the mount named in the write and to
  it alone: a ``relative`` mount has one only if it declares one (grammar,
  dict or YAML) — the parent's does not leak through.
- **Breaking**: ``StorageManager.encrypt(data, domain=...)`` returns enveloped
  bytes and ``decrypt(data)`` routes by header, passing through unenveloped
  content instead of raising.
- ``copy_to()``/``move_to()`` carry the envelope verbatim, which removes both
  0.7.x pathological cases: an encrypted → plain copy now delivers a file that
  still reads back through the library, and a plain → encrypted-mount copy
  reads in passthrough instead of failing to decrypt.

Removed
~~~~~~~

- **Breaking**: ``mount_is_encrypted()`` — the file's header answers for the
  file; the mount only holds a default.
- **Breaking**: mount-level transparent encryption. There is no compatibility
  layer and no legacy bare-token read path: 0.7.x content, written without a
  header, reads back as ciphertext bytes and must be re-written through 0.8.

0.7.2 - July 2026
-----------------

Changed
~~~~~~~

- **Breaking (module path only)**: the grammar module ``genro_storage.config``
  is renamed ``genro_storage.storage_grammar`` — ``config`` is conventionally
  the name of a *configuration file*, while this module holds the grammar
  classes. The public import ``from genro_storage import StorageConfig`` is
  unchanged; only the direct module path moves.

0.7.1 - July 2026
-----------------

Added
~~~~~

- ``StorageConfig`` is now exported from the package: ``from genro_storage
  import StorageConfig``. It is the grammar ``configure()`` accepts as a
  source, so it belongs on the public surface next to ``StorageManager``;
  0.7.0 only exposed it as ``genro_storage.config.StorageConfig``. The
  grammar mixin itself stays reachable as ``StorageManager.grammar``.

0.7.0 - July 2026
-----------------

Added
~~~~~

- At-rest encryption: a mount declared ``encrypted`` stores ciphertext, with
  transparent encrypt/decrypt on the node read/write surface. Key material is
  comma-separated Fernet keys with ``MultiFernet`` semantics (first key
  encrypts, all keys decrypt) supplied as ``storage_key`` or via
  ``set_encryption_keys()``; ``encryption_active`` and
  ``mount_is_encrypted()`` report the state. Requires the new optional extra
  ``genro-storage[encryption]``. See :doc:`encryption`, including the coverage
  boundary — ``open()``, ``local_path()``, ``call()``, ``serve()`` and
  ``copy_to()``/``move_to()`` carry the stored bytes untouched.
- Pythonic configuration through the ``StorageConfig`` builder grammar, with
  closed element signatures validated at the recipe line.
- ``StorageGrammar``, the grammar mixin, exposed as ``StorageManager.grammar``
  so a host dialect can govern a storage section by reference.
- Resolver support on every field whose value may come from the environment:
  a ``BagResolver`` can be passed in place of a literal and is read when
  ``configure()`` consumes it.

Changed
~~~~~~~

- Service-backed SMB and SFTP tests now skip when the service is unreachable
  instead of failing, so a bare ``pytest`` is green with no Docker services
  running.

Removed
~~~~~~~

- **Breaking**: Python 3.10 is no longer supported. The floor is 3.11,
  matching genro-bag and genro-toolbox.
- **Breaking**: the ``^pointer`` / ``${template}`` idiom in the builder
  adapter. Pass a ``BagResolver`` as the value instead — no seeding step and
  no name to keep in sync.

Dependencies
~~~~~~~~~~~~

- ``genro-builders`` floor raised to 0.22.0 (resolver-aware ``runtime_values``,
  sub-builder by reference).
- ``genro-bag>=0.20.1`` added as a direct dependency (0.20.0 imports
  ``typing_extensions`` without declaring it, so a clean install fails).

0.4.4 - November 2025
---------------------

Changed
~~~~~~~

- **Breaking (licensing)**: the project moved from the MIT License to the
  **Apache License 2.0**, with an ``SPDX-License-Identifier`` header on every
  module. The README and the contributing guides kept announcing MIT until
  0.8.0; the ``LICENSE`` file has been Apache-2.0 since this release.
- Capabilities are auto-derived per protocol: the ``@capability`` decorator
  populates ``PROTOCOL_CAPABILITIES``, and ``get_capabilities(protocol)`` is the
  single entry point for single- and multi-protocol backends alike. Declaring a
  capability twice is no longer possible.

Added
~~~~~

- Test infrastructure that starts what it needs: ``scripts/start_test_services.sh``
  and ``stop_test_services.sh``, a ``Makefile`` with ``test`` / ``test-unit`` /
  ``test-integration`` / ``test-all``, and service-backed tests that skip on a
  port check instead of failing when a service is down.
- ``api_introspection``, a JSON description of the public surface derived from
  the decorated methods. Removed again in 0.7.0 together with the
  ``genro_core`` decorators.

0.4.3 - October 2025
--------------------

The first release of the 0.4 line to reach PyPI. It carries everything listed
under 0.4.1 and 0.4.2 below — those two were development milestones on
``develop``, never tagged and never published — plus:

Added
~~~~~

- Native permission control for every backend type (readonly, readwrite,
  delete), validated against the backend's capabilities at configuration time.
- Integration tests against Azurite (Azure), fake-gcs-server (GCS) and HTTP,
  plus wider S3 versioning coverage.
- Complete coverage for ``RelativeMountBackend`` (75% → 96%) and
  ``BackendCapabilities`` (88% → 100%). Overall: 79% → 85%.

Changed
~~~~~~~

- CI starts the full set of Docker services for the integration job, on
  ``docker compose`` v2 syntax; health checks for the optional services no
  longer block the run.

.. note::

   0.4.1 and 0.4.2 were never released: there is no tag, no GitHub release and
   no PyPI artifact for either. Their entries are kept below because they
   describe real work — it simply reached users with 0.4.3.

0.4.2 - October 2025
--------------------

Added
~~~~~

- Git backend support for Git repositories
- GitHub backend support for GitHub repositories
- WebDAV backend support (Nextcloud, ownCloud, SharePoint)
- LibArchive backend support (RAR, 7z, ISO, and 20+ formats)
- Native permission control for all backends (readonly, readwrite, delete)
- Comprehensive permission tests for all backend types
- Validation of permissions against backend capabilities at configuration time
- Test coverage improvements: 79% → 85% (411 tests, 401 passing)
- Complete test coverage for RelativeMountBackend (75% → 96%)
- Complete test coverage for BackendCapabilities (88% → 100%)
- Docker services for integration testing (Azurite, fake-gcs-server, SFTP, SMB, WebDAV)

Changed
~~~~~~~

- Improved CI workflow with all Docker services for integration tests
- Enhanced test infrastructure with service emulators

0.4.1 - October 2025
--------------------

Added
~~~~~

- SMB/CIFS backend support for Windows and Samba shares
- SFTP backend support for SSH File Transfer Protocol
- ZIP archive backend support (read and write)
- TAR archive backend support (with gzip, bzip2, xz compression)
- Configuration tests for new backends
- Backend capability tests

0.4.0 - October 2025
--------------------

Added
~~~~~

- Relative mounts with permissions
- Unified read/write API
- RelativeMountBackend for path prefixing and permission enforcement

Changed
~~~~~~~

- Improved permission handling architecture
- Enhanced backend configuration system

0.3.0 - October 2025
--------------------

Added
~~~~~

- Async/await support via AsyncStorageManager
- AsyncStorageNode for async file operations
- Integration with asyncer for automatic sync→async conversion
- FastAPI compatibility examples
- Async tests and documentation

0.2.0 - October 2025
--------------------

Added
~~~~~

- Virtual nodes (iternode, diffnode)
- Interactive Jupyter notebooks tutorials
- Binder support for online tutorials
- Enhanced testing infrastructure
- Copy strategy improvements

0.1.0-beta - October 2025
-------------------------

**Beta Release** - Ready for production testing

Added
~~~~~

- Complete API implementation with stable interface
- Support for 7 storage backends: Local, S3, GCS, Azure, HTTP, Memory, Base64
- Comprehensive test suite with 195 tests (79% coverage)
- CI/CD testing on Python 3.9, 3.10, 3.11, 3.12
- Full ReadTheDocs documentation
- Mount point configuration system
- StorageManager for managing mount points
- StorageNode for file/directory operations
- Configuration from YAML and JSON files
- Cross-storage copy and move operations
- Intelligent copy skip strategies (exists, size, hash, custom)
- MD5 hashing and content-based equality
- Base64 backend with writable mutable paths
- call() method for external tool integration (ffmpeg, imagemagick, etc.)
- serve() method for WSGI file serving (Flask, Django, Pyramid)
- mimetype property for automatic content-type detection
- local_path() context manager for external tools
- Callable path support for dynamic directories
- Cloud metadata get/set (S3, GCS, Azure)
- URL generation (presigned URLs, data URIs)
- S3 versioning support
- MinIO integration testing

Technical
~~~~~~~~~

- Battle-tested code extracted from Genropy (Python web framework since 2006)
- Storage abstraction layer refined over 6+ years of production use (since 2018)
- Full type hints with Python 3.9+ compatibility
- Powered by fsspec for backend abstraction
