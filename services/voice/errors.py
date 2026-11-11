"""Typed errors shared by the voice engines and API routes."""

from __future__ import annotations

from typing import Any


class VoiceError(RuntimeError):
    """Base class for user-facing voice service failures."""

    status_code = 500
    code = "voice_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def as_detail(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"detail": self.message, "code": self.code}
        if self.details:
            payload["details"] = self.details
        return payload


class VoiceValidationError(VoiceError):
    status_code = 422
    code = "voice_invalid_request"


class VoiceNotFoundError(VoiceError):
    status_code = 404
    code = "voice_not_found"


class VoiceConflictError(VoiceError):
    status_code = 409
    code = "voice_conflict"


class VoiceUnavailableError(VoiceError):
    status_code = 503
    code = "voice_engine_unavailable"


class PiperVoiceMissingError(VoiceUnavailableError):
    code = "piper_voice_missing"


class PiperUnavailableError(VoiceUnavailableError):
    code = "piper_unavailable"


class OmniVoiceUnavailableError(VoiceUnavailableError):
    code = "omnivoice_unavailable"
