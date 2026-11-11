"""OpenCV-based animation backend.

This backend is slower than FFmpeg but provides real depth-map parallax and
particle rendering without a GPU. It renders raw frames into FFmpeg for H.264
encoding.
"""

from __future__ import annotations

import math
import os
import random
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from mvstudio_shared.config import get_settings
from mvstudio_shared.media import MediaError
from mvstudio_shared.models import AudioReactiveConfig, BeatEvent, Scene

SUPPORTED_EFFECTS = {
    "vignette",
    "film_grain",
    "subtle_film_grain",
    "bloom",
    "soft_focus",
    "light_leak",
    "chromatic_aberration",
    "letterbox",
    "shake",
    "particles",
    "beat_pulse",
    "bass_pulse",
}


def _read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise MediaError(f"Could not read image {path.name}")
    return image


def _cover_resize(image: np.ndarray, width: int, height: int) -> np.ndarray:
    source_height, source_width = image.shape[:2]
    scale = max(width / source_width, height / source_height)
    target_width = max(width, int(round(source_width * scale)))
    target_height = max(height, int(round(source_height * scale)))
    resized = cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
    if target_width > width or target_height > height:
        x = (target_width - width) // 2
        y = (target_height - height) // 2
        resized = resized[y : y + height, x : x + width]
    return resized


def _pulse_activity(
    terms: list[tuple[float, float, float]], t: float, decay: float = 16.0
) -> float:
    total = 0.0
    for time, amplitude, window in terms:
        if time <= t <= time + window:
            total += amplitude * math.exp(-decay * (t - time))
    return total


class _Particle:
    def __init__(self, rng: random.Random, width: int, height: int):
        self.x = rng.uniform(0, width)
        self.y = rng.uniform(0, height)
        self.speed = rng.uniform(4.0, 22.0)
        self.drift = rng.uniform(-8.0, 8.0)
        self.radius = rng.uniform(0.6, 2.8)
        self.alpha = rng.uniform(0.12, 0.45)
        self.phase = rng.uniform(0, math.tau)

    def position(self, t: float, width: int, height: int) -> tuple[int, int]:
        x = (self.x + self.drift * t + math.sin(t * 0.8 + self.phase) * 9) % width
        y = (self.y - self.speed * t) % height
        return int(x), int(y)


