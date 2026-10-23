"""Static 720p source cards with measured typography and text contrast."""

from datetime import datetime, timezone
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from news_orchestrator import config, visuals

FONT_ROOT = Path("/usr/share/fonts/truetype/dejavu")
FONTS = {"sans": "DejaVuSans-Bold.ttf", "serif": "DejaVuSerif-Bold.ttf", "body": "DejaVuSans.ttf",
         "mono": "DejaVuSansMono.ttf"}
WIDTH, HEIGHT = 1280, 720


def rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def blend(a, b, fraction):
    return tuple(round(x * (1 - fraction) + y * fraction) for x, y in zip(a, b))


def luminance(color):
    values = [v / 255 for v in color]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(a, b):
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def minimum_contrast(color, backgrounds):
    return min(contrast(color, background) for background in backgrounds)


def readable(preferred, backgrounds):
    if minimum_contrast(preferred, backgrounds) >= 4.5:
        return preferred
    end = max(((255, 255, 255), (10, 17, 28)), key=lambda c: minimum_contrast(c, backgrounds))
    for step in range(1, 21):
        color = blend(preferred, end, step / 20)
        if minimum_contrast(color, backgrounds) >= 4.5:
            return color
    return end


def font(kind, size):
    return ImageFont.truetype(str(FONT_ROOT / FONTS[kind]), size)


def ellipsis(draw, value, face, width):
    value = " ".join(str(value).split())
    if draw.textlength(value, font=face) <= width:
        return value
    while value and draw.textlength(value + "…", font=face) > width:
        value = value[:-1]
    return value.rstrip() + "…"


def wrap(draw, text, face, width):
    lines, current = [], ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        if draw.textlength(candidate, font=face) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        for char in word:
            if current and draw.textlength(current + char, font=face) > width:
                lines.append(current)
                current = ""
            current += char
    if current:
        lines.append(current)
    return lines or ["Última información"]


