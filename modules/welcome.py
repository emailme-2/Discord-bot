from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CANVAS = ROOT / 'assets' / 'welcome_canvas.png'
DEFAULT_FONT = None


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        if DEFAULT_FONT and DEFAULT_FONT.exists():
            return ImageFont.truetype(str(DEFAULT_FONT), size)
    except Exception:
        pass

    try:
        return ImageFont.truetype('arial.ttf', size)
    except Exception:
        try:
            return ImageFont.truetype('DejaVuSans-Bold.ttf', size)
        except Exception:
            return ImageFont.load_default()


def _get_text_width(text: str, font: ImageFont.ImageFont) -> int:
    try:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]
    except AttributeError:
        dummy_image = Image.new('RGB', (1, 1))
        draw = ImageDraw.Draw(dummy_image)
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    words = text.split(' ')
    lines = []
    current = ''

    for word in words:
        test = f'{current} {word}'.strip()
        if _get_text_width(test, font) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    return '\n'.join(lines)


def generate_welcome_image(username: str, created_at, member_count: int, canvas_path: Optional[str] = None) -> BytesIO:
    width, height = 1200, 625
    canvas = None

    if canvas_path:
        path = Path(canvas_path)
        if not path.is_absolute():
            path = ROOT / canvas_path
        if path.exists():
            canvas = Image.open(path).convert('RGBA')

    if canvas is None and DEFAULT_CANVAS.exists():
        canvas = Image.open(DEFAULT_CANVAS).convert('RGBA')

    if canvas is None:
        canvas = Image.new('RGBA', (width, height), (12, 17, 42, 255))
    else:
        canvas = canvas.resize((width, height), Image.LANCZOS)

    overlay = Image.new('RGBA', canvas.size, (0, 0, 0, 140))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    title_font = _load_font(72)
    name_font = _load_font(84)
    info_font = _load_font(44)
    small_font = _load_font(32)

    border_margin = 40
    draw.rectangle(
        [border_margin, border_margin, width - border_margin, height - border_margin],
        outline=(255, 215, 0, 180),
        width=6,
    )

    branding_text = 'Welcome to RF'
    draw.text((80, 70), branding_text, font=info_font, fill=(255, 239, 146, 255))

    member_text = f'Member #{member_count}'
    try:
        member_bbox = draw.textbbox((0, 0), member_text, font=small_font)
        member_width = member_bbox[2] - member_bbox[0]
    except AttributeError:
        member_width = _get_text_width(member_text, small_font)
    draw.text((width - member_width - 80, 70), member_text, font=small_font, fill=(255, 255, 255, 255))

    full_name = username
    draw.text((80, 420), full_name, font=name_font, fill=(255, 255, 255, 255))

    created_text = f'Account created {created_at.strftime("%b %d, %Y")}'
    draw.text((80, 520), created_text, font=info_font, fill=(220, 220, 220, 255))

    buffer = BytesIO()
    canvas.convert('RGB').save(buffer, format='PNG')
    buffer.seek(0)
    return buffer
