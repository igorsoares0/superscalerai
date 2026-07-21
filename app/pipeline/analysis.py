"""CPU image analysis used by the Analyzer stage. No GPU, no network.

Face detection: OpenCV YuNet (MIT-licensed ONNX, bundled in resources/).
Text detection: morphological-gradient heuristic — since 2026-07-21 only
the FALLBACK for when Florence-2's OCR call fails (see Captioner); good
enough to trigger protection on logos/labels over flat backgrounds
(false positives only cost a protected patch).
"""

import math
from pathlib import Path

import cv2
import numpy as np

from app.pipeline.context import Box

YUNET_PATH = Path(__file__).parent / "resources" / "face_detection_yunet_2023mar.onnx"

# margin around detected faces: zoom-and-enhance needs surrounding context
# (hair, hats) to reconstruct the region coherently
FACE_MARGIN = 0.35


def _clamp_box(x0: float, y0: float, x1: float, y1: float, w: int, h: int) -> Box:
    return (max(0, int(x0)), max(0, int(y0)), min(w, int(x1)), min(h, int(y1)))


def detect_faces(bgr: np.ndarray) -> list[Box]:
    h, w = bgr.shape[:2]
    scale = min(1.0, 1024 / max(h, w))
    small = cv2.resize(bgr, (round(w * scale), round(h * scale))) if scale < 1.0 else bgr

    detector = cv2.FaceDetectorYN_create(str(YUNET_PATH), "", (small.shape[1], small.shape[0]))
    _, faces = detector.detect(small)
    if faces is None:
        return []

    boxes: list[Box] = []
    for face in faces:
        x, y, fw, fh = (float(v) / scale for v in face[:4])
        mx, my = fw * FACE_MARGIN, fh * FACE_MARGIN
        boxes.append(_clamp_box(x - mx, y - my, x + fw + mx, y + fh + my, w, h))
    return boxes


def detect_text_regions(bgr: np.ndarray, exclude: list[Box] | None = None) -> list[Box]:
    """`exclude`: boxes (e.g. faces) whose contents must never be flagged as
    text — eyes/eyebrows look text-like to the gradient heuristic."""
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    # connect characters horizontally into word/line blobs
    connected = cv2.morphologyEx(
        bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (int(w * 0.01) | 1, 3))
    )
    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    area = w * h
    boxes: list[Box] = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        frac = (cw * ch) / area
        if not 0.0003 < frac < 0.02:  # too small to matter / too big to be text
            continue
        if not ch * 1.5 <= cw <= ch * 15:  # text lines are wide, but bare lines/edges are wider
            continue
        # text has dense internal edges
        fill = cv2.countNonZero(bw[y : y + ch, x : x + cw]) / (cw * ch)
        if fill < 0.25:
            continue
        cx, cy = x + cw / 2, y + ch / 2
        if any(e[0] <= cx <= e[2] and e[1] <= cy <= e[3] for e in exclude or []):
            continue
        pad = ch // 2
        boxes.append(_clamp_box(x - pad, y - pad, x + cw + pad, y + ch + pad, w, h))
    return _merge_overlapping(boxes)


def ocr_text_regions(pairs: list[tuple[list[float], str]], w: int, h: int) -> list[Box]:
    """Florence-2 'OCR with Region' (quad, label) pairs -> protect boxes.

    Florence hallucinates tiny labels of non-Latin digits on textless
    images (observed 2026-07-21 on the validation photos), so a region
    only qualifies with >=2 real glyphs (letters or ASCII digits) and
    non-trivial area. The floor is 10x lower than the heuristic's: OCR
    quads are tight around glyphs (a real chest logo measured 0.0003).
    """
    boxes: list[Box] = []
    for quad, label in pairs:
        text = label.removeprefix("</s>").strip()
        if sum(c.isalpha() or (c.isascii() and c.isdigit()) for c in text) < 2:
            continue
        xs, ys = quad[0::2], quad[1::2]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        if (x1 - x0) * (y1 - y0) < 0.0001 * w * h:
            continue
        pad = (y1 - y0) / 2  # glyph edges need margin, like the heuristic
        boxes.append(_clamp_box(x0 - pad, y0 - pad, x1 + pad, y1 + pad, w, h))
    return _merge_overlapping(boxes)


def _merge_overlapping(boxes: list[Box]) -> list[Box]:
    merged: list[Box] = []
    for box in sorted(boxes, key=lambda b: (b[1], b[0])):
        for i, other in enumerate(merged):
            if box[0] < other[2] and box[2] > other[0] and box[1] < other[3] and box[3] > other[1]:
                merged[i] = (
                    min(box[0], other[0]), min(box[1], other[1]),
                    max(box[2], other[2]), max(box[3], other[3]),
                )
                break
        else:
            merged.append(box)
    return merged


def blur_level(bgr: np.ndarray) -> str:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    if variance < 50:
        return "high"
    if variance < 200:
        return "medium"
    return "low"


def noise_level(bgr: np.ndarray) -> str:
    """Immerkær's fast noise variance estimate."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float64)
    h, w = gray.shape
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)
    sigma = np.abs(cv2.filter2D(gray, -1, kernel)).sum()
    sigma = sigma * math.sqrt(0.5 * math.pi) / (6.0 * (w - 2) * (h - 2))
    if sigma < 2:
        return "low"
    if sigma < 6:
        return "medium"
    return "high"
