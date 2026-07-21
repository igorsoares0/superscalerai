"""PostProcessor sharpening (gate + anti-halo clamp) and seam scan."""

import numpy as np
from PIL import Image

from app.pipeline.stages.post_processor import seam_scan, sharpen


def checkerboard(size: int = 128, cell: int = 4) -> Image.Image:
    tile = np.indices((size, size)).sum(axis=0) // cell % 2 * 200 + 20
    return Image.fromarray(np.stack([tile] * 3, axis=-1).astype(np.uint8))


def detail(img: Image.Image) -> float:
    import cv2

    gray = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def test_sharpen_adds_detail_on_texture():
    rng = np.random.default_rng(7)
    soft = Image.fromarray(
        np.clip(rng.normal(128, 30, (128, 128, 3)), 0, 255).astype(np.uint8)
    ).resize((256, 256), Image.BILINEAR)  # upscale-soft texture
    assert detail(sharpen(soft)) > detail(soft) * 1.05


def test_sharpen_never_overshoots_neighborhood_extremes():
    """Overshoot past local extremes is exactly what forms a halo."""
    import cv2

    img = np.full((64, 64, 3), 40, np.uint8)
    img[:, 32:] = 220  # hard vertical edge
    out = np.asarray(sharpen(Image.fromarray(img)), dtype=np.int16)
    kernel = np.ones((3, 3), np.uint8)
    lo = cv2.erode(img, kernel).astype(np.int16)
    hi = cv2.dilate(img, kernel).astype(np.int16)
    assert (out >= lo - 1).all() and (out <= hi + 1).all()  # 1 = uint8 rounding


def test_sharpen_gate_leaves_flat_noise_alone():
    rng = np.random.default_rng(7)
    flat = np.clip(rng.normal(128, 1.5, (128, 128, 3)), 0, 255).astype(np.uint8)
    out = np.asarray(sharpen(Image.fromarray(flat)), dtype=np.float32)
    assert np.abs(out - flat.astype(np.float32)).mean() < 0.5  # noise not amplified


def _textured_photo(w: int = 400, h: int = 300) -> Image.Image:
    """Locally smooth field (gradient < ~0.7/px), the regime where a tile
    seam is visible — skin, walls, sky. Seams crossing busy texture are
    below the scanner's zero-false-positive operating point by design."""
    y, x = np.indices((h, w), dtype=np.float32)
    base = 120 + 40 * np.sin(x / 60) * np.cos(y / 45)
    return Image.fromarray(np.stack([base] * 3, axis=-1).astype(np.uint8))


def test_seam_scan_catches_tile_seam():
    original = _textured_photo()
    seamed = np.asarray(original, dtype=np.int16).copy()
    seamed[:, 200:] += 8
    found = seam_scan(Image.fromarray(np.clip(seamed, 0, 255).astype(np.uint8)), original)
    assert any(s["axis"] == "x" and abs(s["position"] - 199) <= 1 for s in found)


def test_seam_scan_quiet_without_seam():
    original = _textured_photo()
    # a legitimate hard edge present in BOTH images must not be flagged
    arr = np.asarray(original).copy()
    arr[:, 100:] = np.clip(arr[:, 100:].astype(np.int16) + 90, 0, 255).astype(np.uint8)
    both = Image.fromarray(arr)
    assert seam_scan(both, both) == []
    assert seam_scan(original, original) == []
