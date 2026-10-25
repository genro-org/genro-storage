"""Tests for LocalStorage backend and StorageNode integration."""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from genro_storage import StorageManager, StorageNotFoundError, StorageConfigError


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
    mgr.configure([{"name": "test", "protocol": "local", "path": temp_dir}])
    return mgr


class TestStorageManager:
    """Test StorageManager configuration and mount management."""

    def test_configure_from_list(self, temp_dir):
        """Test configuring from Python list."""
        storage = StorageManager()
        storage.configure([{"name": "test", "protocol": "local", "path": temp_dir}])

        assert storage.has_mount("test")
        assert "test" in storage.get_mount_names()

    def test_configure_missing_name(self):
        """Test error when mount name is missing."""
        storage = StorageManager()

        with pytest.raises(StorageConfigError, match="missing required field: 'name'"):
            storage.configure([{"protocol": "local", "path": "/tmp"}])

    def test_configure_missing_type(self):
        """Test error when protocol is missing."""
        storage = StorageManager()

        with pytest.raises(StorageConfigError, match="missing required field: 'protocol'"):
            storage.configure([{"name": "test", "path": "/tmp"}])

    def test_configure_with_protocol_field(self, temp_dir):
        """Test configuring with 'protocol' field (new standard)."""
        storage = StorageManager()
        storage.configure([{"name": "test", "protocol": "local", "base_path": temp_dir}])
        assert "test" in storage._mounts

    def test_configure_with_deprecated_type_field(self, temp_dir):
        """Test that 'type', the field name up to 0.4.4, still configures a mount."""
        storage = StorageManager()

        with pytest.warns(DeprecationWarning, match="'type' field is deprecated"):
            storage.configure([{"name": "test", "type": "local", "path": temp_dir}])

        assert storage.has_mount("test")
        assert storage.node("test:file.txt").fullpath == "test:file.txt"

    def test_configure_missing_local_path(self):
        """Test error when local storage path is missing."""
        storage = StorageManager()

        with pytest.raises(StorageConfigError, match="missing required field: 'base_path'"):
            storage.configure([{"name": "test", "protocol": "local"}])

    def test_configure_unknown_type(self):
        """Test error for unknown storage type."""
        storage = StorageManager()

        with pytest.raises(StorageConfigError, match="Unknown storage type"):
            storage.configure([{"name": "test", "protocol": "unknown"}])

    def test_configure_replace_mount(self, temp_dir):
        """Test that configuring same mount name replaces it."""
        storage = StorageManager()
        storage.configure([{"name": "test", "protocol": "local", "path": temp_dir}])

        # Configure again with same name
        storage.configure([{"name": "test", "protocol": "local", "path": temp_dir}])

        # Should still have only one mount
        assert len(storage.get_mount_names()) == 1

    def test_node_mount_not_found(self, storage):
        """Test error when accessing non-existent mount."""
        with pytest.raises(StorageNotFoundError, match="Mount point 'missing' not found"):
            storage.node("missing:file.txt")


