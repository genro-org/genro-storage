"""Implementation tests for the read restart of FsspecBackend (issue #86).

The S3 answers that RustFS cannot produce on demand (a replacement at every
attempt, the AWS error chain) are simulated by replacing ``fs.open`` on a
memory mount with a function that raises the exceptions s3fs raises.
"""

import errno

import pytest
from botocore.exceptions import ClientError
from s3fs.utils import FileExpired

from genro_storage import StorageManager, StorageReadConflictError
from genro_storage.backends.fsspec import READ_ATTEMPTS


def precondition_failed():
    """The OSError s3fs raises for a 412 answer without a Condition field."""
    error = OSError(errno.EINVAL, "At least one of the preconditions you specified did not hold")
    error.__cause__ = ClientError({"Error": {"Code": "PreconditionFailed"}}, "GetObject")
    return error


def file_expired():
    """The FileExpired s3fs raises on AWS, which wraps the OSError of the 412."""
    error = OSError(errno.EINVAL, "At least one of the pre-conditions you specified did not hold")
    error.__cause__ = ClientError({"Error": {"Code": "PreconditionFailed"}}, "GetObject")
    expired = FileExpired(filename="bucket/data.bin", e_tag='"abc"')
    expired.__cause__ = error
    return expired


@pytest.fixture
def backend():
    storage = StorageManager()
    storage.configure([{"name": "mem", "protocol": "memory"}])
    storage.node("mem:data.bin").write_bytes(b"content")
    return storage._mounts["mem"]


def replace_open(monkeypatch, backend, failures):
    """Make the next len(failures) calls of fs.open raise them, then open for real."""
    real_open = backend.fs.open
    calls = []

    def open_with_failures(*args, **kwargs):
        calls.append(args)
        if len(calls) <= len(failures):
            raise failures[len(calls) - 1]
        return real_open(*args, **kwargs)

    monkeypatch.setattr(backend.fs, "open", open_with_failures)
    return calls


def test_x_read_text_returns_the_content(backend):
    assert backend.read_text("data.bin") == "content"


def test_x_read_bytes_restarts_after_a_replacement(monkeypatch, backend):
    calls = replace_open(monkeypatch, backend, [precondition_failed()])
    assert backend.read_bytes("data.bin") == b"content"
    assert len(calls) == 2


def test_x_read_bytes_succeeds_on_the_last_attempt(monkeypatch, backend):
    calls = replace_open(monkeypatch, backend, [precondition_failed()] * (READ_ATTEMPTS - 1))
    assert backend.read_bytes("data.bin") == b"content"
    assert len(calls) == READ_ATTEMPTS


def test_x_read_bytes_raises_read_conflict_when_attempts_run_out(monkeypatch, backend):
    calls = replace_open(monkeypatch, backend, [precondition_failed()] * READ_ATTEMPTS)
    with pytest.raises(StorageReadConflictError):
        backend.read_bytes("data.bin")
    assert len(calls) == READ_ATTEMPTS


def test_x_read_bytes_restarts_after_file_expired(monkeypatch, backend):
    calls = replace_open(monkeypatch, backend, [file_expired()])
    assert backend.read_bytes("data.bin") == b"content"
    assert len(calls) == 2


def test_x_read_bytes_does_not_restart_other_errors(monkeypatch, backend):
    calls = replace_open(monkeypatch, backend, [PermissionError(errno.EACCES, "denied")])
    with pytest.raises(PermissionError):
        backend.read_bytes("data.bin")
    assert len(calls) == 1
