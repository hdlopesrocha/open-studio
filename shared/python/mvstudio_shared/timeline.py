"""Shared timeline transition rules used by animation scheduling and rendering."""

from __future__ import annotations

XFADE_TRANSITIONS = {
    "crossfade": "fade",
    "dissolve": "dissolve",
    "fade_to_black": "fadeblack",
    "fade_to_white": "fadewhite",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "slide_up": "slideup",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
    "circle": "circleopen",
    "cut": "fade",
}


def effective_transition_duration(current, following) -> float:
    """Duration actually used by the renderer for a transition between scenes.

    ``cut`` uses a four-frame-ish dissolve to keep the FFmpeg xfade graph simple;
    all other transitions are clamped so both adjacent scenes remain readable.
    """
    if current.transition.type == "cut":
        return 0.04
    return max(
        0.04,
        min(
            current.transition.duration,
            1.5,
            current.duration * 0.4,
            following.duration * 0.4,
        ),
    )
