from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from .config import OverlayTextureConfig


@dataclass(frozen=True)
class OverlayTexture:
    width_px: int
    height_px: int
    rgba_bytes: bytes


def build_phase1_texture(config: OverlayTextureConfig) -> OverlayTexture:
    image = Image.new("RGBA", (config.width_px, config.height_px), (14, 22, 29, 235))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    outer = 20
    inner = 48
    draw.rounded_rectangle(
        (outer, outer, config.width_px - outer, config.height_px - outer),
        radius=36,
        fill=(18, 31, 41, 245),
        outline=(108, 196, 255, 255),
        width=6,
    )
    draw.rounded_rectangle(
        (inner, inner, config.width_px - inner, config.height_px - inner),
        radius=28,
        outline=(69, 106, 128, 255),
        width=2,
    )

    accent_y = config.height_px // 2 + 28
    draw.line(
        (inner + 24, accent_y, config.width_px - inner - 24, accent_y),
        fill=(108, 196, 255, 255),
        width=4,
    )

    lines = [
        "bikeheadvr",
        "Phase 1 overlay online",
        "Static SteamVR quad rendered via SetOverlayRaw",
    ]
    y = 120
    for text in lines:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        draw.text(
            ((config.width_px - text_width) / 2, y),
            text,
            font=font,
            fill=(235, 244, 247, 255),
        )
        y += 44

    footer = "Ctrl+C in the terminal to destroy the overlay."
    footer_bbox = draw.textbbox((0, 0), footer, font=font)
    footer_width = footer_bbox[2] - footer_bbox[0]
    draw.text(
        ((config.width_px - footer_width) / 2, config.height_px - 88),
        footer,
        font=font,
        fill=(167, 187, 197, 255),
    )

    rgba_bytes = image.tobytes("raw", "RGBA")
    return OverlayTexture(
        width_px=config.width_px,
        height_px=config.height_px,
        rgba_bytes=rgba_bytes,
    )
