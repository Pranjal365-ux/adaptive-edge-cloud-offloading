"""Explainable surface-anomaly inspection shared by the edge and cloud workers."""

from __future__ import annotations

import base64
import binascii
import io
import time
from collections import deque

from PIL import Image, ImageChops, ImageDraw, ImageFilter

MAX_IMAGE_PIXELS = 2_400_000
MAX_IMAGE_BYTES = 3_000_000
SENSITIVITY_THRESHOLDS = {"low": 72, "normal": 48, "high": 30}


def inspect_surface(payload: dict) -> dict:
    """Find compact regions that contrast with their local surface neighborhood.

    This is a deterministic demo heuristic, not a trained or certified QA model.
    """
    started = time.perf_counter()
    encoded = payload.get("image_base64")
    sensitivity = payload.get("sensitivity", "normal")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("image_base64 is required")
    if sensitivity not in SENSITIVITY_THRESHOLDS:
        raise ValueError("sensitivity must be low, normal, or high")
    if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 16:
        raise ValueError("image is too large; upload an image under 3 MB")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image must be valid base64-encoded JPEG, PNG, or WebP") from exc
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("image must be between 1 byte and 3 MB")

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("supported image formats are JPEG, PNG, and WebP")
            width, height = source.size
            if (payload.get("image_width"), payload.get("image_height")) != (width, height):
                raise ValueError("image dimensions do not match the uploaded image")
            if width < 64 or height < 64:
                raise ValueError("image must be at least 64 by 64 pixels")
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("image is too large; select a lower inspection detail")
            source.load()
            image = source.convert("RGB")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("image could not be decoded safely") from exc

    threshold = SENSITIVITY_THRESHOLDS[sensitivity]
    gray = image.convert("L")
    local_surface = gray.filter(ImageFilter.MedianFilter(size=7))
    contrast = ImageChops.difference(gray, local_surface)
    mask = contrast.point(lambda value: 255 if value >= threshold else 0)
    mask_bytes = mask.tobytes()
    width, height = image.size
    pixel_count = width * height
    min_area = max(12, pixel_count // 80_000)
    visited = bytearray(pixel_count)
    defects = []

    # Eight-connected components group adjacent anomalous pixels into defects.
    for start in range(pixel_count):
        if not mask_bytes[start] or visited[start]:
            continue
        visited[start] = 1
        queue = deque([start])
        area = 0
        min_x = max_x = start % width
        min_y = max_y = start // width
        while queue:
            index = queue.popleft()
            x, y = index % width, index // width
            area += 1
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
            y0, y1 = max(0, y - 1), min(height - 1, y + 1)
            x0, x1 = max(0, x - 1), min(width - 1, x + 1)
            for ny in range(y0, y1 + 1):
                for nx in range(x0, x1 + 1):
                    neighbor = ny * width + nx
                    if mask_bytes[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        queue.append(neighbor)
        if area >= min_area:
            defects.append(
                {
                    "x": min_x,
                    "y": min_y,
                    "width": max_x - min_x + 1,
                    "height": max_y - min_y + 1,
                    "area_pixels": area,
                }
            )

    defects.sort(key=lambda item: item["area_pixels"], reverse=True)
    shown_defects = defects[:12]
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    for index, defect in enumerate(shown_defects, start=1):
        x, y = defect["x"], defect["y"]
        right, bottom = x + defect["width"] - 1, y + defect["height"] - 1
        draw.rectangle((x, y, right, bottom), outline=(255, 72, 86), width=max(2, width // 400))
        draw.text(
            (x + 3, max(1, y - 16)),
            f"D{index}",
            fill=(255, 72, 86),
            stroke_width=1,
            stroke_fill=(20, 24, 30),
        )
    output = io.BytesIO()
    annotated.save(output, format="JPEG", quality=82, optimize=True)
    anomaly_pixels = sum(item["area_pixels"] for item in defects)
    return {
        "verdict": "REVIEW" if defects else "PASS",
        "defect_count": len(defects),
        "reported_defect_count": len(shown_defects),
        "anomaly_pixels": anomaly_pixels,
        "anomaly_fraction": round(anomaly_pixels / pixel_count, 6),
        "width": width,
        "height": height,
        "pixels_processed": pixel_count,
        "sensitivity": sensitivity,
        "contrast_threshold": threshold,
        "defects": shown_defects,
        "annotated_image_base64": base64.b64encode(output.getvalue()).decode("ascii"),
        "compute_ms": round((time.perf_counter() - started) * 1000, 3),
        "input_bytes": len(image_bytes),
    }
