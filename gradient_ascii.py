"""The header's blue ASCII field and its moving highlight."""

from functools import lru_cache

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont


CHARACTERS = " =+xX0H8#@"
COLORS = tuple(ImageColor.getrgb(color) for color in ("#1e3fd8", "#f6f8ff", "#a5d8ff", "#38bdf8"))


@lru_cache(maxsize=8)
def glyph_masks(height):
    size = max(1, round(height * .93))
    width = max(1, round(height * .64))
    for family in ("consola.ttf", "Menlo.ttc", "DejaVuSansMono.ttf"):
        try:
            font = ImageFont.truetype(family, size)
            break
        except OSError:
            continue
    else:
        font = ImageFont.load_default()

    masks = []
    for character in CHARACTERS:
        mask = Image.new("L", (width, height))
        ImageDraw.Draw(mask).text((width / 2, height / 2), character, font=font, fill=255, anchor="mm")
        masks.append(mask)
    return tuple(masks)


def paint_glyphs(size, height, indices, colors, opacity):
    image = Image.new("RGB", size)
    alpha_mask = Image.new("L", size)
    masks = glyph_masks(height)
    cell_width = masks[0].width
    for row, column in zip(*np.nonzero((indices > 0) & (opacity >= 1))):
        rgb = tuple(int(channel) for channel in colors[row, column])
        alpha = int(opacity[row, column])
        left, top = int(column) * cell_width, int(row) * height
        image.paste(rgb, (left, top, left + cell_width, top + height))
        alpha_mask.paste(masks[indices[row, column]].point(lambda value: value * alpha // 255), (left, top))
    image.putalpha(alpha_mask)
    return image


def ascii_field(width, height, cell, toolbar, dark):
    columns = (width + glyph_masks(cell)[0].width - 1) // glyph_masks(cell)[0].width
    rows = (height + cell - 1) // cell
    x = np.linspace(-1, 1, columns)[None, :]
    y = ((np.arange(rows) + .5) * cell / height)[:, None]
    random = np.random.default_rng(31).random((rows, columns))
    curve = .59 + .27 * x**2 + .048 * np.sin(x * 3.2)
    band = np.exp(-((y - curve + .24) / .28)**2)
    cutoff = np.clip((curve + .14 - y) / .23, 0, 1)
    light = band * cutoff * (.73 + .14 * np.sin(x * 7 + y * 8))
    indices = np.clip((light * 7.5 + random * 3).astype(int), 0, len(CHARACTERS) - 1)
    indices[random > .42 + .45 * light] = 0
    title_fade = 1 - .93 * np.exp(-(x / .52)**4 - ((y - .34) / .27)**4)
    toolbar_fade = 1 - .70 * np.clip((y * height - toolbar) / (2 * cell), 0, 1)
    opacity = 255 * (.68 if dark else .47) * title_fade * toolbar_fade * light
    tone = np.clip((y + .19 * np.sin(x * 2)) * 1.4, 0, 1)
    colors = np.stack([np.interp(tone, (0, .34, .68, 1), channel) for channel in zip(*COLORS)], axis=-1)
    if not dark:
        colors = colors * .67 + np.array((37, 89, 173)) * .33
    return paint_glyphs((width, height), cell, indices, colors, opacity)


@lru_cache(maxsize=8)
def ascii_sweep(cell):
    width, height = 25 * glyph_masks(cell)[0].width, 5 * cell
    x = np.linspace(-1, 1, width)[None, :]
    y = np.linspace(-1, 1, height)[:, None]
    glow = (208 * np.clip(1 - x**2 - y**2, 0, 1)**1.6).astype(np.uint8)
    return Image.fromarray(glow)
