"""Generate edge-aware signed-distance masks for the ten multiverse regions.

Run with the bundled artifact Python runtime (Pillow + NumPy). The radial search
snaps each coarse world ellipse to the darkest/highest-gradient tendrils nearby,
then bakes a compact signed-distance texture for the WebGL overlay.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "public" / "assets" / "multiverse" / "entangled-ten-worlds.png"
OUTPUT = ROOT / "public" / "assets" / "multiverse" / "masks"
MASK_SIZE = (836, 470)

WORLDS = [
    ("astral", 16.5, 17.5, 31, 31),
    ("tribe", 42, 17.5, 28, 31),
    ("ink", 66, 18, 28, 32),
    ("neon", 88, 25, 22, 36),
    ("frost", 14, 44.5, 28, 35),
    ("inferno", 40.5, 48.5, 31, 35),
    ("verdant", 71, 49.5, 30, 37),
    ("dune", 18, 78, 36, 44),
    ("abyss", 50, 80, 32, 40),
    ("clockwork", 82.5, 79.5, 35, 41),
]


def smooth_circular(values: np.ndarray, passes: int = 9) -> np.ndarray:
    result = values.astype(np.float32)
    kernel = np.array([1, 2, 3, 4, 3, 2, 1], dtype=np.float32)
    kernel /= kernel.sum()
    pad = len(kernel) // 2
    for _ in range(passes):
        extended = np.concatenate([result[-pad:], result, result[:pad]])
        result = np.convolve(extended, kernel, mode="valid")
    return result


def main() -> None:
    source = Image.open(SOURCE).convert("RGB")
    pixels = np.asarray(source, dtype=np.float32) / 255.0
    luminance = pixels[..., 0] * 0.2126 + pixels[..., 1] * 0.7152 + pixels[..., 2] * 0.0722
    gradient_y, gradient_x = np.gradient(luminance)
    gradient = np.hypot(gradient_x, gradient_y)
    gradient /= max(float(np.percentile(gradient, 98)), 1e-6)
    gradient = np.clip(gradient, 0, 1)
    width, height = source.size
    OUTPUT.mkdir(parents=True, exist_ok=True)

    angles = np.linspace(0, np.pi * 2, 720, endpoint=False)
    candidates = np.linspace(0.82, 1.16, 86)
    for world_id, center_x, center_y, region_width, region_height in WORLDS:
        cx = center_x / 100 * width
        cy = center_y / 100 * height
        radius_x = region_width / 200 * width
        radius_y = region_height / 200 * height
        radii = np.empty_like(angles)
        for index, angle in enumerate(angles):
            sample_x = np.clip(np.rint(cx + np.cos(angle) * radius_x * candidates).astype(int), 0, width - 1)
            sample_y = np.clip(np.rint(cy + np.sin(angle) * radius_y * candidates).astype(int), 0, height - 1)
            darkness = 1 - luminance[sample_y, sample_x]
            edge = gradient[sample_y, sample_x]
            proximity = np.abs(candidates - 1)
            score = darkness * 0.48 + edge * 0.4 - proximity * 0.92
            radii[index] = candidates[int(np.argmax(score))]
        radii = smooth_circular(radii)
        points = [
            (
                int(round(cx + np.cos(angle) * radius_x * radius)),
                int(round(cy + np.sin(angle) * radius_y * radius)),
            )
            for angle, radius in zip(angles, radii, strict=True)
        ]
        filled = Image.new("L", source.size, 0)
        ImageDraw.Draw(filled).polygon(points, fill=255)
        small = filled.resize(MASK_SIZE, Image.Resampling.LANCZOS)
        # A wider transition lets the transparent shader build a soft outer glow
        # while the 0.5 contour remains pinned to the same image boundary.
        softened = small.filter(ImageFilter.GaussianBlur(radius=5.5))
        softened.save(OUTPUT / f"{world_id}.png", optimize=True)


if __name__ == "__main__":
    main()
