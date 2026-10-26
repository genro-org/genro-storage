"""Integration tests for S3 storage using MinIO.

These tests require MinIO to be running. Start it with:
    docker-compose up -d

Or skip these tests if MinIO is not available.
"""

import threading

import pytest
from genro_storage import StorageManager, StorageReadConflictError


pytestmark = pytest.mark.integration


class TestS3Storage:
    """Test S3 backend using MinIO."""

    def test_s3_backend_creation(self, storage_with_s3):
        """Test that S3 backend can be created."""
        assert storage_with_s3.has_mount("test-s3")

    def test_write_and_read_text(self, storage_with_s3):
        """Test writing and reading text files on S3."""
        node = storage_with_s3.node("test-s3:test.txt")

        # Write
        node.write("Hello S3 World!")

        # Read
        content = node.read()
        assert content == "Hello S3 World!"

    def test_write_and_read_bytes(self, storage_with_s3):
        """Test writing and reading binary files on S3."""
        node = storage_with_s3.node("test-s3:test.bin")
        data = b"\x00\x01\x02\x03\x04"

        # Write
        node.write(data, mode="wb")

        # Read
        read_data = node.read(mode="rb")
        assert read_data == data

    def test_open_exclusive_create_on_existing_file(self, storage_with_s3):
        """open('xb') on an existing object raises FileExistsError and keeps the content."""
        node = storage_with_s3.node("test-s3:exclusive.bin")
        node.write_bytes(b"original")

        with pytest.raises(FileExistsError):
            with node.open("xb") as f:
                f.write(b"replacement")

        assert node.read_bytes() == b"original"

    def test_open_exclusive_create_on_new_file(self, storage_with_s3):
        """open('xb') on a missing object creates it."""
        node = storage_with_s3.node("test-s3:exclusive_new.bin")

        with node.open("xb") as f:
            f.write(b"created")

        assert node.read_bytes() == b"created"

    def test_read_bytes_during_replacement_returns_a_complete_version(self, storage_with_s3):
        """read_bytes() while another writer replaces the object returns one complete version."""
        node = storage_with_s3.node("test-s3:replaced.bin")
        versions = [bytes([i]) * 4_000_000 for i in range(2)]
        node.write_bytes(versions[0])
        stop, errors, wrong = threading.Event(), [], []

        def reader():
            while not stop.is_set():
                try:
                    if node.read_bytes() not in versions:
                        wrong.append(True)
                except OSError as exc:
                    errors.append(exc)

        thread = threading.Thread(target=reader)
        thread.start()
        for i in range(100):
            node.write_bytes(versions[i % 2])
        stop.set()
        thread.join()

        assert errors == []
        assert wrong == []

    def test_open_rb_on_replaced_object_raises_read_conflict(self, storage_with_s3):
        """Reading a file opened with 'rb' after the object is replaced raises StorageReadConflictError."""
        node = storage_with_s3.node("test-s3:streamed.bin")
        node.write_bytes(b"original")

        with node.open("rb") as f:
            node.write_bytes(b"replacement")
            with pytest.raises(StorageReadConflictError) as excinfo:
                f.read()

        assert isinstance(excinfo.value, OSError)

    def test_file_exists(self, storage_with_s3):
        """Test checking if file exists on S3."""
        node = storage_with_s3.node("test-s3:test.txt")

        # Initially doesn't exist
        assert not node.exists()

        # After writing, exists
        node.write("content")
        assert node.exists()

    def test_file_properties(self, storage_with_s3):
        """Test file properties on S3."""
        node = storage_with_s3.node("test-s3:documents/report.pdf")
        content = "Test content"

        node.write(content)

        assert node.exists()
        assert node.is_file()
        assert node.size() == len(content.encode("utf-8"))
        assert node.basename == "report.pdf"
        assert node.stem == "report"
        assert node.suffix == ".pdf"

    def test_delete_file(self, storage_with_s3):
        """Test deleting a file on S3."""
        node = storage_with_s3.node("test-s3:test.txt")

        # Create file
        node.write("content")
        assert node.exists()

        # Delete
        node.delete()
        assert not node.exists()

    def test_list_directory(self, storage_with_s3):
        """Test listing directory contents on S3."""
        # Create files with same prefix
        storage_with_s3.node("test-s3:mydir/file1.txt").write("content1")
        storage_with_s3.node("test-s3:mydir/file2.txt").write("content2")
        storage_with_s3.node("test-s3:mydir/subdir/file3.txt").write("content3")

        # List directory
        dir_node = storage_with_s3.node("test-s3:mydir")
        children = dir_node.children()
        names = [c.basename for c in children]

        # Should contain direct children
        assert "file1.txt" in names
        assert "file2.txt" in names
        # Subdirectory handling depends on S3 implementation

    def test_copy_file(self, storage_with_s3):
        """Test copying a file on S3."""
        src = storage_with_s3.node("test-s3:source.txt")
        src.write("Hello World")

        dest = storage_with_s3.node("test-s3:destination.txt")

        # Copy
        src.copy_to(dest)

        # Both should exist
        assert src.exists()
        assert dest.exists()
        assert dest.read() == "Hello World"

    def test_move_file(self, storage_with_s3):
        """Test moving a file on S3."""
        src = storage_with_s3.node("test-s3:source.txt")
        src.write("Hello World")

        dest = storage_with_s3.node("test-s3:destination.txt")

        # Move
        src.move_to(dest)

        # Only dest should exist
        assert not storage_with_s3.node("test-s3:source.txt").exists()
        assert dest.exists()
        assert dest.read() == "Hello World"

    def test_nested_paths(self, storage_with_s3):
        """Test working with nested paths on S3."""
        node = storage_with_s3.node("test-s3:a/b/c/d/file.txt")

        # S3 doesn't require mkdir, just write
        node.write("nested content")

        assert node.exists()
        assert node.read() == "nested content"

    def test_path_with_prefix(self, minio_bucket, minio_config):
        """Test S3 storage with path prefix."""
        storage = StorageManager()
        storage.configure(
            [
                {
                    "name": "test-s3-prefix",
                    "protocol": "s3",
                    "bucket": minio_bucket,
                    "prefix": "uploads/",
                    "endpoint_url": minio_config["endpoint_url"],
                    "key": minio_config["aws_access_key_id"],
                    "secret": minio_config["aws_secret_access_key"],
                }
            ]
        )

        # Write file
        node = storage.node("test-s3-prefix:test.txt")
        node.write("prefixed content")

        # Should exist under prefix
        assert node.exists()
        assert node.read() == "prefixed content"


