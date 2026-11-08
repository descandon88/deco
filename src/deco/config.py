"""Configuración por variables de entorno (.env). Nada de secretos en el código."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    brain_path: Path  # carpeta del repo PRIVADO de memoria
    model: str  # modelo "fuerte" (razonamiento, JDs, roadmap, mocks)
    fast_model: str  # modelo rápido/barato (resúmenes, clasificación)
    db_path: Path  # DuckDB derivada (se reconstruye desde el brain)
    auto_commit: bool  # commitear cambios de memoria en el repo del brain


def load_settings() -> Settings:
    # 1) .env del directorio actual  2) ~/.config/deco/.env
    load_dotenv()
    load_dotenv(Path("~/.config/deco/.env").expanduser())

    brain = Path(os.getenv("DECO_BRAIN_PATH", "~/david-brain")).expanduser()
    db_default = brain / ".cache" / "brain.duckdb"
    return Settings(
        brain_path=brain,
        model=os.getenv("DECO_MODEL", "anthropic/claude-sonnet-5-5"),
        fast_model=os.getenv("DECO_FAST_MODEL", "anthropic/claude-haiku-5-5"),
        db_path=Path(os.getenv("DECO_DB_PATH", str(db_default))).expanduser(),
        auto_commit=os.getenv("DECO_AUTO_COMMIT", "true").lower() == "true",
    )
