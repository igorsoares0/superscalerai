"""A/B: does a skin recipe on the zoom-and-enhance FACE pass add pore/skin
detail without breaking identity?

The production face pass (local_enhancers._face_pass) runs the face crop
through Clarity at creativity 0.10 with NO prompt (Clarity's default). This
probes whether an explicit skin prompt with a stronger bundled `more_details`
LoRA — no new license — buys real pore/skin texture while SFace identity
holds. The item-3 identity gate is the safety net that makes nudging
creativity a little higher viable, so the sweep goes 0.10 -> 0.18.

License-clean by design: only the more_details / SDXLrender LoRAs Clarity
already bundles are used. A dedicated skin LoRA is a follow-up ONLY if this
direction pays off.

Runs on the face CROP (cheap: ~3.6s GPU each, ~US$0.005). Baseline ==
production exactly. 3 golden faces x 5 conditions ~= 15 runs ~= US$0.10-0.15.

Usage:
    UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python validation/skin_lora_ab.py [--limit N]
"""

import asyncio
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root, any cwd

import cv2
import numpy as np
from PIL import Image

from validation.calibrate import (
    GOLDEN,
    MAX_INPUT_WIDTH,
    SEED,
    detail_energy,
    identity_similarity,
    load_env,
)

HERE = Path(__file__).parent
OUT = HERE / "outputs" / "skin-lora-ab"

# Same skin cues as the portrait preset (style/negative terms), plus a
# parametrised more_details strength. {md} is filled per condition.
SKIN_PROMPT = (
    "masterpiece, best quality, highres, a close-up portrait, "
    "detailed skin texture, skin pores, natural skin, "
    "<lora:more_details:{md}> <lora:SDXLrender_v2.0:1>"
)
SKIN_NEGATIVE = (
    "(worst quality, low quality, normal quality:2) JuggernautNegative-neg, "
    "plastic skin, waxy skin, airbrushed, smooth skin"
)

# baseline is production (no prompt -> Clarity default). Then hold creativity
# at the calibrated 0.10 while pushing the LoRA, then let creativity rise with
# the LoRA at full strength — the identity gate would catch a bad rise in prod.
CONDITIONS = [
    {"name": "baseline", "md": None, "creativity": 0.10},   # == production face pass
    {"name": "md0.8-c0.10", "md": 0.8, "creativity": 0.10},
    {"name": "md1.0-c0.10", "md": 1.0, "creativity": 0.10},
    {"name": "md1.0-c0.14", "md": 1.0, "creativity": 0.14},
    {"name": "md1.0-c0.18", "md": 1.0, "creativity": 0.18},
]


def face_crop(image: Image.Image) -> Image.Image | None:
    """The crop production's zoom-and-enhance would run on: the largest
    detected face with the pipeline's margin (analysis.detect_faces)."""
    from app.pipeline import analysis

    arr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    boxes = analysis.detect_faces(arr)
    if not boxes:
        return None
    box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    return image.crop(box)


async def main(limit: int | None) -> None:
    from app.providers.replicate import ReplicateProvider

    provider = ReplicateProvider(token=os.environ["REPLICATE_API_TOKEN"])
    OUT.mkdir(parents=True, exist_ok=True)
    results_path = OUT / "results.json"
    results: list[dict] = json.loads(results_path.read_text()) if results_path.exists() else []
    done = {(r["image"], r["condition"]) for r in results}

    for name, path in GOLDEN[: limit or len(GOLDEN)]:
        original = Image.open(path).convert("RGB")
        if original.width > MAX_INPUT_WIDTH:
            original = original.resize(
                (MAX_INPUT_WIDTH, round(original.height * MAX_INPUT_WIDTH / original.width)),
                Image.LANCZOS,
            )
        crop = face_crop(original)
        if crop is None:
            print(f"{name}: no face detected, skipping")
            continue
        input_detail = round(detail_energy(crop), 1)
        crop.save(OUT / f"{name}-crop.png")

        buf = io.BytesIO()
        crop.convert("RGB").save(buf, format="PNG")
        url = await provider.upload(buf.getvalue(), f"{name}-face.png")
        print(f"{name}: face crop {crop.size}, input detail {input_detail}")

        for cond in CONDITIONS:
            if (name, cond["name"]) in done:
                continue
            payload = {
                "image": url,
                "creativity": cond["creativity"],
                "resemblance": 1.2,
                "scale_factor": 4,
                "seed": SEED,
                "num_inference_steps": 18,
            }
            if cond["md"] is not None:  # baseline stays prompt-less like production
                payload["prompt"] = SKIN_PROMPT.format(md=cond["md"])
                payload["negative_prompt"] = SKIN_NEGATIVE
            pred = await provider.run("generative-upscaler", payload)
            data = await provider.download(pred["output"][0])
            result = Image.open(io.BytesIO(data)).convert("RGB")
            result.save(OUT / f"{name}-{cond['name']}.png")

            row = {
                "image": name,
                "condition": cond["name"],
                "md": cond["md"],
                "creativity": cond["creativity"],
                "input_detail": input_detail,
                "identity": identity_similarity(crop, result),
                "detail": round(detail_energy(result), 1),
                "gpu_s": round(pred["metrics"]["predict_time"], 1),
            }
            results.append(row)
            results_path.write_text(json.dumps(results, indent=1))
            ident = row["identity"] and round(row["identity"], 3)
            print(f"  {cond['name']}: id={ident} detail={row['detail']} "
                  f"(input {input_detail}) ({row['gpu_s']}s)")

    _summary(results)


def _summary(results: list[dict]) -> None:
    """Per-condition averages: the money question is detail up, identity flat."""
    print("\ncondition       avg_identity  avg_detail  n")
    by_cond: dict[str, list[dict]] = {}
    for r in results:
        by_cond.setdefault(r["condition"], []).append(r)
    for cond in (c["name"] for c in CONDITIONS):
        rows = by_cond.get(cond, [])
        if not rows:
            continue
        ids = [r["identity"] for r in rows if r["identity"] is not None]
        avg_id = f"{sum(ids) / len(ids):.3f}" if ids else "  n/a"
        avg_det = sum(r["detail"] for r in rows) / len(rows)
        print(f"{cond:<15} {avg_id:>11}  {avg_det:>10.1f}  {len(rows)}")


if __name__ == "__main__":
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    load_env()
    asyncio.run(main(limit))
