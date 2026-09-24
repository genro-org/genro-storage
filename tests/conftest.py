"""Pytest fixtures for testing with MinIO (S3-compatible storage).

This module provides fixtures to set up and tear down MinIO for integration tests.
MinIO provides a local S3-compatible object storage for testing.

Async Testing Support:
    The async branch of ``@smartasync`` lives in ``test_async.py``, as real
    coroutines. There is deliberately no flag to re-run the sync suite "in async
    mode": the only way to do that would be to push each sync test body onto a
    worker thread, where no event loop runs, so ``is_async_context()`` is False
    and the sync branch executes anyway. A ``--async-mode`` flag doing exactly
    that used to live here; it was removed because it verified nothing.
"""

import pytest
import boto3
from botocore.exceptions import ClientError
import time
import os
import tempfile
import shutil
import socket


def is_service_available(host, port, timeout=1):
    """Check if a service is available at the given host and port.

    Args:
        host: Hostname or IP address
        port: Port number
        timeout: Connection timeout in seconds

    Returns:
        bool: True if service is reachable, False otherwise
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture(scope="session")
def minio_config():
    """MinIO connection configuration.

    Returns:
        dict: Configuration for connecting to MinIO
    """
    return {
        "endpoint_url": os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        "aws_access_key_id": os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        "aws_secret_access_key": os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        "region_name": "us-east-1",  # MinIO doesn't care, but boto3 requires it
    }


@pytest.fixture(scope="session")
def minio_client(minio_config):
    """Create boto3 S3 client connected to MinIO.

    Args:
        minio_config: MinIO configuration fixture

    Returns:
        boto3.client: S3 client connected to MinIO

    Raises:
        pytest.skip: If MinIO is not available
    """
    client = boto3.client("s3", **minio_config)

    # Check if MinIO is available
    try:
        client.list_buckets()
    except Exception as e:
        pytest.skip(f"MinIO not available: {e}")

    return client


@pytest.fixture
def minio_bucket(minio_client):
    """Create a temporary test bucket in MinIO WITHOUT versioning.

    Args:
        minio_client: MinIO S3 client fixture

    Yields:
        str: Name of the created bucket (versioning NOT enabled)

    The bucket is automatically cleaned up after the test.
    Note: For versioned buckets, use minio_versioned_bucket instead.
    """
    bucket_name = f"test-bucket-{int(time.time())}"

    # Create bucket WITHOUT versioning
    try:
        minio_client.create_bucket(Bucket=bucket_name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "BucketAlreadyExists":
            raise

    yield bucket_name

    # Cleanup: delete all objects then bucket
    try:
        # List and delete all objects
        response = minio_client.list_objects_v2(Bucket=bucket_name)
        if "Contents" in response:
            objects = [{"Key": obj["Key"]} for obj in response["Contents"]]
            if objects:
                minio_client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects})

        # Delete bucket
        minio_client.delete_bucket(Bucket=bucket_name)
    except Exception as e:
        print(f"Warning: Failed to cleanup bucket {bucket_name}: {e}")


@pytest.fixture
def minio_versioned_bucket(minio_client):
    """Create a temporary test bucket in MinIO WITH versioning enabled.

    Args:
        minio_client: MinIO S3 client fixture

    Yields:
        str: Name of the versioned bucket

    The bucket and all versions are automatically cleaned up after the test.
    """
    bucket_name = f"test-versioned-{int(time.time())}"

    # Create bucket
    minio_client.create_bucket(Bucket=bucket_name)

    # Enable versioning
    minio_client.put_bucket_versioning(
        Bucket=bucket_name, VersioningConfiguration={"Status": "Enabled"}
    )

    yield bucket_name

    # Cleanup: delete all versions then bucket
    try:
        # List and delete all object versions
        paginator = minio_client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket_name):
            # Delete versions
            if "Versions" in page:
                versions = [
                    {"Key": v["Key"], "VersionId": v["VersionId"]} for v in page["Versions"]
                ]
                if versions:
                    minio_client.delete_objects(
                        Bucket=bucket_name, Delete={"Objects": versions, "Quiet": True}
                    )

            # Delete delete markers
            if "DeleteMarkers" in page:
                markers = [
                    {"Key": m["Key"], "VersionId": m["VersionId"]} for m in page["DeleteMarkers"]
                ]
                if markers:
                    minio_client.delete_objects(
                        Bucket=bucket_name, Delete={"Objects": markers, "Quiet": True}
                    )

        # Delete bucket
        minio_client.delete_bucket(Bucket=bucket_name)
    except Exception as e:
        print(f"Warning: Failed to cleanup versioned bucket {bucket_name}: {e}")


@pytest.fixture
def s3_storage_config(minio_bucket, minio_config):
    """Storage configuration for S3 backend using MinIO.

    Args:
        minio_bucket: MinIO bucket fixture
        minio_config: MinIO configuration fixture

    Returns:
        dict: Configuration dict for StorageManager
    """
    return {
        "name": "test-s3",
        "protocol": "s3",
        "bucket": minio_bucket,
        "endpoint_url": minio_config["endpoint_url"],
        "key": minio_config["aws_access_key_id"],
        "secret": minio_config["aws_secret_access_key"],
    }


@pytest.fixture
def storage_manager():
    """Create a fresh StorageManager for each test.

    Returns:
        StorageManager: Empty storage manager
    """
    from genro_storage import StorageManager

    return StorageManager()


@pytest.fixture
def s3_fs(minio_config):
    """Create fsspec S3 filesystem connected to MinIO.

    Args:
        minio_config: MinIO configuration fixture

    Returns:
        S3FileSystem: fsspec S3 filesystem for MinIO
    """
    import fsspec

    try:
        fs = fsspec.filesystem(
            "s3",
            key=minio_config["aws_access_key_id"],
            secret=minio_config["aws_secret_access_key"],
            client_kwargs={"endpoint_url": minio_config["endpoint_url"]},
        )

        # Test connection
        fs.ls("/")

        # Create test-bucket if it doesn't exist
        try:
            fs.mkdir("test-bucket")
        except:
            pass  # Bucket may already exist

        return fs
    except Exception as e:
        pytest.skip(f"MinIO not available: {e}")


@pytest.fixture
def storage_with_s3(s3_storage_config):
    """Create StorageManager configured with MinIO S3 backend.

    Args:
        s3_storage_config: S3 storage configuration fixture

    Returns:
        StorageManager: Configured storage manager with S3 backend
    """
    from genro_storage import StorageManager

    storage = StorageManager()
    storage.configure([s3_storage_config])

    return storage
