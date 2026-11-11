"""Deterministic, prompt-aware procedural artwork.

This is intentionally model-free: Pillow and NumPy produce an attractive
cinematic/key-art style image for any prompt. It is always labelled procedurally
generated in metadata, and is used as the universal fallback for every provider.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

STYLE_SPECS: dict[str, dict[str, Any]] = {
    "cinematic": {
        "name": "Cinematic",
        "description": "Widescreen film look: teal shadows, golden light, atmospheric haze.",
        "palette": ["#020711", "#0E2438", "#2D6378", "#D98A4D", "#F5E3C4"],
        "motif": "mountain",
        "accent": "#F3B56B",
        "text": "#F7F1E6",
    },
    "anime": {
        "name": "Anime",
        "description": "Painterly anime background with luminous clouds and saturated skies.",
        "palette": ["#101733", "#3C5A9A", "#F07BA4", "#FFC95C", "#A7ECFF"],
        "motif": "sky",
        "accent": "#FFD166",
        "text": "#FFF8F2",
    },
    "noir": {
        "name": "Film Noir",
        "description": "High-contrast monochrome, hard light, rain and smoke.",
        "palette": ["#050506", "#17181B", "#43464B", "#999DA3", "#EFEDE7"],
        "motif": "city",
        "accent": "#E8E2D7",
        "text": "#F5F1E8",
    },
    "watercolor": {
        "name": "Watercolor",
        "description": "Soft pigment washes, paper grain and loose expressive edges.",
        "palette": ["#F3EADD", "#D9C2A7", "#A5BFAF", "#DFAE9C", "#586C66"],
        "motif": "flowers",
        "accent": "#9C5C55",
        "text": "#3C3B37",
    },
    "synthwave": {
        "name": "Synthwave",
        "description": "Retro-futurist neon dusk with chrome sun and laser grid.",
        "palette": ["#070113", "#271044", "#FF2A6D", "#05D9E8", "#F9F871"],
        "motif": "grid",
        "accent": "#05D9E8",
        "text": "#F9F871",
    },
    "documentary": {
        "name": "Documentary",
        "description": "Naturalistic observational photography with honest textures.",
        "palette": ["#171B18", "#36453B", "#7C8978", "#C0B398", "#EDE7DB"],
        "motif": "coast",
        "accent": "#D7C7A5",
        "text": "#F4F0E7",
    },
    "abstract": {
        "name": "Abstract",
        "description": "Layered translucent colour fields, curves and luminous depth.",
        "palette": ["#0A0F24", "#3A1D63", "#C13B78", "#F28C5B", "#F6E7B4"],
        "motif": "abstract",
        "accent": "#F28C5B",
        "text": "#FFF9EE",
    },
    "product": {
        "name": "Product",
        "description": "Studio-lit hero composition with podium, reflections and negative space.",
        "palette": ["#080A0D", "#171E25", "#42515A", "#D2A76A", "#F7EAD7"],
        "motif": "studio",
        "accent": "#E8C88A",
        "text": "#F9F6EF",
    },
}

STYLE_ALIASES = {
    "film": "cinematic",
    "photo": "documentary",
    "photographic": "documentary",
    "retro": "synthwave",
    "neon": "synthwave",
    "ink": "noir",
    "bw": "noir",
    "monochrome": "noir",
    "paint": "watercolor",
    "painting": "watercolor",
    "minimal": "abstract",
    "studio": "product",
}

MOTIF_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mountain": ("mountain", "montanha", "peak", "summit", "cliff", "alps", "himalaya", "hill", "valley"),
    "ocean": ("ocean", "sea", "mar", "wave", "beach", "praia", "shore", "coast", "island", "sail", "boat"),
    "city": ("city", "cidade", "street", "neon", "urban", "skyline", "tokyo", "building", "downtown", "rain"),
    "forest": ("forest", "floresta", "tree", "woods", "jungle", "pine", "mata", "árvore"),
    "desert": ("desert", "deserto", "dune", "sand", "areia", "sahara", "mirage"),
    "space": ("space", "espaço", "galaxy", "nebula", "cosmos", "planet", "estrela", "star", "moon", "lua", "astronaut"),
    "portrait": ("portrait", "woman", "man", "person", "figure", "silhouette", "girl", "boy", "face", "retrato"),
    "flowers": ("flower", "flor", "garden", "jardim", "rose", "bloom", "petal", "spring", "primavera"),
    "road": ("road", "estrada", "highway", "journey", "viagem", "drive", "path", "caminho"),
    "rain": ("rain", "chuva", "storm", "tempestade", "thunder", "wet", "umbrella"),
    "snow": ("snow", "neve", "winter", "inverno", "ice", "frost", "gelo"),
    "fire": ("fire", "fogo", "flame", "ember", "burn", "volcano", "lava"),
}

MOOD_WORDS = {
    "warm": ("golden", "sunset", "warm", "love", "hope", "home", "summer", "amber", "dourado", "sol"),
    "cold": ("cold", "winter", "night", "rain", "lonely", "blue", "frio", "noite", "chuva"),
    "epic": ("epic", "battle", "war", "hero", "dragon", "storm", "king", "guerra", "batalha"),
    "dreamy": ("dream", "magic", "ethereal", "float", "sonho", "fairy", "cloud", "moon"),
    "dark": ("dark", "horror", "death", "shadow", "sombra", "gothic", "evil", "noir"),
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _rgb(value: str) -> tuple[int, int, int]:
    value = (value or "#808080").lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) < 6:
        return (128, 128, 128)
    try:
        return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (128, 128, 128)


def _mix(left: Iterable[int], right: Iterable[int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(int(round(a * (1 - amount) + b * amount)) for a, b in zip(left, right))  # type: ignore[return-value]


def _shade(color: Iterable[int], factor: float) -> tuple[int, int, int]:
    rgb = tuple(int(value) for value in color)
    if factor >= 0:
        return _mix(rgb, (255, 255, 255), factor)
    return _mix(rgb, (0, 0, 0), -factor)


def _even(value: int) -> int:
    return max(64, int(value) - (int(value) % 2))


def _fbm(rng: random.Random, length: int, octaves: int = 5) -> np.ndarray:
    x = np.linspace(0.0, 1.0, max(2, length))
    result = np.zeros_like(x)
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


def _ridge_profile(width: int, rng: random.Random, octaves: int = 4) -> np.ndarray:
    """Smooth, mountain-like ridgeline in 0..1 (no high-frequency sawtooth)."""
    x = np.linspace(0.0, math.tau, max(2, width))
    result = np.zeros_like(x)
    weights = (0.58, 0.26, 0.13, 0.07)
    for index in range(octaves):
        frequency = 1.15 * (1.85**index)
        phase = rng.uniform(0, math.tau)
        result += weights[index % len(weights)] * np.sin(x * frequency + phase)
    kernel = np.ones(11) / 11
    result = np.convolve(result, kernel, mode="same")
    span = float(result.max() - result.min())
    return (result - result.min()) / (span if span > 1e-9 else 1.0)


def _vertical_sky_gradient(
    size: tuple[int, int],
    colors: list[str] | list[tuple[int, int, int]],
    horizon: int,
) -> Image.Image:
    """Vertical gradient whose last colour lands exactly on the horizon."""
    width, height = size
    anchors = [_rgb(color) if isinstance(color, str) else tuple(color) for color in colors]
    if len(anchors) < 2:
        anchors = [anchors[0] if anchors else (8, 10, 20), (90, 110, 130)]
    lut_steps = 1024
    positions = np.linspace(0.0, 1.0, len(anchors))
    lut = np.zeros((lut_steps, 3), dtype=np.float32)
    for channel in range(3):
        lut[:, channel] = np.interp(
            np.linspace(0.0, 1.0, lut_steps),
            positions,
            [color[channel] for color in anchors],
        )
    ys = np.linspace(0.0, 1.0, height)
    t = np.clip(ys / max(0.05, horizon / max(1, height)), 0.0, 1.0)
    indices = (t * (lut_steps - 1)).astype(np.int32)
    rows = lut[indices]
    array = np.repeat(rows[:, None, :], width, axis=1)
    return Image.fromarray(array.astype(np.uint8), "RGB")


def _linear_gradient(size: tuple[int, int], colors: list[str] | list[tuple[int, int, int]], angle: float) -> Image.Image:
    width, height = size
    anchors = [_rgb(color) if isinstance(color, str) else tuple(color) for color in colors]
    if not anchors:
        anchors = [(8, 10, 20), (60, 70, 90)]
    if len(anchors) == 1:
        anchors.append(_shade(anchors[0], 0.2))
    lut_steps = 1024
    positions = np.linspace(0.0, 1.0, len(anchors))
    lut = np.zeros((lut_steps, 3), dtype=np.float32)
    for channel in range(3):
        lut[:, channel] = np.interp(np.linspace(0.0, 1.0, lut_steps), positions, [color[channel] for color in anchors])
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = xx / max(1, width - 1)
    ny = yy / max(1, height - 1)
    rad = math.radians(angle)
    t = (nx - 0.5) * math.cos(rad) + (ny - 0.5) * math.sin(rad)
    t = np.clip(t + 0.5, 0.0, 1.0)
    indices = (t * (lut_steps - 1)).astype(np.int32)
    return Image.fromarray(lut[indices].astype(np.uint8), "RGB")


def _radial_glow(
    image: Image.Image,
    center: tuple[float, float],
    radius: float,
    color: tuple[int, int, int],
    strength: float,
) -> Image.Image:
    width, height = image.size
    y, x = np.ogrid[:height, :width]
    distance = np.sqrt((x - center[0]) ** 2 + (y - center[1]) ** 2)
    falloff = np.clip(1.0 - distance / max(radius, 1.0), 0.0, 1.0) ** 2.2
    glow = np.asarray(image).astype(np.float32)
    tint = np.asarray(color, dtype=np.float32)
    glow += (tint[None, None, :] - glow) * (falloff[:, :, None] * max(0.0, min(1.0, strength)))
    # Screen the tinted glow a little so highlights stay luminous.
    screen = 255.0 - (255.0 - glow) * (255.0 - tint[None, None, :] * (falloff[:, :, None] * strength)) / 255.0
    glow = np.clip(glow * 0.72 + screen * 0.28, 0, 255)
    return Image.fromarray(glow.astype(np.uint8), "RGB")


def _blob(
    image: Image.Image,
    rng: random.Random,
    center: tuple[float, float],
    radius: tuple[float, float],
    color: tuple[int, int, int],
    alpha: int,
    blur: float,
) -> Image.Image:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.ellipse(
        [
            center[0] - radius[0],
            center[1] - radius[1],
            center[0] + radius[0],
            center[1] + radius[1],
        ],
        fill=(*color, max(0, min(255, int(alpha)))),
    )
    if blur > 0:
        overlay = overlay.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _draw_stars(image: Image.Image, rng: random.Random, top_fraction: float, count: int, color: tuple[int, int, int]) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    for _ in range(count):
        x = rng.uniform(0, width)
        y = rng.uniform(0, height * top_fraction)
        radius = rng.choice([0.5, 0.7, 0.9, 1.2, 1.7, 2.4]) * max(1.0, width / 1024)
        alpha = rng.randint(70, 230)
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(*color, alpha))
        if radius > 1.5 and rng.random() < 0.25:
            draw.line([x - radius * 4, y, x + radius * 4, y], fill=(*color, alpha // 3), width=1)


def _draw_clouds(
    image: Image.Image,
    rng: random.Random,
    color: tuple[int, int, int],
    horizon: int,
    count: int,
    opacity: float = 1.0,
) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for _ in range(count):
        cx = rng.uniform(-0.05, 1.05) * width
        cy = rng.uniform(height * 0.07, horizon * 0.72)
        cloud_w = rng.uniform(width * 0.16, width * 0.42)
        cloud_h = cloud_w * rng.uniform(0.05, 0.14)
        for _puff in range(rng.randint(4, 9)):
            dx = rng.uniform(-cloud_w * 0.45, cloud_w * 0.45)
            dy = rng.uniform(-cloud_h * 0.35, cloud_h * 0.35)
            rx = rng.uniform(cloud_w * 0.10, cloud_w * 0.28)
            ry = rng.uniform(cloud_h * 0.22, cloud_h * 0.75)
            alpha = int(rng.uniform(20, 68) * opacity)
            draw.ellipse([cx + dx - rx, cy + dy - ry, cx + dx + rx, cy + dy + ry], fill=(*color, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(2, width // 150)))
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))


def _draw_ridges(
    image: Image.Image,
    rng: random.Random,
    colors: list[tuple[int, int, int]],
    horizon: int,
    layers: int = 4,
    snow: bool = False,
) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    for layer in range(layers):
        depth = layer / max(1, layers - 1)
        base = horizon - int(height * (0.01 + depth * 0.13))
        amplitude = height * (0.025 + depth * 0.105)
        noise = _ridge_profile(width, rng, octaves=4)
        points = [(x, base - int((value - 0.5) * amplitude * 2)) for x, value in enumerate(noise)]
        color = _mix(colors[1], colors[0], 0.2 + depth * 0.45)
        draw.polygon(points + [(width, height + 2), (0, height + 2)], fill=(*color, 250))
        if snow and layer >= layers - 2:
            for index in range(0, len(points) - 1, max(1, width // 34)):
                x, y = points[index]
                if y < horizon:
                    peak = rng.uniform(height * 0.004, height * 0.012)
                    draw.polygon(
                        [(x - peak * 2.4, y + peak), (x, y - peak * 0.75), (x + peak * 2.4, y + peak)],
                        fill=(240, 244, 246, 82),
                    )


def _draw_city(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], horizon: int) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    x = -width * 0.02
    while x < width * 1.03:
        building_w = rng.uniform(width * 0.025, width * 0.085)
        building_h = rng.uniform(height * 0.05, height * 0.23) * rng.uniform(0.6, 1.3)
        color = _mix(palette[0], palette[1], rng.uniform(0.1, 0.55))
        draw.rectangle([x, horizon - building_h, x + building_w, horizon], fill=(*color, 250))
        if rng.random() < 0.7:
            window_color = palette[-1]
            step_x = max(5, width // 180)
            step_y = max(7, height // 120)
            for row in range(int(building_h // step_y)):
                for col in range(int(building_w // step_x)):
                    if rng.random() < 0.33:
                        wx = x + step_x * 0.45 + col * step_x
                        wy = horizon - building_h + step_y * 0.5 + row * step_y
                        draw.rectangle(
                            [wx, wy, wx + max(1, step_x * 0.35), wy + max(2, step_y * 0.35)],
                            fill=(*window_color, rng.randint(45, 150)),
                        )
        x += building_w + rng.uniform(1, width * 0.008)
    draw.rectangle([0, horizon - 1, width, horizon + 3], fill=(*palette[-2], 34))


def _draw_water(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], horizon: int, sun_x: float) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(horizon, height):
        depth = (y - horizon) / max(1, height - horizon)
        color = _mix(palette[2], palette[0], 0.35 + depth * 0.5)
        draw.line([0, y, width, y], fill=(*color, 175))
    for y in range(horizon, height, 2):
        depth = (y - horizon) / max(1, height - horizon)
        spread = width * (0.01 + depth * 0.16)
        center = sun_x + math.sin(y * 0.11) * width * 0.006
        for _ in range(2):
            x = rng.gauss(center, spread)
            length = rng.uniform(width * 0.004, width * 0.045) * (0.5 + depth)
            draw.line([x - length / 2, y, x + length / 2, y], fill=(*palette[-1], int(40 + 100 * (1 - depth))), width=1)
    for _ in range(60):
        y = rng.uniform(horizon, height)
        x = rng.uniform(0, width)
        draw.line([x, y, x + rng.uniform(4, width * 0.07), y], fill=(*palette[-1], rng.randint(15, 55)), width=1)
    overlay = overlay.filter(ImageFilter.GaussianBlur(0.5))
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))


def _draw_forest(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], horizon: int) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    for layer in range(3):
        depth = layer / 2
        color = _mix(palette[0], palette[1], 0.32 - depth * 0.16)
        base = horizon + height * (0.01 + depth * 0.055)
        for _ in range(int(16 + 30 * depth)):
            x = rng.uniform(-0.02, 1.02) * width
            tree_h = rng.uniform(height * (0.07 + depth * 0.1), height * (0.17 + depth * 0.17))
            trunk = max(1, int(2 + depth * 4))
            draw.line([x, base, x, base - tree_h], fill=(*color, 220), width=trunk)
            canopy = tree_h * rng.uniform(0.13, 0.26)
            for level in range(rng.randint(2, 4)):
                cy = base - tree_h + canopy * level * 0.6
                draw.ellipse([x - canopy, cy - canopy * 0.7, x + canopy, cy + canopy * 0.7], fill=(*_shade(color, 0.03), 195))
    for _ in range(4):
        x = rng.uniform(width * 0.1, width * 0.9)
        draw.polygon([(x - width * 0.02, 0), (x + width * 0.02, 0), (x + width * 0.15, horizon), (x + width * 0.06, horizon)], fill=(*palette[-1], 14))


def _draw_flowers(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], horizon: int) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for _ in range(int(width * height / 5000)):
        x = rng.uniform(0, width)
        y = rng.uniform(horizon - height * 0.04, height)
        radius = rng.uniform(1.0, 4.5) * max(0.7, width / 1024)
        color = palette[rng.randrange(1, len(palette))] if len(palette) > 2 else palette[-1]
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(*color, rng.randint(35, 115)))
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(1.0, width / 900)))
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))


def _draw_road(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], horizon: int) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    center = int(width * rng.uniform(0.46, 0.54))
    bottom_half = width * rng.uniform(0.17, 0.28)
    top_half = max(2, width // 400)
    draw.polygon(
        [(center - top_half, horizon), (center + top_half, horizon), (int(width * 0.5 + bottom_half), height), (int(width * 0.5 - bottom_half), height)],
        fill=(*_mix(palette[0], (0, 0, 0), 0.22), 220),
    )
    for index in range(1, 12):
        depth = index / 12
        y = horizon + (height - horizon) * depth * depth
        half = top_half + (bottom_half - top_half) * depth
        dash_h = max(2, int(height * 0.007 * depth))
        draw.rectangle([center - max(1, half * 0.025), y, center + max(1, half * 0.025), y + dash_h], fill=(*palette[-1], 190))


def _draw_perspective_grid(image: Image.Image, palette: list[tuple[int, int, int]], horizon: int) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    neon = palette[2] if len(palette) > 2 else (255, 42, 109)
    vanishing = (width // 2, horizon)
    for index in range(-18, 19):
        bottom_x = width // 2 + index * width * 0.105
        draw.line([vanishing, (bottom_x, height)], fill=(*neon, 94), width=max(1, width // 1400))
    for index in range(1, 16):
        fraction = (index / 15) ** 2.15
        y = horizon + (height - horizon) * fraction
        draw.line([0, y, width, y], fill=(*neon, 80), width=max(1, width // 1600))
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(0.4, width / 2500)))
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))


def _draw_figure(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], horizon: int) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    figure_h = height * rng.uniform(0.22, 0.34)
    base_x = width * rng.uniform(0.36, 0.62)
    ground = horizon + height * 0.22
    body = _mix(palette[0], (0, 0, 0), 0.55)
    accent = palette[-2] if len(palette) > 2 else palette[-1]
    head_r = figure_h * 0.1
    head_center = (base_x, ground - figure_h + head_r)
    draw.ellipse([base_x - figure_h * 0.2, ground - figure_h * 0.07, base_x + figure_h * 0.2, ground + figure_h * 0.015], fill=(0, 0, 0, 55))
    draw.polygon(
        [
            (base_x - figure_h * 0.07, ground - figure_h * 0.76),
            (base_x + figure_h * 0.07, ground - figure_h * 0.76),
            (base_x + figure_h * 0.13, ground - figure_h * 0.25),
            (base_x + figure_h * 0.17, ground),
            (base_x - figure_h * 0.17, ground),
            (base_x - figure_h * 0.13, ground - figure_h * 0.25),
        ],
        fill=(*body, 248),
    )
    draw.ellipse(
        [head_center[0] - head_r, head_center[1] - head_r, head_center[0] + head_r, head_center[1] + head_r],
        fill=(*body, 250),
    )
    draw.arc(
        [head_center[0] - head_r, head_center[1] - head_r, head_center[0] + head_r, head_center[1] + head_r],
        285,
        80,
        fill=(*_mix(body, accent, 0.45), 190),
        width=max(1, int(figure_h * 0.012)),
    )
    draw.line([base_x - head_r * 1.2, head_center[1] + head_r * 1.15, base_x + head_r * 1.2, head_center[1] + head_r * 1.25], fill=(*accent, 230), width=max(1, int(figure_h * 0.03)))


def _draw_product(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]], prompt: str) -> tuple[int, int]:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    floor = int(height * 0.74)
    # Studio floor.
    draw.rectangle([0, floor, width, height], fill=(*_mix(palette[0], palette[1], 0.35), 255))
    draw.line([0, floor, width, floor], fill=(*palette[3], 72), width=max(1, width // 900))
    cx = width * 0.5
    # Warm pool of light behind the hero object.
    image.paste(_radial_glow(image.copy(), (cx, floor - height * 0.3), width * 0.4, palette[3], 0.24))
    draw = ImageDraw.Draw(image, "RGBA")
    # Podium.
    podium_w = width * 0.32
    podium_h = height * 0.045
    draw.ellipse([cx - podium_w * 0.72, floor - podium_h * 0.4, cx + podium_w * 0.72, floor + podium_h * 1.4], fill=(*_mix(palette[1], (0, 0, 0), 0.3), 130))
    draw.ellipse([cx - podium_w / 2, floor - podium_h, cx + podium_w / 2, floor + podium_h], fill=(*_mix(palette[1], palette[2], 0.35), 255))
    draw.ellipse([cx - podium_w / 2, floor - podium_h * 1.2, cx + podium_w / 2, floor + podium_h * 0.25], fill=(*_mix(palette[2], palette[-1], 0.12), 255))
    # Object.
    lower = prompt.lower()
    object_h = height * rng.uniform(0.28, 0.36)
    object_w = object_h * (0.46 if "bottle" in lower or "perfume" in lower else 0.52)
    if "phone" in lower:
        object_w, object_h = object_h * 0.42, object_h * 1.4
    if "sphere" in lower or "ball" in lower:
        object_w = object_h
    top = floor - object_h
    body = _mix(palette[2], palette[3], 0.55)
    if "sphere" in lower or "ball" in lower:
        draw.ellipse([cx - object_w / 2, top, cx + object_w / 2, floor], fill=(*body, 255))
        draw.ellipse([cx - object_w * 0.32, top + object_h * 0.12, cx + object_w * 0.05, top + object_h * 0.5], fill=(255, 255, 255, 45))
    elif "phone" in lower:
        draw.rounded_rectangle([cx - object_w / 2, top, cx + object_w / 2, floor], radius=object_w * 0.12, fill=(*_mix(palette[0], palette[1], 0.4), 255))
        draw.rounded_rectangle([cx - object_w * 0.41, top + object_w * 0.14, cx + object_w * 0.41, floor - object_h * 0.04], radius=object_w * 0.08, fill=(*_mix(palette[1], palette[2], 0.3), 255))
        draw.ellipse([cx - object_w * 0.05, top + object_w * 0.03, cx + object_w * 0.05, top + object_w * 0.09], fill=(*palette[-1], 180))
    else:
        # A sculptural bottle/flacon: body, shoulder, neck and cap.
        body_top = top + object_h * 0.19
        neck_w = object_w * 0.24
        cap_w = object_w * 0.34
        draw.rounded_rectangle([cx - object_w / 2, body_top, cx + object_w / 2, floor], radius=object_w * 0.14, fill=(*body, 255))
        draw.polygon(
            [
                (cx - object_w * 0.36, body_top + object_h * 0.03),
                (cx + object_w * 0.36, body_top + object_h * 0.03),
                (cx + neck_w / 2, top + object_h * 0.11),
                (cx - neck_w / 2, top + object_h * 0.11),
            ],
            fill=(*_shade(body, 0.05), 255),
        )
        draw.rectangle(
            [cx - neck_w / 2, top + object_h * 0.06, cx + neck_w / 2, top + object_h * 0.14],
            fill=(*_mix(palette[2], palette[3], 0.3), 255),
        )
        draw.rounded_rectangle(
            [cx - cap_w / 2, top, cx + cap_w / 2, top + object_h * 0.075],
            radius=cap_w * 0.2,
            fill=(*_mix(palette[4], palette[3], 0.45), 255),
        )
        # Label plate with a restrained hairline motif.
        label_y = body_top + (floor - body_top) * 0.48
        label_h = object_h * 0.13
        draw.rounded_rectangle(
            [cx - object_w * 0.34, label_y, cx + object_w * 0.34, label_y + label_h],
            radius=object_w * 0.02,
            fill=(*_mix(palette[4], palette[2], 0.25), 128),
        )
        draw.line(
            [cx - object_w * 0.22, label_y + label_h * 0.55, cx + object_w * 0.22, label_y + label_h * 0.55],
            fill=(*palette[0], 110),
            width=max(1, int(object_w * 0.012)),
        )
        draw.arc(
            [cx - object_w / 2, body_top, cx + object_w / 2, floor],
            100,
            250,
            fill=(*palette[4], 140),
            width=max(1, int(object_w * 0.018)),
        )
        # Gloss and rim light.
        draw.rounded_rectangle(
            [cx - object_w * 0.34, body_top + object_h * 0.06, cx - object_w * 0.15, floor - object_h * 0.07],
            radius=object_w * 0.05,
            fill=(255, 255, 255, 42),
        )
        draw.line(
            [cx + object_w * 0.27, body_top + object_h * 0.06, cx + object_w * 0.27, floor - object_h * 0.07],
            fill=(255, 255, 255, 36),
            width=max(1, int(object_w // 40)),
        )
    # Contact shadow and mirrored reflection.
    draw.ellipse([cx - object_w * 0.75, floor - object_h * 0.03, cx + object_w * 0.75, floor + object_h * 0.055], fill=(0, 0, 0, 80))
    draw.ellipse([cx - object_w * 0.42, floor + object_h * 0.01, cx + object_w * 0.42, floor + object_h * 0.13], fill=(*_mix(body, palette[0], 0.45), 30))
    # Highlight sweep across the backdrop.
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.polygon(
        [(width * 0.18, 0), (width * 0.34, 0), (width * 0.62, floor), (width * 0.44, floor)],
        fill=(*palette[-1], 12),
    )
    overlay = overlay.filter(ImageFilter.GaussianBlur(width / 90))
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))
    return cx, top


def _draw_abstract(image: Image.Image, rng: random.Random, palette: list[tuple[int, int, int]]) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for index in range(rng.randint(4, 7)):
        color = palette[rng.randrange(0, len(palette))]
        points = []
        phase = rng.uniform(0, math.tau)
        frequency = rng.uniform(0.8, 2.0)
        amplitude = height * rng.uniform(0.05, 0.16)
        base = height * rng.uniform(0.2, 0.85)
        for x in range(0, width + 1, max(2, width // 120)):
            y = base + math.sin(x / width * math.tau * frequency + phase) * amplitude
            points.append((x, y))
        band = height * rng.uniform(0.03, 0.12)
        poly = points + [(width, points[-1][1] + band), (0, points[0][1] + band)]
        draw.polygon(poly, fill=(*color, rng.randint(30, 85)))
    for _ in range(rng.randint(4, 8)):
        radius = rng.uniform(width * 0.05, width * 0.22)
        cx = rng.uniform(0, width)
        cy = rng.uniform(0, height)
        color = palette[rng.randrange(0, len(palette))]
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(*color, rng.randint(18, 70)))
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(2, width / 90)))
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))
    # Thin luminous lines for structure.
    lines = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    line_draw = ImageDraw.Draw(lines)
    for _ in range(rng.randint(3, 6)):
        color = palette[rng.randrange(0, len(palette))]
        start = (rng.uniform(0, width), rng.uniform(0, height))
        end = (rng.uniform(0, width), rng.uniform(0, height))
        line_draw.line([start, end], fill=(*color, rng.randint(35, 90)), width=max(1, width // 700))
    lines = lines.filter(ImageFilter.GaussianBlur(max(0.4, width / 2000)))
    image.paste(Image.alpha_composite(image.convert("RGBA"), lines).convert("RGB"))


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)  # type: ignore[call-arg]
    except TypeError:
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: Any) -> int:
    if not text:
        return 0
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return max(0, right - left)


def _wrap_pixels(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int, max_lines: int) -> list[str]:
    text = " ".join((text or "").split())
    if not text:
        return []
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
        else:
            current = candidate
    if len(lines) < max_lines and current:
        lines.append(current)
    if not lines:
        # Unspaced scripts: split by characters.
        current = ""
        for char in text:
            candidate = current + char
            if current and _text_width(draw, candidate, font) > max_width:
                lines.append(current)
                current = char
                if len(lines) >= max_lines:
                    break
            else:
                current = candidate
        if len(lines) < max_lines and current:
            lines.append(current)
    if len(lines) >= max_lines and (" ".join(lines) != text):
        last = lines[-1].rstrip(" .,;:-")
        while last and _text_width(draw, last + "…", font) > max_width:
            last = last[:-1].rstrip()
        lines[-1] = (last or "…") + "…"
    return lines


def _draw_typography(
    image: Image.Image,
    prompt: str,
    style_id: str,
    spec: dict[str, Any],
    rng: random.Random,
) -> None:
    width, height = image.size
    large = ImageDraw.Draw(image)
    body_size = max(13, int(min(width, height) * 0.021))
    label_size = max(10, int(min(width, height) * 0.0135))
    body_font = _font(body_size, bold=False)
    label_font = _font(label_size, bold=True)
    margin = int(min(width, height) * 0.065)
    text_color = _rgb(spec.get("text", "#FFFFFF"))
    accent = _rgb(spec.get("accent", "#FFFFFF"))
    max_width = int(width * 0.52) if width > height else int(width * 0.74)
    lines = _wrap_pixels(large, prompt or "Procedural artwork", body_font, max_width, 3)
    if not lines:
        return
    line_height = int(body_size * 1.32)
    label = f"OPEN STUDIO  /  {spec['name'].upper()}"
    label_h = int(label_size * 1.3)
    block_h = label_h + int(body_size * 0.8) + len(lines) * line_height
    if style_id == "product":
        origin_x, origin_y = margin, height - margin - block_h
    elif style_id == "synthwave":
        origin_x = width // 2 - max_width // 2
        origin_y = height - margin - block_h
    elif style_id == "abstract":
        origin_x, origin_y = margin, height - margin - block_h
    elif style_id == "watercolor":
        origin_x, origin_y = margin, height - margin - block_h
    else:
        origin_x, origin_y = margin, height - margin - block_h
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    shadow = (0, 0, 0, 150)
    label_y = origin_y
    draw.text((origin_x + 1, label_y + 1), label, font=label_font, fill=shadow)
    draw.text((origin_x, label_y), label, font=label_font, fill=(*accent, 230))
    rule_y = label_y + label_h
    draw.line([origin_x, rule_y, origin_x + min(max_width, int(width * 0.32)), rule_y], fill=(*accent, 150), width=max(1, width // 900))
    text_y = rule_y + int(body_size * 0.8)
    for index, line in enumerate(lines):
        y = text_y + index * line_height
        draw.text((origin_x + 2, y + 2), line, font=body_font, fill=(0, 0, 0, 165), stroke_width=max(1, body_size // 22), stroke_fill=(0, 0, 0, 110))
        draw.text((origin_x, y), line, font=body_font, fill=(*text_color, 238))
    # A small index mark keeps the composition feeling designed.
    mark = f"{rng.randint(1, 99):02d}"
    draw.text((width - margin - _text_width(draw, mark, label_font), margin), mark, font=label_font, fill=(*text_color, 80))
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def _has_chromatic(style_id: str) -> bool:
    return style_id in {"synthwave", "anime"}


def _post_process(
    image: Image.Image,
    rng: random.Random,
    np_rng: np.random.Generator,
    style_id: str,
    palette: list[tuple[int, int, int]],
) -> Image.Image:
    width, height = image.size
    bright = image.filter(ImageFilter.GaussianBlur(max(2, width // 110)))
    image = Image.blend(image, ImageChops.screen(image, bright), 0.25 if style_id != "watercolor" else 0.12)
    if style_id == "noir":
        gray = image.convert("L")
        tint = Image.new("RGB", image.size, (168, 181, 188))
        image = ImageChops.multiply(Image.merge("RGB", [gray, gray, gray]), tint)
        image = ImageEnhance.Contrast(image).enhance(1.3)
        image = ImageEnhance.Brightness(image).enhance(0.92)
    elif style_id == "watercolor":
        image = image.filter(ImageFilter.GaussianBlur(max(0.5, width / 900)))
        array = np.asarray(image).astype(np.float32)
        paper = np_rng.normal(0, 7.0, array.shape[:2])[:, :, None]
        dither = np_rng.uniform(-2.4, 2.4, array.shape[:2])[:, :, None]
        array = np.clip(array + paper * 0.55 + dither + 5.0, 0, 255)
        image = Image.fromarray(array.astype(np.uint8), "RGB")
        image = ImageEnhance.Contrast(image).enhance(1.0)
        image = ImageEnhance.Color(image).enhance(1.1)
    elif style_id == "documentary":
        image = ImageEnhance.Color(image).enhance(0.82)
        image = ImageEnhance.Contrast(image).enhance(1.05)
    elif style_id == "anime":
        image = ImageEnhance.Color(image).enhance(1.22)
        image = ImageEnhance.Contrast(image).enhance(1.04)
    elif style_id == "synthwave":
        image = ImageEnhance.Color(image).enhance(1.28)
        image = ImageEnhance.Contrast(image).enhance(1.08)
    elif style_id == "abstract":
        image = ImageEnhance.Color(image).enhance(1.12)
    elif style_id == "product":
        image = ImageEnhance.Contrast(image).enhance(1.05)
        image = ImageEnhance.Brightness(image).enhance(1.02)
    elif style_id == "cinematic":
        image = ImageEnhance.Color(image).enhance(1.08)
        image = ImageEnhance.Contrast(image).enhance(1.07)

    # Chromatic fringing, very restrained.
    if _has_chromatic(style_id):
        array = np.asarray(image).astype(np.int16)
        offset = max(1, width // 900)
        shifted = np.roll(array, offset, axis=1)
        array[:, :, 0] = np.clip(array[:, :, 0] * 0.985 + shifted[:, :, 0] * 0.015, 0, 255)
        shifted_b = np.roll(array, -offset, axis=1)
        array[:, :, 2] = np.clip(array[:, :, 2] * 0.985 + shifted_b[:, :, 2] * 0.015, 0, 255)
        image = Image.fromarray(array.astype(np.uint8), "RGB")

    # Vignette.
    y, x = np.ogrid[:height, :width]
    cx, cy = width / 2, height / 2
    distance = np.sqrt(((x - cx) / width) ** 2 + ((y - cy) / height) ** 2)
    strength = 1.35 if style_id in {"noir", "cinematic", "product"} else (0.7 if style_id == "watercolor" else 1.05)
    vignette = np.clip(1.0 - (distance ** 2.15) * strength, 0.34, 1.0)
    array = np.asarray(image).astype(np.float32) * vignette[:, :, None]
    # Grain.
    grain_sigma = 3.4 if style_id not in {"watercolor", "product"} else 1.8
    grain = np_rng.normal(0, grain_sigma, array.shape[:2])[:, :, None]
    array = np.clip(array + grain, 0, 255)
    image = Image.fromarray(array.astype(np.uint8), "RGB")
    # Unifying warm highlight.
    warm = Image.new("RGB", image.size, _shade(palette[-2], 0.06))
    return Image.blend(image, ImageChops.screen(image, warm), 0.06)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_style(style: str | None) -> str:
    value = (style or "").strip().lower().replace(" ", "-")
    if value in STYLE_SPECS:
        return value
    return STYLE_ALIASES.get(value, "cinematic")


def detect_motif(prompt: str, style_id: str) -> str:
    text = (prompt or "").lower()
    scores: list[tuple[int, str]] = []
    for motif, words in MOTIF_KEYWORDS.items():
        score = sum(1 for word in words if word in text)
        if score:
            scores.append((score, motif))
    if scores:
        scores.sort(key=lambda item: (-item[0], item[1]))
        motif = scores[0][1]
    else:
        motif = str(STYLE_SPECS[style_id].get("motif", "mountain"))
    if style_id == "product":
        return "studio"
    if style_id == "abstract":
        return "abstract"
    if style_id != "noir" and any(word in text for word in ("lake", "lago", "lagoon", "laguna", "reservoir")):
        return "ocean"
    return motif


def _style_palette(style_id: str) -> list[tuple[int, int, int]]:
    palette = [_rgb(color) for color in STYLE_SPECS[style_id]["palette"]]
    if style_id == "noir":
        gray = [int(0.2126 * r + 0.7152 * g + 0.0722 * b) for r, g, b in palette]
        palette = [(value, value, value) for value in gray]
    return palette


def _render_canvas(
    prompt: str,
    style_id: str,
    width: int,
    height: int,
    rng: random.Random,
    np_rng: np.random.Generator,
    motif: str,
) -> Image.Image:
    spec = STYLE_SPECS[style_id]
    palette = _style_palette(style_id)
    horizon = int(height * rng.uniform(0.56, 0.69))
    if motif in {"ocean", "coast"}:
        horizon = int(height * rng.uniform(0.5, 0.6))
    if motif in {"space"}:
        horizon = int(height * rng.uniform(0.68, 0.8))

    if style_id == "product":
        background = _linear_gradient((width, height), [palette[0], palette[1], palette[2]], rng.choice([90, 105, 75]))
        background = _radial_glow(background, (width * 0.5, height * 0.3), width * 0.78, palette[3], 0.34)
        background = _radial_glow(background, (width * 0.5, height * 0.72), width * 0.5, palette[4], 0.1)
        image = background.convert("RGB")
        _draw_product(image, rng, palette, prompt)
        return image

    if style_id == "abstract":
        background = _linear_gradient((width, height), [palette[0], palette[2], palette[3], palette[1]], rng.uniform(20, 160))
        background = _radial_glow(background, (width * rng.uniform(0.25, 0.75), height * rng.uniform(0.2, 0.7)), width * 0.65, palette[2], 0.26)
        image = background.convert("RGB")
        _draw_abstract(image, rng, palette)
        return image

    if style_id == "watercolor":
        background = _linear_gradient((width, height), [palette[0], palette[1], palette[2], palette[0]], rng.uniform(85, 115))
        image = background.convert("RGB")
        wash_horizon = int(height * rng.uniform(0.5, 0.64))
        image = _radial_glow(image, (width * rng.uniform(0.25, 0.78), wash_horizon), width * 0.95, palette[3], 0.18)
        # Broad transparent pigment pools.
        for _ in range(rng.randint(7, 11)):
            image = _blob(
                image,
                rng,
                (rng.uniform(-0.05, 1.05) * width, rng.uniform(0.05, 0.95) * height),
                (rng.uniform(width * 0.08, width * 0.30), rng.uniform(height * 0.05, height * 0.22)),
                palette[rng.randrange(1, len(palette))],
                rng.randint(52, 112),
                rng.uniform(width * 0.006, width * 0.04),
            ).convert("RGB")
        # Soft landscape masses, deliberately out of focus like wet paper.
        for layer in range(3):
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            wash_draw = ImageDraw.Draw(overlay)
            base = wash_horizon + int(height * (0.01 + layer * 0.06))
            noise = _ridge_profile(width, rng, octaves=3)
            amplitude = height * (0.025 + layer * 0.025)
            points = [(x, base - int((value - 0.5) * amplitude * 2)) for x, value in enumerate(noise)]
            color = palette[3] if layer % 2 == 0 else palette[2]
            wash_draw.polygon(points + [(width, height), (0, height)], fill=(*color, 92 + layer * 24))
            overlay = overlay.filter(ImageFilter.GaussianBlur(max(3, width * 0.007)))
            image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))
        if motif in {"ocean", "coast"}:
            # Loose water bands and reflected light below the pigment hills.
            water_top = wash_horizon + int(height * 0.17)
            water = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            water_draw = ImageDraw.Draw(water)
            for index in range(5):
                y = water_top + index * (height - water_top) * 0.18
                water_draw.rectangle(
                    [0, y, width, y + (height - water_top) * 0.16],
                    fill=(*palette[2 if index % 2 else 3], 26 + index * 8),
                )
            for _ in range(35):
                y = rng.uniform(water_top, height)
                x = rng.uniform(width * 0.28, width * 0.72)
                length = rng.uniform(width * 0.01, width * 0.08)
                water_draw.line([x, y, x + length, y], fill=(*palette[0], rng.randint(25, 70)), width=max(1, int(width / 1000)))
            water = water.filter(ImageFilter.GaussianBlur(max(2, width * 0.004)))
            image.paste(Image.alpha_composite(image.convert("RGBA"), water).convert("RGB"))
        # Foreground pigment pooling gives the page weight.
        image = _blob(
            image,
            rng,
            (rng.uniform(0.2, 0.8) * width, height * 1.02),
            (width * rng.uniform(0.45, 0.7), height * rng.uniform(0.10, 0.18)),
            palette[-1],
            70,
            width * 0.03,
        ).convert("RGB")
        # A warm bloom of pigment for the sun, deliberately soft-edged.
        sun_x, sun_y = width * rng.uniform(0.62, 0.8), height * rng.uniform(0.14, 0.24)
        image = _radial_glow(image, (sun_x, sun_y), width * 0.3, palette[3], 0.3)
        sun_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        sun_draw = ImageDraw.Draw(sun_layer)
        sun_r = height * rng.uniform(0.035, 0.06)
        sun_draw.ellipse([sun_x - sun_r, sun_y - sun_r, sun_x + sun_r, sun_y + sun_r], fill=(*palette[3], 95))
        sun_layer = sun_layer.filter(ImageFilter.GaussianBlur(width * 0.006))
        image.paste(Image.alpha_composite(image.convert("RGBA"), sun_layer).convert("RGB"))
        # Sparse ink branches at the edges keep the page loose and organic.
        ink = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ink_draw = ImageDraw.Draw(ink)
        for _ in range(rng.randint(4, 7)):
            if rng.random() < 0.5:
                x = rng.uniform(0, width * 0.2)
            else:
                x = rng.uniform(width * 0.8, width)
            base = height * rng.uniform(0.88, 1.0)
            tree_h = height * rng.uniform(0.1, 0.22)
            ink_draw.line([x, base, x + rng.uniform(-8, 8), base - tree_h], fill=(*palette[-1], rng.randint(55, 100)), width=max(1, int(width / 800)))
            for _branch in range(rng.randint(2, 5)):
                by = base - tree_h * rng.uniform(0.45, 0.92)
                bx = x + rng.uniform(-width * 0.012, width * 0.012)
                ink_draw.line(
                    [bx, by, bx + rng.uniform(-width * 0.04, width * 0.04), by - tree_h * rng.uniform(0.12, 0.3)],
                    fill=(*palette[-1], rng.randint(35, 75)),
                    width=max(1, int(width / 1200)),
                )
        ink = ink.filter(ImageFilter.GaussianBlur(max(0.6, width * 0.0012)))
        image.paste(Image.alpha_composite(image.convert("RGBA"), ink).convert("RGB"))
        draw = ImageDraw.Draw(image, "RGBA")
        for _ in range(int(width / 12)):
            x = rng.uniform(0, width)
            y = rng.uniform(height * 0.82, height)
            length = rng.uniform(height * 0.02, height * 0.08)
            draw.line(
                [x, y, x + rng.uniform(-width * 0.006, width * 0.006), y - length],
                fill=(*palette[-1], rng.randint(35, 95)),
                width=max(1, int(width / 1400)),
            )
        if motif in {"flowers", "forest"}:
            _draw_flowers(image, rng, palette, int(height * 0.52))
        # Loose ink strokes and pigment splatter.
        draw = ImageDraw.Draw(image, "RGBA")
        for _ in range(rng.randint(3, 6)):
            x = rng.uniform(0, width)
            y = rng.uniform(height * 0.3, height * 0.85)
            length = rng.uniform(width * 0.05, width * 0.22)
            draw.line([x, y, x + length, y + rng.uniform(-height * 0.02, height * 0.02)], fill=(*palette[-1], rng.randint(38, 78)), width=max(1, int(width / 900)))
        for _ in range(rng.randint(25, 55)):
            x = rng.uniform(0, width)
            y = rng.uniform(0, height)
            radius = rng.uniform(0.6, 3.0) * max(0.6, width / 1024)
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(*palette[rng.randrange(2, len(palette))], rng.randint(35, 130)))
        return image

    night = motif in {"space"} or style_id in {"synthwave", "noir"} or ("night" in prompt.lower() and style_id != "anime")
    if style_id == "synthwave":
        sky_colors = [palette[0], palette[1], _mix(palette[1], palette[2], 0.55), palette[2]]
    elif night:
        sky_colors = [_shade(palette[0], -0.2), palette[0], _mix(palette[0], palette[1], 0.45)]
    elif style_id == "anime":
        sky_colors = [palette[0], palette[1], palette[2], palette[3]]
    else:
        sky_colors = [palette[0], palette[1], palette[2], palette[-2]]
    sky = _vertical_sky_gradient((width, height), sky_colors, horizon)
    image = sky.convert("RGB")
    if night or style_id == "synthwave":
        _draw_stars(image, rng, 0.72, int(width * height / 18000), palette[-1])
    sun_x = width * rng.uniform(0.36, 0.64)
    if style_id == "anime":
        sun_y = height * rng.uniform(0.15, 0.32)
    elif style_id == "documentary":
        sun_y = horizon - height * rng.uniform(0.08, 0.2)
    else:
        sun_y = horizon - height * rng.uniform(0.03, 0.11)
    if style_id == "synthwave":
        sun_radius = height * rng.uniform(0.16, 0.22)
        image = _radial_glow(image, (sun_x, sun_y), height * 0.62, palette[2], 0.42)
        draw = ImageDraw.Draw(image, "RGBA")
        top = sun_y - sun_radius
        draw.ellipse([sun_x - sun_radius, top, sun_x + sun_radius, sun_y + sun_radius], fill=(*palette[2], 238))
        # Horizontal cut-outs across the sun, painted in the sky colour.
        cut = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        cut_draw = ImageDraw.Draw(cut)
        for index in range(9):
            y = sun_y - sun_radius * 0.35 + index * sun_radius * 0.15
            cut_draw.rectangle([sun_x - sun_radius, y, sun_x + sun_radius, y + max(1, sun_radius * 0.035)], fill=(*palette[1], 195))
        cut = cut.filter(ImageFilter.GaussianBlur(max(0.4, width / 3000)))
        image.paste(Image.alpha_composite(image.convert("RGBA"), cut).convert("RGB"))
        _draw_ridges(image, rng, palette, horizon + height * 0.03, layers=3, snow=False)
    elif night:
        moon_r = height * rng.uniform(0.025, 0.045)
        image = _radial_glow(image, (sun_x, sun_y), height * 0.45, palette[-1], 0.28)
        draw = ImageDraw.Draw(image, "RGBA")
        draw.ellipse([sun_x - moon_r, sun_y - moon_r, sun_x + moon_r, sun_y + moon_r], fill=(*palette[-1], 245))
        _draw_clouds(image, rng, palette[-1], horizon, rng.randint(3, 7), opacity=0.32)
    else:
        sun_r = height * (rng.uniform(0.045, 0.08) if style_id == "anime" else rng.uniform(0.022, 0.055))
        image = _radial_glow(image, (sun_x, sun_y), height * 0.55, palette[-1], 0.42)
        draw = ImageDraw.Draw(image, "RGBA")
        draw.ellipse([sun_x - sun_r, sun_y - sun_r, sun_x + sun_r, sun_y + sun_r], fill=(*_shade(palette[-1], 0.2), 240))
        _draw_clouds(image, rng, palette[-1], horizon, rng.randint(5, 11), opacity=0.95 if style_id != "noir" else 0.45)
        if style_id == "anime":
            _draw_clouds(image, rng, palette[3], horizon, rng.randint(3, 6), opacity=0.7)
    image = _radial_glow(image, (sun_x, horizon), width * 0.58, palette[-2], 0.14)

    if style_id == "noir":
        _draw_city(image, rng, palette, horizon)
        draw = ImageDraw.Draw(image, "RGBA")
        # Hard light shaft.
        beam = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        beam_draw = ImageDraw.Draw(beam)
        beam_draw.polygon([(width * 0.1, 0), (width * 0.32, 0), (width * 0.64, horizon), (width * 0.34, horizon)], fill=(235, 238, 240, 30))
        beam = beam.filter(ImageFilter.GaussianBlur(width / 70))
        image.paste(Image.alpha_composite(image.convert("RGBA"), beam).convert("RGB"))
        for _ in range(int(width / 7)):
            x = rng.uniform(-width * 0.1, width)
            y = rng.uniform(0, height)
            length = rng.uniform(height * 0.02, height * 0.08)
            draw.line([x, y, x + length * 0.3, y + length], fill=(230, 235, 238, rng.randint(18, 55)), width=1)
    else:
        snowy = motif == "snow" or any(
            word in prompt.lower() for word in ("snow", "winter", "alpine", "neve", "inverno", "frost")
        )
        if motif in {"mountain", "snow", "road", "forest"}:
            _draw_ridges(image, rng, palette, horizon, layers=4, snow=snowy)
        if motif == "city":
            _draw_city(image, rng, palette, horizon)
        if motif in {"ocean", "coast"}:
            _draw_ridges(image, rng, palette, max(10, horizon - height // 10), layers=2, snow=False)
            _draw_water(image, rng, palette, horizon, sun_x)
        if motif == "desert":
            draw = ImageDraw.Draw(image, "RGBA")
            for layer in range(3):
                depth = layer / 3
                base = horizon + height * (0.01 + depth * 0.17)
                noise = _ridge_profile(width, rng, octaves=3)
                points = [(x, base + int((value - 0.5) * height * (0.025 + depth * 0.045))) for x, value in enumerate(noise)]
                color = _mix(palette[2], palette[0], 0.28 + depth * 0.5)
                draw.polygon(points + [(width, height), (0, height)], fill=(*color, 250))
        if motif == "forest":
            _draw_forest(image, rng, palette, horizon)
        if motif == "flowers":
            _draw_flowers(image, rng, palette, horizon)
        if motif == "space":
            for _ in range(5):
                cx = rng.uniform(0, width)
                cy = rng.uniform(0, horizon)
                rx = rng.uniform(width * 0.08, width * 0.28)
                ry = rx * rng.uniform(0.3, 0.65)
                overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                overlay_draw = ImageDraw.Draw(overlay)
                overlay_draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(*palette[2], 18))
                overlay = overlay.filter(ImageFilter.GaussianBlur(width / 60))
                image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))
        if motif == "road":
            _draw_road(image, rng, palette, horizon)
        if style_id == "synthwave":
            _draw_perspective_grid(image, palette, horizon)
        if motif == "rain":
            draw = ImageDraw.Draw(image, "RGBA")
            for _ in range(int(width * height / 9000)):
                x = rng.uniform(-width * 0.1, width)
                y = rng.uniform(0, height)
                length = rng.uniform(height * 0.02, height * 0.07)
                draw.line([x, y, x + length * 0.3, y + length], fill=(*palette[-1], rng.randint(14, 50)), width=1)
        if motif == "snow":
            draw = ImageDraw.Draw(image, "RGBA")
            for _ in range(int(width * height / 12000)):
                x = rng.uniform(0, width)
                y = rng.uniform(0, height)
                r = rng.uniform(0.6, 2.6)
                draw.ellipse([x - r, y - r, x + r, y + r], fill=(*palette[-1], rng.randint(40, 150)))

    # Foreground atmosphere for depth.
    if motif in {"mountain", "forest", "desert"}:
        draw = ImageDraw.Draw(image, "RGBA")
        ground = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ground_draw = ImageDraw.Draw(ground)
        noise = _ridge_profile(width, rng, octaves=3)
        y0 = int(height * rng.uniform(0.86, 0.92))
        points = [(x, y0 + int((value - 0.5) * height * 0.03)) for x, value in enumerate(noise)]
        ground_draw.polygon(points + [(width, height), (0, height)], fill=(*_mix(palette[0], (0, 0, 0), 0.3), 235))
        image.paste(Image.alpha_composite(image.convert("RGBA"), ground).convert("RGB"))
    if motif == "portrait":
        _draw_figure(image, rng, palette, horizon)
    if motif in {"flowers", "forest"} and rng.random() < 0.5:
        draw = ImageDraw.Draw(image, "RGBA")
        for _ in range(rng.randint(2, 6)):
            bx = rng.uniform(width * 0.1, width * 0.9)
            by = rng.uniform(height * 0.08, horizon * 0.55)
            size = rng.uniform(width * 0.006, width * 0.015)
            draw.arc([bx - size, by - size * 0.5, bx, by + size * 0.5], 180, 330, fill=(*palette[-1], 120), width=1)
            draw.arc([bx, by - size * 0.5, bx + size, by + size * 0.5], 210, 360, fill=(*palette[-1], 120), width=1)
    # Haze band at the horizon.
    haze = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    haze_draw = ImageDraw.Draw(haze)
    haze_draw.rectangle([0, max(0, horizon - height * 0.02), width, horizon + height * 0.02], fill=(*palette[-2], 34))
    haze = haze.filter(ImageFilter.GaussianBlur(max(3, height / 80)))
    image.paste(Image.alpha_composite(image.convert("RGBA"), haze).convert("RGB"))
    return image


def generate_procedural(
    prompt: str,
    *,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    seed: int = 1987,
    style: str | None = None,
    batch_index: int = 0,
) -> Image.Image:
    """Generate one deterministic procedural image."""
    width, height = _even(width), _even(height)
    style_id = resolve_style(style)
    spec = STYLE_SPECS[style_id]
    actual_seed = int(seed) + int(batch_index) * 7919
    rng = random.Random(actual_seed)
    np_rng = np.random.default_rng(actual_seed)
    motif = detect_motif(prompt, style_id)
    render_scale = 1.0
    if max(width, height) < 2048:
        render_scale = 2.0 if max(width, height) <= 1536 else 1.5
    canvas_w = _even(int(width * render_scale))
    canvas_h = _even(int(height * render_scale))
    canvas = _render_canvas(prompt, style_id, canvas_w, canvas_h, rng, np_rng, motif)
    if render_scale > 1.0:
        canvas = canvas.resize((width, height), Image.Resampling.LANCZOS)
    canvas = _post_process(canvas, rng, np_rng, style_id, _style_palette(style_id))
    _draw_typography(canvas, prompt, style_id, spec, rng)
    # A final very soft light wrap keeps the typography integrated.
    return canvas.convert("RGB")


def style_catalogue() -> list[dict[str, Any]]:
    return [
        {
            "id": style_id,
            "name": spec["name"],
            "description": spec["description"],
            "palette": spec["palette"],
            "motif": spec["motif"],
        }
        for style_id, spec in STYLE_SPECS.items()
    ]


__all__ = ["STYLE_SPECS", "generate_procedural", "resolve_style", "style_catalogue"]
