"""Deterministic framing of existing scene images; no generative API calls."""

import math
from pathlib import Path

from PIL import Image


def validate_crop(box):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError("裁切範圍需填 left, top, right, bottom 四個 0～1 數值")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box):
        raise ValueError("裁切範圍必須是有限數值")
    left, top, right, bottom = box
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("裁切範圍需介於 0～1，且左小於右、上小於下")


def crop_scene(source, destination, box, output_size=(1080, 1920)):
    """Expand to output aspect ratio so the requested region is retained, then resize."""
    validate_crop(box)
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("裁切來源與輸出檔案必須不同")
    with Image.open(source) as original:
        image = original.convert("RGB")
        width, height = image.size
        left, top, right, bottom = [v * size for v, size in zip(box, (width, height, width, height))]
        crop_width, crop_height = right - left, bottom - top
        aspect = output_size[0] / output_size[1]
        if crop_width / crop_height > aspect:
            crop_height = crop_width / aspect
        else:
            crop_width = crop_height * aspect
        if crop_width > width + 1e-6 or crop_height > height + 1e-6:
            raise ValueError("來源圖片比例無法保留完整裁切範圍並填滿輸出；請縮小裁切範圍")
        x = min(max(0, (left + right - crop_width) / 2), width - crop_width)
        y = min(max(0, (top + bottom - crop_height) / 2), height - crop_height)
        pixels = (math.floor(x), math.floor(y), math.ceil(x + crop_width), math.ceil(y + crop_height))
        image.crop(pixels).resize(output_size, Image.Resampling.LANCZOS).save(destination)
    return {"requested_crop": list(box), "source_size": [width, height], "crop_pixels": list(pixels),
            "output_size": list(output_size), "upscale_factor": max(output_size[0] / (pixels[2] - pixels[0]),
                                                                    output_size[1] / (pixels[3] - pixels[1]))}
