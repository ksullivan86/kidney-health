#!/usr/bin/env python3
"""Regenerate the JPEG fixtures in tests/fixtures/ai/images/ (a developer tool; needs Pillow, which the
app and the test suite do not). The images are drawn here, so they carry no real photo and no licence.

    python3 tests/fixtures/ai/make_images.py

* ``label.jpg``: 320×240 baseline JPEG of a drawn "Nutrition Facts" panel, with an EXIF block that
  holds GPS coordinates and a camera make, and a JPEG comment (``COM``): the server must remove both.
* ``progressive.jpg``: 200×150 progressive JPEG (SOF2), with restart markers.
* ``gray.jpg``: 64×64 greyscale baseline JPEG.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "images"


def panel(size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, size[0] - 5, size[1] - 5], outline="black", width=2)
    d.text((12, 10), "Nutrition Facts", fill="black")
    d.text((12, 30), "Serving size 5 crackers (30 g)", fill="black")
    for i, line in enumerate(("Calories 140", "Total Fat 6g", "Sodium 230mg", "Total Carbohydrate 19g", "Protein 2g")):
        d.text((12, 55 + 18 * i), line, fill="black")
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    img = panel((320, 240))
    exif = Image.Exif()
    exif[0x010F] = "FixtureCam"  # Make
    exif[0x0110] = "Model 1"  # Model
    gps = {1: "N", 2: (51.0, 30.0, 0.0), 3: "W", 4: (0.0, 7.0, 0.0)}  # GPSLatitudeRef, GPSLatitude, …
    exif[0x8825] = gps
    img.save(OUT / "label.jpg", "JPEG", quality=60, exif=exif.tobytes(), comment=b"secret comment from the camera")
    panel((200, 150)).save(OUT / "progressive.jpg", "JPEG", quality=60, progressive=True, optimize=True)
    panel((64, 64)).convert("L").save(OUT / "gray.jpg", "JPEG", quality=60)
    for path in sorted(OUT.glob("*.jpg")):
        print(path.name, path.stat().st_size)


if __name__ == "__main__":
    main()
