"""Taste test: does a Magnific-style "creative" recipe produce wow on our
stack (Clarity/SD1.5), before committing to build a Creative mode?

Recipe deltas vs production portrait: creativity up, resemblance down,
more_details LoRA 0.5 -> 1.0, texture-pushing style terms, HDR high.
Baseline for comparison: the calibrated c0.2/r1.2/h3/s24 outputs already
in outputs/calibration/.

Usage:
    UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python validation/creative_taste.py
"""

import asyncio
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from validation.calibrate import (
    GOLDEN,
    MAX_INPUT_WIDTH,
    SEED,
    detail_energy,
    fidelity_psnr,
    identity_similarity,
    load_env,
)

HERE = Path(__file__).parent
OUT = HERE / "outputs" / "creative-taste"

CREATIVE_PROMPT = (
    "masterpiece, best quality, highres, {caption}, intricate details, "
    "hyperdetailed skin and fabric texture, dramatic light, sharp focus, "
    "<lora:more_details:1> <lora:SDXLrender_v2.0:1>"
)
CREATIVE_NEGATIVE = "(worst quality, low quality, normal quality:2) JuggernautNegative-neg"

# (label, creativity, resemblance, hdr)
VARIANTS = [
    ("mild", 0.35, 0.6, 9),
    ("mid", 0.45, 0.9, 6),
    ("strong", 0.45, 0.6, 9),
    ("max", 0.55, 0.6, 9),
]

PHOTOS = ["csz", "tst"]


async def main() -> None:
    from app.pipeline.stages.captioner import TASK, parse_caption
    from app.providers.replicate import ReplicateProvider

    provider = ReplicateProvider(token=os.environ["REPLICATE_API_TOKEN"])
    OUT.mkdir(parents=True, exist_ok=True)
    results_path = OUT / "results.json"
    results: list[dict] = json.loads(results_path.read_text()) if results_path.exists() else []
    done = {(r["image"], r["variant"]) for r in results}

    for name, path in GOLDEN:
        if name not in PHOTOS:
            continue
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
        caption = parse_caption(pred["output"]) or "photo"
        print(f"{name}: caption ok")

        for label, creativity, resemblance, hdr in VARIANTS:
            if (name, label) in done:
                continue
            pred = await provider.run(
                "generative-upscaler",
                {
                    "image": url,
                    "prompt": CREATIVE_PROMPT.format(caption=caption),
                    "negative_prompt": CREATIVE_NEGATIVE,
                    "creativity": creativity,
                    "resemblance": resemblance,
                    "dynamic": hdr,
                    "scale_factor": 2,
                    "seed": SEED,
                    "num_inference_steps": 24,
                },
            )
            data = await provider.download(pred["output"][0])
            result = Image.open(io.BytesIO(data)).convert("RGB")
            result.save(OUT / f"{name}-{label}.png")
            row = {
                "image": name,
                "variant": label,
                "creativity": creativity,
                "resemblance": resemblance,
                "hdr": hdr,
                "identity": identity_similarity(original, result),
                "fidelity": round(fidelity_psnr(original, result), 2),
                "detail": round(detail_energy(result), 1),
                "gpu_s": round(pred["metrics"]["predict_time"], 1),
            }
            results.append(row)
            results_path.write_text(json.dumps(results, indent=1))
            print(f"  {label}: id={row['identity'] and round(row['identity'], 3)} "
                  f"psnr={row['fidelity']} detail={row['detail']} ({row['gpu_s']}s)")


if __name__ == "__main__":
    load_env()
    asyncio.run(main())
