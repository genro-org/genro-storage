# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Pythonic storage configuration grammar.

A ``genro-builders`` grammar that describes a storage configuration as a set
of typed, self-documenting method calls instead of a dict/YAML blob. One
``@element`` per protocol: the tag IS the protocol, so there is no ``protocol``
field anywhere — the adapter reads ``node.node_tag``. Each element documents
the mount from its own signature; required fields are the parameters without a
default, validated by the signature machinery (a missing one raises
``ValueError: Validation failed: required attribute ...``). ``permissions`` is a
``Literal`` so an invalid value is rejected by the same signature check.

The required fields mirror exactly those that ``manager.py:_configure_mount``
raises ``StorageConfigError`` on today; legacy aliases (``path``/``prefix``/
``base_url``/``key``/``secret``) are deliberately dropped — one name per field is
the point of the change.

The module ships the vocabulary and the dialect as two classes.
:class:`StorageGrammar` is a plain mixin carrying only the ``@element``
declarations, so a host document can mount it (``StorageManager.grammar``, whose
builder class ``get_subbuilder`` fabricates on first use);
:class:`StorageConfig` composes it with ``BuilderBase`` into the standalone
dialect ``configure()`` consumes. No element declares ``parent_tags`` — the
``mounts`` container's ``sub_tags`` is the only containment rule, which is what
lets one set of elements serve both shapes.

Every mount lives inside the ``mounts`` collection, keyed by ``name``: two
mounts sharing a name raise ``duplicate collection key``. Values that come from
outside the recipe — secrets, endpoints, deployment roots — are declared IN PLACE
as a ``BagResolver``: the fields that carry them are typed ``... | BagResolver``
and ``configure()`` resolves each one once, where the value lives, with no
datastore entry to pair a pointer with.

At-rest encryption is two fields: ``storage_key`` on the ``mounts`` collection
carries the key material for the whole recipe, ``default_encrypted`` gives a
mount the default of the per-write ``encrypted`` parameter. Encryption itself is
declared at the write site — the mount holds a default, never a state.

Example::

    from genro_bag.resolvers import EnvResolver

    class MyConfig(StorageConfig):
        def main(self, root):
            m = root.mounts(storage_key=EnvResolver("STORAGE_KEY"))
            m.local(name="home", base_path="/srv/data")
            m.local(name="secure", base_path="/srv/secure", default_encrypted=True)
            m.s3(name="uploads", bucket="my-bucket",
                 secret_key=EnvResolver("S3_SECRET"))
            m.relative(name="public", path="home:public", permissions="readonly")
