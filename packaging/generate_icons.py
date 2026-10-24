#!/usr/bin/env python3
"""
Generate application icons (.png, .ico, .icns) for Windows, Linux, and macOS builds.
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw


def generate_icons(output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    S = 1024
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Clean minimalist squircle tile (warm porcelain #F4F5F7 with subtle slate border)
    draw.rounded_rectangle(
        [(64, 64), (S - 64, S - 64)],
        radius=190,
        fill=(244, 245, 247, 255),
        outline=(212, 218, 226, 255),
        width=10,
    )

    # 2. Minimalist architectural "V" ribbon monogram (Vale + Media chevron)
    right_wing = [
        (632, 276),
        (768, 276),
        (564, 764),
        (428, 764),
    ]
    draw.polygon(right_wing, fill=(94, 129, 172, 255))

    overlap_shadow = [
        (460, 688),
        (564, 764),
        (428, 764),
    ]
    draw.polygon(overlap_shadow, fill=(72, 102, 140, 255))

    left_wing = [
        (256, 276),
        (392, 276),
        (564, 764),
        (428, 764),
    ]
    draw.polygon(left_wing, fill=(43, 50, 60, 255))

    draw.ellipse(
        [(474, 276), (550, 352)],
        fill=(94, 129, 172, 255),
    )

    png_512 = out / "media_manager_512.png"
    png_256 = out / "media_manager.png"
    ico_path = out / "media_manager.ico"
    icns_path = out / "media_manager.icns"

    img_512 = img.resize((512, 512), resample=Image.Resampling.LANCZOS)
    img_256 = img.resize((256, 256), resample=Image.Resampling.LANCZOS)

    img_512.save(str(png_512), format="PNG")
    img_256.save(str(png_256), format="PNG")
    img_256.save(
        str(ico_path),
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    try:
        img_512.save(str(icns_path), format="ICNS")
    except Exception:
        pass

    return {
        "png": str(png_256),
        "png_512": str(png_512),
        "ico": str(ico_path),
        "icns": str(icns_path),
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "dist/icons"
    paths = generate_icons(target)
    print(paths["ico"])
