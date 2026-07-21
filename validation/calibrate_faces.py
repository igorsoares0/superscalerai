"""Zoom-and-enhance (face crop) calibration harness.

Mirrors LocalEnhancers._zoom_and_enhance exactly: the analyzer's face box
(YuNet + FACE_MARGIN), Clarity at scale_factor=4 with NO prompt, fixed
seed — then sweeps creativity/resemblance around the production point
(0.25/0.9) to check it against the main calibration's finding that
identity collapses above creativity 0.20.

Crops are downscaled to the small-face regime (the only case where the
Planner triggers repair): a face crop <40% of a 896px-wide frame.

Usage:
    UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python validation/calibrate_faces.py

Results in validation/outputs/calibration-faces/: one PNG per run plus
results.json, resumable (existing runs skipped).
"""

import asyncio
import io
import itertools
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root, any cwd

from PIL import Image

from validation.calibrate import (
    GOLDEN,
    SEED,
    bgr,
    detail_energy,
    fidelity_psnr,
    identity_similarity,
    load_env,
)

HERE = Path(__file__).parent
OUT = HERE / "outputs" / "calibration-faces"

CROP_HEIGHT = 280  # small-face regime: what a repair-worthy crop looks like

CREATIVITY = [0.10, 0.15, 0.20, 0.25]  # 0.25 = current production value
RESEMBLANCE = [0.9, 1.2]  # 0.9 = current production value


def face_crop(original: Image.Image) -> Image.Image | None:
    """The exact crop production would feed Clarity: analyzer box, then
    downscaled into the small-face regime."""
    from app.pipeline import analysis

    boxes = analysis.detect_faces(bgr(original))
    if not boxes:
        return None
    box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    crop = original.crop(box)
    if crop.height > CROP_HEIGHT:
        crop = crop.resize(
            (round(crop.width * CROP_HEIGHT / crop.height), CROP_HEIGHT), Image.LANCZOS
        )
    return crop


async def run_sweep() -> list[dict]:
    from app.providers.replicate import ReplicateProvider

    provider = ReplicateProvider(token=os.environ["REPLICATE_API_TOKEN"])
    OUT.mkdir(parents=True, exist_ok=True)
    results_path = OUT / "results.json"
    results: list[dict] = json.loads(results_path.read_text()) if results_path.exists() else []
    done = {(r["image"], r["creativity"], r["resemblance"]) for r in results}

    for name, path in GOLDEN:
        original = Image.open(path).convert("RGB")
        crop = face_crop(original)
        if crop is None:
            print(f"{name}: no face detected, skipping")
            continue
        crop.save(OUT / f"{name}-input.png")
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        url = await provider.upload(buf.getvalue(), f"{name}-face.png")
        print(f"{name}: face crop {crop.width}x{crop.height}")

        for creativity, resemblance in itertools.product(CREATIVITY, RESEMBLANCE):
            if (name, creativity, resemblance) in done:
                continue
            # mirror LocalEnhancers._zoom_and_enhance: no prompt, 4x, 18 steps
            pred = await provider.run(
                "generative-upscaler",
                {
                    "image": url,
                    "creativity": creativity,
                    "resemblance": resemblance,
                    "scale_factor": 4,
                    "seed": SEED,
                    "num_inference_steps": 18,
                },
            )
            data = await provider.download(pred["output"][0])
            result = Image.open(io.BytesIO(data)).convert("RGB")
            out_name = f"{name}-c{creativity}-r{resemblance}.png"
            result.save(OUT / out_name)

            row = {
                "image": name,
                "creativity": creativity,
                "resemblance": resemblance,
                "file": out_name,
                "identity": identity_similarity(crop, result),
                "fidelity": round(fidelity_psnr(crop, result), 2),
                "detail": round(detail_energy(result), 1),
                "gpu_s": round(pred["metrics"]["predict_time"], 1),
            }
            results.append(row)
            results_path.write_text(json.dumps(results, indent=1))
            print(f"  c={creativity} r={resemblance}: "
                  f"id={row['identity'] and round(row['identity'], 3)} "
                  f"psnr={row['fidelity']} detail={row['detail']} ({row['gpu_s']}s)")
    return results


if __name__ == "__main__":
    load_env()
    asyncio.run(run_sweep())
