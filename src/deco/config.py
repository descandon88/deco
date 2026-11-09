"""Configuración por variables de entorno (.env). Nada de secretos en el código."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

USER_ENV = Path("~/.config/deco/.env").expanduser()


def env_sources() -> list[Path]:
    """Archivos .env que Deco encuentra, en orden de prioridad."""
    found = [Path(f) for f in [find_dotenv(usecwd=True), find_dotenv()] if f]
    if USER_ENV.exists():
        found.append(USER_ENV)
    return list(dict.fromkeys(found))  # sin duplicados, mantiene el orden


@dataclass(frozen=True)
class Settings:
    brain_path: Path  # carpeta del repo PRIVADO de memoria
    model: str  # modelo "fuerte" (razonamiento, JDs, roadmap, mocks)
    fast_model: str  # modelo rápido/barato (resúmenes, clasificación)
    db_path: Path  # DuckDB derivada (se reconstruye desde el brain)
    auto_commit: bool  # commitear cambios de memoria en el repo del brain
    language: str = "es"  # es | en | mix
    temperature: float = 0.7
    max_tokens: int = 2500  # tope por respuesta: corta bucles y cuida el límite de tokens


def load_settings() -> Settings:
    # 1) .env del directorio actual  2) ~/.config/deco/.env
    load_dotenv()
    load_dotenv(USER_ENV)

    brain = Path(os.getenv("DECO_BRAIN_PATH", "~/deco-brain")).expanduser()
    db_default = brain / ".cache" / "brain.duckdb"
    return Settings(
        brain_path=brain,
        model=os.getenv("DECO_MODEL", "anthropic/claude-sonnet-5-5"),
        fast_model=os.getenv("DECO_FAST_MODEL", "anthropic/claude-haiku-5-5"),
        db_path=Path(os.getenv("DECO_DB_PATH", str(db_default))).expanduser(),
        auto_commit=os.getenv("DECO_AUTO_COMMIT", "true").lower() == "true",
        language=os.getenv("DECO_LANG", "es").lower(),
        temperature=float(os.getenv("DECO_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("DECO_MAX_TOKENS", "2500")),
    )
