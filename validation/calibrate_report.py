"""Analyze calibration results: ranking table + face-crop contact sheets.

Selection rule: within each image, keep combos whose identity is within
0.05 of that image's best and PSNR within 2.5 dB of best; among those,
more detail is better. Aggregate = mean rank across images (a combo must
survive the identity/fidelity gate on EVERY image).
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HERE = Path(__file__).parent
CAL = HERE / "outputs" / "calibration"

ID_SLACK = 0.05
PSNR_SLACK = 2.5


def main() -> None:
    rows = json.loads((CAL / "results.json").read_text())
    by_image: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_image[r["image"]].append(r)

    survivors: dict[tuple, list[float]] = defaultdict(list)  # combo -> detail ranks
    for image, entries in by_image.items():
        best_id = max(e["identity"] or 0 for e in entries)
        best_psnr = max(e["fidelity"] for e in entries)
        passed = [
            e for e in entries
            if (e["identity"] or 0) >= best_id - ID_SLACK
            and e["fidelity"] >= best_psnr - PSNR_SLACK
        ]
        print(f"\n=== {image}: {len(passed)}/{len(entries)} pass the gate "
              f"(id>={best_id - ID_SLACK:.3f}, psnr>={best_psnr - PSNR_SLACK:.1f}) ===")
        passed.sort(key=lambda e: -e["detail"])
        for rank, e in enumerate(passed):
            combo = (e["creativity"], e["resemblance"], e["hdr"])
            survivors[combo].append(rank)
            print(f"  #{rank+1} c={e['creativity']} r={e['resemblance']}: "
                  f"id={round(e['identity'], 3)} psnr={e['fidelity']} detail={e['detail']}")

    n_images = len(by_image)
    print("\n=== combos passing the gate on ALL images, by mean detail rank ===")
    universal = {c: ranks for c, ranks in survivors.items() if len(ranks) == n_images}
    for combo, ranks in sorted(universal.items(), key=lambda kv: sum(kv[1])):
        print(f"  c={combo[0]} r={combo[1]} h={combo[2]}: mean rank {np.mean(ranks) + 1:.1f}")

    # contact sheet: for each image, current default vs top candidates (face crop)
    top = [c for c, _ in sorted(universal.items(), key=lambda kv: sum(kv[1]))][:3]
    candidates = [(0.28, 0.8, 6)] + top  # current default first (may not exist in grid)
    for image in by_image:
        tiles = []
        for c, r, h in candidates:
            f = CAL / f"{image}-c{c}-r{r}-h{h}.png"
            if not f.exists():
                continue
            img = Image.open(f)
            w, h2 = img.size
            crop = img.crop((w // 4, h2 // 8, w * 3 // 4, h2 // 8 + w // 2)).resize((420, 420), Image.LANCZOS)
            tiles.append((f"c={c} r={r}", crop))
        if not tiles:
            continue
        sheet = Image.new("RGB", (430 * len(tiles) + 10, 448), "black")
        d = ImageDraw.Draw(sheet)
        for i, (label, tile) in enumerate(tiles):
            sheet.paste(tile, (10 + i * 430, 28))
            d.text((14 + i * 430, 8), label, fill="white")
        sheet.save(CAL / f"sheet-{image}.png")
        print(f"sheet saved: sheet-{image}.png ({len(tiles)} tiles)")


if __name__ == "__main__":
    main()
