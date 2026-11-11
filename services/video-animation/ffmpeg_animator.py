"""FFmpeg-based cinematic image animation (CPU friendly)."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

from mvstudio_shared.config import get_settings
from mvstudio_shared.media import run_command
from mvstudio_shared.models import AudioReactiveConfig, BeatEvent, CameraMove, Scene
from PIL import Image, ImageDraw

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


def _even(value: float, minimum: int = 2) -> int:
    return max(minimum, int(round(value / 2.0) * 2))


class _Graph:
    def __init__(self) -> None:
        self.chunks: list[str] = []
        self.counter = 0

    def label(self, prefix: str = "v") -> str:
        self.counter += 1
        return f"{prefix}{self.counter}"

    def add(self, stream: str, filters: str, prefix: str = "v") -> str:
        out = self.label(prefix)
        self.chunks.append(f"[{stream}]{filters}[{out}]")
        return out


def _camera_expressions(
    camera: CameraMove,
    frames: int,
    fps: float,
    duration: float,
    zoom_pulses: list[tuple[float, float]],
) -> tuple[str, str, str]:
    movement = camera.movement
    zoom = max(1.0, camera.zoom)
    if movement == "pan_left" or movement == "pan_right" or movement == "pan_up" or movement == "pan_down":
        zoom = max(zoom, 1.07)
    if movement in {"rotate_cw", "rotate_ccw"}:
        zoom = max(zoom, 1.08)
    start_zoom = 1.0 if movement == "slow_forward" else zoom if movement == "slow_backward" else max(1.0, zoom * 0.985)
    end_zoom = zoom if movement not in {"slow_backward"} else 1.0
    progress = f"(on/{max(1, frames - 1)})"
    zoom_expr = f"{start_zoom:.5f}+({end_zoom:.5f}-{start_zoom:.5f})*{progress}"
    if movement == "handheld":
        zoom_expr = f"({zoom_expr})+0.004*sin(on*0.37)+0.002*cos(on*0.19)"
    if zoom_pulses:
        pulse = "+".join(
            f"{amplitude:.4f}*between(on,{max(0, int(round(time * fps)))},{max(0, int(round((time + 0.16) * fps)))})"
            for time, amplitude in zoom_pulses[:24]
        )
        zoom_expr = f"({zoom_expr})+{pulse}"
    zoom_expr = f"max(1.0,{zoom_expr})"

    pan_x = camera.pan_x
    pan_y = camera.pan_y
    if movement == "pan_left":
        pan_x = -max(abs(pan_x), 0.32)
    elif movement == "pan_right":
        pan_x = max(abs(pan_x), 0.32)
    elif movement == "pan_up":
        pan_y = -max(abs(pan_y), 0.28)
    elif movement == "pan_down":
        pan_y = max(abs(pan_y), 0.28)
    wobble = ""
    if movement == "handheld":
        wobble = "+sin(on*0.29)*iw*0.003"
    x_expr = (
        f"clip((iw-iw/zoom)/2*(1+({pan_x:.4f})*(2*{progress}-1))"
        f"{wobble if movement == 'handheld' else ''},0,iw-iw/zoom)"
    )
    y_expr = (
        f"clip((ih-ih/zoom)/2*(1+({pan_y:.4f})*(2*{progress}-1))"
        f"{'+cos(on*0.23)*ih*0.002' if movement == 'handheld' else ''},0,ih-ih/zoom)"
    )
    _ = duration
    return zoom_expr, x_expr, y_expr


def _beat_pulse_terms(
    beats: list[BeatEvent],
    clip_start: float,
    duration: float,
    intensity: float,
    mode: str,
) -> list[tuple[float, float]]:
    candidates: list[BeatEvent]
    if mode == "bass":
        downbeats = [beat for beat in beats if beat.downbeat]
        candidates = downbeats or beats[::4]
        amplitude_base = 0.045 + 0.085 * intensity
        decay = 9.0
    else:
        candidates = [beat for beat in beats if beat.strong] or beats
        amplitude_base = 0.025 + 0.055 * intensity
        decay = 18.0
    _ = decay
    terms: list[tuple[float, float]] = []
    for beat in sorted(candidates, key=lambda item: item.time):
        local = beat.time - clip_start
        if local < -0.05 or local > duration:
            continue
        amplitude = amplitude_base * max(0.35, min(1.4, beat.strength + 0.25))
        terms.append((max(0.0, local), amplitude))
        if len(terms) >= 48:
            break
    return terms


def _brightness_expression(terms: list[tuple[float, float]], decay: float = 16.0) -> str:
    if not terms:
        return "0"
    pieces = [
        f"{amplitude:.4f}*if(between(t,{time:.4f},{time + 0.55:.4f}),exp(-{decay:.1f}*(t-{time:.4f})),0)"
        for time, amplitude in terms
    ]
    return "(" + "+".join(pieces) + ")"


def _render_particles_overlay(
    cache_dir: Path, width: int, height: int, seed: int, color: str
) -> Path:
    from PIL import ImageFilter

    path = cache_dir / f"particles_{seed}_{width}x{height}.png"
    if path.is_file():
        return path
    import random

    rng = random.Random(seed)
    try:
        rgb = tuple(int(color.lstrip("#")[index : index + 2], 16) for index in (0, 2, 4))
    except Exception:
        rgb = (244, 162, 97)
    image = Image.new("RGBA", (width + 240, height + 240), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    count = max(60, (width * height) // 45000)
    for _ in range(count):
        x = rng.uniform(0, width + 240)
        y = rng.uniform(0, height + 240)
        radius = rng.uniform(0.6, 3.6)
        alpha = rng.randint(28, 125)
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(*rgb, alpha))
    glow = image.filter(ImageFilter.GaussianBlur(3.0))
    image = Image.alpha_composite(glow, image)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")
    return path


def render_ffmpeg(
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
    particle_color: str = "#F4A261",
    cache_dir: Path | None = None,
) -> dict:
    effects = {effect for effect in scene.visual_effects if effect in SUPPORTED_EFFECTS}
    frames = max(2, int(round(clip_duration * fps)))
    duration = frames / fps
    overscan = 1.08
    base_w = _even(width * overscan)
    base_h = _even(height * overscan)

    beat_pulses = _beat_pulse_terms(beats, clip_start, duration, audio_reactive.intensity, "beat") if (
        audio_reactive.enabled and audio_reactive.beat_pulse and "beat_pulse" in effects
    ) else []
    bass_pulses = _beat_pulse_terms(beats, clip_start, duration, audio_reactive.intensity, "bass") if (
        audio_reactive.enabled and audio_reactive.bass_pulse and "bass_pulse" in effects
    ) else []
    zoom_pulses = [(time, amplitude * 0.35) for time, amplitude in beat_pulses[:16]] if (
        audio_reactive.enabled and audio_reactive.beat_pulse and "beat_pulse" in effects
    ) else []

    zoom_expr, x_expr, y_expr = _camera_expressions(
        scene.camera, frames, fps, duration, zoom_pulses
    )
    graph = _Graph()
    stream = graph.add(
        "0:v",
        (
            f"scale=w={base_w * 2}:h={base_h * 2}:force_original_aspect_ratio=increase,"
            f"crop={base_w * 2}:{base_h * 2},"
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={frames}:"
            f"s={base_w}x{base_h}:fps={fps}"
        ),
        "zp",
    )

    rotation_degrees = scene.camera.rotation
    if scene.camera.movement in {"rotate_cw", "rotate_ccw"} and abs(rotation_degrees) < 0.05:
        rotation_degrees = 0.7 if scene.camera.movement == "rotate_cw" else -0.7
    if abs(rotation_degrees) > 0.01:
        radians = rotation_degrees * math.pi / 180.0
        stream = graph.add(
            stream,
            f"rotate='{radians:.6f}*t/{max(duration, 0.001):.4f}':fillcolor=black@1.0",
            "rot",
        )

    brightness_terms = beat_pulses + bass_pulses
    brightness = _brightness_expression(brightness_terms)
    grade = f"eq=contrast=1.035:saturation=1.04:brightness='{brightness}':eval=frame"
    stream = graph.add(stream, grade, "grade")
    if "vignette" in effects:
        stream = graph.add(stream, "vignette=angle=PI/5", "vig")
    if "chromatic_aberration" in effects:
        stream = graph.add(stream, "rgbashift=rh=2:bh=-2:rv=1:bv=-1", "chr")
    if "light_leak" in effects:
        stream = graph.add(stream, "colorbalance=rm=0.055:gm=0.02:bm=-0.025:rh=0.02:bh=-0.01", "leak")
    if "soft_focus" in effects:
        stream = graph.add(stream, "gblur=sigma=0.85", "soft")
    if "bloom" in effects:
        left = graph.label("bl")
        right = graph.label("bh")
        glow = graph.label("bg")
        merged = graph.label("bm")
        graph.chunks.append(f"[{stream}]format=gbrp,split=2[{left}][{right}]")
        graph.chunks.append(f"[{right}]gblur=sigma=9:steps=2[{glow}]")
        graph.chunks.append(
            f"[{left}][{glow}]blend=all_mode=screen:all_opacity=0.22[{merged}]"
        )
        stream = graph.add(merged, "format=yuv420p", "bconv")
    if "shake" in effects:
        stream = graph.add(
            stream,
            (
                "crop=w=iw*0.955:h=ih*0.955:"
                "x='iw*0.0225+sin(t*13.0)*iw*0.004':"
                "y='ih*0.0225+cos(t*17.0)*ih*0.0036'"
            ),
            "shake",
        )
    if "film_grain" in effects:
        stream = graph.add(stream, "noise=alls=9:allf=t+u", "grain")
    elif "subtle_film_grain" in effects:
        stream = graph.add(stream, "noise=alls=4:allf=t+u", "grain")

    particles_input: Path | None = None
    if "particles" in effects and cache_dir is not None:
        particles_input = _render_particles_overlay(
            cache_dir,
            base_w,
            base_h,
            scene.seed,
            particle_color,
        )
    final_filters = [f"scale={width}:{height}:flags=lanczos"]
    if "letterbox" in effects:
        bar = max(2, int(round(height * 0.055)))
        final_filters.append(f"drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill")
        final_filters.append(
            f"drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill"
        )
    final_filters.append("format=yuv420p")
    if particles_input is not None:
        # The overlay image has a 120px margin on every side.
        final_graph_chunks = graph.chunks + [
            "[1:v]format=rgba,colorchannelmixer=aa=0.85[pt]",
            f"[{stream}][pt]overlay=x='-120+34*sin(t*0.33)':y='-120-7*t':format=auto[withpt]",
            f"[withpt]{','.join(final_filters)}[vout]",
        ]
    else:
        final_graph_chunks = graph.chunks + [f"[{stream}]{','.join(final_filters)}[vout]"]

    filter_graph = ";".join(final_graph_chunks)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=output_path.name + ".", suffix=".mp4", dir=str(output_path.parent))
    os.close(fd)
    command = [get_settings().ffmpeg, "-hide_banner", "-y", "-i", str(image_path)]
    if particles_input is not None:
        command += ["-loop", "1", "-i", str(particles_input)]
    command += [
        "-filter_complex",
        filter_graph,
        "-map",
        "[vout]",
        "-frames:v",
        str(frames),
        "-r",
        str(fps),
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
    ]
    try:
        run_command(command, timeout=1800)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    os.replace(temp_name, output_path)
    return {
        "backend": "ffmpeg",
        "width": width,
        "height": height,
        "fps": fps,
        "duration": round(duration, 3),
        "frames": frames,
        "effects": sorted(effects),
        "filter_graph": filter_graph,
    }
