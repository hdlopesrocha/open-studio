"""Final assembly of animated scenes, music and styled subtitles."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from mvstudio_shared.config import get_settings
from mvstudio_shared.media import (
    MediaError,
    encoder_available,
    escape_filter_path,
    extract_thumbnail,
    probe_duration,
    run_command,
)
from mvstudio_shared.models import OutputConfig, Scene, SubtitleStyle
from mvstudio_shared.srt import parse_srt_file_with_warnings, write_ass, write_srt_file
from mvstudio_shared.storage import ProjectStore
from mvstudio_shared.timeline import XFADE_TRANSITIONS, effective_transition_duration

logger = logging.getLogger("mvstudio.renderer")

XFADE_MAP = XFADE_TRANSITIONS


class RenderError(RuntimeError):
    pass


def _format_seconds(value: float) -> str:
    return f"{max(0.0, value):.3f}"


def _transition_duration(scene: Scene, following: Scene) -> float:
    return effective_transition_duration(scene, following)


def _preprocess_label(index: int) -> str:
    return f"v{index}"


def _build_xfade_graph(
    scene_count: int,
    scenes: list[Scene],
    output: OutputConfig,
    target_duration: float,
    ass_path: Path | None,
    fonts_dir: str | None,
) -> tuple[str, list[str]]:
    width, height, fps = output.width, output.height, output.fps
    chunks: list[str] = []
    for index in range(scene_count):
        chunks.append(
            f"[{index}:v]fps={fps},"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,settb=AVTB"
            f"[{_preprocess_label(index)}]"
        )
    warnings: list[str] = []
    current = _preprocess_label(0)
    for index in range(scene_count - 1):
        following = scenes[index + 1]
        duration = _transition_duration(scenes[index], following)
        requested = scenes[index].transition.duration
        if scenes[index].transition.type != "cut" and duration < requested - 0.01:
            warnings.append(
                f"Transition after scene {scenes[index].scene_id} was shortened from "
                f"{requested:.2f}s to {duration:.2f}s to fit the adjacent scenes."
            )
        offset = max(0.0, scenes[index].end - duration)
        transition = XFADE_MAP.get(scenes[index].transition.type, "fade")
        raw_label = f"xraw{index}"
        label = f"x{index}"
        chunks.append(
            f"[{current}][{_preprocess_label(index + 1)}]"
            f"xfade=transition={transition}:duration={duration:.3f}:offset={offset:.3f}"
            f"[{raw_label}]"
        )
        # xfade output does not always advertise a constant frame rate to the
        # next chained xfade. Normalise without resetting PTS so timeline offsets
        # remain valid.
        chunks.append(f"[{raw_label}]fps={fps},settb=AVTB[{label}]")
        current = label
    filters = [
        f"tpad=stop_mode=add:color=black:stop_duration={handle_pad(target_duration):.3f}",
        f"trim=duration={_format_seconds(target_duration)}",
        "setpts=PTS-STARTPTS",
    ]
    if ass_path is not None:
        ass_filter = f"ass=filename='{escape_filter_path(ass_path)}'"
        if fonts_dir:
            ass_filter += f":fontsdir='{escape_filter_path(fonts_dir)}'"
        filters.append(ass_filter)
    filters.append("format=yuv420p")
    chunks.append(f"[{current}]{','.join(filters)}[vout]")
    return ";".join(chunks), warnings


def handle_pad(target_duration: float) -> float:
    return max(target_duration, 0.0)


def _build_concat_fallback_graph(
    scene_count: int,
    scenes: list[Scene],
    output: OutputConfig,
    target_duration: float,
    ass_path: Path | None,
    fonts_dir: str | None,
) -> str:
    width, height, fps = output.width, output.height, output.fps
    chunks: list[str] = []
    for index in range(scene_count):
        pre_roll = _transition_duration(scenes[index - 1], scenes[index]) if index > 0 else 0.0
        start = pre_roll
        end = pre_roll + scenes[index].duration
        chunks.append(
            f"[{index}:v]fps={fps},"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,"
            f"trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS"
            f"[c{index}]"
        )
    stream_inputs = "".join(f"[c{index}]" for index in range(scene_count))
    chunks.append(f"{stream_inputs}concat=n={scene_count}:v=1:a=0[concatv]")
    filters = [
        f"tpad=stop_mode=add:color=black:stop_duration={_format_seconds(target_duration)}",
        f"trim=duration={_format_seconds(target_duration)}",
        "setpts=PTS-STARTPTS",
    ]
    if ass_path is not None:
        ass_filter = f"ass=filename='{escape_filter_path(ass_path)}'"
        if fonts_dir:
            ass_filter += f":fontsdir='{escape_filter_path(fonts_dir)}'"
        filters.append(ass_filter)
    filters.append("format=yuv420p")
    chunks.append(f"[concatv]{','.join(filters)}[vout]")
    return ";".join(chunks)


def _run_render(
    *,
    scene_count: int,
    scenes: list[Scene],
    clip_paths: list[Path],
    output: OutputConfig,
    target_duration: float,
    audio_path: Path,
    subtitles_path: Path | None,
    subtitle_style: SubtitleStyle,
    title: str,
    width: int,
    height: int,
    fps: int,
    codec: str,
    target_path: Path,
    use_xfade: bool,
) -> list[str]:
    ass_path: Path | None = None
    warnings: list[str] = []
    fonts_dir = os.environ.get("FONTS_DIR", "").strip() or None
    if subtitles_path is not None and output.burn_subtitles:
        lines, srt_warnings = parse_srt_file_with_warnings(subtitles_path)
        warnings.extend(srt_warnings)
        ass_path = target_path.parent / "subtitles.ass"
        write_ass(
            lines,
            ass_path,
            subtitle_style,
            play_res_x=width,
            play_res_y=height,
            title=title,
        )
    if use_xfade:
        graph, graph_warnings = _build_xfade_graph(
            scene_count, scenes, output, target_duration, ass_path, fonts_dir
        )
        warnings.extend(graph_warnings)
    else:
        graph = _build_concat_fallback_graph(
            scene_count, scenes, output, target_duration, ass_path, fonts_dir
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = target_path.suffix or ".mp4"
    fd, temp_name = tempfile.mkstemp(prefix=target_path.stem + ".", suffix=".tmp" + suffix, dir=str(target_path.parent))
    os.close(fd)
    command = [get_settings().ffmpeg, "-hide_banner", "-y"]
    for clip_path in clip_paths:
        command += ["-i", str(clip_path.resolve())]
    command += [
        "-i",
        str(audio_path),
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-map",
        f"{scene_count}:a:0",
        "-t",
        _format_seconds(target_duration),
        "-c:v",
        codec,
        "-preset",
        output.preset,
        "-crf",
        str(output.effective_crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        output.audio_bitrate,
        "-movflags",
        "+faststart",
        "-max_muxing_queue_size",
        "2048",
        "-metadata",
        f"title={title or 'Music Video'}",
        temp_name,
    ]
    try:
        run_command(command, timeout=7200)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    os.replace(temp_name, target_path)
    return warnings


def render_project_video(
    *,
    project_id: str,
    scenes: list[Scene],
    audio_path: str,
    subtitle_path: str,
    output: OutputConfig,
    subtitle_style: SubtitleStyle,
    title: str = "",
) -> dict:
    settings = get_settings()
    store = ProjectStore(settings.projects_root)
    started = time.perf_counter()
    try:
        store.load(project_id)
        paths = store.paths(project_id)
    except Exception as exc:
        raise RenderError(f"Project not found: {project_id}") from exc

    if not scenes:
        raise RenderError("No scenes to render")
    ordered = sorted(scenes, key=lambda scene: scene.start)
    if abs(ordered[0].start) > 0.05:
        raise RenderError("The first scene must begin at 0.0 seconds")
    for index, scene in enumerate(ordered[:-1]):
        gap = ordered[index + 1].start - scene.end
        if abs(gap) > 0.05:
            raise RenderError(
                f"Scene timeline has a gap or overlap of {gap:.2f}s after scene {scene.scene_id}. "
                "Re-plan the scenes or adjust their durations."
            )
        if not scene.video_path:
            raise RenderError(f"Scene {scene.scene_id} has no animated clip")
        video = paths.abs(scene.video_path)
        if not video.is_file():
            raise RenderError(f"Animated clip for scene {scene.scene_id} is missing")
    if not ordered[-1].video_path:
        raise RenderError(f"Scene {ordered[-1].scene_id} has no animated clip")

    audio_file = paths.abs(audio_path)
    if not audio_file.is_file():
        raise RenderError(f"Audio file not found: {audio_path}")
    subtitle_file = paths.abs(subtitle_path)
    if not subtitle_file.is_file():
        raise RenderError(f"Subtitle file not found: {subtitle_path}")
    try:
        audio_duration = probe_duration(audio_file)
    except MediaError as exc:
        raise RenderError(f"Could not read the source audio: {exc}") from exc
    target_duration = round(audio_duration, 3)
    if ordered[-1].end > target_duration + 0.05:
        raise RenderError(
            f"Scenes extend {ordered[-1].end - target_duration:.2f}s beyond the audio. "
            "Trim or re-plan the final scene."
        )

    warnings: list[str] = []
    if ordered[-1].end < target_duration - 0.05:
        warnings.append(
            f"Scenes end {target_duration - ordered[-1].end:.2f}s before the audio; "
            "the last frame will be held and then faded to black."
        )

    width, height, fps = output.width, output.height, output.fps
    codec = "libx264"
    if output.codec == "h265":
        if encoder_available("libx265"):
            codec = "libx265"
        else:
            warnings.append("H.265 encoder (libx265) is not available; falling back to H.264.")
    else:
        if not encoder_available("libx264"):
            raise RenderError("The FFmpeg build has no libx264 encoder; install a full FFmpeg build")

    output_dir = paths.output_dir
    output_filename = output.output_filename or "final_video.mp4"
    target_path = output_dir / output_filename
    clip_paths = [paths.abs(scene.video_path or "") for scene in ordered]
    for index, (scene, clip_path) in enumerate(zip(ordered, clip_paths)):
        pre_roll = effective_transition_duration(ordered[index - 1], scene) if index > 0 else 0.0
        required = scene.duration + pre_roll
        try:
            actual = probe_duration(clip_path)
        except MediaError as exc:
            raise RenderError(
                f"Could not read the animated clip for scene {scene.scene_id}: {exc}"
            ) from exc
        if actual + 0.02 < required:
            raise RenderError(
                f"The animated clip for scene {scene.scene_id} is {actual:.2f}s but the timeline "
                f"needs {required:.2f}s. Re-animate this scene (and its neighbours if timing changed) "
                "before rendering."
            )
    srt_output = output_dir / "subtitles.srt"
    original_lines, srt_warnings = parse_srt_file_with_warnings(subtitle_file)
    warnings.extend(srt_warnings)
    write_srt_file(original_lines, srt_output)

    xfade_error: Exception | None = None
    try:
        warnings.extend(
            _run_render(
                scene_count=len(ordered),
                scenes=ordered,
                clip_paths=clip_paths,
                output=output,
                target_duration=target_duration,
                audio_path=audio_file,
                subtitles_path=subtitle_file,
                subtitle_style=subtitle_style,
                title=title,
                width=width,
                height=height,
                fps=fps,
                codec=codec,
                target_path=target_path,
                use_xfade=True,
            )
        )
    except Exception as exc:
        xfade_error = exc
        logger.warning("XFade render failed, retrying with hard cuts: %s", exc)
        if len(ordered) < 2:
            raise RenderError(f"Rendering failed: {exc}") from exc
        warnings.append(
            "Transition rendering failed; the video was re-rendered with hard cuts. "
            f"Original error: {str(exc)[-500:]}"
        )
        try:
            warnings.extend(
                _run_render(
                    scene_count=len(ordered),
                    scenes=ordered,
                    clip_paths=clip_paths,
                    output=output,
                    target_duration=target_duration,
                    audio_path=audio_file,
                    subtitles_path=subtitle_file,
                    subtitle_style=subtitle_style,
                    title=title,
                    width=width,
                    height=height,
                    fps=fps,
                    codec=codec,
                    target_path=target_path,
                    use_xfade=False,
                )
            )
        except Exception as exc2:
            raise RenderError(
                f"Rendering failed with transitions ({xfade_error}) and with hard cuts ({exc2})"
            ) from exc2

    thumbnail = paths.thumbnails_dir / "final_video.jpg"
    try:
        extract_thumbnail(target_path, thumbnail, time=min(2.0, target_duration / 3), width=640)
        thumbnail_relative = paths.rel(thumbnail)
    except Exception as exc:
        warnings.append(f"Final thumbnail extraction failed: {exc}")
        thumbnail_relative = None

    # Keep an explicit final_video.mp4 alias for the documented output layout.
    alias = output_dir / "final_video.mp4"
    if target_path.suffix.lower() == ".mp4" and target_path.resolve() != alias.resolve():
        try:
            os.link(target_path, alias)
        except OSError:
            try:
                import shutil

                shutil.copy2(target_path, alias)
            except OSError:
                pass

    encoded_seconds = round(time.perf_counter() - started, 2)
    logger.info(
        "Rendered %s (%d scenes, %.1fs, %s)",
        target_path.name,
        len(ordered),
        encoded_seconds,
        codec,
    )
    return {
        "project_id": project_id,
        "video_path": paths.rel(target_path),
        "srt_path": paths.rel(srt_output),
        "thumbnail_path": thumbnail_relative,
        "duration": target_duration,
        "width": width,
        "height": height,
        "fps": fps,
        "codec": "h265" if codec == "libx265" else "h264",
        "encoder": codec,
        "file_size": target_path.stat().st_size,
        "scene_count": len(ordered),
        "warnings": list(dict.fromkeys(warnings)),
        "render_seconds": encoded_seconds,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
