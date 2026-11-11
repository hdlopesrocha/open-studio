"""Deterministic project cover art (Pillow only)."""

from __future__ import annotations

import math
import random
from pathlib import Path

from mvstudio_shared.models import Project, VisualContext
from mvstudio_shared.styles import get_style
from PIL import Image, ImageDraw, ImageFont


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        return (30, 40, 60)
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _gradient(width: int, height: int, colors: list[tuple[int, int, int]]) -> Image.Image:
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    segments = max(1, len(colors) - 1)
    for y in range(height):
        position = y / max(1, height - 1) * segments
        index = min(int(position), segments - 1)
        fraction = position - index
        left, right = colors[index], colors[min(index + 1, len(colors) - 1)]
        color = tuple(int(left[channel] * (1 - fraction) + right[channel] * fraction) for channel in range(3))
        for x in range(width):
            pixels[x, y] = color
    return image


def _font(paths: list[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def generate_cover(
    project: Project,
    cover_path: Path,
    context: VisualContext | None = None,
    *,
    width: int = 1200,
    height: int = 675,
) -> Path:
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    style = get_style(project.config.scenes.style_id)
    palette = context.palette if context and len(context.palette) >= 3 else list(style.palette)
    colors = [_rgb(value) for value in palette[:5]]
    if len(colors) < 2:
        colors = [(8, 17, 31), (58, 107, 126), (242, 214, 179)]
    image = _gradient(width, height, [colors[0], colors[1], colors[min(3, len(colors) - 1)]])
    draw = ImageDraw.Draw(image, "RGBA")
    rng = random.Random(project.id)

    horizon = int(height * 0.62)
    sun_radius = int(height * 0.095)
    sun_x = int(width * rng.uniform(0.6, 0.78))
    sun_y = horizon - int(height * 0.04)
    accent = colors[min(3, len(colors) - 1)]
    for radius in range(sun_radius * 4, 0, -max(1, sun_radius // 6)):
        alpha = max(2, int(28 * (1 - radius / (sun_radius * 4))))
        draw.ellipse(
            [sun_x - radius, sun_y - radius, sun_x + radius, sun_y + radius],
            fill=(*accent, alpha),
        )
    draw.ellipse(
        [sun_x - sun_radius, sun_y - sun_radius, sun_x + sun_radius, sun_y + sun_radius],
        fill=(*accent, 220),
    )
    for layer in range(3):
        depth = layer / 2
        points = [(0, height)]
        base = horizon + int(height * (0.015 + depth * 0.12))
        amplitude = int(height * (0.025 + depth * 0.05))
        for x in range(0, width + 1, 24):
            wave = (
                rng.uniform(-0.35, 0.35) * 0.3
                + math.sin(x / width * (5 + layer * 3) + layer) * 0.65
            )
            points.append((x, base - int(wave * amplitude)))
        points.append((width, height))
        shade = colors[min(layer + 1, len(colors) - 1)]
        draw.polygon(points, fill=(*shade, 235))

    bars = 72
    bar_width = width * 0.55 / bars
    start_x = width * 0.075
    for index in range(bars):
        amplitude = (
            math.sin(index * 0.47) * 0.35
            + math.sin(index * 0.13 + 1.2) * 0.45
            + rng.uniform(-0.12, 0.12)
        )
        bar_height = max(2, int(abs(amplitude) * height * 0.12))
        x = start_x + index * bar_width
        draw.rounded_rectangle(
            [x, height * 0.86 - bar_height, x + bar_width * 0.55, height * 0.86 + bar_height],
            radius=2,
            fill=(*accent, 165),
        )

    title = project.title or project.name
    artist = project.artist or "Local music video"
    title_font = _font(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        ],
        max(26, int(height * 0.085)),
    )
    small_font = _font(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ],
        max(14, int(height * 0.032)),
    )
    margin = int(width * 0.06)
    draw.text((margin, int(height * 0.075)), "OPEN STUDIO · VIDEO", font=small_font, fill=(255, 255, 255, 130))
    wrapped = title
    if len(wrapped) > 42:
        wrapped = wrapped[:39] + "…"
    draw.text((margin, int(height * 0.11)), wrapped, font=title_font, fill=(255, 255, 255, 245))
    draw.text(
        (margin, int(height * 0.11) + int(height * 0.12)),
        artist,
        font=small_font,
        fill=(255, 255, 255, 185),
    )

    image.save(cover_path, format="JPEG", quality=90, optimize=True)
    return cover_path
