# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Standalone validation of the upscale flow (SPEC.md pipeline core).

No queue, no DB, no API — just: image -> caption (BLIP-2) -> generative
upscale (Clarity) -> before/after saved locally.

Usage:
    export REPLICATE_API_TOKEN=r8_...
    uv run validate.py photo.jpg --preset portrait --scale 2
    uv run validate.py https://example.com/photo.jpg --preset product

Outputs land in ./outputs/<run-name>/ with a metrics.json.
"""

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

API = "https://api.replicate.com/v1"

# Pinned versions (SPEC.md: Initial Models — never use floating versions)
CLARITY_VERSION = "dfad41707589d68ecdccd1dfa600d55a208f9310748e44bfe35b4a6291453d5e"  # philz1337x/clarity-upscaler
BLIP2_VERSION = "f677695e5e89f8b236e52ecd1d3f01beb44c34606419bcc19345e046d8f786f9"  # andreasjansson/blip-2

BASE_PROMPT = "masterpiece, best quality, highres, {caption}, <lora:more_details:0.5> <lora:SDXLrender_v2.0:1>"

# SPEC.md: Presets Are Parameter Bundles.
# Clarity mapping: creativity == denoise strength, resemblance == structural guidance.
PRESETS = {
    "portrait": {"creativity": 0.28, "resemblance": 0.8},
    "product": {"creativity": 0.25, "resemblance": 0.9},
    "architecture": {"creativity": 0.35, "resemblance": 0.8},
    "ai-generated": {"creativity": 0.50, "resemblance": 0.6},
}


def client(token: str) -> httpx.Client:
    return httpx.Client(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(120, read=120),
    )


def image_input(http: httpx.Client, source: str) -> str:
    """Return an input Replicate accepts: pass URLs through, upload local files."""
    if source.startswith(("http://", "https://")):
        return source
    path = Path(source)
    data = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if len(data) <= 256_000:
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    r = http.post(f"{API}/files", files={"content": (path.name, data, mime)})
    r.raise_for_status()
    return r.json()["urls"]["get"]


def run_prediction(http: httpx.Client, version: str, input: dict) -> dict:
    for attempt in range(5):
        r = http.post(
            f"{API}/predictions",
            json={"version": version, "input": input},
            headers={"Prefer": "wait"},
        )
        if r.status_code != 429:
            break
        wait = 2**attempt
        print(f"rate limited (429), retrying in {wait}s...")
        time.sleep(wait)
    r.raise_for_status()
    pred = r.json()
    while pred["status"] in ("starting", "processing"):
        time.sleep(3)
        pred = http.get(f"{API}/predictions/{pred['id']}").json()
    if pred["status"] != "succeeded":
        sys.exit(f"prediction {pred['id']} {pred['status']}: {pred.get('error')}")
    return pred


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", help="path or URL of the input image")
    ap.add_argument("--preset", choices=PRESETS, default="portrait")
    ap.add_argument("--scale", type=float, default=2, help="scale factor (spec: max 2x per pass)")
    ap.add_argument("--seed", type=int, default=831442)
    ap.add_argument("--creativity", type=float, help="override preset denoise/creativity")
    ap.add_argument("--mask", help="protection mask (white = preserve), path or URL")
    ap.add_argument("--no-caption", action="store_true", help="skip BLIP-2 captioning")
    args = ap.parse_args()

    token = os.environ.get("REPLICATE_API_TOKEN") or sys.exit("set REPLICATE_API_TOKEN")
    http = client(token)
    source = image_input(http, args.image)

    caption = ""
    caption_secs = 0.0
    if not args.no_caption:
        pred = run_prediction(http, BLIP2_VERSION, {"image": source, "caption": True})
        caption = pred["output"]
        caption_secs = pred["metrics"]["predict_time"]
        print(f"caption ({caption_secs:.1f}s): {caption}")

    params = dict(PRESETS[args.preset])
    if args.creativity is not None:
        params["creativity"] = args.creativity
    if args.mask:
        params["mask"] = image_input(http, args.mask)

    t0 = time.time()
    pred = run_prediction(
        http,
        CLARITY_VERSION,
        {
            "image": source,
            "prompt": BASE_PROMPT.format(caption=caption or args.preset),
            "scale_factor": args.scale,
            "seed": args.seed,
            "num_inference_steps": 18,
            **params,
        },
    )
    wall_secs = time.time() - t0
    upscale_secs = pred["metrics"]["predict_time"]
    output_url = pred["output"][0]
    print(f"upscale: {upscale_secs:.1f}s GPU, {wall_secs:.1f}s wall")

    run_name = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-{args.preset}"
    out_dir = Path(__file__).parent / "outputs" / run_name
    out_dir.mkdir(parents=True)
    if not args.image.startswith(("http://", "https://")):
        src = Path(args.image)
        (out_dir / f"before{src.suffix}").write_bytes(src.read_bytes())
    (out_dir / "after.png").write_bytes(httpx.get(output_url, timeout=120).content)
    (out_dir / "metrics.json").write_text(
        json.dumps(
            {
                "input": args.image,
                "preset": args.preset,
                "params": params,
                "scale": args.scale,
                "seed": args.seed,
                "caption": caption,
                "caption_predict_time": caption_secs,
                "upscale_predict_time": upscale_secs,
                "wall_time": wall_secs,
                "prediction_id": pred["id"],
                "output_url": output_url,
            },
            indent=2,
        )
    )
    print(f"saved to {out_dir}")


if __name__ == "__main__":
    main()
