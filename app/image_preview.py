"""Bounded rendering for uploaded-image previews; originals are never modified."""
import math

import numpy as np
from PIL import Image, ImageDraw

MAX_THUMBNAIL_SIZE = 2048
MAX_PREVIEW_PIXELS = 100_000_000


def render_preview(source, size, center_x=0.5, center_y=0.5, zoom=1, points=()):
    w, h = source.size
    # Inspect lazy image headers before draft, decoding, transforms or arrays.
    if w < 1 or h < 1 or w * h > MAX_PREVIEW_PIXELS:
        raise ValueError("Source exceeds preview pixel budget")
    if not 1 <= size <= MAX_THUMBNAIL_SIZE:
        raise ValueError("Invalid preview size")
    size = min(size, max(w, h))
    target = (max(1, round(w * size / max(w, h))),
              max(1, round(h * size / max(w, h))))
    scale = 2 ** (zoom - 1)
    # JPEG decoders can discard resolution before decoding. Account for zoom.
    source.draft(source.mode, (math.ceil(target[0] * scale),
                               math.ceil(target[1] * scale)))
    w, h = source.size
    box = (w * (center_x - 0.5 / scale), h * (center_y - 0.5 / scale),
           w * (center_x + 0.5 / scale), h * (center_y + 0.5 / scale))
    # EXTENT pads out-of-bounds areas without allocating a source-sized crop.
    preview = source.transform(target, Image.Transform.EXTENT, box,
                               resample=Image.Resampling.NEAREST)
    if preview.mode != 'RGB':
        arr = np.asarray(preview, dtype=np.float32).copy()
        np.nan_to_num(arr, copy=False)
        low, high = arr.min(), arr.max()
        if low != high:
            arr -= low
            arr *= 255.0 / (high - low)
        preview = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert('RGB')
    draw = ImageDraw.Draw(preview)
    for point in points:
        x = (point['x'] - center_x + 0.5 / scale) * scale * target[0]
        y = (point['y'] - center_y + 0.5 / scale) * scale * target[1]
        radius = point['radius'] * max(target) / 100.0
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     outline=point['color'], width=max(1, math.floor(radius / 3)))
    return preview
