from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICON_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
COLORS = {
    "B": "#274c77",
    "H": "#6096ba",
    "V": "#a3cef1",
    "R": "#8b1e3f",
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    png_path = root / "bikeheadvr.png"
    ico_path = root / "bikeheadvr.ico"

    base = render_icon(256)
    base.save(png_path)
    base.save(ico_path, sizes=ICON_SIZES)
    return 0


def render_icon(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    half = size // 2
    quadrants = [
        (0, 0, "B"),
        (half, 0, "H"),
        (0, half, "V"),
        (half, half, "R"),
    ]

    for x, y, label in quadrants:
        draw.rectangle((x, y, x + half, y + half), fill=COLORS[label])
        _draw_centered_label(draw, label, x, y, half, size)

    border = max(2, size // 48)
    draw.rectangle((0, 0, size - 1, size - 1), outline="#0d1b2a", width=border)
    return image


def _draw_centered_label(
    draw: ImageDraw.ImageDraw,
    label: str,
    x: int,
    y: int,
    quadrant_size: int,
    icon_size: int,
) -> None:
    font_size = max(10, icon_size // 4)
    try:
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    text_x = x + (quadrant_size - text_width) / 2
    text_y = y + (quadrant_size - text_height) / 2 - icon_size * 0.02

    shadow_offset = max(1, icon_size // 96)
    draw.text(
        (text_x + shadow_offset, text_y + shadow_offset),
        label,
        font=font,
        fill="#0d1b2a",
    )
    draw.text((text_x, text_y), label, font=font, fill="white")


if __name__ == "__main__":
    raise SystemExit(main())
