"""Engine orchestration for OmniVoice and Piper.

All heavy calls run in worker threads so the FastAPI event loop stays
responsive. OmniVoice work is split at sentence boundaries, which gives the
job system a cancellation checkpoint between model calls without trying to
interrupt the model itself.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from openstudio_common import JobCancelled, relative_path, utc_now

from . import audio
from .config import Settings
from .errors import (
    OmniVoiceUnavailableError,
    PiperUnavailableError,
    PiperVoiceMissingError,
    VoiceConflictError,
    VoiceError,
    VoiceNotFoundError,
    VoiceUnavailableError,
    VoiceValidationError,
)
from .languages import PORTUGUESE_VARIANT_IDS, normalize_model_language
from .model_manager import ModelManager, ModelNotReadyError
from .piper_engine import PiperEngine
from .schemas import BatchTTSRequest, GenerationParams, TTSRequest, public_generation_params
from .storage import OutputStore, VoiceStore
from .text import split_speech_segments, split_text_for_jobs
from .voices import PiperVoice, get_voice, language_matches

logger = logging.getLogger(__name__)

Reporter = Callable[[float, str, str | None], Awaitable[None]]
Checker = Callable[[], Awaitable[None]]

GAP_SECONDS = 0.06
PIPER_MAX_SPEED = 2.0
PIPER_MIN_SPEED = 0.5


async def _report(
    reporter: Reporter | None,
    progress: float,
    stage: str,
    message: str | None = None,
) -> None:
    if reporter is not None:
        await reporter(max(0.0, min(100.0, progress)), stage, message)


async def _check(checker: Checker | None) -> None:
    if checker is not None:
        await checker()


def preview_text_for_language(language: str | None, default: str) -> str:
    if language == "pt-PT":
        return "Olá! Esta é uma pré-visualização da minha voz em português de Portugal."
    if language == "pt-BR":
        return "Olá! Esta é uma prévia da minha voz em português do Brasil."
    return default


class VoiceRuntime:
    """Shared operations used by job handlers, sync routes and internal TTS."""

    def __init__(
        self,
        settings: Settings,
        voices: VoiceStore,
        outputs: OutputStore,
        manager: ModelManager,
        piper: PiperEngine,
    ) -> None:
        self.settings = settings
        self.voices = voices
        self.outputs = outputs
        self.manager = manager
        self.piper = piper

    # ── Validation ─────────────────────────────────────────────────────────

    @staticmethod
    def resolve_engine(req: GenerationParams) -> str:
        engine = (req.engine or "omnivoice").strip().lower()
        if engine == "auto":
            return "piper" if req.piper_voice else "omnivoice"
        return engine

    def validate_request(self, req: TTSRequest | GenerationParams) -> str:
        engine = self.resolve_engine(req)
        if engine == "piper":
            self._validate_piper(req)
        elif engine == "omnivoice":
            self._validate_omnivoice(req)
        else:  # pragma: no cover - pydantic already constrains this
            raise VoiceValidationError(f"Unknown TTS engine: {engine}")
        return engine

    def _validate_piper(self, req: GenerationParams) -> PiperVoice:
        try:
            voice = get_voice(req.piper_voice, self.settings.default_piper_voice)
        except KeyError as exc:
            raise VoiceValidationError(str(exc)) from exc
        if req.format not in audio.PIPER_FORMATS:
            raise VoiceValidationError(
                f"Piper supports {', '.join(audio.PIPER_FORMATS)} output only.",
                details={"format": req.format},
            )
        speed = float(req.speed or 1.0)
        if not PIPER_MIN_SPEED <= speed <= PIPER_MAX_SPEED:
            raise VoiceValidationError(
                f"Piper speed must be between {PIPER_MIN_SPEED} and {PIPER_MAX_SPEED}.",
                details={"speed": speed},
            )
        if req.language and not language_matches(req.language, voice.language):
            raise VoiceValidationError(
                f"The selected Piper voice '{voice.id}' speaks {voice.language}, not {req.language}.",
                details={"voice": voice.id, "language": voice.language},
            )
        if req.language_variant and not language_matches(req.language_variant, voice.language):
            raise VoiceValidationError(
                f"The selected Piper voice '{voice.id}' speaks {voice.language}, not "
                f"{req.language_variant}.",
                details={"voice": voice.id, "language": voice.language},
            )
        if not audio.pitch_is_identity(req.pitch) and not voice.pitch_supported:
            raise VoiceValidationError(
                "The selected Piper voice does not support pitch adjustment.",
                details={"voice": voice.id, "pitch_supported": False},
            )
        if not voice.available(self.settings.piper_dir):
            raise PiperVoiceMissingError(
                f"The Piper voice {voice.id} is not installed.",
                details={
                    "voice_id": voice.id,
                    "install": f'POST /api/voice/piper/install {{"voice_id":"{voice.id}"}}',
                },
            )
        if not self.piper.module_available():
            raise PiperUnavailableError(
                "piper-tts is not installed in this image; Piper voices are unavailable."
            )
        return voice

    def _validate_omnivoice(self, req: TTSRequest | GenerationParams) -> None:
        if self.manager.status in {"unavailable", "error"}:
            raise OmniVoiceUnavailableError(
                self.manager.error or self.manager.status_message
            )
        if len(getattr(req, "text", "") or "") > self.settings.max_input_chars:
            raise VoiceValidationError(
                f"OmniVoice text is limited to {self.settings.max_input_chars} characters."
            )
        if not audio.pitch_is_identity(req.pitch):
            raise VoiceValidationError("Pitch adjustment is only supported by Piper voices.")

        voice_meta: dict[str, Any] | None = None
        if req.mode == "voice":
            if not req.voice_id:
                raise VoiceValidationError("voice_id is required when mode is 'voice'")
            try:
                voice_meta = self.voices.get_meta(req.voice_id)
            except KeyError as exc:
                raise VoiceNotFoundError("Voice not found") from exc
            if not self.voices.prompt_path(req.voice_id).is_file():
                raise VoiceConflictError(
                    "This voice has no trained prompt. Retrain it first."
                )
        elif req.mode == "design" and not req.instruct:
            raise VoiceValidationError("instruct is required when mode is 'design'")

        language = req.language or (voice_meta.get("language") if voice_meta else None)
        variant = req.language_variant or (
            language if language in PORTUGUESE_VARIANT_IDS else None
        )
        if variant in PORTUGUESE_VARIANT_IDS:
            if req.mode != "voice":
                raise VoiceValidationError(
                    f"{variant} requires a trained voice profile recorded with a matching "
                    "reference clip. Auto voice and voice design cannot guarantee the accent."
                )
            if voice_meta is None or voice_meta.get("language") != variant:
                raise VoiceValidationError(
                    f"This voice is tagged "
                    f"{voice_meta.get('language') if voice_meta else 'unknown'}, not {variant}. "
                    "Retrain or tag the voice with a matching reference clip first."
                )

    # ── OmniVoice readiness ────────────────────────────────────────────────

    async def _wait_ready(
        self,
        reporter: Reporter | None,
        checker: Checker | None,
    ) -> None:
        if self.manager.ready:
            return
        if self.manager.status == "unavailable":
            raise OmniVoiceUnavailableError(self.manager.status_message)
        if self.manager.status == "error":
            raise OmniVoiceUnavailableError(
                f"OmniVoice model failed to load: {self.manager.error or self.manager.status_message}"
            )
        started = time.time()
        while not self.manager.ready:
            await _check(checker)
            if self.manager.status == "unavailable":
                raise OmniVoiceUnavailableError(self.manager.status_message)
            if self.manager.status == "error":
                raise OmniVoiceUnavailableError(
                    f"OmniVoice model failed to load: {self.manager.error or self.manager.status_message}"
                )
            if time.time() - started > self.settings.model_wait_seconds:
                raise VoiceUnavailableError(
                    "OmniVoice is still loading. Try again after warm-up completes.",
                    details={"waited_seconds": round(time.time() - started, 1)},
                )
            await _report(
                reporter,
                1.0,
                "Loading model",
                "Waiting for the OmniVoice model to finish loading.",
            )
            await asyncio.sleep(2.0)
        try:
            self.manager.ensure_ready()
        except ModelNotReadyError as exc:
            raise OmniVoiceUnavailableError(str(exc)) from exc

    # ── TTS ────────────────────────────────────────────────────────────────

    async def synthesize(
        self,
        req: TTSRequest,
        *,
        reporter: Reporter | None = None,
        checker: Checker | None = None,
    ) -> dict[str, Any]:
        engine = self.validate_request(req)
        if engine == "piper":
            return await self._synthesize_piper(req, reporter=reporter, checker=checker)
        return await self._synthesize_omnivoice(req, reporter=reporter, checker=checker)

    async def _synthesize_omnivoice(
        self,
        req: TTSRequest,
        *,
        reporter: Reporter | None,
        checker: Checker | None,
    ) -> dict[str, Any]:
        self.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        await _report(reporter, 2.0, "Preparing", "Preparing the OmniVoice request.")
        await _check(checker)
        await self._wait_ready(reporter, checker)
        await _check(checker)

        voice_meta: dict[str, Any] | None = None
        prompt: Any = None
        if req.mode == "voice":
            try:
                voice_meta = self.voices.get_meta(req.voice_id or "")
            except KeyError as exc:
                raise VoiceNotFoundError("Voice not found") from exc
            prompt_path = self.voices.prompt_path(req.voice_id or "")
            if not prompt_path.is_file():
                raise VoiceConflictError("This voice has no trained prompt. Retrain it first.")
            try:
                prompt = await asyncio.to_thread(
                    self.manager.load_prompt, req.voice_id or "", prompt_path
                )
            except ModelNotReadyError as exc:
                raise OmniVoiceUnavailableError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise VoiceValidationError(
                    f"Could not load the voice profile: {exc}"
                ) from exc

        language = req.language or (voice_meta.get("language") if voice_meta else None)
        model_language = normalize_model_language(language)
        variant = req.language_variant or (
            language if language in PORTUGUESE_VARIANT_IDS else None
        )
        chunks = (
            [req.text]
            if req.duration is not None
            else split_text_for_jobs(req.text, max_chars=420)
        )

        generated: list[Any] = []
        timeline: list[dict[str, Any]] = []
        sample_rate = self.manager.sample_rate
        cursor = 0.0
        total_elapsed = 0.0

        try:
            import numpy as np

            for index, chunk in enumerate(chunks, start=1):
                await _check(checker)
                await _report(
                    reporter,
                    6.0 + 70.0 * ((index - 1) / max(1, len(chunks))),
                    "Generating",
                    f"Generating segment {index}/{len(chunks)}.",
                )
                try:
                    segment, sample_rate, elapsed = await asyncio.to_thread(
                        self.manager.generate,
                        text=chunk,
                        language=model_language,
                        voice_clone_prompt=prompt,
                        instruct=(
                            req.instruct
                            if req.mode == "design"
                            else (req.style_instruct if req.mode == "voice" else None)
                        ),
                        speed=req.speed,
                        duration=req.duration,
                        num_step=req.num_step,
                        guidance_scale=req.guidance_scale,
                        denoise=req.denoise,
                        t_shift=req.t_shift,
                        position_temperature=req.position_temperature,
                        class_temperature=req.class_temperature,
                        layer_penalty_factor=req.layer_penalty_factor,
                        postprocess_output=req.postprocess_output,
                        pad_duration=req.pad_duration,
                        fade_duration=req.fade_duration,
                        audio_chunk_duration=req.audio_chunk_duration,
                        audio_chunk_threshold=req.audio_chunk_threshold,
                        normalize_text=req.normalize_text,
                        seed=req.seed if index == 1 else None,
                    )
                except ModelNotReadyError as exc:
                    raise OmniVoiceUnavailableError(str(exc)) from exc

                total_elapsed += elapsed
                await _check(checker)

                if generated:
                    gap = np.zeros(int(sample_rate * GAP_SECONDS), dtype=np.float32)
                    generated.append(gap)
                    cursor += GAP_SECONDS
                duration = len(segment) / sample_rate if sample_rate else 0.0
                generated.append(segment)
                timeline.append(
                    {
                        "index": len(timeline) + 1,
                        "text": chunk,
                        "start": round(cursor, 3),
                        "end": round(cursor + duration, 3),
                    }
                )
                cursor += duration

            if not generated:
                raise VoiceValidationError("No audio was generated.")

            audio_array = generated[0] if len(generated) == 1 else np.concatenate(generated)
            computed_duration = len(audio_array) / sample_rate if sample_rate else 0.0
            await _report(reporter, 82.0, "Encoding", "Encoding the requested audio format.")
            await _check(checker)

            with tempfile.TemporaryDirectory(prefix="voice-omni-", dir=str(self.settings.uploads_dir)) as tmp:
                target = Path(tmp) / f"audio.{req.format}"
                try:
                    await asyncio.to_thread(
                        audio.write_audio_file,
                        target,
                        audio_array,
                        sample_rate,
                        req.format,
                        normalize=req.normalize_audio,
                    )
                except audio.AudioConversionError as exc:
                    raise VoiceError(f"Audio encoding failed: {exc}") from exc
                await _check(checker)

                try:
                    duration = await asyncio.to_thread(audio.probe_duration, target)
                except audio.AudioConversionError:
                    duration = computed_duration

                output_meta = {
                    "engine": "omnivoice",
                    "mode": req.mode,
                    "text": req.text,
                    "text_preview": req.text[:180],
                    "voice_id": req.voice_id if req.mode == "voice" else None,
                    "voice_name": voice_meta.get("name") if voice_meta else None,
                    "voice": (
                        voice_meta.get("name")
                        if voice_meta
                        else ("OmniVoice design" if req.mode == "design" else "OmniVoice auto")
                    ),
                    "piper_voice": None,
                    "instruct": req.instruct if req.mode == "design" else None,
                    "style_instruct": req.style_instruct if req.mode == "voice" else None,
                    "language": language,
                    "language_variant": variant,
                    "seed": req.seed,
                    "format": req.format,
                    "duration_seconds": round(duration, 3),
                    "generation_seconds": round(total_elapsed, 3),
                    "rtf": round(total_elapsed / duration, 4) if duration > 0 else None,
                    "sample_rate": sample_rate,
                    "created_at": utc_now(),
                    "timeline": timeline,
                    "params": public_generation_params(req),
                }
                await _report(reporter, 94.0, "Saving", "Saving audio and metadata.")
                output = await asyncio.to_thread(
                    self.outputs.save_file, target, req.format, output_meta
                )
                try:
                    await _check(checker)
                except JobCancelled:
                    self.outputs.delete(output["id"])
                    raise
        except ImportError as exc:
            raise OmniVoiceUnavailableError(
                f"OmniVoice is missing a Python dependency: {exc}"
            ) from exc
        await _report(reporter, 100.0, "Complete", "Speech generation complete.")
        return output

    async def _synthesize_piper(
        self,
        req: TTSRequest,
        *,
        reporter: Reporter | None,
        checker: Checker | None,
    ) -> dict[str, Any]:
        self.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        voice = self._validate_piper(req)
        if len(req.text) > self.settings.piper_max_text_chars:
            raise VoiceValidationError(
                f"Piper text is limited to {self.settings.piper_max_text_chars} characters."
            )
        segments = split_speech_segments(
            req.text,
            voice.language,
            self.settings.piper_max_segment_chars,
        )
        if not segments:
            raise VoiceValidationError("No speakable sentences were found in the text.")
        if len(segments) > self.settings.max_sentences:
            raise VoiceValidationError(
                f"The text contains more than {self.settings.max_sentences} sentences.",
                details={"sentences": len(segments), "max": self.settings.max_sentences},
            )

        await _report(reporter, 2.0, "Preparing", f"Preparing {len(segments)} sentence(s).")
        await _check(checker)
        gap = self.settings.sentence_gap_ms / 1000.0
        generation_started = time.time()

        with tempfile.TemporaryDirectory(prefix="voice-piper-", dir=str(self.settings.uploads_dir)) as tmp:
            work = Path(tmp)
            chunks_dir = work / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunk_paths: list[Path] = []
            for index, sentence in enumerate(segments):
                await _check(checker)
                chunk_path = chunks_dir / f"{index:05d}.wav"
                try:
                    await asyncio.to_thread(
                        self.piper.synthesize_sentence,
                        voice,
                        sentence,
                        float(req.speed or 1.0),
                        chunk_path,
                    )
                except (PiperVoiceMissingError, PiperUnavailableError):
                    raise
                chunk_paths.append(chunk_path)
                await _report(
                    reporter,
                    4.0 + 76.0 * ((index + 1) / max(1, len(segments))),
                    "Synthesizing",
                    f"Synthesized sentence {index + 1} of {len(segments)}.",
                )

            await _check(checker)
            await _report(reporter, 84.0, "Merging", "Merging sentence audio with real durations.")
            master = work / "master.wav"
            try:
                timeline, master_duration = await asyncio.to_thread(
                    audio.merge_wav_chunks, chunk_paths, segments, master, gap
                )
            except audio.AudioConversionError as exc:
                raise VoiceError(f"Could not merge Piper audio: {exc}") from exc
            await _check(checker)

            target = work / f"audio.{req.format}"
            try:
                await asyncio.to_thread(
                    audio.convert_wav_to,
                    master,
                    target,
                    req.format,
                    normalize=req.normalize_audio,
                    pitch_semitones=req.pitch,
                )
            except audio.AudioConversionError as exc:
                raise VoiceError(f"Audio encoding failed: {exc}") from exc
            await _check(checker)

            try:
                duration = await asyncio.to_thread(audio.probe_duration, target)
            except audio.AudioConversionError:
                duration = master_duration

            output_meta = {
                "engine": "piper",
                "mode": "piper",
                "text": req.text,
                "text_preview": req.text[:180],
                "voice_id": None,
                "voice_name": voice.name,
                "voice": voice.id,
                "piper_voice": voice.id,
                "instruct": None,
                "language": req.language or voice.language,
                "language_variant": voice.language if voice.language.startswith("pt-") else None,
                "seed": req.seed,
                "format": req.format,
                "duration_seconds": round(duration, 3),
                "generation_seconds": round(time.time() - generation_started, 3),
                "rtf": (
                    round((time.time() - generation_started) / duration, 4)
                    if duration > 0
                    else None
                ),
                "sample_rate": voice.sample_rate,
                "created_at": utc_now(),
                "timeline": timeline,
                "normalize_audio": req.normalize_audio,
                "pitch": req.pitch,
                "params": public_generation_params(req),
            }
            await _report(reporter, 94.0, "Saving", "Saving audio and metadata.")
            output = await asyncio.to_thread(
                self.outputs.save_file, target, req.format, output_meta
            )
            try:
                await _check(checker)
            except JobCancelled:
                self.outputs.delete(output["id"])
                raise

        await _report(reporter, 100.0, "Complete", "Speech generation complete.")
        return output

    # ── Voice training ─────────────────────────────────────────────────────

    async def train_voice(
        self,
        *,
        name: str,
        language: str | None,
        transcript: str | None,
        transcript_provided: bool,
        audio_path: Path | None,
        voice_id: str | None,
        preprocess_prompt: bool = True,
        consent: bool = True,
        description: str | None = None,
        tags: list[str] | None = None,
        reporter: Reporter | None = None,
        checker: Checker | None = None,
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name and voice_id:
            try:
                name = str(self.voices.get_meta(voice_id).get("name") or "").strip()
            except KeyError:
                name = ""
        if not name:
            raise VoiceValidationError("Voice name is required")
        if not consent:
            raise VoiceValidationError(
                "Consent confirmation is required. Only clone voices you own or have "
                "explicit permission to use."
            )

        await _report(reporter, 2.0, "Preparing", "Preparing voice training.")
        await self._wait_ready(reporter, checker)
        await _check(checker)

        created = voice_id is None
        voice_dir: Path | None = None
        temp_wav: Path | None = None
        temp_prompt: Path | None = None

        try:
            if created:
                if audio_path is None:
                    raise VoiceValidationError("A reference audio file is required")
                voice_id, voice_dir = self.voices.create()
                ref_path = self.voices.reference_path(voice_id)
                candidate_ref = ref_path
                await _report(reporter, 10.0, "Decoding", "Decoding reference audio.")
                try:
                    await asyncio.to_thread(audio.convert_to_wav, audio_path, ref_path)
                    duration = await asyncio.to_thread(audio.probe_duration, ref_path)
                except audio.AudioConversionError as exc:
                    raise VoiceValidationError(
                        f"Could not decode the reference audio: {exc}"
                    ) from exc
                transcript_clean = (transcript or "").strip() or None
                language_value = (language or "").strip() or None
                existing_meta: dict[str, Any] | None = None
            else:
                try:
                    existing_meta = self.voices.get_meta(voice_id)
                except KeyError as exc:
                    raise VoiceNotFoundError("Voice not found") from exc
                voice_dir = self.voices.reference_path(voice_id).parent
                ref_path = self.voices.reference_path(voice_id)
                candidate_ref = ref_path

                if audio_path is not None:
                    temp_wav = voice_dir / "reference.new.wav"
                    await _report(reporter, 10.0, "Decoding", "Decoding new reference audio.")
                    try:
                        await asyncio.to_thread(audio.convert_to_wav, audio_path, temp_wav)
                        duration = await asyncio.to_thread(audio.probe_duration, temp_wav)
                    except audio.AudioConversionError as exc:
                        raise VoiceValidationError(
                            f"Could not decode the reference audio: {exc}"
                        ) from exc
                    candidate_ref = temp_wav
                else:
                    await _report(reporter, 10.0, "Checking", "Checking reference audio.")
                    try:
                        duration = await asyncio.to_thread(audio.probe_duration, ref_path)
                    except audio.AudioConversionError as exc:
                        raise VoiceValidationError(
                            f"Could not read the reference audio: {exc}"
                        ) from exc

                if transcript_provided:
                    transcript_clean = (transcript or "").strip() or None
                else:
                    transcript_clean = existing_meta.get("transcript") or None
                language_value = (
                    ((language or "").strip() or None)
                    if language is not None
                    else existing_meta.get("language")
                )

            await _check(checker)
            if duration < self.settings.min_voice_seconds:
                raise VoiceValidationError(
                    f"Reference audio is too short ({duration:.1f}s). Use at least "
                    f"{self.settings.min_voice_seconds:.0f}s; 3-10s is ideal."
                )
            if duration > self.settings.max_voice_seconds:
                raise VoiceValidationError(
                    f"Reference audio is too long ({duration:.1f}s). Trim it to "
                    f"{self.settings.max_voice_seconds:.0f}s or less; 3-10s is ideal."
                )

            await _report(reporter, 35.0, "Training", "Encoding the voice prompt.")
            try:
                prompt = await asyncio.to_thread(
                    self.manager.create_prompt,
                    str(candidate_ref),
                    transcript_clean,
                    preprocess_prompt,
                )
            except ModelNotReadyError as exc:
                raise OmniVoiceUnavailableError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise VoiceValidationError(f"Could not create the voice prompt: {exc}") from exc
            await _check(checker)
            ref_text = str(getattr(prompt, "ref_text", None) or transcript_clean or "").strip()

            prompt_path = self.voices.prompt_path(voice_id)
            if created:
                await _report(reporter, 75.0, "Saving", "Saving the voice prompt.")
                await asyncio.to_thread(prompt.save, str(prompt_path))
                await _check(checker)
            else:
                temp_prompt = voice_dir / "prompt.new.pt"
                await _report(reporter, 75.0, "Saving", "Saving the voice prompt.")
                await asyncio.to_thread(prompt.save, str(temp_prompt))
                await _check(checker)
                if candidate_ref != ref_path:
                    candidate_ref.replace(ref_path)
                    temp_wav = None
                temp_prompt.replace(prompt_path)
                temp_prompt = None

            now = utc_now()
            if created:
                meta = {
                    "id": voice_id,
                    "name": name,
                    "language": language_value,
                    "transcript": ref_text or None,
                    "description": (description or "").strip() or None,
                    "tags": tags or [],
                    "duration_seconds": round(duration, 3),
                    "sample_rate": self.manager.sample_rate,
                    "created_at": now,
                    "updated_at": now,
                    "has_preview": False,
                    "preview_updated_at": None,
                    "reference_filename": "reference.wav",
                    "prompt_filename": "prompt.pt",
                    "consent": True,
                    "consent_at": now,
                }
            else:
                meta = existing_meta or {}
                meta.update(
                    {
                        "name": name or meta.get("name"),
                        "language": language_value,
                        "transcript": ref_text or None,
                        "description": (
                            (description or "").strip() or None
                            if description is not None
                            else meta.get("description")
                        ),
                        "tags": tags if tags is not None else (meta.get("tags") or []),
                        "duration_seconds": round(duration, 3),
                        "updated_at": now,
                        "has_preview": False,
                        "preview_updated_at": None,
                        "consent": True,
                        "consent_at": meta.get("consent_at") or now,
                    }
                )
                self.voices.preview_path(voice_id).unlink(missing_ok=True)

            await _report(reporter, 92.0, "Saving", "Saving voice metadata.")
            self.voices.save_meta(voice_id, meta)
            self.manager.invalidate_voice(voice_id)
            await _report(reporter, 100.0, "Complete", "Voice profile ready.")
            return meta
        except Exception:
            if created and voice_id is not None:
                self.voices.delete(voice_id)
            raise
        finally:
            if temp_wav is not None:
                temp_wav.unlink(missing_ok=True)
            if temp_prompt is not None:
                temp_prompt.unlink(missing_ok=True)

    # ── Preview / transcribe ───────────────────────────────────────────────

    async def generate_preview(
        self,
        *,
        voice_id: str,
        text: str | None = None,
        reporter: Reporter | None = None,
        checker: Checker | None = None,
    ) -> dict[str, Any]:
        await self._wait_ready(reporter, checker)
        await _check(checker)
        try:
            meta = self.voices.get_meta(voice_id)
        except KeyError as exc:
            raise VoiceNotFoundError("Voice not found") from exc
        prompt_path = self.voices.prompt_path(voice_id)
        if not prompt_path.is_file():
            raise VoiceConflictError("This voice has no trained prompt. Retrain it first.")
        try:
            prompt = await asyncio.to_thread(self.manager.load_prompt, voice_id, prompt_path)
        except ModelNotReadyError as exc:
            raise OmniVoiceUnavailableError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise VoiceValidationError(f"Could not load the voice profile: {exc}") from exc

        profile_language = meta.get("language")
        preview_text = (
            text
            or preview_text_for_language(profile_language, self.settings.preview_text)
        ).strip()
        if not preview_text:
            preview_text = self.settings.preview_text
        await _report(reporter, 15.0, "Generating", "Generating the voice preview.")
        try:
            audio_array, sample_rate, elapsed = await asyncio.to_thread(
                self.manager.generate,
                text=preview_text,
                language=normalize_model_language(profile_language),
                voice_clone_prompt=prompt,
                num_step=16,
            )
        except ModelNotReadyError as exc:
            raise OmniVoiceUnavailableError(str(exc)) from exc
        await _check(checker)

        preview_path = self.voices.preview_path(voice_id)
        temp_preview = preview_path.with_name("preview.new.wav")
        await _report(reporter, 75.0, "Saving", "Saving the preview.")
        try:
            await asyncio.to_thread(audio.write_wav, temp_preview, audio_array, sample_rate)
            await _check(checker)
            temp_preview.replace(preview_path)
        except Exception:
            temp_preview.unlink(missing_ok=True)
            raise
        meta["has_preview"] = True
        meta["preview_updated_at"] = utc_now()
        meta["updated_at"] = meta["preview_updated_at"]
        self.voices.save_meta(voice_id, meta)

        duration = len(audio_array) / sample_rate if sample_rate else 0.0
        await _report(reporter, 100.0, "Complete", "Preview ready.")
        return {
            "voice_id": voice_id,
            "voice_name": meta.get("name"),
            "text": preview_text,
            "duration_seconds": round(duration, 3),
            "generation_seconds": round(elapsed, 3),
            "format": "wav",
            "path": relative_path(self.voices.preview_path(voice_id)),
            "preview_updated_at": meta["preview_updated_at"],
        }

    async def transcribe_audio(
        self,
        audio_path: Path,
        *,
        reporter: Reporter | None = None,
        checker: Checker | None = None,
    ) -> dict[str, Any]:
        if not audio_path.is_file():
            raise VoiceValidationError("Uploaded audio file was not found")
        await _report(reporter, 5.0, "Loading ASR", "Loading the Whisper ASR model.")
        await self._wait_ready(reporter, checker)
        await _check(checker)
        try:
            text = await asyncio.to_thread(self.manager.transcribe, str(audio_path))
        except ModelNotReadyError as exc:
            raise OmniVoiceUnavailableError(str(exc)) from exc
        await _check(checker)
        await _report(reporter, 100.0, "Complete", "Transcription complete.")
        return {"text": text, "filename": audio_path.name, "path": str(audio_path)}

    # ── Batch ──────────────────────────────────────────────────────────────

    async def synthesize_batch(
        self,
        req: BatchTTSRequest,
        *,
        reporter: Reporter | None = None,
        checker: Checker | None = None,
    ) -> list[dict[str, Any]]:
        items = list(req.items or [])
        if not items:
            raise VoiceValidationError("At least one batch item is required")
        if len(items) > self.settings.max_batch_items:
            raise VoiceValidationError(
                f"Batch supports at most {self.settings.max_batch_items} items."
            )
        results: list[dict[str, Any]] = []
        total = len(items)
        for index, text in enumerate(items):
            await _check(checker)
            item_req = req.to_tts_request(text)
            self.validate_request(item_req)

            async def item_report(
                value: float,
                stage: str,
                message: str | None = None,
                *,
                index: int = index,
            ) -> None:
                overall = ((index + (value / 100.0)) / total) * 100.0
                await _report(reporter, overall, stage, f"Item {index + 1}/{total}: {message or stage}")

            result = await self.synthesize(item_req, reporter=item_report, checker=checker)
            results.append(result)
        await _report(reporter, 100.0, "Complete", "Batch complete.")
        return results