class TestFileOperations:
    """Test basic file operations."""

    def test_write_and_read_text(self, storage):
        """Test writing and reading text files."""
        node = storage.node("test:file.txt")

        # Write
        node.write("Hello World")

        # Read
        content = node.read()
        assert content == "Hello World"

    def test_write_and_read_bytes(self, storage):
        """Test writing and reading binary files."""
        node = storage.node("test:file.bin")
        data = b"\x00\x01\x02\x03\x04"

        # Write
        node.write(data, mode="wb")

        # Read
        read_data = node.read(mode="rb")
        assert read_data == data

    def test_file_exists(self, storage):
        """Test checking if file exists."""
        node = storage.node("test:file.txt")

        # Initially doesn't exist
        assert not node.exists()

        # After writing, exists
        node.write("content")
        assert node.exists()

    def test_is_file_is_dir(self, storage):
        """Test isfile and isdir properties."""
        file_node = storage.node("test:file.txt")
        dir_node = storage.node("test:directory")

        # Create file
        file_node.write("content")
        assert file_node.is_file()
        assert not file_node.is_dir()

        # Create directory
        dir_node.mkdir()
        assert dir_node.is_dir()
        assert not dir_node.is_file()

    def test_file_size(self, storage):
        """Test getting file size."""
        node = storage.node("test:file.txt")
        content = "Hello World"

        node.write(content)

        assert node.size() == len(content.encode("utf-8"))

    def test_file_mtime(self, storage):
        """Test getting modification time."""
        node = storage.node("test:file.txt")

        before = datetime.now().timestamp()
        node.write("content")

        mtime = node.mtime()
        # Allow small timing tolerance (filesystem may round timestamps)
        assert abs(mtime - before) < 2  # Within 2 seconds is reasonable

    def test_file_path_properties(self, storage):
        """Test path-related properties."""
        node = storage.node("test:documents/report.pdf")

        assert node.fullpath == "test:documents/report.pdf"
        assert node.basename == "report.pdf"
        assert node.stem == "report"
        assert node.suffix == ".pdf"

    def test_file_open_context_manager(self, storage):
        """Test using open() with context manager."""
        node = storage.node("test:file.txt")

        # Write using context manager
        with node.open("w") as f:
            f.write("Line 1\n")
            f.write("Line 2\n")

        # Read using context manager
        with node.open("r") as f:
            content = f.read()

        assert content == "Line 1\nLine 2\n"

    def test_open_exclusive_create_on_existing_file(self, storage):
        """open('xb') on an existing file raises FileExistsError and keeps the content."""
        node = storage.node("test:file.bin")
        node.write_bytes(b"original")

        with pytest.raises(FileExistsError):
            with node.open("xb") as f:
                f.write(b"replacement")

        assert node.read_bytes() == b"original"

    def test_file_delete(self, storage):
        """Test deleting a file."""
        node = storage.node("test:file.txt")

        # Create file
        node.write("content")
        assert node.exists()

        # Delete
        node.delete()
        assert not node.exists()

        # Delete again (idempotent)
        node.delete()  # Should not raise error

    def test_url_without_base_url(self, storage):
        """Test URL generation returns None when no base_url configured.

        Related to issue #55.
        """
        node = storage.node("test:static/css/style.css")
        node.write("body { color: red; }")

        # Without base_url, should return None
        url = node.url()
        assert url is None

    def test_url_with_base_url(self, temp_dir):
        """Test URL generation with base_url configured.

        Related to issue #55.
        """
        # Create storage with base_url
        mgr = StorageManager()
        mgr.configure([{
            "name": "static",
            "protocol": "local",
            "path": temp_dir,
            "base_url": "/static"
        }])

        # Create file
        node = mgr.node("static:css/style.css")
        node.write("body { color: blue; }")

        # Should generate URL with base_url
        url = node.url()
        assert url == "/static/css/style.css"

    def test_url_with_base_url_trailing_slash(self, temp_dir):
        """Test URL generation handles trailing slashes correctly.

        Related to issue #55.
        """
        # Create storage with base_url that has trailing slash
        mgr = StorageManager()
        mgr.configure([{
            "name": "static",
            "protocol": "local",
            "path": temp_dir,
            "base_url": "/static/"  # trailing slash
        }])

        node = mgr.node("static:js/app.js")
        node.write("console.log('test');")

        url = node.url()
        # Should normalize to single slash
        assert url == "/static/js/app.js"

    def test_url_with_nested_path(self, temp_dir):
        """Test URL generation with deeply nested paths.

        Related to issue #55.
        """
        mgr = StorageManager()
        mgr.configure([{
            "name": "assets",
            "protocol": "local",
            "path": temp_dir,
            "base_url": "/assets"
        }])

        node = mgr.node("assets:images/icons/favicon.ico")
        node.write(b"\x00", mode="wb")

        url = node.url()
        assert url == "/assets/images/icons/favicon.ico"

    def test_resolved_path_returns_absolute_path(self, temp_dir):
        """Test resolved_path returns absolute filesystem path.

        Related to issue #59.
        """
        mgr = StorageManager()
        mgr.configure([{
            "name": "test",
            "protocol": "local",
            "path": temp_dir
        }])

        # Test with simple path
        node = mgr.node("test:file.txt")
        node.write("content")

        resolved = node.resolved_path
        assert resolved is not None
        assert resolved.startswith('/')  # Absolute path
        assert resolved.endswith('/file.txt')
        assert temp_dir in resolved

    def test_resolved_path_with_nested_directories(self, temp_dir):
        """Test resolved_path with nested directory structure.

        Related to issue #59.
        """
        mgr = StorageManager()
        mgr.configure([{
            "name": "test",
            "protocol": "local",
            "path": temp_dir
        }])

        node = mgr.node("test:deep/nested/path/file.txt")
        node.write("content")

        resolved = node.resolved_path
        assert resolved is not None
        assert resolved.endswith('/deep/nested/path/file.txt')
        assert temp_dir in resolved

    def test_resolved_path_for_nonexistent_file(self, temp_dir):
        """Test resolved_path works for files that don't exist yet.

        Related to issue #59.
        """
        mgr = StorageManager()
        mgr.configure([{
            "name": "test",
            "protocol": "local",
            "path": temp_dir
        }])

        # File doesn't exist yet
        node = mgr.node("test:future_file.txt")
        assert not node.exists()

        # But resolved_path still returns the path
        resolved = node.resolved_path
        assert resolved is not None
        assert resolved.endswith('/future_file.txt')
        assert temp_dir in resolved

        # Can use it to create the file
        with open(resolved, 'w') as f:
            f.write("created via resolved_path")

        # Now it exists via genro-storage too
        assert node.exists()
        assert node.read() == "created via resolved_path"


