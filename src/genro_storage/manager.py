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

"""StorageManager - Main entry point for configuring and accessing storage.

This module provides the StorageManager class which is the primary interface
for configuring storage backends and creating StorageNode instances.

At-rest encryption
------------------

Encryption is per file, declared at the write site: a node's ``write_bytes``,
``write_text`` and ``write()`` take ``encrypted=True`` (the default domain) or
``encrypted='<domain>'``, and reads need no declaration at all::

    storage.configure(MyConfig)                     # 'storage_key' in the recipe
    storage.node('secure:token.json').write_text(payload, encrypted=True)

A mount may carry ``default_encrypted`` — the value that parameter takes when a
write declares nothing — readable through ``mount_default_encrypted(name)``. It
is a default and nothing more: an explicit ``encrypted=`` at the write site wins
in both directions. The default belongs to the mount named in the write and to
it alone — a ``relative`` mount has one only if it declares one; the parent's
does not leak through.

The coverage boundary: node paths that expose the stored bytes directly —
``open()``, ``local_path()`` (and ``call()``/``serve()`` built on it),
``copy_to()``/``move_to()``, versioned reads, ``size()``/``md5hash()`` — hand
out or report on the stored bytes as they are. What they deliver for an
encrypted file is the envelope, so the file stays self-describing wherever it
lands and a copy or move needs no matching mount.

Encrypted content is self-describing. Every encrypted payload carries a textual
envelope — the first line ``#GNRE1:<domain>`` followed by the Fernet token — so
a read never has to be told what it is looking at: header present means decrypt
through that domain's keyring, header absent means passthrough. The header is
routing metadata, not a security boundary (see ``_parse_envelope``).

Key material is one or more comma-separated Fernet keys, each optionally
prefixed with ``<domain>:``. Keys of the same domain group into ONE
``MultiFernet``: the FIRST key of a domain encrypts, ALL of them decrypt, which
is how a key is rotated. An unprefixed key belongs to the default (empty)
domain, so the pre-existing syntax keeps working; the domain of the FIRST
configured key is the one an unqualified encryption uses. The keys are never
exposed; ``encryption_active`` only reports whether any are installed.

There is no silent degradation. Encrypting or decrypting for a domain with no
installed keys raises ``StorageError`` naming that domain, key material that
resolves empty is a ``StorageConfigError`` at configuration time, and a payload
no installed key can decrypt raises ``InvalidToken`` rather than falling back to
plaintext. Encryption is opt-in: with no key material no cipher is ever built
and ``cryptography`` is never needed.
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from typing import Annotated, Any

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    from cryptography.fernet import Fernet, MultiFernet

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

from .backends import StorageBackend
from .backends.base64 import Base64Backend
from .backends.fsspec import FsspecBackend
from .backends.local import LocalStorage
from .backends.relative import RelativeMountBackend
from .exceptions import StorageConfigError, StorageError, StorageNotFoundError
from .node import StorageNode
from .storage_grammar import StorageConfig, StorageGrammar


class StorageManager:
    """Main entry point for configuring and accessing storage.

    StorageManager is responsible for:
    - Configuring mount points that map to storage backends
    - Creating StorageNode instances for file/directory access
    - Managing the lifecycle of storage backend connections

    A mount point is a logical name (e.g., "home", "uploads", "s3") that
    maps to an actual storage backend (local filesystem, S3 bucket, etc.).

    Examples:
        >>> # Create manager
        >>> storage = StorageManager()
        >>>
        >>> # Configure from file
        >>> storage.configure('/etc/app/storage.yaml')
        >>>
        >>> # Configure programmatically
        >>> storage.configure([
        ...     {'name': 'home', 'protocol': 'local', 'path': '/home/user'},
        ...     {'name': 'uploads', 'protocol': 's3', 'bucket': 'my-bucket'}
        ... ])
        >>>
        >>> # Access files
        >>> node = storage.node('home:documents/report.pdf')
        >>> content = node.read_text()
    """

    #: The storage vocabulary, for a host document that wants to declare mounts
    #: inline: a host element carrying ``_meta={"subbuilder": "<kwarg>:grammar"}``
    #: reads this attribute off the manager and ``get_subbuilder`` fabricates the
    #: builder class from it. Standalone recipes use ``StorageConfig`` instead.
    grammar = StorageGrammar

    #: Envelope header of an encrypted payload: ``#GNRE1:<domain>`` on its own
    #: first line. Version 1 of the format; the whole envelope stays ASCII.
    ENVELOPE_PREFIX = b"#GNRE1:"

    #: Upper bound of the header scan. A first line longer than this is not a
    #: header, so a large binary payload is never searched end to end.
    ENVELOPE_MAX_HEADER = 128

    #: The charset an encryption domain may use — lowercase, digits, ``_``,
    #: ``-``; the empty string is the default domain.
    DOMAIN_PATTERN = re.compile(r"^[a-z0-9_-]{0,64}$")

    def __init__(self):
        """Initialize a new StorageManager with no configured mounts.

        After initialization, you must call ``configure()`` to set up
        mount points before you can access any files.

        Examples:
            >>> from genro_storage import StorageManager
            >>> storage = StorageManager()
        """
        # Dictionary mapping mount names to backend instances
        self._mounts: dict[str, Any] = {}
        # Per-mount default of the ``encrypted`` write parameter, and one
        # cipher per encryption domain. Key material is never exposed: only
        # ``encryption_active`` reports whether it is installed.
        self._default_encrypted: dict[str, bool | str] = {}
        self._ciphers: dict[str, Any] = {}
        # Domain of the first configured key: what an unqualified encryption uses.
        self._default_domain: str = ""

    # ==================== At-rest encryption ====================

    def _validate_domain(
        self, domain: Annotated[str, "Encryption domain name"]
    ) -> Annotated[str, "The domain itself, once validated"]:
        """Check a domain against ``DOMAIN_PATTERN`` and return it.

        Raises:
            StorageConfigError: On a domain outside the charset — a malformed
                domain is a configuration mistake, never a silent default.
        """
        if not self.DOMAIN_PATTERN.match(domain):
            raise StorageConfigError(
                f"Invalid encryption domain {domain!r}: expected [a-z0-9_-] up to 64 characters"
            )
        return domain

    def set_encryption_keys(
        self,
        keys: Annotated[str, "Comma-separated Fernet keys, each optionally '<domain>:' prefixed"],
    ) -> None:
        """Install the key material, grouped by encryption domain.

        Each comma-separated entry is either a bare Fernet key — the default
        (empty) domain — or ``<domain>:<key>``. The split is on the FIRST ``:``
        and unambiguous by construction: a Fernet key is base64url and holds no
        colon. Keys of one domain are wrapped in a single ``MultiFernet``, so
        the FIRST key of a domain encrypts and ALL of them decrypt: rotating
        means prepending the new key and keeping the old one until the content
        has been rewritten. The domain of the first entry overall becomes the
        default write domain. Calling this again replaces everything installed.

        Args:
            keys: e.g. "<key>", "<new>,<old>", "acme:k1,acme:k2,partner:k3"

        Raises:
            StorageConfigError: If ``cryptography`` is not installed, if ``keys``
                holds no key — key material that resolves empty is a
                configuration error, never a silent no-encryption fallback — or
                if an entry carries an invalid domain.

        Examples:
            >>> storage.set_encryption_keys(os.environ['STORAGE_KEY'])
            >>> storage.set_encryption_keys('acme:<new>,acme:<old>,partner:<k>')
        """
        if not HAS_CRYPTOGRAPHY:
            raise StorageConfigError(
                "At-rest encryption requires the 'cryptography' package. "
                "Install it with: pip install genro-storage[encryption]"
            )
        entries = [k.strip() for k in (keys or "").split(",") if k.strip()]
        if not entries:
            raise StorageConfigError(
                "set_encryption_keys: at least one key is required (got empty key material)"
            )
        by_domain: dict[str, list[Any]] = {}
        for entry in entries:
            domain, sep, key = entry.partition(":")
            if not sep:
                domain, key = "", entry
            domain, key = self._validate_domain(domain.strip()), key.strip()
            by_domain.setdefault(domain, []).append(Fernet(key))
        self._ciphers = {domain: MultiFernet(keyring) for domain, keyring in by_domain.items()}
        self._default_domain = next(iter(by_domain))

    @property
    def encryption_active(self) -> Annotated[bool, "True when key material is installed"]:
        """True when key material is installed; the keys themselves stay private."""
        return bool(self._ciphers)

    @property
    def encryption_domains(self) -> Annotated[list[str], "Domains with installed key material"]:
        """The configured domain names, in declaration order; the keys stay private."""
        return list(self._ciphers)

    def mount_default_encrypted(
        self, name: Annotated[str | None, "Mount point name"]
    ) -> Annotated[bool | str, "The mount's default for the ``encrypted`` write parameter"]:
        """The mount's ``default_encrypted``: what a write that declares nothing uses.

        The mount holds a default, never a state — what a given file is, its own
        header answers. The default belongs to the mount named in the write and
        to it alone: a ``relative`` mount has one only if it declares one; the
        parent's does not leak through. An undeclared mount defaults to plain.

        Examples:
            >>> storage.mount_default_encrypted('secure')
            True
        """
        return self._default_encrypted.get(name, False) if name else False

    def _build_envelope(
        self,
        domain: Annotated[str, "Encryption domain the token belongs to"],
        token: Annotated[bytes, "The Fernet token"],
    ) -> Annotated[bytes, "Header line plus token"]:
        """Wrap a Fernet token in the ``#GNRE1:<domain>`` envelope."""
        return self.ENVELOPE_PREFIX + domain.encode("ascii") + b"\n" + token

    def _parse_envelope(
        self, data: Annotated[bytes, "Stored bytes, enveloped or not"]
    ) -> Annotated[tuple[str | None, bytes], "Domain (None when unenveloped) and payload"]:
        """Split stored bytes into their domain and payload.

        The scan is bounded — the first ``ENVELOPE_MAX_HEADER`` bytes only — so
        content that is not an envelope costs a prefix comparison, and a header
        line longer than the bound is simply not a header.

        The header is NOT authenticated: the Fernet HMAC covers the token alone.
        Tampering with it misroutes the key lookup and decryption then fails
        loudly. The domain is routing metadata travelling in cleartext, never a
        security boundary — do not put a secret in a domain name.
        """
        if not data.startswith(self.ENVELOPE_PREFIX):
            return None, data
        newline = data.find(b"\n", 0, self.ENVELOPE_MAX_HEADER)
        if newline < 0:
            return None, data
        domain = data[len(self.ENVELOPE_PREFIX) : newline].decode("ascii", errors="replace")
        if not self.DOMAIN_PATTERN.match(domain):
            return None, data
        return domain, data[newline + 1 :]

    def _domain_cipher(
        self, domain: Annotated[str, "Encryption domain"], action: Annotated[str, "encrypt/decrypt"]
    ) -> Any:
        """The keyring of a domain, or a loud error naming the domain."""
        cipher = self._ciphers.get(domain)
        if cipher is None:
            raise StorageError(
                f"Cannot {action} for encryption domain {domain!r}: it requires installed "
                "key material (StorageManager.set_encryption_keys or 'storage_key' in the "
                "configuration)"
            )
        return cipher

    def encrypt(
        self,
        data: Annotated[bytes, "Plaintext bytes"],
        domain: Annotated[str | None, "Encryption domain; None uses the default one"] = None,
    ) -> Annotated[bytes, "Enveloped ciphertext"]:
        """Encrypt bytes and return them enveloped (the domain's first key encrypts).

        Raises:
            StorageConfigError: If ``domain`` is outside the allowed charset.
            StorageError: If the domain has no installed key material — a domain
                with no key is dormant, and using it is a runtime error.
        """
        domain = self._default_domain if domain is None else self._validate_domain(domain)
        return self._build_envelope(domain, self._domain_cipher(domain, "encrypt").encrypt(data))

    def decrypt(self, data: Annotated[bytes, "Stored bytes, enveloped or not"]) -> bytes:
        """Return the plaintext of an enveloped payload; pass anything else through.

        The read is deterministic: a ``#GNRE1:`` header routes the payload to
        that domain's keyring, its absence means the content was never encrypted
        by this library and is returned untouched. No content sniffing.

        Raises:
            StorageError: If the envelope names a domain with no installed keys.
            cryptography.fernet.InvalidToken: On an enveloped payload no key of
                its domain can decrypt — never a plaintext fallback.
        """
        domain, payload = self._parse_envelope(data)
        if domain is None:
            return payload
        return self._domain_cipher(domain, "decrypt").decrypt(payload)

    def configure(
        self,
        source: Annotated[
            str | list[dict[str, Any]] | StorageConfig | type[StorageConfig],
            "Configuration source: a StorageConfig subclass or instance, a path to a "
            "YAML/JSON file, or a list of mount configuration dicts",
        ],
        storage_key: Annotated[
            str | None,
            "At-rest key material for the encrypted mounts: comma-separated Fernet keys",
        ] = None,
    ) -> None:
        """Configure mount points from various sources.

        This method can be called multiple times. If a mount with the same
        name already exists, it will be replaced with the new configuration.

        Args:
            source: Configuration source, can be:

                - StorageConfig subclass or instance: the pythonic grammar (see
                  ``genro_storage.storage_grammar``). A subclass is instantiated and built
                  on a fresh handler; an instance is used as already built.
                  ``BagResolver`` values are resolved once, here, at configuration time.
                - str: Path to YAML or JSON configuration file
                - list[dict]: List of mount configurations
            storage_key: Key material for the encrypted writes of the recipe, the
                equivalent of the grammar's ``mounts(storage_key=...)``. Passed
                straight to ``set_encryption_keys``; a recipe that declares it
                wins over this parameter, being the more specific source.

        Raises:
            FileNotFoundError: If configuration file doesn't exist
            StorageConfigError: If configuration format is invalid
            TypeError: If source is not a StorageConfig subclass/instance, str, or list

        Configuration Dictionary Format:
            Each mount configuration dict must have:

            - name (str, required): Mount point name (e.g., "home", "uploads")
            - protocol (str, required): Backend protocol ("local", "s3", "gcs", "azure", "http", "memory")
            - Additional fields depend on protocol (see examples below)

        Examples:
            **Local Storage:**

            >>> storage.configure([{
            ...     'name': 'home',
            ...     'protocol': 'local',
            ...     'path': '/home/user'  # required: absolute path
            ... }])

            **S3 Storage:**

            >>> storage.configure([{
            ...     'name': 'uploads',
            ...     'protocol': 's3',
            ...     'bucket': 'my-bucket',    # required
            ...     'prefix': 'uploads/',     # optional, default: ""
            ...     'region': 'eu-west-1',    # optional
            ...     'anon': False             # optional, default: False
            ... }])

            **GCS Storage:**

            >>> storage.configure([{
            ...     'name': 'backups',
            ...     'protocol': 'gcs',
            ...     'bucket': 'my-backups',   # required
            ...     'prefix': '',             # optional
            ...     'token': 'path/to/service-account.json'  # optional
            ... }])

            **Azure Blob Storage:**

            >>> storage.configure([{
            ...     'name': 'archive',
            ...     'protocol': 'azure',
            ...     'container': 'archives',      # required
            ...     'account_name': 'myaccount',  # required
            ...     'account_key': '...'          # optional if using managed identity
            ... }])

            **HTTP Storage (read-only):**

            >>> storage.configure([{
            ...     'name': 'cdn',
            ...     'protocol': 'http',
            ...     'base_url': 'https://cdn.example.com'  # required
            ... }])

            **Memory Storage (for testing):**

            >>> storage.configure([{
            ...     'name': 'test',
            ...     'protocol': 'memory'
            ... }])

            **From YAML File:**

            .. code-block:: yaml

                # storage.yaml
                - name: home
                  protocol: local
                  path: /home/user

                - name: uploads
                  protocol: s3
                  bucket: my-app-uploads
                  region: eu-west-1

            >>> storage.configure('/etc/app/storage.yaml')

            **From JSON File:**

            .. code-block:: json

                [
                  {
                    "name": "home",
                    "protocol": "local",
                    "path": "/home/user"
                  },
                  {
                    "name": "uploads",
                    "protocol": "s3",
                    "bucket": "my-app-uploads",
                    "region": "eu-west-1"
                  }
                ]

            >>> storage.configure('./config/storage.json')

            **Multiple Calls (mounts are replaced if same name):**

            >>> storage.configure([{'name': 'home', 'protocol': 'local', 'path': '/home/user'}])
            >>> storage.configure([{'name': 'uploads', 'protocol': 's3', 'bucket': 'my-bucket'}])
            >>> # Now both 'home' and 'uploads' are configured
        """
        # Parse source
        recipe_key = None
        if isinstance(source, type) and issubclass(source, StorageConfig):
            page = source()
            page.create()
            recipe_key, config_list = self._mounts_from_builder(page)
        elif isinstance(source, StorageConfig):
            recipe_key, config_list = self._mounts_from_builder(source)
        elif isinstance(source, str):
            config_list = self._load_config_file(source)
        elif isinstance(source, list):
            config_list = source
        else:
            raise TypeError(
                "source must be a StorageConfig subclass or instance, a str "
                f"(file path), or list[dict], got {type(source).__name__}"
            )

        # Install key material before the mounts that will use it. The recipe's
        # own declaration is the more specific source and wins over the argument.
        key_material = recipe_key if recipe_key is not None else storage_key
        if key_material is not None:
            self.set_encryption_keys(key_material)

        # Validate and configure each mount
        for config in config_list:
            self._configure_mount(config)

    def add_mount(
        self, config: Annotated[dict[str, Any], "Mount configuration dictionary"]
    ) -> None:
        """Add or update a single mount point.

        If a mount with the same name already exists, it will be replaced.

        Args:
            config: Mount configuration dictionary with 'name' and 'protocol' fields

        Raises:
            StorageConfigError: If configuration is invalid

        Examples:
            >>> storage.add_mount({
            ...     'name': 'uploads',
            ...     'protocol': 's3',
            ...     'bucket': 'my-bucket'
            ... })
        """
        self._configure_mount(config)

    def delete_mount(self, name: Annotated[str, "Mount point name to delete"]) -> None:
        """Delete a mount point.

        Args:
            name: Name of the mount point to remove

        Raises:
            KeyError: If mount point doesn't exist

        Examples:
            >>> storage.delete_mount('uploads')
        """
        if name not in self._mounts:
            raise KeyError(f"Mount point '{name}' not found")
        del self._mounts[name]
        self._default_encrypted.pop(name, None)

    def _mounts_from_builder(self, page: StorageConfig) -> tuple[str | None, list[dict[str, Any]]]:
        """Flatten a built ``StorageConfig`` into the ``list[dict]`` the dict path consumes.

        Walks the ``mounts`` collection in bag order — which is declaration order —
        resolving each node's ``BagResolver`` values through ``runtime_values`` and
        tagging the protocol from ``node_tag``. A ``relative`` node carries its parent
        in ``path`` and is routed by ``_configure_mount`` on the ``:`` separator, so it
        gets no ``protocol`` key. The resulting dicts feed the unchanged
        ``_configure_mount``; each resolver is read once, here.

        The collection node carries one attribute of its own, ``storage_key``,
        resolved the same way and returned apart: it belongs to the manager, not
        to any single mount.

        Args:
            page: A built ``StorageConfig`` (its ``create()`` has run)

        Returns:
            tuple: The recipe's ``storage_key`` (``None`` if undeclared) and one
                mount configuration dict per declared mount, in order

        Raises:
            StorageConfigError: If ``page`` was never built (its source is
                empty) — an instance is expected already built.
        """
        # An unbuilt instance has an empty source: its ``main`` never ran. This
        # is misuse, not an empty configuration — signal it instead of silently
        # mounting nothing.
        if not len(page.source):
            raise StorageConfigError(
                "StorageConfig instance has not been built: pass a StorageConfig "
                "subclass (built automatically) or an instance whose create() "
                "has already run."
            )

        mounts_node = page.source.get_node("mounts")
        if mounts_node is None:
            return None, []

        _value, mounts_attrs = page.runtime_values(mounts_node)
        storage_key = mounts_attrs.get("storage_key")

        config_list: list[dict[str, Any]] = []
        # A ``mounts`` collection with no children has ``value is None`` (not an
        # empty Bag); zero mounts is a legitimate state, so treat it as no mounts.
        for node in mounts_node.value or ():
            _value, attrs = page.runtime_values(node)
            config = dict(attrs)
            if node.node_tag != "relative":
                config["protocol"] = node.node_tag
            config_list.append(config)
        return storage_key, config_list

    def _load_config_file(self, filepath: str) -> list[dict[str, Any]]:
        """Load configuration from YAML or JSON file.

        Args:
            filepath: Path to configuration file

        Returns:
            list[dict]: List of mount configurations

        Raises:
            FileNotFoundError: If file doesn't exist
            StorageConfigError: If file format is invalid
        """
        path = Path(filepath)

        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {filepath}")

        # Determine format from extension
        suffix = path.suffix.lower()

        try:
            with open(path, "r") as f:
                if suffix in (".yaml", ".yml"):
                    if not HAS_YAML:
                        raise StorageConfigError(
                            "YAML support not available. Install PyYAML: pip install PyYAML"
                        )
                    config = yaml.safe_load(f)
                elif suffix == ".json":
                    config = json.load(f)
                else:
                    raise StorageConfigError(
                        f"Unsupported configuration file format: {suffix}. "
                        f"Use .yaml, .yml, or .json"
                    )
        except Exception as e:
            if HAS_YAML and isinstance(e, yaml.YAMLError):
                raise StorageConfigError(f"Failed to parse YAML file: {e}")
            elif isinstance(e, json.JSONDecodeError):
                raise StorageConfigError(f"Failed to parse JSON file: {e}")
            else:
                raise

        if not isinstance(config, list):
            raise StorageConfigError(
                f"Configuration must be a list of mount configs, got {type(config).__name__}"
            )

        return config

    def _configure_mount(self, config: dict[str, Any]) -> None:
        """Configure a single mount point.

        Args:
            config: Mount configuration dictionary

        Raises:
            StorageConfigError: If configuration is invalid
        """
        # Validate required fields
        if "name" not in config:
            raise StorageConfigError("Mount configuration missing required field: 'name'")

        mount_name = config["name"]

        # Check for relative mount (child mount referencing a parent)
        # Only check if path is a string (not callable)
        if "path" in config and isinstance(config["path"], str) and ":" in config["path"]:
            self._configure_relative_mount(mount_name, config)
            return

        if "protocol" not in config:
            if "type" not in config:
                raise StorageConfigError(
                    f"Mount configuration for '{config['name']}' missing required field: 'protocol'"
                )
            # 'type' was the field name up to 0.4.4; accepted until 1.0.
            warnings.warn(
                f"Mount '{mount_name}': the 'type' field is deprecated, use 'protocol' instead",
                DeprecationWarning,
                stacklevel=3,
            )

        backend_type = config.get("protocol") or config["type"]

        # Create appropriate backend
        if backend_type == "local":
            # Accept 'base_path' as standard
            base_path = config.get("base_path") or config.get("path")
            if not base_path:
                raise StorageConfigError(
                    f"Local storage '{mount_name}' missing required field: 'base_path'"
                )
            # LocalStorage supports both string paths and callables
            # Optional base_url for URL generation
            backend: StorageBackend = LocalStorage(path=base_path, base_url=config.get("base_url"))

        elif backend_type == "memory":
            backend = FsspecBackend("memory", base_path=config.get("base_path", ""))

        elif backend_type == "s3":
            if "bucket" not in config:
                raise StorageConfigError(
                    f"S3 storage '{mount_name}' missing required field: 'bucket'"
                )
            # Build S3 path: bucket/base_path
            path = config["bucket"]
            # Accept 'base_path' as standard, 'prefix' for legacy
            if config.get("base_path"):
                path = f"{path}/{config['base_path'].strip('/')}"
            elif config.get("prefix"):
                path = f"{path}/{config['prefix'].strip('/')}"

            kwargs = {}
            if "region" in config:
                kwargs["client_kwargs"] = {"region_name": config["region"]}
            if "anon" in config:
                kwargs["anon"] = config["anon"]
            # Accept 'access_key'/'secret_key' as standard, 'key'/'secret' for legacy
            if config.get("access_key"):
                kwargs["key"] = config["access_key"]
            elif config.get("key"):
                kwargs["key"] = config["key"]
            if config.get("secret_key"):
                kwargs["secret"] = config["secret_key"]
            elif config.get("secret"):
                kwargs["secret"] = config["secret"]
            if "endpoint_url" in config:
                kwargs["endpoint_url"] = config["endpoint_url"]
            if "version_aware" in config:
                kwargs["version_aware"] = config["version_aware"]

            backend = FsspecBackend("s3", base_path=path, **kwargs)

        elif backend_type == "gcs":
            if "bucket" not in config:
                raise StorageConfigError(
                    f"GCS storage '{mount_name}' missing required field: 'bucket'"
                )
            path = config["bucket"]
            # Accept 'base_path' as standard, 'prefix' for legacy
            if config.get("base_path"):
                path = f"{path}/{config['base_path'].strip('/')}"
            elif config.get("prefix"):
                path = f"{path}/{config['prefix'].strip('/')}"

            kwargs = {}
            if "token" in config:
                kwargs["token"] = config["token"]
            if "project" in config:
                kwargs["project"] = config["project"]
            if "endpoint_url" in config:
                kwargs["endpoint_url"] = config["endpoint_url"]

            backend = FsspecBackend("gcs", base_path=path, **kwargs)

        elif backend_type == "azure":
            if "container" not in config:
                raise StorageConfigError(
                    f"Azure storage '{mount_name}' missing required field: 'container'"
                )
            if "account_name" not in config:
                raise StorageConfigError(
                    f"Azure storage '{mount_name}' missing required field: 'account_name'"
                )

            # Base path is just the container name for Azure
            base_path = config["container"]

            kwargs = {"account_name": config["account_name"]}
            if "account_key" in config:
                kwargs["account_key"] = config["account_key"]
            if "sas_token" in config:
                kwargs["sas_token"] = config["sas_token"]
            if "connection_string" in config:
                kwargs["connection_string"] = config["connection_string"]

            backend = FsspecBackend("az", base_path=base_path, **kwargs)

        elif backend_type == "http":
            # Accept 'base_path' as standard, 'base_url' for legacy
            base_path_value = config.get("base_path") or config.get("base_url")
            if not base_path_value:
                raise StorageConfigError(
                    f"HTTP storage '{mount_name}' missing required field: 'base_path'"
                )
            backend = FsspecBackend("http", base_path=base_path_value)

        elif backend_type == "smb":
            if "host" not in config:
                raise StorageConfigError(
                    f"SMB storage '{mount_name}' missing required field: 'host'"
                )
            if "share" not in config:
                raise StorageConfigError(
                    f"SMB storage '{mount_name}' missing required field: 'share'"
                )

            # Build SMB path: /share/base_path
            path = f"/{config['share']}"
            # Accept 'base_path' as standard, 'path' for legacy
            if config.get("base_path"):
                path = f"{path}/{config['base_path'].strip('/')}"
            elif config.get("path"):
                path = f"{path}/{config['path'].strip('/')}"

            kwargs = {"host": config["host"]}
            if "username" in config:
                kwargs["username"] = config["username"]
            if "password" in config:
                kwargs["password"] = config["password"]
            if "domain" in config:
                kwargs["domain"] = config["domain"]
            if "port" in config:
                kwargs["port"] = config["port"]

            backend = FsspecBackend("smb", base_path=path, **kwargs)

        elif backend_type == "sftp":
            if "host" not in config:
                raise StorageConfigError(
                    f"SFTP storage '{mount_name}' missing required field: 'host'"
                )
            if "username" not in config:
                raise StorageConfigError(
                    f"SFTP storage '{mount_name}' missing required field: 'username'"
                )

            # Build SFTP path: host:/base_path
            # Accept 'base_path' as standard, 'path' for legacy
            path = config.get("base_path") or config.get("path", "/")

            kwargs = {"host": config["host"], "username": config["username"]}
            if "password" in config:
                kwargs["password"] = config["password"]
            if "port" in config:
                kwargs["port"] = config["port"]
            if "key_filename" in config:
                kwargs["key_filename"] = config["key_filename"]
            if "passphrase" in config:
                kwargs["passphrase"] = config["passphrase"]
            if "timeout" in config:
                kwargs["timeout"] = config["timeout"]

            backend = FsspecBackend("sftp", base_path=path, **kwargs)

        elif backend_type == "zip":
            if "file" not in config:
                raise StorageConfigError(
                    f"ZIP storage '{mount_name}' missing required field: 'file'"
                )

            # ZIP archives use 'fo' parameter for file path
            kwargs = {"fo": config["file"]}
            if "mode" in config:
                kwargs["mode"] = config["mode"]
            if "target_protocol" in config:
                kwargs["target_protocol"] = config["target_protocol"]
            if "target_options" in config:
                kwargs["target_options"] = config["target_options"]

            backend = FsspecBackend("zip", base_path="", **kwargs)

        elif backend_type == "tar":
            if "file" not in config:
                raise StorageConfigError(
                    f"TAR storage '{mount_name}' missing required field: 'file'"
                )

            # TAR archives use 'fo' parameter for file path
            kwargs = {"fo": config["file"]}
            if "compression" in config:
                kwargs["compression"] = config["compression"]
            if "target_protocol" in config:
                kwargs["target_protocol"] = config["target_protocol"]
            if "target_options" in config:
                kwargs["target_options"] = config["target_options"]

            backend = FsspecBackend("tar", base_path="", **kwargs)

        elif backend_type == "git":
            # Accept 'base_path' as standard, 'path' for legacy
            git_path = config.get("base_path") or config.get("path")
            if not git_path:
                raise StorageConfigError(
                    f"Git storage '{mount_name}' missing required field: 'base_path'"
                )

            # Git backend accesses local Git repositories
            kwargs = {"path": git_path}
            if "ref" in config:
                kwargs["ref"] = config["ref"]  # commit, tag, or branch
            if "fo" in config:
                kwargs["fo"] = config["fo"]

            backend = FsspecBackend("git", base_path="", **kwargs)

        elif backend_type == "github":
            if "org" not in config:
                raise StorageConfigError(
                    f"GitHub storage '{mount_name}' missing required field: 'org'"
                )
            if "repo" not in config:
                raise StorageConfigError(
                    f"GitHub storage '{mount_name}' missing required field: 'repo'"
                )

            # GitHub backend accesses remote repositories via API
            kwargs = {"org": config["org"], "repo": config["repo"]}
            if "sha" in config:
                kwargs["sha"] = config["sha"]  # commit, branch, or tag
            if "username" in config:
                kwargs["username"] = config["username"]  # GitHub username for auth
            if "token" in config:
                kwargs["token"] = config["token"]  # GitHub personal access token

            backend = FsspecBackend("github", base_path="", **kwargs)

        elif backend_type == "webdav":
            if "url" not in config:
                raise StorageConfigError(
                    f"WebDAV storage '{mount_name}' missing required field: 'url'"
                )

            # WebDAV backend for Nextcloud, ownCloud, SharePoint, etc.
            kwargs = {"base_url": config["url"]}
            if "username" in config and "password" in config:
                kwargs["auth"] = (config["username"], config["password"])
            if "token" in config:
                kwargs["token"] = config["token"]
            if "cert" in config:
                kwargs["cert"] = config["cert"]
            if "verify_ssl" in config:
                kwargs["verify_ssl"] = config["verify_ssl"]

            backend = FsspecBackend("webdav", base_path="", **kwargs)

        elif backend_type == "libarchive":
            if "file" not in config:
                raise StorageConfigError(
                    f"LibArchive storage '{mount_name}' missing required field: 'file'"
                )

            # LibArchive backend for universal archive support (7z, rar, iso, etc.)
            kwargs = {"fo": config["file"]}
            if "target_protocol" in config:
                kwargs["target_protocol"] = config["target_protocol"]
            if "target_options" in config:
                kwargs["target_options"] = config["target_options"]

            backend = FsspecBackend("libarchive", base_path="", **kwargs)

        elif backend_type == "base64":
            # Base64 backend has no configuration parameters
            backend = Base64Backend()

        else:
            raise StorageConfigError(
                f"Unknown storage type '{backend_type}' for mount '{mount_name}'. "
                f"Supported types: local, s3, gcs, azure, http, memory, base64, smb, sftp, zip, tar, "
                f"git, github, webdav, libarchive"
            )

        # Apply permission restrictions if specified
        if "permissions" in config:
            backend = self._apply_permissions(mount_name, backend, config["permissions"])

        # ``default_encrypted`` is a manager-level property of the mount, not a
        # backend option: the bytes are enveloped above the backend, so every
        # backend stores them the same way. It is only the default of the write
        # parameter — a write declaring ``encrypted=`` overrides it in both
        # directions. Reconfiguring a mount replaces the default, hence the pop;
        # a name reused by a non-relative mount also sheds its old parent link.
        default_encrypted = config.get("default_encrypted", False)
        if default_encrypted:
            self._default_encrypted[mount_name] = self._checked_default_encrypted(
                mount_name, default_encrypted
            )
        else:
            self._default_encrypted.pop(mount_name, None)

        self._mounts[mount_name] = backend

    def _checked_default_encrypted(
        self,
        mount_name: Annotated[str, "Mount being configured, for the error message"],
        value: Annotated[bool | str, "The declared default, already truthy"],
    ) -> Annotated[bool | str, "The value itself, once checked"]:
        """Validate a declared ``default_encrypted`` before storing it.

        Raises:
            StorageConfigError: If ``cryptography`` is missing, or the value
                names a domain outside the charset.
        """
        if not HAS_CRYPTOGRAPHY:
            raise StorageConfigError(
                f"Mount '{mount_name}' declares default_encrypted but the 'cryptography' "
                "package is not installed. Install it with: "
                "pip install genro-storage[encryption]"
            )
        if isinstance(value, str):
            self._validate_domain(value)
        return value

    def _configure_relative_mount(self, mount_name: str, config: dict[str, Any]) -> None:
        """Configure a relative mount point that references a parent mount.

        A relative mount is a child mount that inherits the backend type and
        configuration from a parent mount, but adds a relative path prefix
        and optional permission restrictions.

        Args:
            mount_name: Name for the new child mount
            config: Configuration dict with 'path' and optional 'permissions'

        Raises:
            StorageConfigError: If path format is invalid or parent mount not found

        Examples:
            >>> # After configuring parent:
            >>> # {'name': 'data', 'protocol': 's3', 'bucket': 'my-bucket'}
            >>> # Configure child with permissions:
            >>> # {'name': 'public', 'path': 'data:public', 'permissions': 'readonly'}
            >>> # Now 'public:file.txt' can only read from 'data:public/file.txt'
        """
        mount_path = config["path"]

        # Parse parent mount and relative path
        if ":" not in mount_path:
            raise StorageConfigError(
                f"Relative mount path must contain ':' separator (got '{mount_path}')"
            )

        parent_mount_name, relative_path = mount_path.split(":", 1)

        # Validate parent mount exists
        if parent_mount_name not in self._mounts:
            available = ", ".join(f"'{m}'" for m in self._mounts) if self._mounts else "none"
            raise StorageConfigError(
                f"Parent mount '{parent_mount_name}' not found for relative mount '{mount_name}'. "
                f"Available mounts: {available}"
            )

        # Get parent backend and create relative wrapper
        parent_backend = self._mounts[parent_mount_name]

        # Get permissions (default: 'delete' = full access)
        permissions = config.get("permissions", "delete")

        # Validate permissions value
        valid_permissions = ("readonly", "readwrite", "delete")
        if permissions not in valid_permissions:
            raise StorageConfigError(
                f"Invalid permissions '{permissions}' for mount '{mount_name}'. "
                f"Valid values: {', '.join(valid_permissions)}"
            )

        relative_backend = RelativeMountBackend(parent_backend, relative_path, permissions)

        # The write default belongs to the mount named in the write and to it
        # alone: a relative mount has one only if it declares one — the
        # parent's does NOT leak through. Reconfiguration replaces the record.
        own_default = config.get("default_encrypted", False)
        if own_default:
            self._default_encrypted[mount_name] = self._checked_default_encrypted(
                mount_name, own_default
            )
        else:
            self._default_encrypted.pop(mount_name, None)

        self._mounts[mount_name] = relative_backend

    def _apply_permissions(
        self, mount_name: str, backend: StorageBackend, permissions: str
    ) -> StorageBackend:
        """Apply permission restrictions to a backend by wrapping with RelativeMountBackend.

        Validates that requested permissions are compatible with backend capabilities.
        For example, cannot request 'readwrite' on a read-only backend like HTTP.

        Args:
            mount_name: Name of the mount (for error messages)
            backend: The backend to wrap
            permissions: Permission level ('readonly', 'readwrite', 'delete')

        Returns:
            StorageBackend: Original backend wrapped with permission layer

        Raises:
            StorageConfigError: If permissions are invalid or incompatible with backend
        """
        # Validate permissions value
        valid_permissions = ("readonly", "readwrite", "delete")
        if permissions not in valid_permissions:
            raise StorageConfigError(
                f"Invalid permissions '{permissions}' for mount '{mount_name}'. "
                f"Valid values: {', '.join(valid_permissions)}"
            )

        # Check compatibility with backend capabilities
        caps = backend.capabilities

        # If backend is readonly, can only request 'readonly' permission
        if caps.readonly and permissions in ("readwrite", "delete"):
            raise StorageConfigError(
                f"Cannot configure mount '{mount_name}' with '{permissions}' permission. "
                f"Backend type is read-only (supports only 'readonly' permission)"
            )

        # If backend doesn't support write, cannot request write/delete
        if not caps.write and permissions in ("readwrite", "delete"):
            raise StorageConfigError(
                f"Cannot configure mount '{mount_name}' with '{permissions}' permission. "
                f"Backend does not support write operations"
            )

        # If backend doesn't support delete, cannot request delete permission
        if not caps.delete and permissions == "delete":
            raise StorageConfigError(
                f"Cannot configure mount '{mount_name}' with 'delete' permission. "
                f"Backend does not support delete operations"
            )

        # Wrap backend with permission layer (empty relative path = no prefix)
        return RelativeMountBackend(backend, relative_path="", permissions=permissions)

    def node(
        self,
        mount_or_path: Annotated[
            str | None, "Mount name or full path (mount:path format), or None for dummy node"
        ] = None,
        *path_parts: str,
        version: Annotated[
            int | str | None, "Optional version: int for index (-1=latest), str for version_id"
        ] = None,
    ) -> StorageNode:
        """Create a StorageNode pointing to a file or directory.

        This is the primary way to access files and directories. The path
        uses a mount:path format where the mount name refers to a configured
        storage backend.

        When called without arguments, creates a dummy/accumulator node that
        can be used to build content from multiple sources.

        Args:
            mount_or_path: Either:
                - Full path with mount: "mount:path/to/file"
                - Just mount name: "mount"
                - None: creates a dummy accumulator node (no storage backend)
            *path_parts: Additional path components to join
            version: Optional version specifier for versioned storage (S3, GCS).
                If specified, creates a read-only snapshot node of that version.
                Can be int (index: -1=latest, -2=previous) or str (version_id).

        Returns:
            StorageNode: A new StorageNode instance

        Raises:
            KeyError: If mount point doesn't exist (wrapped as StorageNotFoundError)
            ValueError: If path format is invalid

        Path Normalization:
            - Multiple slashes collapsed: "a//b" → "a/b"
            - Leading/trailing slashes stripped
            - No support for ".." (parent directory) - raises ValueError

        Examples:
            **Full path in one string:**

            >>> node = storage.node('home:documents/report.pdf')

            **Mount + path parts:**

            >>> node = storage.node('home', 'documents', 'report.pdf')

            **Mix styles:**

            >>> node = storage.node('home:documents', 'reports', 'q4.pdf')

            **Dynamic composition:**

            >>> user_id = '123'
            >>> year = '2024'
            >>> node = storage.node('uploads', 'users', user_id, year, 'avatar.jpg')
            >>> # Result: uploads:users/123/2024/avatar.jpg

            **Just mount (root of storage):**

            >>> node = storage.node('home')
            >>> # Result: home:

            **Path with special characters:**

            >>> # Spaces and unicode are OK
            >>> node = storage.node('home:My Documents/Café Menu.pdf')

            **Invalid paths (will raise ValueError):**

            >>> # Parent directory traversal not allowed
            >>> node = storage.node('home:documents/../etc/passwd')  # ValueError

            **Dummy node (accumulator):**

            >>> dummy = storage.node()  # No parameters
            >>> dummy.append(node1)
            >>> dummy.extend(node2, node3)
            >>> dummy.read_text()  # Concatenates all sources
        """
        # Create dummy node if no mount specified
        if mount_or_path is None:
            return StorageNode(self, None, None, version=version)

        # Parse mount and path
        if ":" in mount_or_path:
            # Format: "mount:path"
            mount_name, initial_path = mount_or_path.split(":", 1)
            path_components = [initial_path] if initial_path else []
        else:
            # Just mount name
            mount_name = mount_or_path
            path_components = []

        # Add additional path parts
        path_components.extend(path_parts)

        # Check if mount exists
        if mount_name not in self._mounts:
            raise StorageNotFoundError(
                f"Mount point '{mount_name}' not found. "
                f"Available mounts: {', '.join(self._mounts.keys())}"
            )

        # Join and normalize path
        path = "/".join(path_components)
        path = self._normalize_path(path)

        # Create and return node
        return StorageNode(self, mount_name, path, version=version)

    def iternode(self, *nodes) -> StorageNode:
        """Create a virtual node that concatenates multiple nodes lazily.

        This creates a virtual node (no physical storage) that accumulates
        references to other nodes. Content is only read when materialized
        via read_text(), read_bytes(), copy(), or zip().

        Args:
            *nodes: StorageNode instances to concatenate

        Returns:
            StorageNode: Virtual node with concatenation capability

        Examples:
            >>> # Create from existing nodes
            >>> n1 = storage.node('mem:part1.txt')
            >>> n2 = storage.node('mem:part2.txt')
            >>> combined = storage.iternode(n1, n2)
            >>>
            >>> # Read concatenated content
            >>> content = combined.read_text()
            >>>
            >>> # Add more nodes
            >>> n3 = storage.node('mem:part3.txt')
            >>> combined.append(n3)
            >>>
            >>> # Save to file
            >>> result = storage.node('mem:result.txt')
            >>> combined.copy(result)
            >>>
            >>> # Create ZIP
            >>> zip_bytes = combined.zip()
        """
        from .node import StorageNode

        node = StorageNode(self, None, None, version=None)
        node._is_virtual = True
        node._virtual_type = "iter"
        node._sources = list(nodes)
        return node

    def diffnode(self, node1: StorageNode, node2: StorageNode) -> StorageNode:
        """Create a virtual node that generates a diff between two nodes.

        This creates a virtual node that generates a unified diff between
        two text files. The diff is only computed when materialized via
        read_text() or copy().

        Args:
            node1: First node (old version)
            node2: Second node (new version)

        Returns:
            StorageNode: Virtual node with diff capability

        Raises:
            ValueError: If nodes contain binary data

        Examples:
            >>> # Compare two versions
            >>> v1 = storage.node('mem:config_v1.txt')
            >>> v2 = storage.node('mem:config_v2.txt')
            >>> diff = storage.diffnode(v1, v2)
            >>>
            >>> # Read diff
            >>> changes = diff.read_text()
            >>>
            >>> # Save diff to file
            >>> diff_file = storage.node('mem:changes.diff')
            >>> diff.copy(diff_file)
        """
        from .node import StorageNode

        node = StorageNode(self, None, None, version=None)
        node._is_virtual = True
        node._virtual_type = "diff"
        node._sources = [node1, node2]
        return node

    def _normalize_path(self, path: str) -> str:
        """Normalize a path.

        Args:
            path: Path to normalize

        Returns:
            str: Normalized path

        Raises:
            ValueError: If path contains invalid components (e.g., "..")
        """
        if not path:
            return ""

        # Check for parent directory traversal
        if ".." in path.split("/"):
            raise ValueError("Parent directory traversal (..) is not supported")

        # Normalize: strip leading/trailing slashes, collapse multiple slashes
        parts = [p for p in path.split("/") if p]
        return "/".join(parts)

    def get_mount_names(self) -> Annotated[list[str], "List of configured mount point names"]:
        """Get list of configured mount names.

        Returns:
            list[str]: List of mount point names

        Examples:
            >>> storage.configure([
            ...     {'name': 'home', 'protocol': 'local', 'path': '/home/user'},
            ...     {'name': 'uploads', 'protocol': 's3', 'bucket': 'my-bucket'}
            ... ])
            >>> print(storage.get_mount_names())
            ['home', 'uploads']
        """
        return list(self._mounts.keys())

    def has_mount(
        self, name: Annotated[str, "Mount point name to check"]
    ) -> Annotated[bool, "True if mount exists"]:
        """Check if a mount point is configured.

        Args:
            name: Mount point name to check

        Returns:
            bool: True if mount exists

        Examples:
            >>> if storage.has_mount('uploads'):
            ...     node = storage.node('uploads:file.txt')
            ... else:
            ...     print("Uploads storage not configured")
        """
        return name in self._mounts

    def __repr__(self) -> str:
        """String representation for debugging."""
        mount_names = ", ".join(self._mounts.keys()) if self._mounts else "none"
        return f"StorageManager(mounts=[{mount_names}])"
