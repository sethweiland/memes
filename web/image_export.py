"""
Image export utilities — resize memes for Instagram and other formats.
"""

from io import BytesIO

from PIL import Image, ImageFilter


INSTAGRAM_WIDTH = 1080
INSTAGRAM_HEIGHT = 1350


def resize_for_instagram(input_path: str) -> BytesIO:
    """Resize an image to Instagram portrait format (1080x1350) with blurred background fill.

    The original image is scaled to fit within the target dimensions while
    maintaining its aspect ratio. A heavily blurred, zoomed-in version of the
    image is used as the background to fill any remaining space.

    Returns a BytesIO buffer containing the JPEG result.
    """
    with Image.open(input_path) as img:
        img = img.convert("RGB")

        target_w, target_h = INSTAGRAM_WIDTH, INSTAGRAM_HEIGHT

        # --- Blurred background: resize to cover the target area ---
        img_w, img_h = img.size
        scale_cover = max(target_w / img_w, target_h / img_h)
        cover_w = int(img_w * scale_cover)
        cover_h = int(img_h * scale_cover)
        bg = img.resize((cover_w, cover_h), Image.LANCZOS)

        # Center-crop to exact target size
        left = (cover_w - target_w) // 2
        top = (cover_h - target_h) // 2
        bg = bg.crop((left, top, left + target_w, top + target_h))

        # Apply strong blur
        bg = bg.filter(ImageFilter.GaussianBlur(radius=30))

        # --- Foreground: resize to fit within target area ---
        scale_fit = min(target_w / img_w, target_h / img_h)
        fit_w = int(img_w * scale_fit)
        fit_h = int(img_h * scale_fit)
        fg = img.resize((fit_w, fit_h), Image.LANCZOS)

        # Paste centered on blurred background
        paste_x = (target_w - fit_w) // 2
        paste_y = (target_h - fit_h) // 2
        bg.paste(fg, (paste_x, paste_y))

        # Write to buffer
        buf = BytesIO()
        bg.save(buf, format="JPEG", quality=95)
        buf.seek(0)
        return buf
