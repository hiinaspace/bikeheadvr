from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from .config import ButtonConfig


@dataclass(frozen=True)
class OverlayTexture:
    width_px: int
    height_px: int
    rgba_bytes: bytes


def build_button_texture(button: ButtonConfig, hovered: bool) -> OverlayTexture:
    image = Image.new("RGBA", (button.texture.width_px, button.texture.height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    frame = 18
    accent = (255, 194, 87, 255) if hovered else (96, 189, 255, 255)
    fill = (66, 49, 20, 230) if hovered else (17, 28, 37, 220)
    text = (255, 243, 218, 255) if hovered else (238, 245, 248, 255)

    bounds = (frame, frame, button.texture.width_px - frame, button.texture.height_px - frame)
    if button.shape == "circle":
        draw.ellipse(bounds, fill=fill, outline=accent, width=8)
        inner = 64
        draw.ellipse(
            (inner, inner, button.texture.width_px - inner, button.texture.height_px - inner),
            outline=(255, 255, 255, 72),
            width=2,
        )
    else:
        draw.rounded_rectangle(bounds, radius=42, fill=fill, outline=accent, width=8)
        inset = 46
        draw.rounded_rectangle(
            (inset, inset, button.texture.width_px - inset, button.texture.height_px - inset),
            radius=28,
            outline=(255, 255, 255, 64),
            width=2,
        )

    title = button.label.upper()
    title_bbox = draw.textbbox((0, 0), title, font=font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(
        ((button.texture.width_px - title_width) / 2, button.texture.height_px / 2 - 16),
        title,
        font=font,
        fill=text,
    )

    subtitle = "HOVER" if hovered else "LOOK HERE"
    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=font)
    subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
    draw.text(
        ((button.texture.width_px - subtitle_width) / 2, button.texture.height_px / 2 + 20),
        subtitle,
        font=font,
        fill=accent,
    )

    return OverlayTexture(
        width_px=button.texture.width_px,
        height_px=button.texture.height_px,
        rgba_bytes=image.tobytes("raw", "RGBA"),
    )
