# Copyright (c) 2025 Softwell Srl, Milano, Italy
# SPDX-License-Identifier: Apache-2.0

"""The async half of the ``@smartasync`` surface.

Every I/O method of :class:`~genro_storage.node.StorageNode` is decorated with
``@smartasync``: in a sync caller it runs directly, in a coroutine it returns an
awaitable. The rest of the suite only ever exercises the first branch, so
without this module the async contract the README advertises is entirely
unverified.

The tests here run as real coroutines, which is the only way to get
``is_async_context()`` to be true. Wrapping a sync test body in
``asyncio.to_thread`` does NOT work: the body lands on a worker thread with no
running loop, ``@smartasync`` takes the sync branch, and the test proves
nothing about async at all.

Two properties are checked throughout:

- the awaited result equals what the sync call returns;
- the un-awaited call is an awaitable, i.e. the decorator really did switch
  branch rather than doing the work eagerly.
"""

import asyncio
import inspect

import pytest
from genro_toolbox import is_async_context

from genro_storage import StorageManager

try:
    from cryptography.fernet import Fernet

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False


@pytest.fixture
def storage(tmp_path):
    """A manager with one local mount and one memory mount."""
    manager = StorageManager()
    manager.configure(
        [
            {"name": "home", "protocol": "local", "base_path": str(tmp_path)},
            {"name": "mem", "protocol": "memory"},
        ]
    )
    return manager


@pytest.mark.asyncio
async def test_async_context_is_detected():
    """The premise of every test below: a coroutine IS an async context."""
    assert is_async_context() is True
    # And a worker thread is not - this is why --async-mode used to be a no-op.
    assert await asyncio.to_thread(is_async_context) is False


@pytest.mark.asyncio
async def test_write_then_read_text(storage):
    node = storage.node("home:greeting.txt")
    await node.write_text("hello async")
    assert await node.read_text() == "hello async"


@pytest.mark.asyncio
async def test_write_then_read_bytes(storage):
    node = storage.node("home:payload.bin")
    await node.write_bytes(b"\x00\x01\x02")
    assert await node.read_bytes() == b"\x00\x01\x02"


@pytest.mark.asyncio
async def test_io_methods_return_awaitables(storage):
    """The decorator switches branch instead of doing the work eagerly."""
    node = storage.node("home:probe.txt")

    pending = node.write_text("probe")
    assert inspect.isawaitable(pending)
    await pending

    pending = node.exists()
    assert inspect.isawaitable(pending)
    assert await pending is True


@pytest.mark.asyncio
async def test_stat_surface(storage):
    node = storage.node("home:sized.txt")
    await node.write_text("12345")

    assert await node.exists() is True
    assert await node.is_file() is True
    assert await node.is_dir() is False
    assert await node.size() == 5
    assert await node.mtime() is not None
    assert await node.md5hash() == await node.md5hash()


@pytest.mark.asyncio
async def test_non_io_properties_stay_sync(storage):
    """Properties are not decorated: they must not become awaitables."""
    node = storage.node("home:report.pdf")

    assert node.mimetype == "application/pdf"
    assert node.basename == "report.pdf"
    assert not inspect.isawaitable(node.path)


@pytest.mark.asyncio
async def test_directory_surface(storage):
    parent = storage.node("home:tree")
    await parent.mkdir()

    for name in ("a.txt", "b.txt"):
        await storage.node(f"home:tree/{name}").write_text(name)

    children = await parent.children()
    assert sorted(child.basename for child in children) == ["a.txt", "b.txt"]
    assert await parent.is_dir() is True


@pytest.mark.asyncio
async def test_copy_between_mounts(storage):
    source = storage.node("home:source.txt")
    await source.write_text("carried across")

    dest = storage.node("mem:copied.txt")
    await source.copy_to(dest)

    assert await dest.read_text() == "carried across"
    assert await source.exists() is True


@pytest.mark.asyncio
async def test_delete(storage):
    node = storage.node("home:transient.txt")
    await node.write_text("here")
    assert await node.exists() is True

    await node.delete()
    assert await node.exists() is False


@pytest.mark.asyncio
async def test_concurrent_writes_are_independent(storage):
    """The point of the async surface: many files in flight at once."""

    async def write_one(index: int) -> str:
        node = storage.node(f"home:batch/file_{index}.txt")
        await node.write_text(f"content {index}")
        return await node.read_text()

    results = await asyncio.gather(*(write_one(i) for i in range(10)))
    assert results == [f"content {i}" for i in range(10)]


@pytest.mark.skipif(not HAS_CRYPTOGRAPHY, reason="requires the [encryption] extra")
@pytest.mark.asyncio
async def test_encrypted_write_and_read(tmp_path):
    """Encryption rides on write_bytes/read_bytes, so it must work awaited too."""
    manager = StorageManager()
    manager.configure(
        [{"name": "secure", "protocol": "local", "base_path": str(tmp_path)}],
        storage_key=Fernet.generate_key().decode(),
    )

    node = manager.node("secure:token.json")
    await node.write_text('{"tok": 1}', encrypted=True)

    assert await node.read_text() == '{"tok": 1}'
    # The stored bytes carry the envelope, not the plaintext.
    assert (tmp_path / "token.json").read_bytes().startswith(b"#GNRE1:")


def test_sync_still_works_alongside(storage):
    """A plain sync test in the same module: no event loop leaks into it."""
    node = storage.node("home:sync.txt")
    node.write_text("plain")
    assert node.read_text() == "plain"
    assert node.exists() is True
