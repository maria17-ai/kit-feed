#!/usr/bin/env python3
"""Download supplier photos, normalize them to 1200x1200 and add a watermark."""

from __future__ import annotations

import argparse
import io
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
)


def font_path() -> str:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("Не найден шрифт для водяного знака")


def download(url: str, attempts: int = 4) -> bytes:
    error = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 KIT-image-builder"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as exc:  # network errors differ by server
            error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Не удалось скачать {url}: {error}")


def normalize_image(source: bytes, destination: Path, mark_font: str) -> None:
    with Image.open(io.BytesIO(source)) as opened:
        image = opened.convert("RGB")

    image = ImageEnhance.Contrast(image).enhance(1.04)
    image = ImageEnhance.Color(image).enhance(1.02)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.4, percent=115, threshold=3))

    max_side = 1040
    scale = min(max_side / image.width, max_side / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    image = image.resize(size, Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (1200, 1200), "white")
    canvas.paste(image, ((1200 - image.width) // 2, (1200 - image.height) // 2))

    overlay = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.truetype(mark_font, 34)
    label = "ТД МК"
    bbox = draw.textbbox((0, 0), label, font=font)
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    padding_x, padding_y = 18, 11
    right, bottom = 1160, 1155
    left = right - width - 2 * padding_x
    top = bottom - height - 2 * padding_y
    draw.rounded_rectangle((left, top, right, bottom), radius=12, fill=(255, 255, 255, 178))
    draw.text((left + padding_x, top + padding_y - bbox[1]), label, font=font, fill=(20, 75, 145, 150))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.jpg")
    canvas.save(temporary, "JPEG", quality=88, optimize=True, progressive=True)
    temporary.replace(destination)


def process(entry: dict, output_dir: Path, mark_font: str, force: bool) -> tuple[str, str]:
    destination = output_dir / entry["filename"]
    if destination.exists() and destination.stat().st_size > 1000 and not force:
        return "skipped", entry["filename"]
    source = download(entry["source_url"])
    normalize_image(source, destination, mark_font)
    return "created", entry["filename"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="image_manifest.json", type=Path)
    parser.add_argument("--output", default="images", type=Path)
    parser.add_argument("--workers", default=12, type=int)
    parser.add_argument("--start", default=0, type=int)
    parser.add_argument("--limit", default=0, type=int, help="0 = обработать все оставшиеся")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    selected = manifest[args.start : args.start + args.limit if args.limit else None]
    args.output.mkdir(parents=True, exist_ok=True)
    mark_font = font_path()
    counters = {"created": 0, "skipped": 0, "failed": 0}
    failures = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(process, entry, args.output, mark_font, args.force): entry for entry in selected}
        for number, future in enumerate(as_completed(futures), start=1):
            entry = futures[future]
            try:
                status, filename = future.result()
                counters[status] += 1
            except Exception as exc:
                counters["failed"] += 1
                failures.append({"article": entry.get("article"), "url": entry.get("source_url"), "error": str(exc)})
            if number % 100 == 0 or number == len(selected):
                print(f"Обработано {number}/{len(selected)}: {counters}", flush=True)

    Path("image_failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": len(selected), **counters}, ensure_ascii=False))
    if counters["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