def render_opencv(
    *,
    image_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    clip_duration: float,
    scene: Scene,
    beats: list[BeatEvent],
    clip_start: float,
    audio_reactive: AudioReactiveConfig,
    depth_map_path: Path | None = None,
    particle_color: str = "#F4A261",
) -> dict:
    image = _read_image(image_path)
    frames = max(2, int(round(clip_duration * fps)))
    duration = frames / fps
    effects = {effect for effect in scene.visual_effects if effect in SUPPORTED_EFFECTS}
    rng = random.Random(scene.seed + 7717)
    np_rng = np.random.default_rng(scene.seed + 91)

    # Pre-scale with overscan for panning and rotation.
    canvas_scale = 1.22
    canvas_w = int(width * canvas_scale)
    canvas_h = int(height * canvas_scale)
    canvas = _cover_resize(image, canvas_w, canvas_h)

    depth: np.ndarray | None = None
    if scene.camera.movement == "parallax" and depth_map_path and depth_map_path.is_file():
        depth_raw = cv2.imread(str(depth_map_path), cv2.IMREAD_GRAYSCALE)
        if depth_raw is not None:
            depth = cv2.resize(depth_raw, (width, height), interpolation=cv2.INTER_LINEAR).astype(np.float32)
            depth = depth / max(1.0, float(depth.max()))

    movement = scene.camera.movement
    camera_zoom = max(1.0, scene.camera.zoom)
    if movement in {"pan_left", "pan_right", "pan_up", "pan_down", "parallax"}:
        camera_zoom = max(camera_zoom, 1.08)
    if movement in {"rotate_cw", "rotate_ccw"}:
        camera_zoom = max(camera_zoom, 1.1)
    if movement == "slow_backward":
        start_zoom, end_zoom = camera_zoom, 1.0
    elif movement == "slow_forward":
        start_zoom, end_zoom = 1.0, camera_zoom
    else:
        start_zoom, end_zoom = camera_zoom * 0.98, camera_zoom

    pan_x = scene.camera.pan_x
    pan_y = scene.camera.pan_y
    if movement == "pan_left":
        pan_x = -max(abs(pan_x), 0.32)
    elif movement == "pan_right":
        pan_x = max(abs(pan_x), 0.32)
    elif movement == "pan_up":
        pan_y = -max(abs(pan_y), 0.28)
    elif movement == "pan_down":
        pan_y = max(abs(pan_y), 0.28)

    rotation_degrees = scene.camera.rotation
    if movement in {"rotate_cw", "rotate_ccw"} and abs(rotation_degrees) < 0.05:
        rotation_degrees = 0.6 if movement == "rotate_cw" else -0.6

    beat_terms: list[tuple[float, float, float]] = []
    bass_terms: list[tuple[float, float, float]] = []
    if audio_reactive.enabled:
        for beat in beats:
            local = beat.time - clip_start
            if local < -0.05 or local > duration:
                continue
            if "beat_pulse" in effects and audio_reactive.beat_pulse:
                beat_terms.append(
                    (
                        max(0.0, local),
                        (0.035 + 0.07 * audio_reactive.intensity) * max(0.4, beat.strength),
                        0.55,
                    )
                )
            if (
                "bass_pulse" in effects
                and audio_reactive.bass_pulse
                and (beat.downbeat or not any(item.downbeat for item in beats))
            ):
                bass_terms.append(
                    (
                        max(0.0, local),
                        (0.05 + 0.1 * audio_reactive.intensity) * max(0.5, beat.strength),
                        0.8,
                    )
                )
    beat_terms.sort(key=lambda item: item[0])
    bass_terms.sort(key=lambda item: item[0])

    # Precomputed looks.
    vignette = None
    if "vignette" in effects:
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        cx, cy = width / 2, height / 2
        dist = np.sqrt(((xx - cx) / width) ** 2 + ((yy - cy) / height) ** 2)
        vignette = np.clip(1.0 - (dist**2.1) * 1.15, 0.35, 1.0)[:, :, None]
    light_leak = None
    if "light_leak" in effects:
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        glow = np.clip(1.0 - np.sqrt(((xx - width * 0.84) / (width * 0.55)) ** 2 + ((yy - height * 0.18) / (height * 0.55)) ** 2), 0, 1) ** 2
        light_leak = (glow[:, :, None] * np.asarray([38.0, 20.0, 8.0])).astype(np.float32)
    particles: list[_Particle] = []
    if "particles" in effects:
        particles = [_Particle(rng, width, height) for _ in range(70)]

    fd, temp_name = tempfile.mkstemp(prefix=output_path.name + ".", suffix=".mp4", dir=str(output_path.parent))
    os.close(fd)
    encoder = subprocess.Popen(
        [
            get_settings().ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            temp_name,
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        for index in range(frames):
            t = index / fps
            raw_progress = index / max(1, frames - 1)
            progress = raw_progress * raw_progress * (3 - 2 * raw_progress)
            brightness = _pulse_activity(beat_terms, t) + _pulse_activity(bass_terms, t, decay=9.0)
            zoom = start_zoom + (end_zoom - start_zoom) * progress
            if movement == "handheld":
                zoom += math.sin(t * 7.2) * 0.004 + math.cos(t * 3.7) * 0.002
            if "beat_pulse" in effects and audio_reactive.enabled:
                zoom += _pulse_activity(beat_terms, t) * 0.18
            zoom = max(1.0, zoom)

            crop_w = width / zoom
            crop_h = height / zoom
            center_x = canvas_w / 2 + pan_x * 0.5 * (canvas_w - crop_w) * progress
            center_y = canvas_h / 2 + pan_y * 0.5 * (canvas_h - crop_h) * progress
            if movement == "handheld":
                center_x += math.sin(t * 2.7) * canvas_w * 0.004
                center_y += math.cos(t * 3.1) * canvas_h * 0.003
            if "shake" in effects:
                center_x += math.sin(t * 13.0) * width * 0.003
                center_y += math.cos(t * 17.0) * height * 0.003
            center_x = min(canvas_w - crop_w / 2, max(crop_w / 2, center_x))
            center_y = min(canvas_h - crop_h / 2, max(crop_h / 2, center_y))
            frame = cv2.getRectSubPix(canvas, (max(2, int(crop_w)), max(2, int(crop_h))), (center_x, center_y))
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LANCZOS4)

            if depth is not None:
                parallax = 10.0 * math.sin(progress * math.pi) * (pan_x or 0.35)
                map_x = np.tile(np.arange(width, dtype=np.float32), (height, 1)) + parallax * (1.0 - depth)
                map_y = np.tile(np.arange(height, dtype=np.float32)[:, None], (1, width))
                frame = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

            if abs(rotation_degrees) > 0.01:
                angle = rotation_degrees * progress
                matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.03)
                frame = cv2.warpAffine(
                    frame,
                    matrix,
                    (width, height),
                    flags=cv2.INTER_LANCZOS4,
                    borderMode=cv2.BORDER_REFLECT,
                )

            frame = frame.astype(np.float32)
            # Brightness, contrast and saturation.
            frame = (frame - 127.5) * 1.035 + 127.5
            frame += brightness * 255.0
            if "soft_focus" in effects:
                frame = cv2.GaussianBlur(frame, (0, 0), 0.9)
            if "bloom" in effects:
                blur = cv2.GaussianBlur(frame, (0, 0), 7.0)
                glow = 255.0 - (255.0 - frame) * (255.0 - blur) / 255.0
                frame = frame * 0.82 + glow * 0.18
            if "chromatic_aberration" in effects:
                red_shift = np.roll(frame[:, :, 2], 2, axis=1)
                blue_shift = np.roll(frame[:, :, 0], -2, axis=1)
                frame[:, :, 2] = red_shift
                frame[:, :, 0] = blue_shift
            if light_leak is not None:
                frame = 255.0 - (255.0 - frame) * (255.0 - light_leak) / 255.0
            if vignette is not None:
                frame *= vignette
            if "subtle_film_grain" in effects:
                frame += np_rng.normal(0, 2.2, (height, width, 1)).astype(np.float32)
            elif "film_grain" in effects:
                frame += np_rng.normal(0, 5.0, (height, width, 1)).astype(np.float32)
            frame = np.clip(frame, 0, 255).astype(np.uint8)

            if particles:
                overlay = np.zeros_like(frame)
                try:
                    hex_value = particle_color.lstrip("#")
                    color = (
                        int(hex_value[4:6], 16),
                        int(hex_value[2:4], 16),
                        int(hex_value[0:2], 16),
                    )
                except (ValueError, IndexError):
                    color = (120, 170, 200)
                for particle in particles:
                    x, y = particle.position(t, width, height)
                    alpha = particle.alpha * (0.6 + 0.4 * math.sin(t + particle.phase))
                    scaled = tuple(int(channel * (0.5 + alpha)) for channel in color)
                    cv2.circle(overlay, (x, y), max(1, int(particle.radius)), scaled, -1, lineType=cv2.LINE_AA)
                overlay = cv2.GaussianBlur(overlay, (0, 0), 1.4)
                frame = cv2.addWeighted(frame, 1.0, overlay, 0.5, 0)

            if "letterbox" in effects:
                bar = max(2, int(round(height * 0.055)))
                frame[:bar, :, :] = 0
                frame[-bar:, :, :] = 0

            if encoder.stdin is None:
                raise MediaError("FFmpeg encoder pipe is unavailable")
            encoder.stdin.write(frame.tobytes())

        encoder.stdin.close()
        stderr = encoder.stderr.read().decode("utf-8", errors="replace") if encoder.stderr else ""
        return_code = encoder.wait(timeout=120)
        if return_code != 0:
            raise MediaError(f"OpenCV animation encoding failed: {stderr[-3000:]}")
    except Exception:
        if encoder.poll() is None:
            encoder.kill()
        try:
            encoder.wait(timeout=5)
        except Exception:
            pass
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    os.replace(temp_name, output_path)
    return {
        "backend": "opencv",
        "width": width,
        "height": height,
        "fps": fps,
        "duration": round(duration, 3),
        "frames": frames,
        "effects": sorted(effects),
        "depth_parallax": depth is not None,
    }
