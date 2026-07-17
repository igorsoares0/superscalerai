"""Storage layer: key resolution, roundtrip, backend selection."""

from pathlib import Path

from app.services.storage import LocalStorage, get_storage, media_type_for


def test_local_roundtrip(tmp_path):
    s = LocalStorage(tmp_path)
    s.put("uploads/a.png", b"data")
    assert s.get("uploads/a.png") == b"data"
    s.delete("uploads/a.png")
    assert not (tmp_path / "uploads" / "a.png").exists()
    s.delete("uploads/a.png")  # idempotent


def test_local_reads_legacy_full_paths(tmp_path):
    """Pre-storage-layer rows stored real paths, not keys."""
    legacy = tmp_path / "legacy.png"
    legacy.write_bytes(b"old")
    assert LocalStorage(tmp_path / "elsewhere").get(str(legacy)) == b"old"


def test_media_types():
    assert media_type_for("jobs/1/enhanced.png") == "image/png"
    assert media_type_for("jobs/1/thumb.jpg") == "image/jpeg"
    assert media_type_for("uploads/x.webp") == "image/webp"


def test_default_backend_is_local():
    get_storage.cache_clear()
    s = get_storage()
    assert isinstance(s, LocalStorage)
    assert s.base == Path("storage")
