"""A/B: philz1337x/clarity-pro-upscaler ("creative upscaler which keeps
identity", closed-source, $0.03/output MP) vs our calibrated Clarity.

User-approved exception to the open-source rule (2026-07-21) for this
test only. Same 896px inputs as the main calibration harness, so the
existing c0.2-r1.2-h3-s24 outputs are the baseline.

Usage:
    UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python validation/clarity_pro_ab.py
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
    detail_energy,
    fidelity_psnr,
    identity_similarity,
    load_env,
)

HERE = Path(__file__).parent
OUT = HERE / "outputs" / "clarity-pro-ab"

# (image, creativity) — creativity scale here is -10..10, default 0
RUNS = [("tst", 0), ("tst", 5), ("csz", 0), ("csz", 5), ("degraded", 5)]


async def main() -> None:
    from app.providers import replicate as rep

    rep.MODELS["clarity-pro"] = (
        "philz1337x/clarity-pro-upscaler:"
        "8e33eb474936d75d3ceaa787f3e66f5ba16f35db0853a7697a4ca4e5fc14b6cd"
    )
    provider = rep.ReplicateProvider(token=os.environ["REPLICATE_API_TOKEN"])
    OUT.mkdir(parents=True, exist_ok=True)
    results_path = OUT / "results.json"
    results: list[dict] = json.loads(results_path.read_text()) if results_path.exists() else []
    done = {(r["image"], r["creativity"]) for r in results}

    urls: dict[str, str] = {}
    originals: dict[str, Image.Image] = {}
    for name, path in GOLDEN:
        original = Image.open(path).convert("RGB")
        if original.width > MAX_INPUT_WIDTH:
            original = original.resize(
                (MAX_INPUT_WIDTH, round(original.height * MAX_INPUT_WIDTH / original.width)),
                Image.LANCZOS,
            )
        originals[name] = original
        buf = io.BytesIO()
        original.save(buf, format="PNG")
        urls[name] = await provider.upload(buf.getvalue(), f"{name}.png")

    for name, creativity in RUNS:
        if (name, creativity) in done:
            continue
        pred = await provider.run(
            "clarity-pro",
            {"image": urls[name], "creativity": creativity, "scale_factor": 2},
        )
        output = pred["output"]
        uri = output[0] if isinstance(output, list) else output
        data = await provider.download(uri)
        result = Image.open(io.BytesIO(data)).convert("RGB")
        result.save(OUT / f"{name}-pro-c{creativity}.png")
        original = originals[name]
        row = {
            "image": name,
            "creativity": creativity,
            "identity": identity_similarity(original, result),
            "fidelity": round(fidelity_psnr(original, result), 2),
            "detail": round(detail_energy(result), 1),
            "gpu_s": round(pred["metrics"].get("predict_time", 0.0), 1),
            "out_mp": round(result.width * result.height / 1e6, 1),
        }
        results.append(row)
        results_path.write_text(json.dumps(results, indent=1))
        print(f"{name} c={creativity}: id={row['identity'] and round(row['identity'], 3)} "
              f"psnr={row['fidelity']} detail={row['detail']} "
              f"({row['gpu_s']}s, {row['out_mp']}MP)")


if __name__ == "__main__":
    load_env()
    asyncio.run(main())
