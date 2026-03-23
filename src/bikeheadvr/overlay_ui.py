from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from .config import ButtonConfig, RenderConfig
from .interaction import ButtonVisualState


@dataclass(frozen=True)
class OverlayTexture:
    width_px: int
    height_px: int
    rgba_bytes: bytes


@dataclass(frozen=True)
class TextureVariant:
    hovered: bool
    armed: bool
    committed: bool
    dwell_bucket: int
    dwell_steps: int
    cooldown_bucket: int
    cooldown_steps: int


def quantize_visual(visual: ButtonVisualState, render: RenderConfig) -> TextureVariant:
    return TextureVariant(
        hovered=visual.hovered,
        armed=visual.armed,
        committed=visual.committed,
        dwell_bucket=_bucketize(visual.dwell_progress, render.dwell_steps),
        dwell_steps=render.dwell_steps,
        cooldown_bucket=_bucketize(visual.cooldown_progress, render.cooldown_steps),
        cooldown_steps=render.cooldown_steps,
    )


def build_button_texture(
    button: ButtonConfig, variant: TextureVariant
) -> OverlayTexture:
    image = Image.new(
        "RGBA", (button.texture.width_px, button.texture.height_px), (0, 0, 0, 0)
    )
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    frame = 18
    hovered = variant.hovered
    accent = (255, 194, 87, 255) if hovered else (96, 189, 255, 255)
    if variant.committed:
        accent = (122, 255, 163, 255)
    fill = (66, 49, 20, 230) if hovered else (17, 28, 37, 220)
    if variant.committed:
        fill = (19, 61, 35, 235)
    text = (255, 243, 218, 255) if hovered else (238, 245, 248, 255)

    bounds = (
        frame,
        frame,
        button.texture.width_px - frame,
        button.texture.height_px - frame,
    )
    if button.shape == "circle":
        draw.ellipse(bounds, fill=fill, outline=accent, width=8)
        inner = 64
        draw.ellipse(
            (
                inner,
                inner,
                button.texture.width_px - inner,
                button.texture.height_px - inner,
            ),
            outline=(255, 255, 255, 72),
            width=2,
        )
    else:
        draw.rounded_rectangle(bounds, radius=42, fill=fill, outline=accent, width=8)
        inset = 46
        draw.rounded_rectangle(
            (
                inset,
                inset,
                button.texture.width_px - inset,
                button.texture.height_px - inset,
            ),
            radius=28,
            outline=(255, 255, 255, 64),
            width=2,
        )

    _draw_progress(draw, button, variant, accent)

    title = button.label.upper()
    title_bbox = draw.textbbox((0, 0), title, font=font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(
        (
            (button.texture.width_px - title_width) / 2,
            button.texture.height_px / 2 - 16,
        ),
        title,
        font=font,
        fill=text,
    )

    subtitle = "LOOK HERE"
    if variant.committed:
        subtitle = "COMMITTED"
    elif variant.cooldown_bucket > 0:
        subtitle = "COOLDOWN"
    elif variant.armed:
        subtitle = "DWELLING"
    elif hovered:
        subtitle = "HOVER"
    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=font)
    subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
    draw.text(
        (
            (button.texture.width_px - subtitle_width) / 2,
            button.texture.height_px / 2 + 20,
        ),
        subtitle,
        font=font,
        fill=accent,
    )

    return OverlayTexture(
        width_px=button.texture.width_px,
        height_px=button.texture.height_px,
        rgba_bytes=image.tobytes("raw", "RGBA"),
    )


def _draw_progress(
    draw: ImageDraw.ImageDraw,
    button: ButtonConfig,
    variant: TextureVariant,
    accent: tuple[int, int, int, int],
) -> None:
    if not (variant.hovered or variant.cooldown_bucket > 0):
        return

    pad = 28
    ring_bounds = (
        pad,
        pad,
        button.texture.width_px - pad,
        button.texture.height_px - pad,
    )
    base_color = (255, 255, 255, 42)
    draw.arc(ring_bounds, start=0, end=359, fill=base_color, width=10)

    if variant.cooldown_bucket > 0:
        progress = variant.cooldown_bucket / variant.cooldown_steps
        end_angle = -90 + int((1.0 - progress) * 360)
        draw.arc(
            ring_bounds, start=-90, end=end_angle, fill=(181, 181, 181, 255), width=10
        )
        return

    if variant.armed or variant.committed:
        progress = variant.dwell_bucket / variant.dwell_steps
        end_angle = -90 + int(progress * 360)
        draw.arc(ring_bounds, start=-90, end=end_angle, fill=accent, width=10)


def _bucketize(progress: float, steps: int) -> int:
    if progress <= 0.0:
        return 0
    if progress >= 1.0:
        return steps
    return max(1, min(steps, int(round(progress * steps))))