def title_layout(draw, title, kind, box):
    x0, y0, x1, y1 = box
    for size in range(64, 29, -2):
        face = font(kind, size)
        lines = wrap(draw, title, face, x1 - x0)
        height = round(size * 1.26)
        if len(lines) * height <= y1 - y0:
            return face, lines, height, size, False
    count = max(1, (y1 - y0) // height)
    visible = lines[:count]
    visible[-1] = ellipsis(draw, visible[-1] + " …", face, x1 - x0)
    return face, visible, height, size, True


def render(directory, article, title, channel, selected):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    accent = rgb(selected["accent"])
    dark = selected["theme"] == "dark"
    base = blend((14, 21, 35) if dark else (250, 249, 246), accent, 0.20 if dark else 0.08)
    far = blend(base, accent, 0.23 if dark else 0.12)
    # All text is drawn directly over the gradient and decorative shapes.
    strip = Image.new("RGB", (WIDTH, 1))
    strip.putdata([blend(base, far, x / (WIDTH - 1)) for x in range(WIDTH)])
    image = strip.resize((WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    decorative = blend(far, accent, 0.25)
    if selected["decoration"] == 0:
        draw.ellipse((960, -240, 1500, 300), fill=decorative)
    elif selected["decoration"] == 1:
        draw.polygon([(850, 0), (1130, 0), (1280, 420), (1280, 680)], fill=decorative)
    else:
        for x in range(850, 1280, 58):
            draw.line((x, 0, x - 180, 720), fill=decorative, width=2)
    # Measure every background color before adding text, the logo and the top
    # accent border (which has no text). This also covers decorative overlaps.
    backgrounds = tuple(color for _, color in image.getcolors(WIDTH * HEIGHT))
    draw.rectangle((0, 0, WIDTH, 8), fill=accent)
    ink = readable((248, 250, 255) if dark else (20, 30, 43), backgrounds)
    accent_ink = readable(accent, backgrounds)
    secondary = readable(blend(ink, base, 0.28), backgrounds)
    draw.text((64, 48), ellipsis(draw, channel, font("sans", 21), 900), font=font("sans", 21), fill=ink, anchor="lt")
    draw.text((64, 80), "NOTICIAS · ACTUALIDAD", font=font("mono", 12), fill=secondary, anchor="lt")
    layout = selected["layout"]
    if layout == "sidebar":
        logo_box, title_box, label_at = (64, 190, 338, 436), (400, 197, 1208, 525), (400, 128)
    elif layout == "banner":
        logo_box, title_box, label_at = (64, 120, 302, 248), (64, 296, 1208, 545), (342, 158)
    else:
        logo_box, title_box, label_at = (970, 120, 1216, 258), (64, 278, 1208, 545), (64, 170)
    # Preserve the logo's original colors/aspect ratio on its separate plaque.
    x, y = label_at
    label_width = 790 if layout == "banner" else 780
    if layout == "sidebar":
        label_width = 808
    draw.text((x, y), "FUENTE", font=font("mono", 13), fill=secondary, anchor="lt")
    draw.text((x, y + 24), ellipsis(draw, selected["source_name"], font("sans", 25), label_width),
              font=font("sans", 25), fill=accent_ink, anchor="lt")
    draw.rounded_rectangle(logo_box, radius=18, fill=(255, 255, 255))
    used_logo = False
    if selected["logo"]:
        try:
            path = visuals.LOGOS / selected["logo"]["file"]
            if path.is_symlink() or visuals.digest(path) != selected["logo"]["sha256"]:
                raise ValueError("El logo local ha cambiado durante el montaje.")
            with Image.open(path) as source:
                if source.width > 4096 or source.height > 4096:
                    raise ValueError("Logo demasiado grande.")
                logo = source.convert("RGBA")
            available = (logo_box[2] - logo_box[0] - 72, logo_box[3] - logo_box[1] - 72)
            # Avoid making tiny favicons blurry by enlarging them excessively.
            scale = min(available[0] / logo.width, available[1] / logo.height, 2.0)
            size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
            logo = logo.resize(size, Image.Resampling.LANCZOS)
            at = ((logo_box[0] + logo_box[2] - size[0]) // 2, (logo_box[1] + logo_box[3] - size[1]) // 2)
            image.paste(logo, at, logo)
            used_logo = True
        except (OSError, ValueError):
            logging.exception("Logo unavailable; using the publisher name")
    if not used_logo:
        # A textual source label is a fallback, not a fabricated corporate logo.
        face = font("sans", 20)
        name = ellipsis(draw, selected["source_name"], face, logo_box[2] - logo_box[0] - 40)
        draw.text(((logo_box[0] + logo_box[2]) / 2, (logo_box[1] + logo_box[3]) / 2), name,
                  font=face, fill=(20, 30, 43), anchor="mm")
    face, lines, line_height, size, truncated = title_layout(draw, title, selected["title_font"], title_box)
    for index, line in enumerate(lines):
        draw.text((title_box[0], title_box[1] + index * line_height), line, font=face, fill=ink, anchor="lt")
    draw.line((64, 584, 1216, 584), fill=accent_ink, width=2)
    location = selected["domain"] or selected["source_name"]
    draw.text((64, 606), ellipsis(draw, location, font("body", 20), 1120), font=font("body", 20), fill=ink, anchor="lt")
    publication = ""
    if article.get("published_at"):
        date = datetime.fromisoformat(article["published_at"])
        date = date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date
        publication = date.astimezone(ZoneInfo(selected["timezone"])).strftime("%d/%m/%Y · %H:%M")
    provenance = selected["discovery"]
    if provenance and provenance != selected["source_name"] and not provenance.startswith(selected["source_name"] + ":"):
        provenance = "Encontrado en: " + provenance
    else:
        provenance = ""
    footer = "   ·   ".join(v for v in (publication, provenance) if v)
    draw.text((64, 652), ellipsis(draw, footer, font("mono", 15), 1120), font=font("mono", 15), fill=secondary, anchor="lt")
    temporary = directory / "poster.part.png"
    image.save(temporary, format="PNG")
    temporary.replace(directory / "poster.png")
    config.atomic_json(directory / "visual.json", {"plan": selected, "logo_used": used_logo,
                       "title_size": size, "title_lines": len(lines), "title_truncated": truncated,
                       "text_colors": {"title": ink, "source": accent_ink, "secondary": secondary},
                       "contrast": {"title": round(minimum_contrast(ink, backgrounds), 2),
                                    "source": round(minimum_contrast(accent_ink, backgrounds), 2),
                                    "secondary": round(minimum_contrast(secondary, backgrounds), 2)}, "background": base})
    return directory / "poster.png"
