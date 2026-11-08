"""Extrae las grillas de píxeles de docs/assets/deco-banner.svg para src/deco/banner.py.

Uso: python scripts/svg_to_banner.py docs/assets/deco-banner.svg
Si cambiás el logo, corré esto y copiá DOG y WORD en banner.py.
"""

import re
import sys
from pathlib import Path

DOG_PALETTE = {"#2a211c": "K", "#c8843a": "T", "#ffffff": "W", "#000000": "N", "#e8737a": "P"}
WORD_COLORS = ["#ffe14d", "#ffb52e", "#ff8a1f", "#ff5a1f", "#e8301f", "#b81f4a", "#7a1f6e"]


def main(path: str) -> None:
    svg = Path(path).read_text(encoding="utf-8")
    rects = [dict(re.findall(r'(\w+)="([^"]+)"', m)) for m in re.findall(r"<rect ([^>]+)/>", svg)]
    dog, word = {}, {}
    for r in rects:
        fill = r.get("fill")
        if fill not in DOG_PALETTE and fill not in WORD_COLORS:
            continue  # fondo, scanlines y sombra
        x, y, w = int(r["x"]), int(r["y"]), int(r["width"])
        if fill in DOG_PALETTE:  # perro: grilla de 8px desde (40, 36)
            for cx in range(x, x + w, 8):
                dog[((y - 36) // 8, (cx - 40) // 8)] = DOG_PALETTE[fill]
        elif fill in WORD_COLORS:  # letras: grilla de 12px desde (216, 34)
            for cx in range(x, x + w, 12):
                word[((y - 34) // 12, (cx - 216) // 12)] = "1"
    rows = max(k[0] for k in dog) + 1
    rows += rows % 2  # par, para los medios bloques
    cols = max(k[1] for k in word) + 1
    print("DOG = [")
    for r in range(rows):
        print(f'    "{"".join(dog.get((r, c), ".") for c in range(16))}",')
    print("]\nWORD = [")
    for r in range(7):
        print(f'    "{"".join(word.get((r, c), "0") for c in range(cols))}",')
    print("]")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/assets/deco-banner.svg")