class TestDirectoryOperations:
    """Test directory operations."""

    def test_mkdir(self, storage):
        """Test creating a directory."""
        node = storage.node("test:mydir")

        assert not node.exists()

        node.mkdir()

        assert node.exists()
        assert node.is_dir()

    def test_mkdir_at_mount_root_on_memory(self):
        """Test mkdir of a top-level directory on a backend with no root entry."""
        storage = StorageManager()
        storage.configure([{"name": "mem", "protocol": "memory"}])

        node = storage.node("mem:project")
        node.mkdir()

        assert node.exists()
        assert node.is_dir()

    def test_mkdir_parents(self, storage):
        """Test creating nested directories."""
        node = storage.node("test:a/b/c/d")

        node.mkdir(parents=True)

        assert node.exists()
        assert node.is_dir()

    def test_mkdir_exist_ok(self, storage):
        """Test mkdir with exist_ok flag."""
        node = storage.node("test:mydir")

        node.mkdir()

        # Should raise error without exist_ok
        with pytest.raises(FileExistsError):
            node.mkdir(exist_ok=False)

        # Should not raise with exist_ok
        node.mkdir(exist_ok=True)

    def test_list_directory(self, storage):
        """Test listing directory contents."""
        # Create directory with files
        dir_node = storage.node("test:mydir")
        dir_node.mkdir()

        # Create some files
        dir_node.child("file1.txt").write("content1")
        dir_node.child("file2.txt").write("content2")
        dir_node.child("subdir").mkdir()

        # List children
        children = dir_node.children()
        names = [c.basename for c in children]

        assert len(children) == 3
        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "subdir" in names

    def test_child_method(self, storage):
        """Test child() with single path and varargs."""
        parent = storage.node("test:documents")
        parent.mkdir()

        # Single component
        child = parent.child("report.pdf")
        child.write("content")

        assert child.fullpath == "test:documents/report.pdf"
        assert child.exists()

        # Single path with slashes
        child2 = parent.child("2024/reports/q4.pdf")
        assert child2.fullpath == "test:documents/2024/reports/q4.pdf"

        # Varargs
        child3 = parent.child("2024", "reports", "q4.pdf")
        assert child3.fullpath == "test:documents/2024/reports/q4.pdf"

    def test_parent_property(self, storage):
        """Test parent property."""
        node = storage.node("test:documents/reports/file.pdf")

        parent = node.parent
        assert parent.fullpath == "test:documents/reports"

        grandparent = parent.parent
        assert grandparent.fullpath == "test:documents"

    def test_dirname_property(self, storage):
        """Test dirname property."""
        node = storage.node("test:documents/reports/file.pdf")

        # dirname should return parent fullpath as string
        assert node.dirname == "test:documents/reports"
        assert node.dirname == node.parent.fullpath

        # Test with parent's dirname
        parent = node.parent
        assert parent.dirname == "test:documents"

        # Test with root level
        root_file = storage.node("test:file.txt")
        assert root_file.dirname == "test:"

    def test_ext_property(self, storage):
        """Test ext property (extension without dot)."""
        # File with extension
        node = storage.node("test:document.pdf")
        assert node.ext == "pdf"
        assert node.suffix == ".pdf"  # Compare with suffix

        # Multiple dots
        node_tar = storage.node("test:archive.tar.gz")
        assert node_tar.ext == "gz"
        assert node_tar.suffix == ".gz"

        # No extension
        node_no_ext = storage.node("test:README")
        assert node_no_ext.ext == ""
        assert node_no_ext.suffix == ""

        # Directory (no extension)
        node_dir = storage.node("test:documents/")
        assert node_dir.ext == ""

    def test_splitext_method(self, storage):
        """Test splitext() method."""
        # Simple case
        node = storage.node("test:documents/report.pdf")
        name, ext = node.splitext()
        assert name == "documents/report"
        assert ext == ".pdf"

        # Multiple dots
        node_tar = storage.node("test:archive.tar.gz")
        name, ext = node_tar.splitext()
        assert name == "archive.tar"
        assert ext == ".gz"

        # No extension
        node_no_ext = storage.node("test:README")
        name, ext = node_no_ext.splitext()
        assert name == "README"
        assert ext == ""

        # Root level file
        node_root = storage.node("test:file.txt")
        name, ext = node_root.splitext()
        assert name == "file"
        assert ext == ".txt"

    def test_ext_attributes_property(self, storage, temp_dir):
        """Test ext_attributes property (batch attributes)."""
        # Create a test file
        test_file = storage.node("test:testfile.txt")
        test_file.write("test content")

        # Get attributes together
        mtime, size, isdir = test_file.ext_attributes

        assert mtime is not None
        assert isinstance(mtime, float)
        assert size == 12  # 'test content' is 12 bytes
        assert isdir is False

        # Test with directory
        dir_node = storage.node("test:testdir/")
        dir_node.mkdir()

        mtime_dir, size_dir, isdir_dir = dir_node.ext_attributes
        assert mtime_dir is not None
        assert size_dir is None  # Directories have None size
        assert isdir_dir is True

        # Test with non-existent file
        nonexistent = storage.node("test:nonexistent.txt")
        mtime_none, size_none, isdir_none = nonexistent.ext_attributes
        assert mtime_none is None
        assert size_none is None
        assert isdir_none is False

        # Cleanup
        test_file.delete()
        dir_node.delete()

    def test_delete_directory(self, storage):
        """Test deleting a directory recursively."""
        dir_node = storage.node("test:mydir")
        dir_node.mkdir()

        # Create files inside
        dir_node.child("file1.txt").write("content")
        dir_node.child("subdir").mkdir()
        dir_node.child("subdir", "file2.txt").write("content")

        # Delete recursively
        dir_node.delete()

        assert not dir_node.exists()