class TestS3VersionAware:
    """The ``version_aware`` mount option (issue #84)."""

    def make_storage(self, minio_bucket, minio_config, **options):
        storage = StorageManager()
        storage.configure(
            [
                {
                    "name": "s3",
                    "protocol": "s3",
                    "bucket": minio_bucket,
                    "endpoint_url": minio_config["endpoint_url"],
                    "key": minio_config["aws_access_key_id"],
                    "secret": minio_config["aws_secret_access_key"],
                    **options,
                }
            ]
        )
        return storage

    def test_default_reports_versioning(self, minio_bucket, minio_config):
        storage = self.make_storage(minio_bucket, minio_config)
        assert storage.node("s3:a.txt").capabilities.versioning is True

    def test_disabled_reports_no_versioning(self, minio_bucket, minio_config):
        storage = self.make_storage(minio_bucket, minio_config, version_aware=False)
        capabilities = storage.node("s3:a.txt").capabilities
        assert capabilities.versioning is False
        assert capabilities.version_listing is False
        assert capabilities.version_access is False

    def test_disabled_supports_file_operations(self, minio_bucket, minio_config):
        storage = self.make_storage(minio_bucket, minio_config, version_aware=False)
        storage.node("s3:dir/one.txt").write("one")
        storage.node("s3:dir/two.txt").write("two")
        assert sorted(c.basename for c in storage.node("s3:dir").children()) == [
            "one.txt",
            "two.txt",
        ]

        storage.node("s3:dir/one.txt").copy_to(storage.node("s3:copied.txt"))
        assert storage.node("s3:copied.txt").read() == "one"

        storage.node("s3:dir/two.txt").move_to(storage.node("s3:moved.txt"))
        assert not storage.node("s3:dir/two.txt").exists()
        assert storage.node("s3:moved.txt").read() == "two"

        storage.node("s3:moved.txt").delete()
        assert not storage.node("s3:moved.txt").exists()


class TestS3ToLocalCopy:
    """Test copying between S3 and local storage."""

    def test_copy_s3_to_local(self, storage_with_s3, temp_dir):
        """Test copying file from S3 to local storage."""
        # Setup both storages
        storage = storage_with_s3
        storage.configure([{"name": "local", "protocol": "local", "path": temp_dir}])

        # Create file on S3
        s3_node = storage.node("test-s3:source.txt")
        s3_node.write("S3 content")

        # Copy to local
        local_node = storage.node("local:destination.txt")
        s3_node.copy_to(local_node)

        # Verify on local
        assert local_node.exists()
        assert local_node.read() == "S3 content"

    def test_copy_local_to_s3(self, storage_with_s3, temp_dir):
        """Test copying file from local to S3."""
        # Setup both storages
        storage = storage_with_s3
        storage.configure([{"name": "local", "protocol": "local", "path": temp_dir}])

        # Create file locally
        local_node = storage.node("local:source.txt")
        local_node.write("Local content")

        # Copy to S3
        s3_node = storage.node("test-s3:destination.txt")
        local_node.copy_to(s3_node)

        # Verify on S3
        assert s3_node.exists()
        assert s3_node.read() == "Local content"


class TestMemoryStorage:
    """Test in-memory storage backend."""

    @pytest.fixture
    def memory_storage(self):
        """Create storage with memory backend."""
        storage = StorageManager()
        storage.configure([{"name": "memory", "protocol": "memory"}])
        return storage

    def test_memory_backend_creation(self, memory_storage):
        """Test that memory backend can be created."""
        assert memory_storage.has_mount("memory")

    def test_write_and_read_text(self, memory_storage):
        """Test writing and reading text in memory."""
        node = memory_storage.node("memory:test.txt")

        node.write("Hello Memory!")
        assert node.read() == "Hello Memory!"

    def test_file_isolation(self, memory_storage):
        """Test that files are isolated in memory."""
        node1 = memory_storage.node("memory:file1.txt")
        node2 = memory_storage.node("memory:file2.txt")

        node1.write("Content 1")
        node2.write("Content 2")

        assert node1.read() == "Content 1"
        assert node2.read() == "Content 2"

    def test_memory_delete(self, memory_storage):
        """Test deleting files in memory."""
        node = memory_storage.node("memory:test.txt")

        node.write("content")
        assert node.exists()

        node.delete()
        assert not node.exists()

    def test_memory_directory_operations(self, memory_storage):
        """Test directory operations in memory."""
        # Create files
        memory_storage.node("memory:dir/file1.txt").write("c1")
        memory_storage.node("memory:dir/file2.txt").write("c2")

        # List directory
        dir_node = memory_storage.node("memory:dir")
        children = dir_node.children()
        names = [c.basename for c in children]

        assert len(names) == 2
        assert "file1.txt" in names
        assert "file2.txt" in names


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
