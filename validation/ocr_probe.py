"""Probe Florence-2 'OCR with Region' output shape on the validation photos,
and compare its boxes against the current gradient heuristic.

Usage:
    UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python validation/ocr_probe.py
"""

import asyncio
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw

from validation.calibrate import GOLDEN, load_env

HERE = Path(__file__).parent
OUT = HERE / "outputs" / "ocr"


async def main() -> None:
    from app.pipeline import analysis
    from app.providers.replicate import ReplicateProvider

    provider = ReplicateProvider(token=os.environ["REPLICATE_API_TOKEN"])
    OUT.mkdir(parents=True, exist_ok=True)

    for name, path in GOLDEN:
        original = Image.open(path).convert("RGB")
        buf = io.BytesIO()
        original.save(buf, format="JPEG", quality=90)
        url = await provider.upload(buf.getvalue(), f"{name}.jpg")

        pred = await provider.run("captioner", {"image": url, "task_input": "OCR with Region"})
        (OUT / f"{name}-raw.json").write_text(json.dumps(pred["output"], indent=1, default=str))
        print(f"{name}: raw output -> {OUT / f'{name}-raw.json'}")
        print(f"  text field: {pred['output'].get('text') if isinstance(pred['output'], dict) else pred['output']!r}"[:400])

        bgr = np.asarray(original)[:, :, ::-1].copy()
        heur = analysis.detect_text_regions(bgr, exclude=analysis.detect_faces(bgr))
        print(f"  heuristic boxes: {heur}")

        overlay = original.copy()
        draw = ImageDraw.Draw(overlay)
        for b in heur:
            draw.rectangle(b, outline=(255, 80, 80), width=3)  # red = heuristic
        overlay.save(OUT / f"{name}-heuristic.png")


if __name__ == "__main__":
    load_env()
    asyncio.run(main())
