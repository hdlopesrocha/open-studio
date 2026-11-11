"""Procedural scene artwork used when no image model is configured.

The generator is deliberately dependency-light (Pillow + NumPy) and creates
deterministic cinematic compositions from the scene's lyrics, visual context
and style. It is clearly labelled as procedural artwork, never as AI output.
"""

from __future__ import annotations

import math
import random
from typing import Iterable

import numpy as np
from .video_models import Scene, VisualContext
from .video_styles import get_style
from .video_text import detect_motifs, infer_mood, mood_colours
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        return (128, 128, 128)
    try:
        return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (128, 128, 128)


def _mix(left: tuple[int, int, int], right: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(int(round(a * (1 - amount) + b * amount)) for a, b in zip(left, right))  # type: ignore[return-value]


def _shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    if factor >= 0:
        return _mix(color, (255, 255, 255), factor)
    return _mix(color, (0, 0, 0), -factor)


def _luminance(color: tuple[int, int, int]) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def _palette(context: VisualContext, mood: str) -> list[tuple[int, int, int]]:
    style = get_style(context.style_id)
    source = context.palette if len(context.palette) >= 3 else list(style.palette)
    colors = [_rgb(value) for value in source]
    mood_colors = [_rgb(value) for value in mood_colours(mood)]
    # Keep the project palette authoritative but allow the emotional palette to
    # warm/cool the extremes slightly.
    if colors:
        colors[-1] = _mix(colors[-1], mood_colors[-1], 0.2)
    return colors


def _fbm(rng: random.Random, length: int, octaves: int = 5) -> np.ndarray:
    x = np.linspace(0.0, 1.0, length)
    result = np.zeros(length)
    amplitude = 1.0
    frequency = 3
    total = 0.0
    for _ in range(octaves):
        controls = np.asarray([rng.random() for _ in range(frequency + 1)])
        points = np.linspace(0.0, 1.0, frequency + 1)
        layer = np.interp(x, points, controls)
        kernel = np.ones(7) / 7
        layer = np.convolve(layer, kernel, mode="same")
        result += amplitude * layer
        total += amplitude
        amplitude *= 0.55
        frequency *= 2
    return result / max(total, 1e-9)


def _gradient(size: tuple[int, int], colors: Iterable[tuple[int, int, int]]) -> np.ndarray:
    width, height = size
    anchors = list(colors)
    ys = np.linspace(0.0, 1.0, height)
    output = np.zeros((height, width, 3), dtype=np.float32)
    if not anchors:
        anchors = [(10, 10, 20), (60, 60, 80)]
    segments = len(anchors) - 1
    for y_index, y in enumerate(ys):
        position = y * segments
        index = min(int(position), segments - 1) if segments else 0
        fraction = position - index if segments else 0.0
        left = anchors[max(0, index)]
        right = anchors[min(len(anchors) - 1, index + 1)]
        color = _mix(left, right, fraction)
        output[y_index, :, :] = color
    return output


def _merge_overlay(image: Image.Image, overlay: Image.Image) -> None:
    base = image.convert("RGBA")
    merged = Image.alpha_composite(base, overlay).convert("RGB")
    image.paste(merged)


def _add_radial_glow(
    image: Image.Image,
    center: tuple[float, float],
    radius: float,
    color: tuple[int, int, int],
    strength: float,
) -> Image.Image:
    width, height = image.size
    y, x = np.ogrid[:height, :width]
    distance = np.sqrt((x - center[0]) ** 2 + (y - center[1]) ** 2)
    falloff = np.clip(1.0 - distance / max(radius, 1.0), 0.0, 1.0) ** 2
    alpha = (falloff * (255 * strength)).astype(np.uint8)
    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    overlay[:, :, 0] = color[0]
    overlay[:, :, 1] = color[1]
    overlay[:, :, 2] = color[2]
    overlay[:, :, 3] = alpha
    glow = Image.fromarray(overlay, "RGBA")
    return Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")


def _draw_clouds(
    image: Image.Image,
    rng: random.Random,
    palette: list[tuple[int, int, int]],
    horizon: int,
    count: int,
    opacity: float,
) -> Image.Image:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    light = palette[-1]
    for _ in range(count):
        y = rng.uniform(height * 0.08, horizon * 0.7)
        center_x = rng.uniform(-0.1, 1.1) * width
        cloud_width = rng.uniform(width * 0.15, width * 0.45)
        cloud_height = cloud_width * rng.uniform(0.06, 0.18)
        for _puff in range(rng.randint(4, 8)):
            dx = rng.uniform(-cloud_width * 0.45, cloud_width * 0.45)
            dy = rng.uniform(-cloud_height * 0.3, cloud_height * 0.3)
            rx = rng.uniform(cloud_width * 0.12, cloud_width * 0.3)
            ry = rng.uniform(cloud_height * 0.25, cloud_height * 0.7)
            alpha = int(rng.uniform(25, 70) * opacity)
            draw.ellipse(
                [center_x + dx - rx, y + dy - ry, center_x + dx + rx, y + dy + ry],
                fill=(*light, alpha),
            )
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(2, width // 180)))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _draw_stars(image: Image.Image, rng: random.Random, horizon: int, count: int, color: tuple[int, int, int]) -> None:
    width, _height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    for _ in range(count):
        x = rng.uniform(0, width)
        y = rng.uniform(0, horizon * 0.95)
        radius = rng.choice([0.6, 0.8, 1.0, 1.4, 2.0, 2.6])
        alpha = int(rng.uniform(80, 230))
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(*color, alpha))
        if radius > 1.8 and rng.random() < 0.4:
            draw.line([x - radius * 3, y, x + radius * 3, y], fill=(*color, alpha // 3), width=1)
            draw.line([x, y - radius * 3, x, y + radius * 3], fill=(*color, alpha // 3), width=1)


def _draw_mountains(
    image: Image.Image,
    rng: random.Random,
    palette: list[tuple[int, int, int]],
    horizon: int,
    snow: bool = False,
) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    layers = 4
    for layer in range(layers):
        depth = layer / max(1, layers - 1)
        base = horizon - int(height * (0.02 + depth * 0.13))
        amplitude = height * (0.035 + depth * 0.11)
        noise = _fbm(rng, width, octaves=5)
        points = [(x, base - int((value - 0.5) * amplitude * 2)) for x, value in enumerate(noise)]
        color = _mix(palette[1], palette[0], 0.25 + depth * 0.4)
        points += [(width, horizon + height), (0, horizon + height)]
        draw.polygon(points, fill=(*color, int(210 + depth * 40)))
        if snow and layer >= layers - 2:
            for point_index in range(0, len(points) - 2, max(1, width // 80)):
                x, y = points[point_index]
                if y < horizon:
                    draw.polygon(
                        [(x - 4, y + 8), (x, y - 3), (x + 4, y + 8)],
                        fill=(240, 243, 245, 110),
                    )


def _draw_city(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], horizon: int) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    base = horizon + 1
    x = -10
    while x < width + 20:
        building_width = rng.uniform(width * 0.018, width * 0.075)
        building_height = rng.uniform(height * 0.04, height * 0.2) * rng.uniform(0.5, 1.2)
        shade = _mix(palette[0], palette[1], rng.uniform(0.2, 0.7))
        draw.rectangle(
            [x, base - building_height, x + building_width, base],
            fill=(*shade, 245),
        )
        if rng.random() < 0.6:
            window_color = palette[-1]
            for row in range(int(building_height // 12)):
                for column in range(int(building_width // 10)):
                    if rng.random() < 0.42:
                        wx = x + 4 + column * 10
                        wy = base - building_height + 6 + row * 12
                        draw.rectangle([wx, wy, wx + 3, wy + 5], fill=(*window_color, 150))
        x += building_width + rng.uniform(1, 8)
    # Street reflections / horizon haze.
    draw.rectangle([0, horizon - 1, width, horizon + 4], fill=(*palette[-2], 38))
    for _ in range(24):
        x = rng.uniform(0, width)
        street_y = rng.uniform(horizon + height * 0.03, height * 0.85)
        draw.line(
            [x, street_y, x + rng.uniform(2, width * 0.04), street_y],
            fill=(*palette[-1], rng.randint(12, 40)),
            width=1,
        )


def _draw_forest(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], horizon: int) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    for layer in range(3):
        depth = layer / 2
        count = int(18 + 25 * depth)
        tree_color = _mix(palette[0], palette[1], 0.35 - depth * 0.2)
        base = horizon + height * (0.01 + depth * 0.06)
        for _ in range(count):
            x = rng.uniform(-20, width + 20)
            tree_height = rng.uniform(height * (0.08 + depth * 0.1), height * (0.2 + depth * 0.18))
            trunk_width = max(1, int(2 + depth * 5))
            draw.line([x, base, x, base - tree_height], fill=(*tree_color, 210), width=trunk_width)
            canopy_r = tree_height * rng.uniform(0.14, 0.28)
            for level in range(rng.randint(2, 4)):
                cy = base - tree_height + canopy_r * level * 0.6
                draw.ellipse(
                    [x - canopy_r, cy - canopy_r * 0.7, x + canopy_r, cy + canopy_r * 0.7],
                    fill=(*_shade(tree_color, 0.03), 190),
                )
    # Light shafts through the trees.
    for _ in range(5):
        x = rng.uniform(width * 0.1, width * 0.9)
        draw.polygon(
            [(x - 25, 0), (x + 25, 0), (x + 170, horizon), (x + 60, horizon)],
            fill=(*palette[-1], 14),
        )


def _draw_dunes(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], horizon: int) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    for layer in range(4):
        depth = layer / 3
        base = horizon + int(height * (0.01 + depth * 0.2))
        amplitude = height * (0.025 + depth * 0.07)
        noise = _fbm(rng, width, octaves=3)
        points = [(x, base + int((value - 0.5) * amplitude)) for x, value in enumerate(noise)]
        color = _mix(palette[2], palette[0], 0.2 + depth * 0.5)
        draw.polygon(points + [(width, height), (0, height)], fill=(*color, 255))


def _draw_water(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], horizon: int, sun_x: float) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(horizon, height):
        depth = (y - horizon) / max(1, height - horizon)
        color = _mix(palette[2], palette[0], 0.35 + depth * 0.45)
        draw.line([0, y, width, y], fill=(*color, 170))
    # Reflection column.
    for y in range(horizon, height, 2):
        depth = (y - horizon) / max(1, height - horizon)
        spread = width * (0.01 + depth * 0.2)
        center = sun_x + math.sin(y * 0.12) * width * 0.008
        for _ in range(3):
            x = rng.gauss(center, spread)
            length = rng.uniform(width * 0.005, width * 0.05) * (0.4 + depth)
            draw.line(
                [x - length / 2, y, x + length / 2, y],
                fill=(*palette[-1], int(50 + 100 * (1 - depth))),
                width=1 if depth > 0.4 else 2,
            )
    # Horizontal glints.
    for _ in range(80):
        y = rng.uniform(horizon, height)
        depth = (y - horizon) / max(1, height - horizon)
        x = rng.uniform(0, width)
        draw.line(
            [x, y, x + rng.uniform(4, width * 0.08), y],
            fill=(*palette[-1], int(rng.uniform(20, 70) * (1 - depth * 0.5))),
            width=1,
        )
    overlay = overlay.filter(ImageFilter.GaussianBlur(0.4))
    _merge_overlay(image, overlay)


def _draw_road(
    image: Image.Image,
    rng: random.Random,
    palette: list[tuple[int, int, int]],
    width: int,
    height: int,
    horizon: int,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    vanishing = (int(width * rng.uniform(0.45, 0.55)), horizon)
    road_half_bottom = width * rng.uniform(0.18, 0.32)
    road_half_horizon = max(2, width // 300)
    points = [
        (vanishing[0] - road_half_horizon, vanishing[1]),
        (vanishing[0] + road_half_horizon, vanishing[1]),
        (int(width * 0.5 + road_half_bottom), height),
        (int(width * 0.5 - road_half_bottom), height),
    ]
    draw.polygon(points, fill=(*_mix(palette[0], (0, 0, 0), 0.25), 215))
    for index in range(1, 10):
        depth = index / 10
        y = horizon + (height - horizon) * depth * depth
        half_width = road_half_horizon + (road_half_bottom - road_half_horizon) * depth
        dash_height = max(2, int(height * 0.008 * depth))
        draw.rectangle(
            [
                int(vanishing[0] - half_width * 0.03),
                int(y),
                int(vanishing[0] + half_width * 0.03),
                int(y + dash_height),
            ],
            fill=(*palette[-1], 180),
        )


def _draw_fireflies(image: Image.Image, rng: random.Random, color: tuple[int, int, int], count: int) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for _ in range(count):
        x = rng.uniform(0, width)
        y = rng.uniform(height * 0.25, height * 0.97)
        radius = rng.uniform(0.7, 2.4)
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(*color, rng.randint(90, 210)))
    overlay = overlay.filter(ImageFilter.GaussianBlur(1.0))
    _merge_overlay(image, overlay)


def _draw_ground_plane(
    image: Image.Image,
    rng: random.Random,
    palette: list[tuple[int, int, int]],
    horizon: int,
    *,
    hills: bool = True,
) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(horizon, height):
        depth = (y - horizon) / max(1, height - horizon)
        color = _mix(_mix(palette[1], palette[0], 0.5), palette[0], 0.25 + depth * 0.65)
        draw.line([0, y, width, y], fill=(*color, 245))
    if hills:
        layers = 3
        for layer in range(layers):
            depth = layer / max(1, layers - 1)
            base = horizon + int(height * (0.015 + depth * 0.11))
            amplitude = height * (0.018 + depth * 0.05)
            noise = _fbm(rng, width, octaves=4)
            points = [
                (x, base - int((value - 0.45) * amplitude * 2))
                for x, value in enumerate(noise)
            ]
            color = _mix(palette[2], palette[0], 0.25 + depth * 0.5)
            draw.polygon(points + [(width, height), (0, height)], fill=(*color, 235))
    overlay = overlay.filter(ImageFilter.GaussianBlur(0.5))
    _merge_overlay(image, overlay)
    # Atmospheric haze softens the seam between sky and ground.
    haze = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    haze_draw = ImageDraw.Draw(haze)
    haze_draw.rectangle(
        [0, max(0, horizon - int(height * 0.055)), width, horizon + int(height * 0.035)],
        fill=(*palette[-2], 55),
    )
    haze = haze.filter(ImageFilter.GaussianBlur(max(3, height // 70)))
    _merge_overlay(image, haze)


def _draw_horizon_haze(
    image: Image.Image,
    palette: list[tuple[int, int, int]],
    horizon: int,
) -> None:
    width, height = image.size
    band = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(band)
    draw.rectangle(
        [0, max(0, horizon - int(height * 0.025)), width, horizon + int(height * 0.025)],
        fill=(*palette[-2], 42),
    )
    band = band.filter(ImageFilter.GaussianBlur(max(3, height // 80)))
    _merge_overlay(image, band)


def _draw_figure(
    image: Image.Image,
    rng: random.Random,
    context: VisualContext,
    palette: list[tuple[int, int, int]],
    ground: float,
    *,
    companion: bool,
    scale: float = 1.0,
    shadow: bool = True,
) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    character = context.characters[0] if context.characters else None
    accent = _rgb(character.accent_color) if character else palette[-2]
    companion_accent = (
        _rgb(context.characters[1].accent_color) if len(context.characters) > 1 else accent
    )
    figure_height = max(28.0, height * 0.135 * scale)
    ground = min(height - 2, ground)
    base_x = width * rng.uniform(0.36, 0.6)
    body_color = _mix(palette[0], (0, 0, 0), 0.62)
    rim_color = _mix(body_color, palette[1], 0.45)
    figure_count = 2 if companion and len(context.characters) > 1 else 1
    for figure_index in range(figure_count):
        x = base_x + figure_index * figure_height * 0.62
        if x > width * 0.82:
            x -= figure_height * 1.3
        head_radius = figure_height * 0.105
        head_center = (x, ground - figure_height + head_radius)
        # Soft contact shadow, deliberately restrained.
        if shadow and figure_index == 0:
            draw.ellipse(
                [x - figure_height * 0.28, ground - figure_height * 0.015,
                 x + figure_height * 0.28, ground + figure_height * 0.045],
                fill=(0, 0, 0, 65),
            )
            draw.ellipse(
                [x - figure_height * 0.16, ground - figure_height * 0.01,
                 x + figure_height * 0.2, ground + figure_height * 0.025],
                fill=(0, 0, 0, 28),
            )
        # Legs.
        leg_top = ground - figure_height * 0.36
        leg_width = max(1.0, figure_height * 0.052)
        draw.line([(x - figure_height * 0.055, leg_top), (x - figure_height * 0.065, ground)], fill=(*body_color, 245), width=max(2, int(leg_width)))
        draw.line([(x + figure_height * 0.055, leg_top), (x + figure_height * 0.07, ground)], fill=(*body_color, 245), width=max(2, int(leg_width)))
        # Coat / torso.
        draw.polygon(
            [
                (x - figure_height * 0.075, ground - figure_height * 0.72),
                (x + figure_height * 0.075, ground - figure_height * 0.72),
                (x + figure_height * 0.105, ground - figure_height * 0.34),
                (x + figure_height * 0.15, ground - figure_height * 0.18),
                (x - figure_height * 0.15, ground - figure_height * 0.18),
                (x - figure_height * 0.105, ground - figure_height * 0.34),
            ],
            fill=(*body_color, 248),
        )
        # Neck and head.
        draw.rectangle(
            [x - head_radius * 0.34, head_center[1] + head_radius * 0.7,
             x + head_radius * 0.34, ground - figure_height * 0.73],
            fill=(*body_color, 248),
        )
        draw.ellipse(
            [x - head_radius, head_center[1] - head_radius, x + head_radius, head_center[1] + head_radius],
            fill=(*body_color, 250),
        )
        # Rim light.
        draw.arc(
            [x - head_radius, head_center[1] - head_radius, x + head_radius, head_center[1] + head_radius],
            300, 80, fill=(*rim_color, 180), width=max(1, int(figure_height * 0.012)),
        )
        figure_accent = accent if figure_index == 0 else companion_accent
        # Scarf and a single bright accent stripe make the recurring character recognisable.
        draw.line(
            [(x - head_radius * 1.25, head_center[1] + head_radius * 1.15),
             (x + head_radius * 1.25, head_center[1] + head_radius * 1.25)],
            fill=(*figure_accent, 235), width=max(1, int(figure_height * 0.032)),
        )
        draw.line(
            [(x, ground - figure_height * 0.68), (x, ground - figure_height * 0.22)],
            fill=(*_mix(figure_accent, body_color, 0.35), 200), width=max(1, int(figure_height * 0.022)),
        )
        # Arm suggestion.
        draw.line(
            [(x + figure_height * 0.08, ground - figure_height * 0.64),
             (x + figure_height * 0.16, ground - figure_height * 0.42)],
            fill=(*body_color, 245), width=max(2, int(leg_width * 0.85)),
        )


def _draw_rain(image: Image.Image, rng: random.Random, color: tuple[int, int, int], count: int) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for _ in range(count):
        x = rng.uniform(-width * 0.1, width)
        y = rng.uniform(0, height)
        length = rng.uniform(height * 0.02, height * 0.09)
        drift = length * 0.34
        draw.line([x, y, x + drift, y + length], fill=(*color, rng.randint(22, 80)), width=1)
    _merge_overlay(image, overlay)


def _draw_snow(image: Image.Image, rng: random.Random, color: tuple[int, int, int], count: int) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for _ in range(count):
        x = rng.uniform(0, width)
        y = rng.uniform(0, height)
        radius = rng.uniform(0.8, 3.2)
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(*color, rng.randint(50, 190)))
    _merge_overlay(image, overlay)


def _draw_synthwave_grid(image: Image.Image, palettes: list[tuple[int, int, int]], horizon: int) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    neon = palettes[2] if len(palettes) > 2 else (255, 42, 109)
    vanishing = (width // 2, horizon)
    for index in range(-14, 15):
        bottom_x = width // 2 + index * width * 0.12
        draw.line([vanishing, (bottom_x, height)], fill=(*neon, 75), width=1)
    for index in range(1, 12):
        fraction = (index / 12) ** 2.2
        y = horizon + (height - horizon) * fraction
        draw.line([0, y, width, y], fill=(*neon, 60), width=1)
    overlay = overlay.filter(ImageFilter.GaussianBlur(0.7))
    _merge_overlay(image, overlay)


def _post_process(
    image: Image.Image,
    rng: random.Random,
    style_id: str,
    palette: list[tuple[int, int, int]],
    scene: Scene,
) -> Image.Image:
    width, height = image.size
    # Bloom / halation.
    bright = image.filter(ImageFilter.GaussianBlur(max(2, width // 120)))
    image = Image.blend(image, ImageChops.screen(image, bright), 0.28)
    if style_id == "noir":
        gray = image.convert("L")
        tint = Image.new("RGB", image.size, (160, 178, 190))
        image = ImageChops.multiply(Image.merge("RGB", [gray, gray, gray]), tint)
        image = ImageEnhance.Contrast(image).enhance(1.25)
        image = ImageEnhance.Brightness(image).enhance(0.9)
    elif style_id == "watercolor":
        image = image.filter(ImageFilter.GaussianBlur(1.1))
        paper = np.asarray(image).astype(np.float32)
        texture = np.random.default_rng(scene.seed).normal(0, 9, paper.shape[:2])[:, :, None]
        paper = np.clip(paper + texture * 0.35 + 6, 0, 255)
        image = Image.fromarray(paper.astype(np.uint8), "RGB")
        image = ImageEnhance.Contrast(image).enhance(0.92)
        image = ImageEnhance.Color(image).enhance(0.9)
    elif style_id == "documentary":
        image = ImageEnhance.Color(image).enhance(0.78)
        image = ImageEnhance.Contrast(image).enhance(1.06)
    elif style_id == "anime":
        image = ImageEnhance.Color(image).enhance(1.22)
        image = ImageEnhance.Contrast(image).enhance(1.04)
    elif style_id == "synthwave":
        image = ImageEnhance.Color(image).enhance(1.3)
        image = ImageEnhance.Contrast(image).enhance(1.08)
    elif style_id == "cinematic":
        image = ImageEnhance.Color(image).enhance(1.1)
        image = ImageEnhance.Contrast(image).enhance(1.08)

    # Vignette.
    y, x = np.ogrid[:height, :width]
    cx, cy = width / 2, height / 2
    distance = np.sqrt(((x - cx) / width) ** 2 + ((y - cy) / height) ** 2)
    vignette = np.clip(1.0 - (distance**2.1) * 1.25, 0.38, 1.0)
    array = np.asarray(image).astype(np.float32) * vignette[:, :, None]
    # Grain.
    grain_rng = np.random.default_rng(scene.seed + len(scene.visual_effects))
    grain = grain_rng.normal(0, 4.2 if style_id != "watercolor" else 2.2, array.shape[:2])[:, :, None]
    array = np.clip(array + grain, 0, 255)
    image = Image.fromarray(array.astype(np.uint8), "RGB")
    # A restrained warm highlight wash to unify the palette.
    warm = Image.new("RGB", image.size, _shade(palette[-2], 0.05))
    image = Image.blend(image, ImageChops.screen(image, warm), 0.07)
    return image


def generate_procedural_art(
    scene: Scene,
    context: VisualContext,
    width: int,
    height: int,
    *,
    variant: int = 0,
) -> Image.Image:
    seed = int(scene.seed) * 101 + variant * 7919 + int(context.seed)
    rng = random.Random(seed)
    style = get_style(context.style_id)
    scene_text = " ".join([scene.description, scene.lyrics])
    motifs = detect_motifs([scene_text], limit=5)
    if not motifs:
        motifs = context.motifs[:4] or ["journey"]
    terrain_priority = {
        "forest": 0,
        "ocean": 1,
        "river": 2,
        "mountain": 3,
        "desert": 4,
        "city": 5,
        "road": 6,
        "journey": 7,
        "flowers": 8,
        "snow": 9,
        "fire": 10,
        "war": 11,
        "rain": 12,
        "space": 13,
        "night": 14,
        "sunrise": 15,
        "home": 16,
        "childhood": 17,
        "freedom": 18,
        "dance": 19,
    }
    motif = sorted(motifs, key=lambda value: terrain_priority.get(value, 50))[0]
    mood = infer_mood([scene.lyrics, scene.description], energy=scene.energy)
    palette = _palette(context, mood)
    if style.id == "noir":
        palette = [_mix(color, (128, 128, 128), 0.82) for color in palette]
    width, height = max(320, width), max(180, height)
    horizon = int(height * rng.uniform(0.58, 0.7))
    if motif in {"ocean", "river", "rain"}:
        horizon = int(height * rng.uniform(0.48, 0.58))
    if motif in {"space", "night"}:
        horizon = int(height * rng.uniform(0.65, 0.78))

    sky_colors = [palette[0], _mix(palette[0], palette[1], 0.55), palette[-2]]
    sky_array = _gradient((width, height), sky_colors)
    image = Image.fromarray(sky_array.astype(np.uint8), "RGB").convert("RGBA")

    night = motif in {"night", "space"} or mood in {"dark", "dreamy"} and rng.random() < 0.4
    if night:
        _draw_stars(image, rng, horizon, int(width * height / 16000), palette[-1])
        moon_x = rng.uniform(width * 0.62, width * 0.82)
        moon_y = rng.uniform(height * 0.1, horizon * 0.5)
        radius = height * rng.uniform(0.03, 0.055)
        image = _add_radial_glow(image, (moon_x, moon_y), radius * 5, palette[-1], 0.22)
        draw = ImageDraw.Draw(image, "RGBA")
        draw.ellipse(
            [moon_x - radius, moon_y - radius, moon_x + radius, moon_y + radius],
            fill=(*palette[-1], 245),
        )
        # Crater suggestion.
        draw.ellipse(
            [moon_x - radius * 0.3, moon_y - radius * 0.2, moon_x + radius * 0.1, moon_y + radius * 0.15],
            fill=(*_shade(palette[-1], -0.12), 100),
        )
    else:
        sun_x = width * rng.uniform(0.22, 0.78)
        sun_y = horizon - height * rng.uniform(0.02, 0.1)
        sun_radius = height * rng.uniform(0.025, 0.065)
        image = _add_radial_glow(image, (sun_x, sun_y), height * 0.5, palette[-1], 0.35)
        draw = ImageDraw.Draw(image, "RGBA")
        draw.ellipse(
            [sun_x - sun_radius, sun_y - sun_radius, sun_x + sun_radius, sun_y + sun_radius],
            fill=(*_shade(palette[-1], 0.2), 245),
        )
        if motif in {"fire", "desert"}:
            image = _add_radial_glow(image, (sun_x, sun_y), height * 0.8, _rgb("#F97316"), 0.25)

    image = _draw_clouds(
        image,
        rng,
        palette,
        horizon,
        count=6 if night else rng.randint(5, 11),
        opacity=0.4 if night else 1.0,
    )

    if motif in {"mountain", "snow", "war"}:
        _draw_mountains(image, rng, palette, horizon, snow=motif in {"snow", "mountain"})
    if motif == "city":
        _draw_city(image, rng, palette, horizon)
    if motif == "forest":
        _draw_forest(image, rng, palette, horizon)
    if motif == "desert":
        _draw_dunes(image, rng, palette, horizon)
    if motif in {"ocean", "river"}:
        _draw_mountains(image, rng, palette, max(10, horizon - height // 8), snow=False)
        _draw_water(image, rng, palette, horizon, sun_x=width * 0.5)
    if motif == "road" or motif == "journey":
        _draw_mountains(image, rng, palette, horizon, snow=motif == "snow")
    if motif == "flowers":
        _draw_mountains(image, rng, palette, horizon, snow=False)

    image = image.convert("RGBA")
    if motif in {"ocean", "river"}:
        # A dark foreground shore gives the character something to stand on.
        shore_band = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        shore_draw = ImageDraw.Draw(shore_band)
        noise = _fbm(rng, width, octaves=3)
        shore_y = int(height * 0.88)
        points = [
            (x, shore_y + int((value - 0.5) * height * 0.025))
            for x, value in enumerate(noise)
        ]
        shore_draw.polygon(
            points + [(width, height), (0, height)],
            fill=(*_mix(palette[0], (0, 0, 0), 0.25), 250),
        )
        _merge_overlay(image, shore_band)
    elif motif == "desert":
        horizon_band = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        band_draw = ImageDraw.Draw(horizon_band)
        band_draw.rectangle([0, horizon + 4, width, height], fill=(*_mix(palette[2], palette[0], 0.68), 55))
        _merge_overlay(image, horizon_band)
    elif motif in {"city", "forest"}:
        _draw_ground_plane(image, rng, palette, horizon, hills=(motif == "forest"))
    else:
        _draw_ground_plane(image, rng, palette, horizon)

    _draw_horizon_haze(image, palette, horizon)

    if motif in {"road", "journey"}:
        _draw_road(image, rng, palette, width, height, horizon)

    if motif == "space":
        # Nebula wash.
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for _ in range(4):
            x = rng.uniform(0, width)
            y = rng.uniform(0, horizon)
            radius = rng.uniform(width * 0.08, width * 0.3)
            colour = palette[2] if len(palette) > 2 else (100, 100, 180)
            draw.ellipse([x - radius, y - radius * 0.5, x + radius, y + radius * 0.5], fill=(*colour, 22))
        overlay = overlay.filter(ImageFilter.GaussianBlur(width // 60))
        image = Image.alpha_composite(image, overlay)

    if motif in {"fire", "night"}:
        _draw_fireflies(image, rng, palette[-1] if motif == "night" else _rgb("#FFB45C"), rng.randint(18, 45))
    if motif == "forest":
        _draw_fireflies(image, rng, _rgb("#FFE29A"), rng.randint(12, 28))
    if motif == "rain":
        _draw_rain(image, rng, palette[-1], int(width * height / 9000))
    if motif == "snow":
        _draw_snow(image, rng, palette[-1], int(width * height / 12000))
    if motif == "synthwave" or style.id == "synthwave":
        _draw_synthwave_grid(image, palette, horizon)
    if motif == "flowers":
        draw = ImageDraw.Draw(image, "RGBA")
        for _ in range(70):
            x = rng.uniform(0, width)
            y = rng.uniform(horizon, height)
            radius = rng.uniform(1, 4.5)
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(*palette[-2], rng.randint(60, 160)))
    if rng.random() < 0.35:
        # Distant birds for scale and life.
        draw = ImageDraw.Draw(image, "RGBA")
        for _ in range(rng.randint(2, 6)):
            bx = rng.uniform(width * 0.1, width * 0.9)
            by = rng.uniform(height * 0.1, horizon * 0.7)
            size = rng.uniform(3, 9)
            draw.arc([bx - size, by - size / 2, bx, by + size / 2], 180, 330, fill=(*palette[-1], 120), width=1)
            draw.arc([bx, by - size / 2, bx + size, by + size / 2], 210, 360, fill=(*palette[-1], 120), width=1)

    companion = len(context.characters) > 1 and mood in {"romantic", "hopeful"}
    description_lower = scene.description.lower()
    if "close" in description_lower:
        figure_scale = 1.75
    elif "aerial" in description_lower or "wide" in description_lower:
        figure_scale = 0.9
    else:
        figure_scale = 1.15
    if motif == "city":
        figure_ground = int(height * 0.83)
    elif motif in {"ocean", "river"}:
        figure_ground = int(height * 0.9)
    else:
        figure_ground = int(height * 0.87)
    _draw_figure(
        image,
        rng,
        context,
        palette,
        figure_ground,
        companion=companion,
        scale=figure_scale,
        shadow=motif not in {"ocean", "river"},
    )

    image = image.convert("RGB")
    image = _post_process(image, rng, style.id, palette, scene)
    return image
