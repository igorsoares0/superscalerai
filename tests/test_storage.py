"""Storage layer: key resolution, roundtrip, backend selection."""

from pathlib import Path

import pytest

from app.services.storage import LocalStorage, get_storage, media_type_for


def test_local_roundtrip(tmp_path):
    s = LocalStorage(tmp_path)
    s.put("uploads/a.png", b"data")
    assert s.get("uploads/a.png") == b"data"
    s.delete("uploads/a.png")
    assert not (tmp_path / "uploads" / "a.png").exists()
    s.delete("uploads/a.png")  # idempotent


def test_local_reads_legacy_prefixed_keys(tmp_path):
    """Pre-storage-layer rows stored "storage/uploads/x.png" — the key with
    the storage dir still on the front. That prefix is stripped; it is NOT
    trusted as a path of its own (see test_local_refuses_keys_outside_base)."""
    base = tmp_path / "storage"
    (base / "uploads").mkdir(parents=True)
    (base / "uploads" / "a.png").write_bytes(b"old")
    assert LocalStorage(base).get("storage/uploads/a.png") == b"old"


def test_local_refuses_keys_outside_base(tmp_path):
    """Every key is ours today. This is the one place where a key from
    anywhere else would turn into a file read, so it stays shut by
    construction rather than by who happens to call it."""
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"not yours")
    s = LocalStorage(tmp_path / "storage")

    for key in (str(outside), "../secret.txt", "uploads/../../secret.txt", "/etc/passwd"):
        with pytest.raises(FileNotFoundError):
            s.get(key)


def test_local_stream_matches_get(tmp_path):
    s = LocalStorage(tmp_path)
    payload = bytes(range(256)) * 4000  # > one CHUNK
    s.put("uploads/big.png", payload)
    assert b"".join(s.stream("uploads/big.png")) == payload


def test_local_stream_reports_a_missing_file_before_streaming(tmp_path):
    """The 404 in /download depends on this: a generator that only fails on
    its first chunk fails after the response has already begun."""
    with pytest.raises(FileNotFoundError):
        LocalStorage(tmp_path).stream("uploads/gone.png")


def test_media_types():
    assert media_type_for("jobs/1/enhanced.png") == "image/png"
    assert media_type_for("jobs/1/thumb.jpg") == "image/jpeg"
    assert media_type_for("uploads/x.webp") == "image/webp"


def test_default_backend_is_local():
    get_storage.cache_clear()
    s = get_storage()
    assert isinstance(s, LocalStorage)
    assert s.base == Path("storage")
