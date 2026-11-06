"""Draws the VeilMark shield icon (assets/veilmark.ico, .icns for the Mac, .png). Run: python assets/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
here = Path(__file__).parent


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # shield silhouette
    top, bottom, left, right = 90, 960, 150, 874
    shield = [(S // 2, top), (right, 220), (right, 500), (S // 2 + 230, 800), (S // 2, bottom),
              (S // 2 - 230, 800), (left, 500), (left, 220)]
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(x, y + 18) for x, y in shield], fill=(20, 16, 60, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    d.polygon(shield, fill=(91, 79, 224, 255))
    inner = [(S // 2, top + 70), (right - 60, 260), (right - 60, 495), (S // 2 + 195, 760), (S // 2, bottom - 80),
             (S // 2 - 195, 760), (left + 60, 495), (left + 60, 260)]
    d.polygon(inner, fill=(74, 63, 196, 255))
    # "veil" wave lines (watermark) + check mark
    for i, y in enumerate((430, 520)):
        d.arc((300, y - 90, 724, y + 90), 200, 340, fill=(255, 255, 255, 90 + 40 * i), width=26)
    d.line([(370, 600), (480, 710), (680, 470)], fill=(255, 255, 255, 255), width=74, joint="curve")
    return img


if __name__ == "__main__":
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(here / "veilmark.png")
    big.save(here / "veilmark.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    # Mac app icon: Apple's grid leaves ~10% transparent margin around the artwork
    mac = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    inset = int(S * 0.8)
    mac.alpha_composite(big.resize((inset, inset), Image.LANCZOS), ((S - inset) // 2, (S - inset) // 2))
    mac.save(here / "veilmark.icns")
    print("icon written")