class TestCopyMove:
    """Test copy and move operations."""

    def test_copy_file(self, storage):
        """Test copying a file."""
        src = storage.node("test:source.txt")
        src.write("Hello World")

        dest = storage.node("test:destination.txt")

        # Copy
        result = src.copy_to(dest)

        # Both should exist
        assert src.exists()
        assert dest.exists()
        assert result.fullpath == dest.fullpath

        # Content should be the same
        assert dest.read() == "Hello World"

    def test_copy_with_string_dest(self, storage):
        """Test copying with string destination."""
        src = storage.node("test:source.txt")
        src.write("content")

        # Copy using string
        dest = src.copy_to("test:destination.txt")

        assert dest.exists()
        assert dest.fullpath == "test:destination.txt"

    def test_move_file(self, storage):
        """Test moving a file."""
        src = storage.node("test:source.txt")
        src.write("Hello World")

        dest = storage.node("test:destination.txt")

        # Move
        result = src.move_to(dest)

        # Source should not exist, dest should
        assert not storage.node("test:source.txt").exists()
        assert dest.exists()
        assert result.fullpath == dest.fullpath

        # Content preserved
        assert dest.read() == "Hello World"

    def test_move_updates_self(self, storage):
        """Test that move updates the node itself."""
        node = storage.node("test:old.txt")
        node.write("content")

        original_id = id(node)

        # Move
        node.move_to("test:new.txt")

        # Same object, updated path
        assert id(node) == original_id
        assert node.fullpath == "test:new.txt"
        assert node.exists()

    def test_copy_directory(self, storage):
        """Test copying a directory recursively."""
        # Create source directory with contents
        src = storage.node("test:src_dir")
        src.mkdir()
        src.child("file1.txt").write("content1")
        src.child("subdir").mkdir()
        src.child("subdir", "file2.txt").write("content2")

        # Copy
        dest = storage.node("test:dest_dir")
        src.copy_to(dest)

        # Check structure copied
        assert dest.exists()
        assert dest.child("file1.txt").exists()
        assert dest.child("subdir").exists()
        assert dest.child("subdir", "file2.txt").exists()

        # Check content
        assert dest.child("file1.txt").read() == "content1"
        assert dest.child("subdir", "file2.txt").read() == "content2"


