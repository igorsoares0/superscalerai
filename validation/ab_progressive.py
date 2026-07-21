"""A/B: single-pass 4x vs progressive 2x -> re-caption -> 2x (SPEC.md
Progressive Scaling: "max 2x per generative pass").

Both arms use the calibrated portrait point (c=0.20, r=1.2, hdr=3,
steps=24) and the same seed. Inputs capped at 768px wide so the final
4x output lands at ~3072px — the product's output ceiling.

Usage:
    UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python validation/ab_progressive.py
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
    SEED,
    detail_energy,
    fidelity_psnr,
    identity_similarity,
    load_env,
)

HERE = Path(__file__).parent
OUT = HERE / "outputs" / "ab-progressive"
MAX_INPUT_WIDTH = 768

CREATIVITY, RESEMBLANCE, HDR, STEPS = 0.20, 1.2, 3, 24


async def caption(provider, url: str) -> str:
    from app.pipeline.presets import PRESETS

    from app.pipeline.stages.captioner import TASK, parse_caption

    pred = await provider.run("captioner", {"image": url, "task_input": TASK})
    return parse_caption(pred["output"]) or PRESETS["portrait"].name


async def upscale_2x_or_4x(provider, url: str, prompt_caption: str, scale: int) -> tuple[Image.Image, float]:
    from app.pipeline.presets import BASE_NEGATIVE, BASE_PROMPT, PRESETS

    preset = PRESETS["portrait"]
    pred = await provider.run(
        "generative-upscaler",
        {
            "image": url,
            "prompt": BASE_PROMPT.format(caption=prompt_caption) + preset.style_terms,
            "negative_prompt": BASE_NEGATIVE + preset.negative_terms,
            "creativity": CREATIVITY,
            "resemblance": RESEMBLANCE,
            "dynamic": HDR,
            "scale_factor": scale,
            "seed": SEED,
            "num_inference_steps": STEPS,
        },
    )
    data = await provider.download(pred["output"][0])
    return Image.open(io.BytesIO(data)).convert("RGB"), pred["metrics"]["predict_time"]


async def upload(provider, image: Image.Image, name: str) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return await provider.upload(buf.getvalue(), name)


async def main() -> None:
    from app.providers.replicate import ReplicateProvider

    provider = ReplicateProvider(token=os.environ["REPLICATE_API_TOKEN"])
    OUT.mkdir(parents=True, exist_ok=True)
    results_path = OUT / "results.json"
    results: list[dict] = json.loads(results_path.read_text()) if results_path.exists() else []
    done = {(r["image"], r["arm"]) for r in results}

    for name, path in GOLDEN:
        original = Image.open(path).convert("RGB")
        if original.width > MAX_INPUT_WIDTH:
            original = original.resize(
                (MAX_INPUT_WIDTH, round(original.height * MAX_INPUT_WIDTH / original.width)),
                Image.LANCZOS,
            )
        url = await upload(provider, original, f"{name}.png")
        cap = await caption(provider, url)
        print(f"{name}: input {original.size}, caption ok")

        if (name, "single") not in done:
            result, gpu = await upscale_2x_or_4x(provider, url, cap, 4)
            result.save(OUT / f"{name}-single.png")
            results.append({
                "image": name, "arm": "single", "gpu_s": round(gpu, 1),
                "identity": identity_similarity(original, result),
                "fidelity": round(fidelity_psnr(original, result), 2),
                "detail": round(detail_energy(result), 1),
            })
            results_path.write_text(json.dumps(results, indent=1))
            print(f"  single 4x: {results[-1]}")

        if (name, "progressive") not in done:
            mid, gpu1 = await upscale_2x_or_4x(provider, url, cap, 2)
            mid_url = await upload(provider, mid, f"{name}-mid.png")
            cap2 = await caption(provider, mid_url)  # re-caption: the fresh
            # detail at 2x steers the second pass better than the 1x caption
            result, gpu2 = await upscale_2x_or_4x(provider, mid_url, cap2, 2)
            result.save(OUT / f"{name}-progressive.png")
            results.append({
                "image": name, "arm": "progressive", "gpu_s": round(gpu1 + gpu2, 1),
                "identity": identity_similarity(original, result),
                "fidelity": round(fidelity_psnr(original, result), 2),
                "detail": round(detail_energy(result), 1),
            })
            results_path.write_text(json.dumps(results, indent=1))
            print(f"  progressive 2x+2x: {results[-1]}")


if __name__ == "__main__":
    load_env()
    asyncio.run(main())
