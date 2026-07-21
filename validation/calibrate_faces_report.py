"""Comparison sheet + ranking for the face-crop calibration sweep.

Reads outputs/calibration-faces/results.json, prints a per-image table
(production point flagged), and writes face-calibration-{name}.png sheets:
input crop (Lanczos 4x, what compositing without repair looks like) next
to every run, labeled with params and metrics.

Usage:
    UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python validation/calibrate_faces_report.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
OUT = HERE / "outputs" / "calibration-faces"

SAME_PERSON = 0.363  # SFace cosine threshold (main harness)
LABEL_H = 44
TILE_W = 360


def tile(img: Image.Image, label: str, ok: bool = True) -> Image.Image:
    img = img.resize((TILE_W, round(img.height * TILE_W / img.width)), Image.LANCZOS)
    canvas = Image.new("RGB", (TILE_W, img.height + LABEL_H), (18, 18, 18))
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, img.height + 6), label, fill=(235, 235, 235) if ok else (255, 90, 90))
    return canvas


def main() -> None:
    results = json.loads((OUT / "results.json").read_text())
    by_image: dict[str, list[dict]] = {}
    for row in results:
        by_image.setdefault(row["image"], []).append(row)

    for name, rows in by_image.items():
        rows.sort(key=lambda r: (r["creativity"], r["resemblance"]))
        print(f"\n{name}")
        print(f"  {'creat':>5} {'resem':>5} {'id':>6} {'psnr':>6} {'detail':>7}")
        for r in rows:
            prod = " <- production (0.25/0.9)" if (r["creativity"], r["resemblance"]) == (0.25, 0.9) else ""
            ident = r["identity"]
            flag = "" if ident is None or ident >= SAME_PERSON else " ID FAIL"
            print(f"  {r['creativity']:>5} {r['resemblance']:>5} "
                  f"{ident if ident is None else round(ident, 3):>6} "
                  f"{r['fidelity']:>6} {r['detail']:>7}{flag}{prod}")

        tiles = [tile(Image.open(OUT / f"{name}-input.png"), "input (Lanczos view)")]
        for r in rows:
            ident = r["identity"]
            ok = ident is not None and ident >= SAME_PERSON
            label = (f"c={r['creativity']} r={r['resemblance']}  "
                     f"id={ident if ident is None else round(ident, 3)} psnr={r['fidelity']}")
            tiles.append(tile(Image.open(OUT / r["file"]), label, ok))

        h = max(t.height for t in tiles)
        sheet = Image.new("RGB", (TILE_W * len(tiles), h), (18, 18, 18))
        for i, t in enumerate(tiles):
            sheet.paste(t, (i * TILE_W, 0))
        out = OUT / f"face-calibration-{name}.png"
        sheet.save(out)
        print(f"  sheet: {out}")


if __name__ == "__main__":
    main()
