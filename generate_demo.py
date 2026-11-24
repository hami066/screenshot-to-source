"""Generate synthetic examples that can be shared publicly."""

import random
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

DEMO = Path(__file__).parent / "demo"
WIDTH, HEIGHT = 780, 960


def font(size):
    for family in ("C:/Windows/Fonts/arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(family, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def export(version, title, subtitle, background, accent, seed):
    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">']

    def rect(x, y, width, height, color):
        draw.rectangle((x, y, x + width - 1, y + height - 1), fill=color)
        svg.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{color}"/>')

    def line(points, color, weight):
        draw.line(points, fill=color, width=weight)
        route = " ".join(f"{x},{y}" for x, y in points)
        svg.append(f'<polyline points="{route}" stroke="{color}" stroke-width="{weight}" fill="none"/>')

    def label(x, y, value, size, color):
        draw.text((x, y), value, anchor="ls", font=font(size), fill=color)
        svg.append(
            f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-weight="bold" '
            f'font-size="{size}" fill="{color}">{escape(value)}</text>'
        )

    rect(0, 0, WIDTH, HEIGHT, background)
    label(48, 72, "FIELD NOTES  /  " + version, 24, "#f5eee6")
    label(48, 183, title, 80, "#f5eee6")
    label(52, 230, subtitle, 22, accent)
    rect(48, 271, 684, 500, accent)
    rect(65, 288, 650, 466, "#18212b")
    rng = random.Random(seed)
    for row in range(8):
        for col in range(12):
            x, y = 92 + col * 50 + rng.randrange(12), 316 + row * 47 + rng.randrange(15)
            w, h = rng.randrange(12, 43), rng.randrange(14, 39)
            color = (accent, "#f5eee6", "#aec1ca", "#627789")[rng.randrange(4)]
            if rng.random() < 0.7:
                line([(x, y + h), (x + rng.randrange(w), y), (x + w, y + rng.randrange(h))], color, rng.randrange(3, 8))
            else:
                rect(x, y, w, h, color)
    label(48, 835, "SAMPLE RELEASE", 26, accent)
    label(48, 895, "INDEPENDENT DESIGN STUDY", 30, "#f5eee6")
    label(670, 895, f"0{seed}", 25, accent)
    svg.append("</svg>")
    (DEMO / f"可编辑原稿 {version}.svg").write_text("\n".join(svg), encoding="utf-8")
    image.save(DEMO / f"导出图 {version}.png")
    return image


def main():
    DEMO.mkdir(exist_ok=True)
    export("A", "Moon Trail", "A quiet place after dark", "#17213a", "#acbdf5", 1)
    target = export("B", "After Rain", "Things we notice outdoors", "#203633", "#d4ea94", 2)
    export("C", "Heat Wave", "A warm day in the city", "#482527", "#ffab89", 3)
    crop = target.crop((111, 134, 682, 720)).resize((438, 449), Image.Resampling.LANCZOS)
    screen = Image.new("RGB", (544, 575), "#f1f2f3")
    screen.paste(crop, (54, 67))
    draw = ImageDraw.Draw(screen)
    draw.text((18, 15), "Client feedback", font=font(23), fill="#253142")
    draw.ellipse((58, 71, 467, 147), outline="#ed3434", width=5)
    draw.text((54, 537), "Please update this title.", font=font(19), fill="#253142")
    screen.save(DEMO / "客户截图.jpg", quality=65)


if __name__ == "__main__":
    main()
