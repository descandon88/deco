"""Banner de Deco para la terminal: el mismo diseño que docs/assets/deco-banner.svg,
redibujado con caracteres de bloque (pixel art).

Las grillas se extrajeron del SVG: cada carácter es un píxel del logo.
"""

from __future__ import annotations

import os

from rich.console import Console
from rich.text import Text

# Pastor alemán (grilla de 8px del SVG). Cada letra es un color de PALETTE; "." es vacío.
# Se dibuja con medios bloques: 2 píxeles verticales por carácter.
DOG = [
    ".K......K.",
    "KTK....KTK",
    "KTTK..KTTK",
    "KTKKKKKKTK",
    ".KKKKKKKK.",
    "KTWKKKKWTK",
    "KTTTKKTTTK",
    ".KTTKKTTK.",
    "..KTNNTK..",
    "...KPPK...",
]
PALETTE = {
    "K": "#4a3a30",  # pelaje oscuro
    "T": "#c8843a",  # pelaje canela
    "W": "#ffffff",  # ojos
    "N": "#000000",  # nariz
    "P": "#e8737a",  # lengua
}

# "DECO" (grilla de 12px del SVG). 1 = píxel lleno.
WORD = [
    "111110011111100111110011110",
    "110011011000001100000110011",
    "110011011000001100000110011",
    "110011011111001100000110011",
    "110011011000001100000110011",
    "110011011000001100000110011",
    "111110011111100111110011110",
]
# Degradé del logo, una fila por color (de arriba hacia abajo).
ROW_COLORS = ["#ffe14d", "#ffb52e", "#ff8a1f", "#ff5a1f", "#e8301f", "#b81f4a", "#7a1f6e"]
SUBTITLE_COLOR = "#ffb52e"

PIXEL = "█"  # dos caracteres por píxel para que se vea cuadrado
MIN_WIDTH_WITH_DOG = 50
MIN_WIDTH = 35


def banner_lines() -> list[str]:
    return ["".join(PIXEL if bit == "1" else " " * len(PIXEL) for bit in row).rstrip() for row in WORD]


def dog_lines() -> list[Text]:
    """Convierte la grilla del perro en líneas con medios bloques de color."""
    lines = []
    for top, bottom in zip(DOG[0::2], DOG[1::2], strict=True):
        line = Text()
        for a, b in zip(top, bottom, strict=True):
            ca, cb = PALETTE.get(a), PALETTE.get(b)
            if ca and cb:
                line.append("▀", style=f"{ca} on {cb}")
            elif ca:
                line.append("▀", style=ca)
            elif cb:
                line.append("▄", style=cb)
            else:
                line.append(" ")
        lines.append(line)
    return lines

def word_lines_compact() -> list[Text]:
    """Letras con medios bloques: 2 filas de píxeles por línea, con su color cada una."""
    rows = [*WORD, "0" * len(WORD[0])]  # 8 filas: tiene que ser par
    colors = [*ROW_COLORS, ROW_COLORS[-1]]
    lines = []
    for i in range(0, len(rows), 2):
        line = Text()
        for a, b in zip(rows[i], rows[i + 1], strict=True):
            ca = colors[i] if a == "1" else None
            cb = colors[i + 1] if b == "1" else None
            if ca and cb:
                line.append("▀", style=f"{ca} on {cb}")
            elif ca:
                line.append("▀", style=ca)
            elif cb:
                line.append("▄", style=cb)
            else:
                line.append(" ")
        lines.append(line)
    return lines


def _subtitle(text: str) -> Text:
    # spaced = " ".join(text.upper())  # imita el letter-spacing del SVG
    spaced = "  ".join(text.upper().split())
    return Text(spaced, style=f"bold {SUBTITLE_COLOR}")


def print_banner(console: Console, subtitle: str = "mentor de IA en la terminal") -> None:
    if os.getenv("DECO_BANNER", "true").lower() == "false" or console.width < MIN_WIDTH:
        return
    # word = [Text(line, style=color) for line, color in zip(banner_lines(), ROW_COLORS, strict=True)]
    word = word_lines_compact()
    sub = _subtitle(subtitle)
    console.print()
    if console.width < MIN_WIDTH_WITH_DOG:  # sin espacio para el perro: solo las letras
        for line in [*word, Text(""), sub]:
            console.print(Text("  ") + line)
        console.print()
        return
    dog = dog_lines()
    right = word  # las letras ocupan 7 líneas, el perro 8: quedan alineadas arriba
    for i, dog_line in enumerate(dog):
        # text = right[i] if i < len(right) else Text("")
        j = i - (len(dog) - len(right)) // 2
        text = right[j] if 0 <= j < len(right) else Text("")
        console.print(Text("  ") + dog_line + Text("    ") + text)
    console.print(Text(" " * (2 + len(DOG[0]) + 4)) + sub)
    console.print()
