"""Golden-set calibration harness (SPEC.md Quality Roadmap item 1).

Sweeps Clarity parameters over a set of reference images with a fixed
seed and scores every run with objective metrics:

- identity: SFace cosine similarity between the largest face in the
  original and in the (downscaled) result. 1.0 = same person.
- fidelity: PSNR of the result downscaled back to input size vs the
  original. Measures content drift, not quality.
- detail:  Laplacian variance of the result's luminance — texture/detail
  energy. Higher = more perceived detail (and, past a point, artifacts).

Usage:
    UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python validation/calibrate.py

Results land in validation/outputs/calibration/: one PNG per run,
plus results.json with every metric, resumable (existing runs skipped).
"""

import asyncio
import io
import itertools
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root, any cwd

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "outputs" / "calibration"
SFACE = HERE / "face_recognition_sface_2021dec.onnx"
YUNET = HERE.parent / "app" / "pipeline" / "resources" / "face_detection_yunet_2023mar.onnx"

SEED = 42
MAX_INPUT_WIDTH = 896  # keeps each run ~US$0.02

# golden set: (name, path). People photos — the portrait preset's domain.
GOLDEN = [
    ("tst", HERE / "inputs" / "tst.jpg"),
    ("csz", HERE / "inputs" / "csz.png"),
    ("degraded", HERE / "outputs" / "20260711-001642-portrait" / "before.png"),
]

# 2026-07-16 sweep: creativity/resemblance grid at hdr=6, steps=18.
# 2026-07-21 sweep: hdr/steps grid at the calibrated portrait point.
CREATIVITY = [0.20]
RESEMBLANCE = [1.2]
HDR = [3, 6, 9]
STEPS = [12, 18, 24, 30]


def load_env() -> None:
    for line in (HERE / ".env").read_text().splitlines():
        k, _, v = line.strip().partition("=")
        if k and v:
            os.environ[k] = v.strip('"').strip("'")


# ---- metrics ----------------------------------------------------------------


def bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def largest_face(image_bgr: np.ndarray):
    detector = cv2.FaceDetectorYN_create(str(YUNET), "", (image_bgr.shape[1], image_bgr.shape[0]))
    _, faces = detector.detect(image_bgr)
    if faces is None or len(faces) == 0:
        return None
    return max(faces, key=lambda f: f[2] * f[3])


def identity_similarity(original: Image.Image, result: Image.Image) -> float | None:
    """SFace cosine similarity between aligned face crops (None = no face)."""
    recognizer = cv2.FaceRecognizerSF_create(str(SFACE), "")
    embeddings = []
    small = result.resize(original.size, Image.LANCZOS)
    for img in (original, small):
        arr = bgr(img)
        face = largest_face(arr)
        if face is None:
            return None
        aligned = recognizer.alignCrop(arr, face)
        embeddings.append(recognizer.feature(aligned).copy())
    return float(recognizer.match(embeddings[0], embeddings[1], cv2.FaceRecognizerSF_FR_COSINE))


def fidelity_psnr(original: Image.Image, result: Image.Image) -> float:
    small = np.asarray(result.resize(original.size, Image.LANCZOS), dtype=np.float64)
    ref = np.asarray(original.convert("RGB"), dtype=np.float64)
    mse = ((small - ref) ** 2).mean()
    return float(10 * math.log10(255**2 / mse)) if mse else 99.0

def detail_energy(result: Image.Image) -> float:
    gray = cv2.cvtColor(np.asarray(result.convert("RGB")), cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# ---- sweep ------------------------------------------------------------------


async def run_sweep() -> list[dict]:
    from app.pipeline.presets import BASE_NEGATIVE, BASE_PROMPT, PRESETS
    from app.pipeline.stages.captioner import TASK, parse_caption
    from app.providers.replicate import ReplicateProvider

    preset = PRESETS["portrait"]
    provider = ReplicateProvider(token=os.environ["REPLICATE_API_TOKEN"])
    OUT.mkdir(parents=True, exist_ok=True)
    results_path = OUT / "results.json"
    results: list[dict] = json.loads(results_path.read_text()) if results_path.exists() else []
    done = {
        (r["image"], r["creativity"], r["resemblance"], r["hdr"], r.get("steps", 18))
        for r in results
    }

    for name, path in GOLDEN:
        original = Image.open(path).convert("RGB")
        if original.width > MAX_INPUT_WIDTH:
            original = original.resize(
                (MAX_INPUT_WIDTH, round(original.height * MAX_INPUT_WIDTH / original.width)),
                Image.LANCZOS,
            )
        buf = io.BytesIO()
        original.save(buf, format="PNG")
        url = await provider.upload(buf.getvalue(), f"{name}.png")

        pred = await provider.run("captioner", {"image": url, "task_input": TASK})
        caption = parse_caption(pred["output"]) or "portrait"
        print(f"{name}: caption ok ({len(caption)} chars)")

        for creativity, resemblance, hdr, steps in itertools.product(
            CREATIVITY, RESEMBLANCE, HDR, STEPS
        ):
            key = (name, creativity, resemblance, hdr, steps)
            if key in done:
                continue
            pred = await provider.run(
                "generative-upscaler",
                {
                    "image": url,
                    "prompt": BASE_PROMPT.format(caption=caption) + preset.style_terms,
                    "negative_prompt": BASE_NEGATIVE + preset.negative_terms,
                    "creativity": creativity,
                    "resemblance": resemblance,
                    "dynamic": hdr,
                    "scale_factor": 2,
                    "seed": SEED,
                    "num_inference_steps": steps,
                },
            )
            data = await provider.download(pred["output"][0])
            result = Image.open(io.BytesIO(data)).convert("RGB")
            out_name = f"{name}-c{creativity}-r{resemblance}-h{hdr}-s{steps}.png"
            result.save(OUT / out_name)

            row = {
                "image": name,
                "creativity": creativity,
                "resemblance": resemblance,
                "hdr": hdr,
                "steps": steps,
                "file": out_name,
                "identity": identity_similarity(original, result),
                "fidelity": round(fidelity_psnr(original, result), 2),
                "detail": round(detail_energy(result), 1),
                "gpu_s": round(pred["metrics"]["predict_time"], 1),
            }
            results.append(row)
            results_path.write_text(json.dumps(results, indent=1))
            print(f"  c={creativity} r={resemblance} h={hdr} s={steps}: "
                  f"id={row['identity'] and round(row['identity'], 3)} "
                  f"psnr={row['fidelity']} detail={row['detail']} ({row['gpu_s']}s)")
    return results


if __name__ == "__main__":
    load_env()
    asyncio.run(run_sweep())
