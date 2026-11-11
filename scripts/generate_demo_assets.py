"""Generate the deterministic demo artwork used by the screenshot build.

These are deliberately abstract rather than stock photos: the README screenshots
show the actual Open Studio UI with a coherent visual identity.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "demo"
OUT.mkdir(parents=True, exist_ok=True)

PALETTES = [
    ["#070a12", "#1b1140", "#7c3aed", "#22d3ee", "#f59e0b"],
    ["#05080c", "#0d2233", "#0ea5e9", "#f472b6", "#fde68a"],
    ["#0c0a08", "#2b1a0f", "#f59e0b", "#ef4444", "#fef3c7"],
    ["#080b10", "#102018", "#10b981", "#84cc16", "#e0f2fe"],
    ["#0b0710", "#25123b", "#c026d3", "#818cf8", "#fbcfe8"],
    ["#070b0e", "#15202b", "#64748b", "#22d3ee", "#f8fafc"],
    ["#0a0806", "#2a1210", "#f97316", "#fb7185", "#fef9c3"],
    ["#05090f", "#0b1e3a", "#3b82f6", "#06b6d4", "#c7d2fe"],
]


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))  # type: ignore[return-value]


def gradient(size: int, colors: list[tuple[int, int, int]]) -> Image.Image:
    image = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(image)
    for y in range(size):
        t = y / max(1, size - 1)
        if t < 0.55:
            color = mix(colors[0], colors[1], t / 0.55)
        else:
            color = mix(colors[1], colors[2], (t - 0.55) / 0.45)
        draw.line([(0, y), (size, y)], fill=color)
    return image


def radial_glow(size: int, center: tuple[int, int], radius: int, color: tuple[int, int, int], strength: int) -> Image.Image:
    layer = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for r in range(radius, 0, -4):
        t = 1 - r / radius
        alpha = int(strength * (t**2))
        draw.ellipse(
            [center[0] - r, center[1] - r, center[0] + r, center[1] + r],
            fill=tuple(int(c * alpha / 255) for c in color),
        )
    return layer.filter(ImageFilter.GaussianBlur(radius // 8))


def make(index: int) -> None:
    random.seed(7000 + index)
    size = 1024
    palette = PALETTES[index % len(PALETTES)]
    colors = [hex_rgb(value) for value in palette]
    image = gradient(size, colors)
    draw = ImageDraw.Draw(image, "RGBA")

    # Large atmospheric glow.
    image = Image.blend(image, radial_glow(size, (int(size * 0.3), int(size * 0.35)), 620, colors[3], 180), 0.55)
    image = Image.blend(image, radial_glow(size, (int(size * 0.78), int(size * 0.7)), 440, colors[4], 120), 0.4)
    draw = ImageDraw.Draw(image, "RGBA")

    motif = index % 4
    if motif == 0:  # city blocks / horizon
        for layer in range(5):
            base = int(size * (0.55 + layer * 0.07))
            alpha = 40 + layer * 14
            x = -40
            while x < size + 40:
                width = random.randint(40, 130)
                height = random.randint(40, 190) + layer * 18
                draw.rectangle([x, base - height, x + width, base], fill=(*colors[0], alpha))
                for wy in range(base - height + 12, base - 8, 22):
                    for wx in range(x + 8, x + width - 8, 18):
                        if random.random() < 0.35:
                            draw.rectangle([wx, wy, wx + 5, wy + 8], fill=(*colors[4], random.randint(60, 160)))
                x += width + random.randint(8, 26)
    elif motif == 1:  # rings / orbital
        cx, cy = size // 2, int(size * 0.46)
        for i in range(9):
            r = 90 + i * 52
            draw.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                outline=(*colors[3], 40 + i * 6),
                width=max(2, 14 - i),
            )
        draw.ellipse([cx - 120, cy - 120, cx + 120, cy + 120], fill=(*colors[4], 30))
        for i in range(60):
            angle = random.random() * math.tau
            radius = random.uniform(120, 500)
            x = cx + math.cos(angle) * radius
            y = cy + math.sin(angle) * radius * 0.62
            draw.ellipse([x, y, x + 3, y + 3], fill=(*colors[4], random.randint(80, 220)))
    elif motif == 2:  # landscape / dunes
        points = [(0, size)]
        for x in range(0, size + 1, 16):
            y = int(size * 0.62 + math.sin(x / 120 + index) * 60 + random.uniform(-8, 8))
            points.append((x, y))
        points.append((size, size))
        draw.polygon(points, fill=(*colors[1], 180))
        points2 = [(0, size)]
        for x in range(0, size + 1, 16):
            y = int(size * 0.78 + math.sin(x / 80 + index * 2) * 46 + random.uniform(-6, 6))
            points2.append((x, y))
        points2.append((size, size))
        draw.polygon(points2, fill=(*colors[0], 220))
        draw.ellipse([size * 0.72, size * 0.16, size * 0.84, size * 0.28], fill=(*colors[4], 220))
    else:  # vertical light / figure
        for i in range(22):
            x = int(size * 0.5 + math.sin(i * 0.7 + index) * 18)
            width = random.randint(6, 26)
            draw.line([(x, 0), (x + random.randint(-50, 50), size)], fill=(*colors[3], 12), width=width)
        draw.ellipse([size * 0.36, size * 0.34, size * 0.64, size * 0.82], fill=(*colors[0], 120))
        draw.ellipse([size * 0.44, size * 0.28, size * 0.56, size * 0.4], fill=(*colors[0], 160))

    # Grain.
    noise = Image.effect_noise((size, size), 28).convert("L")
    image = Image.composite(image, image.point(lambda p: min(255, p + 10)), noise.point(lambda p: 18 if p > 128 else 0))

    # Vignette.
    vignette = Image.new("L", (size, size), 0)
    vdraw = ImageDraw.Draw(vignette)
    vdraw.ellipse([-size * 0.18, -size * 0.18, size * 1.18, size * 1.18], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(140))
    black = Image.new("RGB", (size, size), (2, 3, 6))
    image = Image.composite(image, black, vignette)

    # Subtle title band.
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rectangle([0, int(size * 0.84), size, size], fill=(3, 4, 8, 130))
    odraw.text((56, int(size * 0.89)), f"OPEN STUDIO / STUDY {index + 1:02d}", fill=(235, 240, 250, 220))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    image.save(OUT / f"art-{index + 1:02d}.png", quality=92)

    # 16:9 cinematic crop for video previews.
    if index < 4:
        wide = image.crop((0, 120, size, size - 120)).resize((1280, 720), Image.LANCZOS)
        wide.save(OUT / f"film-{index + 1:02d}.jpg", quality=90)


def main() -> None:
    for i in range(8):
        make(i)
    print(f"Wrote demo art to {OUT}")


if __name__ == "__main__":
    main()
