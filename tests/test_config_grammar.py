# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Tests for the ``StorageConfig`` grammar (``genro_storage.storage_grammar``).

The grammar is a data-only ``genro-builders`` dialect: one ``@element`` per
protocol, each mount living inside the ``mounts`` collection keyed by ``name``.
These tests exercise the grammar in isolation (no ``StorageManager``), through
the same ``_build`` idiom the genro-builders tests use
(``tests/test_collection_key.py:42``): a throw-away subclass whose ``main``
recipe is supplied per test, built with ``create()``.

Validation is the signature's own: a required field (a parameter without a
default) missing raises ``Validation failed: required attribute ...``; a
``permissions`` value outside the ``Literal`` raises ``Validation failed``; two
mounts with the same ``name`` clash on the collection key; a tag that is not a
mount inside ``mounts`` violates its ``sub_tags``.

The boundary is flat: no element declares ``parent_tags``, so the same elements
build under a standalone ``mounts`` root and under a host envelope that mounts
``StorageManager.grammar`` — both shapes are exercised at the end of the module.
"""

from __future__ import annotations

import pytest
from genro_bag.resolver import BagCbResolver
from genro_builders.builder import BuilderBase, element

from genro_storage.storage_grammar import StorageConfig
from genro_storage.manager import StorageManager


def _build(main):
    """Build a ``StorageConfig`` whose ``mounts`` are populated by ``main(root)``.

    Mirrors ``genro-builders`` ``tests/test_collection_key.py:_build``: a fresh
    subclass gets ``main`` injected, then ``create()`` calls it. A grammar error
    inside the recipe propagates out of ``create()``.
    """

    class _H(StorageConfig):
        pass

    _H.main = lambda self, root: main(root)
    page = _H()
    page.create()
    return page


def _mounts(page):
    """The ``mounts`` collection bag of a built page."""
    return page.source.get_node("mounts").value


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_mounts_keyed_by_name_and_tagged_by_protocol():
    """Each mount is labelled by its ``name`` and carries its protocol as node_tag."""

    def rec(root):
        m = root.mounts()
        m.local(name="home", base_path="/srv/data")
        m.s3(name="uploads", bucket="my-bucket", endpoint_url="http://minio:9000")
        m.memory(name="scratch")

    mounts = _mounts(_build(rec))
    assert [n.label for n in mounts] == ["home", "uploads", "scratch"]
    assert mounts.get_node("home").node_tag == "local"
    assert mounts.get_node("uploads").node_tag == "s3"
    assert mounts.get_node("scratch").node_tag == "memory"


def test_only_provided_fields_are_captured_as_attributes():
    """Unset optional fields are dropped; the set ones survive as node attributes."""
    mounts = _mounts(_build(lambda root: root.mounts().s3(name="uploads", bucket="b")))
    attrs = dict(mounts.get_node("uploads").attr)
    assert attrs == {"name": "uploads", "bucket": "b"}


def test_version_aware_captured_on_an_s3_mount():
    """``version_aware=False`` survives as a node attribute of the s3 mount."""
    mounts = _mounts(
        _build(lambda root: root.mounts().s3(name="uploads", bucket="b", version_aware=False))
    )
    assert mounts.get_node("uploads").attr.get("version_aware") is False


@pytest.mark.parametrize("value", [True, "acmespa"])
def test_default_encrypted_captured_on_a_local_mount(value):
    """``default_encrypted`` accepts both shapes of the write parameter it defaults."""
    mounts = _mounts(
        _build(
            lambda root: root.mounts().local(name="v", base_path="/srv", default_encrypted=value)
        )
    )
    assert mounts.get_node("v").attr.get("default_encrypted") == value


def test_relative_mount_builds():
    """``relative(name=..., path='parent:sub')`` builds with its permissions."""

    def rec(root):
        m = root.mounts()
        m.local(name="home", base_path="/srv/data")
        m.relative(name="public", path="home:public", permissions="readonly")

    node = _mounts(_build(rec)).get_node("public")
    assert node.node_tag == "relative"
    assert node.attr.get("path") == "home:public"
    assert node.attr.get("permissions") == "readonly"


@pytest.mark.parametrize("value", ["readonly", "readwrite", "delete"])
def test_valid_permissions_accepted(value):
    """Every permission in the ``Literal`` is accepted."""
    mounts = _mounts(_build(lambda root: root.mounts().memory(name="m", permissions=value)))
    assert mounts.get_node("m").attr.get("permissions") == value


# ---------------------------------------------------------------------------
# Resolver-capable fields: a ``BagResolver`` sits in the recipe where the value
# lives, and passes the signature type check on the field that declares it
# ---------------------------------------------------------------------------


def test_resolver_accepted_on_resolver_capable_field():
    """A ``BagResolver`` on a resolver-capable field is stored unresolved by the grammar."""
    resolver = BagCbResolver(lambda: "s3cr3t")
    mounts = _mounts(
        _build(lambda root: root.mounts().s3(name="uploads", bucket="b", secret_key=resolver))
    )
    # The grammar only records it; resolution happens in ``configure()``.
    assert mounts.get_node("uploads").attr.get("secret_key") is resolver


def test_resolver_accepted_on_azure_secret_field():
    """The azure secret fields accept a ``BagResolver`` like every other backend."""
    resolver = BagCbResolver(lambda: "k3y")
    mounts = _mounts(
        _build(
            lambda root: root.mounts().azure(
                name="blobs", container="c", account_name="acct", account_key=resolver
            )
        )
    )
    assert mounts.get_node("blobs").attr.get("account_key") is resolver


def test_resolver_accepted_on_wide_typed_field():
    """The wide-typed ``port`` accepts a resolver as well as a native value."""
    resolver = BagCbResolver(lambda: 445)
    mounts = _mounts(
        _build(lambda root: root.mounts().smb(name="share", host="h", share="s", port=resolver))
    )
    assert mounts.get_node("share").attr.get("port") is resolver


def test_env_resolver_is_the_documented_idiom_for_environment_values(tmp_path, monkeypatch):
    """``EnvResolver('VAR')`` — the docs' idiom — feeds a field from the environment.

    Unlike a callback resolver it carries only the variable NAME, so it
    serializes with the recipe and the dumped configuration round-trips.
    """
    from genro_bag.resolvers import EnvResolver

    from genro_storage import StorageManager
    from genro_storage.storage_grammar import StorageConfig

    monkeypatch.setenv("TEST_BASE_PATH", str(tmp_path))
    recipe = type(
        "_EnvConfig",
        (StorageConfig,),
        {
            "main": lambda self, root: root.mounts().local(
                name="home", base_path=EnvResolver("TEST_BASE_PATH")
            )
        },
    )

    storage = StorageManager()
    storage.configure(recipe)

    node = storage.node("home:probe.txt")
    node.write_text("via EnvResolver")
    assert (tmp_path / "probe.txt").read_text() == "via EnvResolver"


def test_native_int_still_accepted_on_wide_typed_field():
    """The wide type keeps the native value valid too."""
    mounts = _mounts(
        _build(lambda root: root.mounts().smb(name="share", host="h", share="s", port=445))
    )
    assert mounts.get_node("share").attr.get("port") == 445


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_missing_required_field_raises():
    """A required field (``s3.bucket``) missing raises on ``required attribute``."""
    with pytest.raises(ValueError, match="required attribute"):
        _build(lambda root: root.mounts().s3(name="uploads"))


def test_missing_name_raises():
    """``name`` is required on every mount element."""
    with pytest.raises(ValueError, match="required attribute"):
        _build(lambda root: root.mounts().memory())


def test_invalid_permissions_raises():
    """A ``permissions`` value outside the ``Literal`` raises ``Validation failed``."""
    with pytest.raises(ValueError, match="Validation failed"):
        _build(lambda root: root.mounts().local(name="home", base_path="/srv", permissions="bogus"))


def test_duplicate_name_raises():
    """Two mounts resolving to the same ``name`` clash on the collection key."""

    def rec(root):
        m = root.mounts()
        m.memory(name="dup")
        m.memory(name="dup")

    with pytest.raises(ValueError, match="duplicate collection key"):
        _build(rec)


def test_foreign_tag_inside_mounts_raises():
    """``mounts`` accepts only the mount tags: anything else violates its sub_tags."""
    with pytest.raises(ValueError):
        _build(lambda root: root.mounts().mounts())


# ---------------------------------------------------------------------------
# Flat boundary: the same elements work standalone and mounted under a host
# ---------------------------------------------------------------------------


def test_mount_outside_mounts_is_allowed():
    """No element declares parent_tags, so a mount on the root is not a grammar error.

    Containment is the ``mounts`` container's ``sub_tags`` alone — what makes the
    same elements usable under a host envelope (see the test below).
    """
    page = _build(lambda root: root.s3(name="x", bucket="b"))
    # Outside the ``mounts`` collection nothing keys the node by name, so it
    # carries the auto-label: the point is only that building it does not raise.
    node = list(page.source)[0]
    assert node.node_tag == "s3"
    assert node.attr.get("name") == "x"


def test_grammar_mounts_under_a_host_envelope():
    """A host dialect mounts ``StorageManager.grammar`` and builds mounts under it.

    The host declares ``_meta={"subbuilder": "app:grammar"}``; the recipe passes
    the manager as ``app``, ``get_subbuilder`` fabricates the builder class from
    the mixin, and the envelope's children resolve against the storage grammar.
    """

    class _Host(BuilderBase):
        _name = "storage_grammar_host"

        @element(_meta={"subbuilder": "app:grammar"})
        def storage(self, app=None):
            """Envelope node whose subtree is governed by ``app.grammar``."""

    class _Page(_Host):
        def main(self, root):
            m = root.storage(app=StorageManager).mounts()
            m.local(name="home", base_path="/srv/data")
            m.memory(name="scratch")

    page = _Page()
    page.create()
    envelope = list(page.source)[0]
    mounts = envelope.value.get_node("mounts").value
    assert [n.label for n in mounts] == ["home", "scratch"]
    assert mounts.get_node("home").node_tag == "local"
