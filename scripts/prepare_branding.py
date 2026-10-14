from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "static" / "img"


def compact_logo(filename, width):
    with Image.open(IMAGES / filename) as source:
        image = source.convert("RGBA")
    bounds = image.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError(f"Logo has no visible pixels: {filename}")
    image = image.crop(bounds)
    height = round(width * image.height / image.width)
    return image.resize((width, height), Image.Resampling.LANCZOS)


def main():
    symbol = compact_logo("Elrise-Logo.png", 256)
    wordmark = compact_logo("Elrise-NameLogo.png", 552)
    symbol.save(IMAGES / "elrise-symbol-web.png", optimize=True)
    wordmark.save(IMAGES / "elrise-wordmark-web.png", optimize=True)
    symbol.thumbnail((56, 56), Image.Resampling.LANCZOS)
    favicon = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    favicon.alpha_composite(symbol, ((64 - symbol.width) // 2, (64 - symbol.height) // 2))
    favicon.save(IMAGES / "favicon.png", optimize=True)
    print("Web logos and favicon generated; original logo files are unchanged.")


if __name__ == "__main__":
    main()
