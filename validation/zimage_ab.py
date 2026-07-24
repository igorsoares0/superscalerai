"""Phase A: is Z-Image Turbo (Tongyi-MAI, 6B DiT, Apache-2.0) a viable
creative backbone where SD 1.5 failed?

Recipe is the classic tiled-upscale move, minus the tiling: Lanczos 2x to
the target size, then img2img at low strength to hallucinate texture back
in. One whole-image call here — tiling is Phase B, only if this passes.

Gate: csz is the discriminator. SD 1.5's creative recipe turned a Black
woman with braids into a white woman with straight hair at every dose,
and clarity-pro invented freckles. Identity must hold while detail rises.

Controls (free): the Lanczos 2x input itself, and the calibrated
c0.2-r1.2-h3-s24 Clarity output already in outputs/calibration/.

Usage:
    UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python validation/zimage_ab.py [--limit N]
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
    OUT as CALIB_OUT,
    SEED,
    detail_energy,
    fidelity_psnr,
    identity_similarity,
    load_env,
)

HERE = Path(__file__).parent
OUT = HERE / "outputs" / "zimage-ab"

VERSION = "7142e836070262fece6f2c4356aec87e9aec27bf31c65ef6b3983e0153e9518c"

# Turbo: guidance must stay 0, 8 steps is the distilled operating point.
# No <lora:...> tag syntax here — that is an A1111/SD1.5 convention the
# DiT text encoder would read as literal text.
PROMPT = (
    "{caption}, photorealistic, intricate detail, natural skin texture with "
    "visible pores, individual hair strands, sharp focus, high dynamic range"
)

# Probe order: the middle dose first, so one run tells us geometry + cost.
STRENGTHS = [0.25, 0.15, 0.35]
PHOTOS = ["csz"]


async def main(limit: int | None) -> None:
    from app.pipeline.stages.captioner import TASK, parse_caption
    from app.providers import replicate as rep

    rep.MODELS["zimage-img2img"] = f"prunaai/z-image-turbo-img2img:{VERSION}"
    provider = rep.ReplicateProvider(token=os.environ["REPLICATE_API_TOKEN"])
    OUT.mkdir(parents=True, exist_ok=True)
    results_path = OUT / "results.json"
    results: list[dict] = json.loads(results_path.read_text()) if results_path.exists() else []
    done = {(r["image"], r["strength"]) for r in results}
    spent = 0

    for name, path in GOLDEN:
        if name not in PHOTOS:
            continue
        original = Image.open(path).convert("RGB")
        if original.width > MAX_INPUT_WIDTH:
            original = original.resize(
                (MAX_INPUT_WIDTH, round(original.height * MAX_INPUT_WIDTH / original.width)),
                Image.LANCZOS,
            )

        # deterministic 2x — both the z-image input and the free control
        upscaled = original.resize((original.width * 2, original.height * 2), Image.LANCZOS)
        upscaled.save(OUT / f"{name}-lanczos2x.png")
        if (name, "lanczos") not in done:
            results.append({
                "image": name,
                "strength": "lanczos",
                "identity": identity_similarity(original, upscaled),
                "fidelity": round(fidelity_psnr(original, upscaled), 2),
                "detail": round(detail_energy(upscaled), 1),
                "gpu_s": 0.0,
            })
            results_path.write_text(json.dumps(results, indent=1))

        # baseline: our calibrated Clarity output, if the sweep left one
        baseline = CALIB_OUT / f"{name}-c0.2-r1.2-h3-s24.png"
        if baseline.exists() and (name, "clarity") not in done:
            ref = Image.open(baseline).convert("RGB")
            results.append({
                "image": name,
                "strength": "clarity",
                "identity": identity_similarity(original, ref),
                "fidelity": round(fidelity_psnr(original, ref), 2),
                "detail": round(detail_energy(ref), 1),
                "gpu_s": 0.0,
            })
            results_path.write_text(json.dumps(results, indent=1))

        buf = io.BytesIO()
        original.save(buf, format="PNG")
        caption_url = await provider.upload(buf.getvalue(), f"{name}.png")
        pred = await provider.run("captioner", {"image": caption_url, "task_input": TASK})
        caption = parse_caption(pred["output"]) or "photo"
        print(f"{name}: caption ok ({len(caption)} chars)")

        buf = io.BytesIO()
        upscaled.save(buf, format="PNG")
        url = await provider.upload(buf.getvalue(), f"{name}-2x.png")

        for strength in STRENGTHS:
            if (name, strength) in done:
                continue
            if limit is not None and spent >= limit:
                print(f"limit {limit} reached — stopping")
                return
            pred = await provider.run(
                "zimage-img2img",
                {
                    "image": url,
                    "prompt": PROMPT.format(caption=caption),
                    "strength": strength,
                    "guidance_scale": 0,
                    "num_inference_steps": 8,
                    "seed": SEED,
                    "output_format": "png",
                },
            )
            spent += 1
            output = pred["output"]
            uri = output[0] if isinstance(output, list) else output
            data = await provider.download(uri)
            result = Image.open(io.BytesIO(data)).convert("RGB")
            result.save(OUT / f"{name}-s{strength}.png")

            row = {
                "image": name,
                "strength": strength,
                "size": f"{result.width}x{result.height}",
                "identity": identity_similarity(original, result),
                "fidelity": round(fidelity_psnr(original, result), 2),
                "detail": round(detail_energy(result), 1),
                "gpu_s": round(pred["metrics"].get("predict_time", 0.0), 1),
            }
            results.append(row)
            results_path.write_text(json.dumps(results, indent=1))
            print(f"  s={strength}: {row['size']} "
                  f"id={row['identity'] and round(row['identity'], 3)} "
                  f"psnr={row['fidelity']} detail={row['detail']} ({row['gpu_s']}s)")


if __name__ == "__main__":
    load_env()
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    asyncio.run(main(limit))
