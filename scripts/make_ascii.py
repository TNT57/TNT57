"""Turn a photo into ASCII art for the profile card.

How it works (simple version):
  1. Find the plain background (grey pixels touching the edge) and blank it out.
  2. Crop to head + shoulders and shrink the photo to a small grid
     (one grid cell = one character).
  3. Brighter cell -> "heavier" character (like @ or #); darker -> lighter (like . or :).

Two versions are made:
  profile/ascii_dark.txt  - bright skin = heavy characters (light text on dark card)
  profile/ascii_light.txt - dark hair = heavy characters (dark text on light card)

Settings live in profile/config.toml under [ascii].
"""

import tomllib
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent

# Light -> heavy (ordered by how much ink each glyph uses). Space = background.
RAMP = "`.-':~;!*+/=|?lcviLtjfxJYCunoehkwZXPAUbdmOH0D#R8QBWNM@"  # sorted by measured ink


def background_mask(rgb: np.ndarray, tol: int) -> np.ndarray:
    """True where a pixel is plain background connected to the image border."""
    r, g, b = (rgb[..., i].astype(int) for i in range(3))
    grey = (np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)) < 18
    lum = rgb.mean(axis=2)
    # Background colour = typical grey on the left/right edges (ignoring white
    # rounded corners some photos have).
    edges = np.concatenate([lum[:, :6].ravel(), lum[:, -6:].ravel()])
    bg_lum = np.median(edges[edges < 200])
    candidate = grey & ((np.abs(lum - bg_lum) < tol) | (lum > 200))

    h, w = candidate.shape
    seen = np.zeros_like(candidate)
    queue = deque()
    for x in range(w):
        for y in (0, h - 1):
            if candidate[y, x]:
                seen[y, x] = True
                queue.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if candidate[y, x] and not seen[y, x]:
                seen[y, x] = True
                queue.append((y, x))
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < h and 0 <= nx < w and candidate[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                queue.append((ny, nx))
    return seen


def make_ascii(cfg: dict, invert: bool = False) -> list[str]:
    img = Image.open(ROOT / cfg["photo"]).convert("RGB")
    rgb = np.asarray(img)
    bg = background_mask(rgb, cfg.get("bg_tolerance", 30))

    # Clean the mask edge a little so the outline is smooth.
    mask_img = Image.fromarray((~bg * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(5))

    left, top, right, bottom = cfg.get("crop", [0, 0, img.width, img.height])
    gray = img.convert("L").crop((left, top, right, bottom))
    mask_img = mask_img.crop((left, top, right, bottom))

    if cfg.get("sharpen", 0):
        gray = gray.filter(ImageFilter.UnsharpMask(radius=3, percent=int(cfg["sharpen"] * 100), threshold=2))

    cols = cfg.get("cols", 40)
    # A character cell is 0.6em wide and `line_height` tall.
    char_aspect = 0.6 * cfg.get("font_size", 16) / cfg.get("line_height", 20)
    rows = round(cols * (gray.height / gray.width) * char_aspect)
    small = np.asarray(gray.resize((cols, rows), Image.LANCZOS)).astype(float)
    subject = np.asarray(mask_img.resize((cols, rows), Image.BILINEAR)) > 110

    # Stretch contrast using only the person's pixels, then apply gamma.
    vals = small[subject]
    lo, hi = np.percentile(vals, cfg.get("low_pct", 3)), np.percentile(vals, cfg.get("high_pct", 99))
    stretched = np.clip((small - lo) / max(hi - lo, 1), 0, 1)
    # Equalize: rank each cell among the person's cells, so every character in
    # the ramp gets used (shows more detail in the face).
    ranks = np.searchsorted(np.sort(vals), small, side="right") / len(vals)
    mix = cfg.get("equalize", 0.5)
    norm = np.clip((1 - mix) * stretched + mix * ranks, 0, 1) ** cfg.get("gamma", 1.0)
    if invert:
        norm = 1 - norm

    lines = []
    for y in range(rows):
        row = []
        for x in range(cols):
            if not subject[y, x]:
                row.append(" ")
            else:
                row.append(RAMP[min(int(norm[y, x] * len(RAMP)), len(RAMP) - 1)])
        lines.append("".join(row).rstrip())
    # Drop empty rows at the top/bottom.
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def main() -> None:
    cfg = tomllib.loads((ROOT / "profile" / "config.toml").read_text(encoding="utf-8"))["ascii"]
    for theme in ("dark", "light"):
        lines = make_ascii(cfg, invert=(theme == "light"))
        out = ROOT / "profile" / f"ascii_{theme}.txt"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{len(lines)} rows x {max(map(len, lines))} cols -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
