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
    button: ButtonConfig,
    variant: TextureVariant,
    title_text: str | None = None,
    subtitle_text: str | None = None,
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

    title = title_text if title_text is not None else button.label.upper()
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

    subtitle = subtitle_text
    if subtitle is None:
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


def build_skate_foot_texture(
    width_px: int,
    height_px: int,
    side: str,
    grounded: bool,
    contact_load: float = 1.0,
) -> OverlayTexture:
    image = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    if grounded and contact_load >= 0.6:
        fill = (20, 112, 63, 122)
        outline = (87, 255, 151, 245)
        axis = (235, 255, 242, 255)
    elif grounded:
        fill = (113, 81, 20, 116)
        outline = (255, 205, 87, 235)
        axis = (255, 244, 211, 245)
    else:
        fill = (36, 61, 96, 96)
        outline = (111, 180, 255, 220)
        axis = (214, 232, 255, 235)

    pad_x = 18
    pad_y = 28
    body = (pad_x, pad_y, width_px - pad_x, height_px - pad_y)
    draw.rounded_rectangle(body, radius=22, fill=fill, outline=outline, width=8)

    center_y = height_px // 2
    draw.line((42, center_y, width_px - 42, center_y), fill=axis, width=7)
    draw.polygon(
        (
            (width_px - 38, center_y),
            (width_px - 76, center_y - 20),
            (width_px - 76, center_y + 20),
        ),
        fill=axis,
    )

    for x in (width_px * 0.28, width_px * 0.72):
        draw.line((x, pad_y + 12, x, height_px - pad_y - 12), fill=outline, width=4)

    label = side[:1].upper()
    draw.text(
        (24, 16),
        label,
        font=font,
        fill=axis,
    )
    state = (
        f"{int(round(max(0.0, min(1.0, contact_load)) * 100)):02d}" if grounded else "A"
    )
    state_bbox = draw.textbbox((0, 0), state, font=font)
    draw.text(
        (width_px - (state_bbox[2] - state_bbox[0]) - 24, 16),
        state,
        font=font,
        fill=axis,
    )

    return OverlayTexture(
        width_px=width_px,
        height_px=height_px,
        rgba_bytes=image.tobytes("raw", "RGBA"),
    )


def build_debug_marker_texture(
    width_px: int,
    height_px: int,
    color: tuple[int, int, int, int],
) -> OverlayTexture:
    image = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pad = max(6, min(width_px, height_px) // 8)
    bounds = (pad, pad, width_px - pad, height_px - pad)
    fill = (color[0], color[1], color[2], max(48, color[3] // 3))
    draw.ellipse(bounds, fill=fill, outline=color, width=max(3, pad // 2))
    cx = width_px // 2
    cy = height_px // 2
    draw.line((cx, pad * 2, cx, height_px - pad * 2), fill=color, width=3)
    draw.line((pad * 2, cy, width_px - pad * 2, cy), fill=color, width=3)
    return OverlayTexture(width_px, height_px, image.tobytes("raw", "RGBA"))


def build_debug_arrow_texture(
    width_px: int,
    height_px: int,
    color: tuple[int, int, int, int],
    *,
    arrow_head: bool = True,
) -> OverlayTexture:
    image = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    center_y = height_px // 2
    start_x = max(8, width_px // 12)
    end_x = width_px - start_x
    line_width = max(4, height_px // 7)
    draw.line((start_x, center_y, end_x, center_y), fill=color, width=line_width)
    if arrow_head:
        head = max(12, height_px // 3)
        draw.polygon(
            (
                (end_x, center_y),
                (end_x - head, center_y - head // 2),
                (end_x - head, center_y + head // 2),
            ),
            fill=color,
        )
    return OverlayTexture(width_px, height_px, image.tobytes("raw", "RGBA"))


def build_debug_torque_texture(
    width_px: int,
    height_px: int,
    color: tuple[int, int, int, int],
    clockwise: bool,
) -> OverlayTexture:
    image = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pad = max(10, min(width_px, height_px) // 8)
    bounds = (pad, pad, width_px - pad, height_px - pad)
    width = max(5, min(width_px, height_px) // 10)
    if clockwise:
        start, end = 35, 305
        head = (
            (width_px - pad, height_px // 2),
            (width_px - pad - 20, height_px // 2 - 18),
            (width_px - pad - 5, height_px // 2 + 22),
        )
    else:
        start, end = 215, -55
        head = (
            (pad, height_px // 2),
            (pad + 20, height_px // 2 - 18),
            (pad + 5, height_px // 2 + 22),
        )
    draw.arc(bounds, start=start, end=end, fill=color, width=width)
    draw.polygon(head, fill=color)
    return OverlayTexture(width_px, height_px, image.tobytes("raw", "RGBA"))


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
