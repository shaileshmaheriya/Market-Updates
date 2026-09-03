"""
Generates a simple branded image card (headline + verdict badge) for each
Instagram post, then uploads it to imgbb (free image host) so it has a public
URL — which is what Instagram's API requires for the `image_url` field.

Swap `upload_to_imgbb` for S3 / Cloudinary / your own storage later if you want
more control over branding or don't want a third-party image host.
"""
import io
import os
import textwrap
import requests
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1080  # Instagram square

VERDICT_COLORS = {
    "BULLISH": (34, 139, 87),
    "BEARISH": (178, 34, 34),
    "NEUTRAL": (184, 134, 11),
    "UNCLEAR": (90, 90, 90),
}

BG_COLOR = (18, 18, 20)
TEXT_COLOR = (245, 245, 245)


def _font(size, bold=False):
    # DejaVuSans ships with Pillow's default font set on most systems.
    try:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold \
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def build_image(headline: str, verdict: str) -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Verdict badge
    color = VERDICT_COLORS.get(verdict.upper(), VERDICT_COLORS["UNCLEAR"])
    badge_font = _font(42, bold=True)
    badge_text = verdict.upper()
    bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 24
    badge_x, badge_y = 80, 80
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + bw + pad * 2, badge_y + bh + pad * 2],
        radius=16, fill=color,
    )
    draw.text((badge_x + pad, badge_y + pad - 6), badge_text, font=badge_font, fill=(255, 255, 255))

    # Headline, word-wrapped
    headline_font = _font(64, bold=True)
    wrapped = textwrap.fill(headline, width=20)
    draw.multiline_text((80, 320), wrapped, font=headline_font, fill=TEXT_COLOR, spacing=14)

    # Footer label
    footer_font = _font(30)
    draw.text((80, HEIGHT - 120), "Market News Intelligence", font=footer_font, fill=(150, 150, 150))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def upload_to_imgbb(image_bytes: bytes) -> str:
    api_key = os.environ["IMGBB_API_KEY"]
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        params={"key": api_key},
        files={"image": ("card.png", image_bytes)},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"imgbb upload failed: {data}")
    return data["data"]["url"]


def make_public_image_url(headline: str, verdict: str) -> str:
    image_bytes = build_image(headline, verdict)
    return upload_to_imgbb(image_bytes)
