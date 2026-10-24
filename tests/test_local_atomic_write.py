"""Contract tests: replacing a file on the local backend is atomic for readers.

A concurrent reader sees either the complete old content or the complete new
content, never an empty or partial file (issue #83).
"""

import json
import os
import shutil
import sys
import tempfile
import threading

import pytest

from genro_storage import StorageManager

PAD = "x" * 200_000
GENERATIONS = 100


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture
def storage(temp_dir):
    """Create a StorageManager with local storage."""
    mgr = StorageManager()
    mgr.configure([{"name": "data", "protocol": "local", "path": temp_dir}])
    return mgr


def payload(generation):
    return json.dumps({"generation": generation, "pad": PAD})


def count_invalid_reads(storage, write):
    """Run write(generation) repeatedly while a thread parses the file."""
    write(0)
    counters = {"reads": 0, "invalid": 0}
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                json.loads(storage.node("data:pointer.json").read_bytes())
            except ValueError:
                counters["invalid"] += 1
            counters["reads"] += 1

    thread = threading.Thread(target=reader)
    thread.start()
    for generation in range(1, GENERATIONS):
        write(generation)
    stop.set()
    thread.join()
    assert counters["reads"] > 0
    return counters["invalid"]


class TestConcurrentReaders:
    """A reader never observes a partially replaced file."""

    def test_write_bytes(self, storage):
        node = storage.node("data:pointer.json")
        assert count_invalid_reads(storage, lambda g: node.write_bytes(payload(g).encode())) == 0

    def test_write_text(self, storage):
        node = storage.node("data:pointer.json")
        assert count_invalid_reads(storage, lambda g: node.write_text(payload(g))) == 0

    def test_open_wb(self, storage):
        node = storage.node("data:pointer.json")

        def write(generation):
            with node.open("wb") as f:
                f.write(payload(generation).encode())

        assert count_invalid_reads(storage, write) == 0

    def test_open_w(self, storage):
        node = storage.node("data:pointer.json")

        def write(generation):
            with node.open("w") as f:
                f.write(payload(generation))

        assert count_invalid_reads(storage, write) == 0


class TestReplaceOutcome:
    """What the destination and its directory look like after a write."""

    def test_no_temporary_files_left(self, storage, temp_dir):
        node = storage.node("data:pointer.json")
        node.write_bytes(b"one")
        node.write_text("two")
        with node.open("wb") as f:
            f.write(b"three")
        assert os.listdir(temp_dir) == ["pointer.json"]
        assert node.read_bytes() == b"three"

    def test_error_inside_open_keeps_old_content(self, storage, temp_dir):
        node = storage.node("data:pointer.json")
        node.write_text("old")
        with pytest.raises(RuntimeError):
            with node.open("w") as f:
                f.write("partial")
                raise RuntimeError("writer failed")
        assert node.read_text() == "old"
        assert os.listdir(temp_dir) == ["pointer.json"]

    def test_open_w_creates_parent_directories(self, storage):
        node = storage.node("data:a/b/pointer.json")
        with node.open("w") as f:
            f.write("nested")
        assert node.read_text() == "nested"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    def test_existing_file_keeps_its_mode(self, storage, temp_dir):
        node = storage.node("data:pointer.json")
        node.write_text("old")
        path = os.path.join(temp_dir, "pointer.json")
        os.chmod(path, 0o640)
        node.write_text("new")
        assert os.stat(path).st_mode & 0o777 == 0o640

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    def test_new_file_follows_umask(self, storage, temp_dir):
        previous = os.umask(0o027)
        try:
            storage.node("data:pointer.json").write_text("new")
        finally:
            os.umask(previous)
        path = os.path.join(temp_dir, "pointer.json")
        assert os.stat(path).st_mode & 0o777 == 0o640