"""

from __future__ import annotations

from typing import Callable, Literal

from genro_bag import BagResolver
from genro_builders.builder import BuilderBase, element

#: Permission level accepted by every mount element. Declared once, reused
#: everywhere; the ``Literal`` in the signature IS the validation — never
#: re-checked in Python.
Permissions = Literal["readonly", "readwrite", "delete"]

#: Every protocol tag plus ``relative``, in the order they are declared below.
#: Used as the ``mounts`` container ``sub_tags`` so only these tags are valid
#: children.
_MOUNT_TAGS = (
    "local,memory,s3,gcs,azure,http,smb,sftp,"
    "zip,tar,git,github,webdav,libarchive,base64,relative"
)


class StorageGrammar:
    """The storage vocabulary alone: ``mounts`` plus one element per protocol.

    A plain mixin, deliberately not a builder — so it can be either composed
    into a standalone dialect (:class:`StorageConfig`, below) or mounted inside
    a host document, where ``get_subbuilder`` fabricates the builder class for
    it. ``StorageManager.grammar`` exposes it for that second use.

    No element declares ``parent_tags``: containment is governed by the
    ``mounts`` container's ``sub_tags``, so the same elements are valid under a
    standalone ``mounts`` root and under a host envelope node.
    """

    @element(sub_tags=_MOUNT_TAGS, collection_key="name", node_label="mounts")
    def mounts(self, *, storage_key: str | BagResolver | None = None):
        """Collection of named mount points; each child is keyed by its ``name``.

        ``storage_key`` is the at-rest key material shared by the encrypted
        mounts of the collection: one or more comma-separated Fernet keys with
        ``MultiFernet`` semantics — the FIRST encrypts, ALL decrypt, which is
        what makes key rotation a configuration change. It is the one field a
        recipe should never spell out inline: declare it as a ``BagResolver``.
        """

    # -- local / in-process ----------------------------------------------
    @element()
    def local(
        self,
        *,
        name: str,
        base_path: str | Callable | BagResolver,
        base_url: str | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """Local filesystem mount; ``base_path`` may be a callable resolved at runtime.

        ``default_encrypted`` is the default of the per-write ``encrypted``
        parameter on this mount — ``True`` for the default encryption domain, a
        string for a named one — overridable at every write site in both
        directions; it requires ``storage_key`` on ``mounts``.
        """

    @element()
    def memory(
        self,
        *,
        name: str,
        base_path: str | BagResolver | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """In-memory filesystem, for tests and ephemeral scratch space."""

    @element()
    def base64(
        self,
        *,
        name: str,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """Inline base64 data mount with writable paths; no configuration."""

    # -- cloud object stores ---------------------------------------------
    @element()
    def s3(
        self,
        *,
        name: str,
        bucket: str,
        base_path: str | BagResolver | None = None,
        region: str | None = None,
        anon: bool | str | BagResolver | None = None,
        access_key: str | BagResolver | None = None,
        secret_key: str | BagResolver | None = None,
        endpoint_url: str | BagResolver | None = None,
        version_aware: bool | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """S3 or S3-compatible bucket; MinIO and friends via ``endpoint_url``.

        ``version_aware=False`` disables object-version listing, for servers
        without ``ListObjectVersions``; the default keeps it on.
        """

    @element()
    def gcs(
        self,
        *,
        name: str,
        bucket: str,
        base_path: str | BagResolver | None = None,
        token: str | BagResolver | None = None,
        project: str | None = None,
        endpoint_url: str | BagResolver | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """Google Cloud Storage bucket."""

    @element()
    def azure(
        self,
        *,
        name: str,
        container: str,
        account_name: str,
        account_key: str | BagResolver | None = None,
        sas_token: str | BagResolver | None = None,
        connection_string: str | BagResolver | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """Azure Blob Storage container; ``account_name`` identifies the account."""

    # -- remote protocols ------------------------------------------------
    @element()
    def http(
        self,
        *,
        name: str,
        base_path: str | BagResolver,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """Read-only HTTP(S) tree rooted at ``base_path``."""

    @element()
    def smb(
        self,
        *,
        name: str,
        host: str | BagResolver,
        share: str,
        base_path: str | BagResolver | None = None,
        username: str | BagResolver | None = None,
        password: str | BagResolver | None = None,
        domain: str | None = None,
        port: int | str | BagResolver | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """SMB/CIFS network share on ``host``."""

    @element()
    def sftp(
        self,
        *,
        name: str,
        host: str | BagResolver,
        username: str | BagResolver,
        base_path: str | BagResolver | None = None,
        password: str | BagResolver | None = None,
        port: int | str | BagResolver | None = None,
        key_filename: str | None = None,
        passphrase: str | BagResolver | None = None,
        timeout: int | str | BagResolver | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """SFTP server accessed over SSH on ``host``."""

    @element()
    def webdav(
        self,
        *,
        name: str,
        url: str | BagResolver,
        username: str | BagResolver | None = None,
        password: str | BagResolver | None = None,
        token: str | BagResolver | None = None,
        cert: str | None = None,
        verify_ssl: bool | str | BagResolver | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """WebDAV server (Nextcloud, ownCloud, SharePoint) at ``url``."""

    # -- archives --------------------------------------------------------
    @element()
    def zip(
        self,
        *,
        name: str,
        file: str,
        mode: str | None = None,
        target_protocol: str | None = None,
        target_options: dict | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """ZIP archive addressed as a filesystem; ``file`` is the archive path."""

    @element()
    def tar(
        self,
        *,
        name: str,
        file: str,
        compression: str | None = None,
        target_protocol: str | None = None,
        target_options: dict | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """TAR archive addressed as a filesystem; ``file`` is the archive path."""

    @element()
    def libarchive(
        self,
        *,
        name: str,
        file: str,
        target_protocol: str | None = None,
        target_options: dict | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """Universal archive (7z, rar, iso, ...) via libarchive; ``file`` is the path."""

    # -- version control -------------------------------------------------
    @element()
    def git(
        self,
        *,
        name: str,
        base_path: str | BagResolver,
        ref: str | None = None,
        fo: str | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """Local Git repository; ``base_path`` is the repo, ``ref`` a commit/branch/tag."""

    @element()
    def github(
        self,
        *,
        name: str,
        org: str,
        repo: str,
        sha: str | None = None,
        username: str | BagResolver | None = None,
        token: str | BagResolver | None = None,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """Remote GitHub repository via the API (``org``/``repo``)."""

    # -- composition -----------------------------------------------------
    @element()
    def relative(
        self,
        *,
        name: str,
        path: str,
        default_encrypted: bool | str = False,
        permissions: Permissions | None = None,
    ):
        """Child mount of an already-declared parent — ``path`` is 'parent:subpath'.

        ``default_encrypted`` is this mount's own; the parent's default does
        not leak through.
        """


class StorageConfig(BuilderBase, StorageGrammar):
    """Standalone builder for a storage configuration: the grammar as a dialect.

    Subclass it and populate ``mounts`` in ``main``, passing a ``BagResolver``
    wherever a value comes from outside the recipe; ``page.create()`` builds and
    resolves it.
    No renderer or compiler: the configuration is consumed by the adapter, not
    rendered.
    """

    _name = "storage_config"