class TestPathNormalization:
    """Test path handling and normalization."""

    def test_path_with_slashes(self, storage):
        """Test various path formats."""
        # These should all work
        n1 = storage.node("test:a/b/c")
        n2 = storage.node("test", "a", "b", "c")
        n3 = storage.node("test:a", "b", "c")

        assert n1.fullpath == "test:a/b/c"
        assert n2.fullpath == "test:a/b/c"
        assert n3.fullpath == "test:a/b/c"

    def test_path_parent_traversal_blocked(self, storage):
        """Test that .. in paths is blocked."""
        with pytest.raises(ValueError, match="Parent directory traversal"):
            storage.node("test:documents/../etc/passwd")

    def test_root_of_mount(self, storage):
        """Test accessing root of mount."""
        root = storage.node("test:")

        assert root.fullpath == "test:"
        assert root.is_dir()


class TestEncodings:
    """Test different text encodings."""

    def test_utf8_encoding(self, storage):
        """Test UTF-8 encoding (default)."""
        node = storage.node("test:utf8.txt")
        content = "Hello 世界 🌍"

        node.write(content)
        assert node.read() == content

    def test_latin1_encoding(self, storage):
        """Test Latin-1 encoding."""
        node = storage.node("test:latin1.txt")
        content = "Héllo Wørld"

        node.write(content, mode="w", encoding="latin-1")
        assert node.read(mode="r", encoding="latin-1") == content


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_read_nonexistent_file(self, storage):
        """Test reading a file that doesn't exist."""
        node = storage.node("test:missing.txt")

        with pytest.raises(FileNotFoundError):
            node.read()

    def test_size_of_nonexistent_file(self, storage):
        """Test getting size of nonexistent file."""
        node = storage.node("test:missing.txt")

        with pytest.raises(FileNotFoundError):
            _ = node.size()

    def test_mtime_of_nonexistent_file(self, storage):
        """Test getting mtime of nonexistent file raises FileNotFoundError.

        This is the correct behavior: metadata properties that require
        the file to exist should raise FileNotFoundError, consistent
        with read operations.

        Boolean properties (exists, isfile, isdir) return False instead.
        See issue #58.
        """
        node = storage.node("test:missing.txt")

        # Boolean properties should not raise
        assert node.exists() is False
        assert node.is_file() is False
        assert node.is_dir() is False

        # Metadata properties should raise
        with pytest.raises(FileNotFoundError):
            _ = node.mtime()

        with pytest.raises(FileNotFoundError):
            _ = node.size()

    def test_size_of_directory(self, storage):
        """Test getting size of directory (should error)."""
        node = storage.node("test:mydir")
        node.mkdir()

        with pytest.raises(ValueError, match="directory"):
            _ = node.size()

    def test_empty_file(self, storage):
        """Test working with empty files."""
        node = storage.node("test:empty.txt")

        node.write("")
        assert node.exists()
        assert node.size() == 0
        assert node.read() == ""

    def test_nested_directory_creation(self, storage):
        """Test creating deeply nested directories."""
        deep = storage.node("test:a/b/c/d/e/f/g/h")
        deep.mkdir(parents=True)

        assert deep.exists()
        assert deep.is_dir()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
