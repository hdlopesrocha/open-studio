"""Visual style presets used by the planner, image generator and UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StylePreset:
    id: str
    name: str
    description: str
    palette: tuple[str, ...]
    lighting: str
    art_direction: str
    prompt_suffix: str
    negative_prompt: str
    default_effects: tuple[str, ...] = ()
    preferred_transitions: tuple[str, ...] = ("crossfade", "dissolve")


STYLE_PRESETS: dict[str, StylePreset] = {
    "cinematic": StylePreset(
        id="cinematic",
        name="Cinematic",
        description="Widescreen film looks with teal shadows, warm highlights and volumetric light.",
        palette=("#08111F", "#16324F", "#3A6B7E", "#E9A268", "#F2D6B3"),
        lighting="golden-hour rim light with deep cinematic shadows",
        art_direction="35mm anamorphic film still, volumetric haze, rich contrast",
        prompt_suffix=(
            "cinematic film still, anamorphic lens, volumetric light, dramatic composition, "
            "rich colour grade, atmospheric depth, ultra detailed"
        ),
        negative_prompt="text, watermark, logo, deformed hands, extra limbs, low quality, blurry",
        default_effects=("vignette", "subtle_film_grain"),
        preferred_transitions=("crossfade", "fade_to_black", "dissolve"),
    ),
    "anime": StylePreset(
        id="anime",
        name="Anime",
        description="Hand-painted anime backgrounds with candy-coloured skies and clean silhouettes.",
        palette=("#10152B", "#354C7C", "#F27EA9", "#FFC857", "#9BE7FF"),
        lighting="soft pastel rim light and glowing skies",
        art_direction="lush anime background art, painterly clouds, crisp line work",
        prompt_suffix=(
            "beautiful anime background art, painterly clouds, cinematic composition, "
            "soft light, vivid but harmonious colours, highly detailed illustration"
        ),
        negative_prompt="text, watermark, photorealistic, low quality, blurry, deformed",
        default_effects=("bloom", "vignette"),
        preferred_transitions=("crossfade", "circle", "dissolve"),
    ),
    "noir": StylePreset(
        id="noir",
        name="Film Noir",
        description="Monochrome contrast, hard shadows and smoky night streets.",
        palette=("#050506", "#141517", "#3C3E42", "#9A9DA1", "#EDE9E1"),
        lighting="hard single-source light, smoky chiaroscuro",
        art_direction="classic film noir, high contrast black and white, rain-slicked streets",
        prompt_suffix=(
            "classic film noir still, high contrast monochrome, hard shadows, "
            "smoke and rain, dramatic chiaroscuro, 1950s cinema"
        ),
        negative_prompt="text, watermark, colour, low quality, blurry, deformed hands",
        default_effects=("vignette", "film_grain", "light_leak"),
        preferred_transitions=("fade_to_black", "dissolve", "crossfade"),
    ),
    "watercolor": StylePreset(
        id="watercolor",
        name="Watercolor",
        description="Dreamlike washes of pigment, soft edges and warm paper texture.",
        palette=("#F4EBDD", "#D8C3A5", "#A7BEAE", "#E3B7A0", "#5C6F68"),
        lighting="soft diffused daylight with gentle blooms of colour",
        art_direction="expressive watercolour painting, visible paper grain, loose brushwork",
        prompt_suffix=(
            "delicate watercolour painting, loose expressive brushwork, soft pigment blooms, "
            "visible paper texture, dreamlike atmosphere"
        ),
        negative_prompt="text, watermark, harsh contrast, photographic, low quality, blurry",
        default_effects=("soft_focus", "subtle_film_grain", "vignette"),
        preferred_transitions=("dissolve", "crossfade"),
    ),
    "synthwave": StylePreset(
        id="synthwave",
        name="Synthwave",
        description="Neon dusk, chrome horizons and retro-futurist night drives.",
        palette=("#080214", "#271344", "#FF2A6D", "#05D9E8", "#F9F871"),
        lighting="neon magenta and cyan glow against deep violet night",
        art_direction="1980s retro-futurism, neon grid, chrome reflections, laser haze",
        prompt_suffix=(
            "retro-futuristic synthwave artwork, neon magenta and cyan light, "
            "chrome reflections, night atmosphere, cinematic composition"
        ),
        negative_prompt="text, watermark, daylight, muted colours, low quality, blurry",
        default_effects=("bloom", "chromatic_aberration", "vignette"),
        preferred_transitions=("slide_left", "crossfade", "cut"),
    ),
    "documentary": StylePreset(
        id="documentary",
        name="Documentary",
        description="Naturalistic, observational imagery with honest textures and muted tones.",
        palette=("#171A17", "#3B4A3D", "#7D8A75", "#C6B89B", "#EDE7DB"),
        lighting="available natural light, overcast softness, honest shadows",
        art_direction="observational documentary photography, natural grain, unposed framing",
        prompt_suffix=(
            "observational documentary photograph, natural light, honest textures, "
            "35mm grain, understated composition, authentic atmosphere"
        ),
        negative_prompt="text, watermark, fantasy, neon, low quality, blurry, deformed",
        default_effects=("subtle_film_grain", "vignette"),
        preferred_transitions=("cut", "crossfade", "dissolve"),
    ),
    "custom": StylePreset(
        id="custom",
        name="Custom",
        description="Start from a neutral cinematic base and provide your own visual style prompt.",
        palette=("#0B1020", "#243B53", "#6B8F9E", "#E0A96D", "#F4E3C8"),
        lighting="cinematic natural light",
        art_direction="cinematic concept art",
        prompt_suffix="cinematic concept art, atmospheric, highly detailed",
        negative_prompt="text, watermark, logo, low quality, blurry, deformed",
        default_effects=("vignette",),
        preferred_transitions=("crossfade",),
    ),
}


def get_style(style_id: str) -> StylePreset:
    return STYLE_PRESETS.get(style_id, STYLE_PRESETS["cinematic"])


def style_catalogue() -> list[dict]:
    return [
        {
            "id": style.id,
            "name": style.name,
            "description": style.description,
            "palette": list(style.palette),
            "lighting": style.lighting,
            "prompt_suffix": style.prompt_suffix,
        }
        for style in STYLE_PRESETS.values()
    ]
