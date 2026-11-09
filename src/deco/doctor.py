"""`deco doctor`: diagnóstico del entorno. Cada chequeo dice qué está mal y cómo arreglarlo."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

import deco
from deco.config import Settings, env_sources
from deco.context import LANGUAGES
from deco.db import build_db, run_query
from deco.memory import Brain

OK, WARN, FAIL = "ok", "warn", "fail"

# prefijo de LiteLLM -> (variable de entorno, prefijo esperado de la clave)
PROVIDERS = {
    "anthropic": ("ANTHROPIC_API_KEY", "sk-ant-"),
    "groq": ("GROQ_API_KEY", "gsk_"),
    "xai": ("XAI_API_KEY", "xai-"),
    "openai": ("OPENAI_API_KEY", "sk-"),
    "gemini": ("GEMINI_API_KEY", None),
    "ollama": (None, None),
    "ollama_chat": (None, None),
}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""


def check_python() -> Check:
    v = sys.version_info
    if v >= (3, 11):
        return Check("Python", OK, f"{v.major}.{v.minor}.{v.micro}")
    return Check("Python", FAIL, f"{v.major}.{v.minor}", "Deco necesita Python 3.11 o superior.")


def check_package_location(cwd: Path | None = None) -> Check:
    """Detecta una copia vieja de `deco/` que pisa al paquete real (nos pasó)."""
    cwd = cwd or Path.cwd()
    pkg = Path(deco.__file__).resolve().parent
    shadow = cwd / "deco" / "__init__.py"
    if shadow.exists() and shadow.resolve().parent != pkg:
        return Check(
            "Paquete",
            FAIL,
            f"hay una copia de deco/ en {cwd}",
            "Movela a la papelera: Python la carga antes que la versión real.",
        )
    if pkg.parent.name != "src":
        return Check("Paquete", WARN, str(pkg), "Se está usando una copia instalada, no la de src/.")
    return Check("Paquete", OK, str(pkg))


def check_env_files() -> Check:
    sources = env_sources()
    if not sources:
        return Check(
            ".env",
            WARN,
            "no se encontró ningún .env",
            "Creá ~/.config/deco/.env (copiá .env.example) para usar Deco desde cualquier carpeta.",
        )
    return Check(".env", OK, " · ".join(str(s) for s in sources))


def check_brain(settings: Settings) -> list[Check]:
    brain = settings.brain_path
    if not brain.exists():
        return [
            Check("Brain", FAIL, f"no existe {brain}", "Corré `deco init <ruta>` o corregí DECO_BRAIN_PATH.")
        ]
    checks = [Check("Brain", OK, str(brain))]
    repo_root = Path(deco.__file__).resolve().parents[2]
    if brain.resolve().is_relative_to(repo_root):
        checks.append(
            Check(
                "Privacidad",
                FAIL,
                "el brain está DENTRO del repo público de Deco",
                "Movelo a una carpeta aparte: podrías subir tu memoria al repo público.",
            )
        )
    if not (brain / ".git").exists():
        checks.append(Check("Git del brain", WARN, "no es un repo git", "Corré `git init` en el brain."))
    else:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=brain, capture_output=True, text=True, check=False
        ).stdout.strip()
        pending = subprocess.run(
            ["git", "status", "--porcelain"], cwd=brain, capture_output=True, text=True, check=False
        ).stdout.strip()
        if not remote:
            checks.append(
                Check("Git del brain", WARN, "sin remoto", "Conectalo a un repo PRIVADO para tener backup.")
            )
        else:
            n = len(pending.splitlines()) if pending else 0
            checks.append(
                Check(
                    "Git del brain",
                    OK if n == 0 else WARN,
                    f"{remote} · {n} cambios sin commitear",
                    "" if n == 0 else "Hacé commit y push en el brain.",
                )
            )
    return checks


def check_brain_content(settings: Settings) -> list[Check]:
    brain = Brain(settings.brain_path)
    if not brain.exists():
        return []
    checks = []
    try:
        data = yaml.safe_load((brain.root / "skills.yaml").read_text(encoding="utf-8")) or {}
        n = sum(len(v or []) for v in (data.get("domains") or {}).values())
        checks.append(Check("skills.yaml", OK if n else WARN, f"{n} skills"))
    except FileNotFoundError:
        checks.append(Check("skills.yaml", FAIL, "no existe", "Copialo de la plantilla con `deco init`."))
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        where = f" (línea {line + 1})" if line is not None else ""
        checks.append(Check("skills.yaml", FAIL, f"YAML inválido{where}", "Casi siempre es la sangría."))
        return checks
    pending = brain.read_optional("profile.md").count("<completar")
    checks.append(
        Check(
            "profile.md",
            OK if pending == 0 else WARN,
            "completo" if pending == 0 else f"{pending} campos <completar>",
            "" if pending == 0 else "Completarlos mejora las recomendaciones.",
        )
    )
    try:
        counts = build_db(brain, settings.db_path)
        _, rows = run_query(settings.db_path, "select count(*) from mart_unmapped_requirements")
        unmapped = rows[0][0]
        detail = ", ".join(f"{k}={v}" for k, v in counts.items())
        checks.append(Check("DuckDB", OK, detail))
        checks.append(
            Check(
                "Requisitos sin skill",
                OK if unmapped == 0 else WARN,
                str(unmapped),
                "" if unmapped == 0 else 'Ver `deco sql "select * from mart_unmapped_requirements"`.',
            )
        )
    except Exception as exc:
        checks.append(
            Check(
                "DuckDB", FAIL, f"{type(exc).__name__}: {exc}"[:200], "Revisá el formato de jobs/ y events/."
            )
        )
    return checks


def check_model(settings: Settings) -> list[Check]:
    provider = settings.model.split("/", 1)[0]
    checks = [Check("Modelo", OK, settings.model)]
    if provider not in PROVIDERS:
        checks.append(Check("API key", WARN, f"proveedor '{provider}' no reconocido por doctor", ""))
        return checks
    var, prefix = PROVIDERS[provider]
    if var is None:
        checks.append(Check("API key", OK, "modelo local, no necesita clave"))
        return checks
    key = os.getenv(var, "")
    if not key:
        checks.append(Check("API key", FAIL, f"falta {var}", f"Agregala a tu .env: {var}=..."))
    elif prefix and not key.startswith(prefix):
        checks.append(
            Check(
                "API key",
                FAIL,
                f"{var} no tiene el formato esperado ({prefix}…)",
                "Probablemente es de otro proveedor (ej. Grok/xAI vs Groq).",
            )
        )
    else:
        checks.append(Check("API key", OK, f"{var} presente"))
    if settings.language not in LANGUAGES:
        checks.append(Check("Idioma", FAIL, settings.language, f"Usá uno de: {', '.join(LANGUAGES)}"))
    if not 0 <= settings.temperature <= 2:
        checks.append(Check("Temperatura", WARN, str(settings.temperature), "Valores típicos: 0.3 a 1.0"))
    return checks


def check_dependencies() -> list[Check]:
    checks = []
    for mod, why in [
        ("litellm", "llamadas al modelo"),
        ("mcp", "lo importa litellm"),
        ("duckdb", "base de datos"),
        ("rich", "terminal"),
    ]:
        try:
            importlib.import_module(mod)
            checks.append(Check(f"dep: {mod}", OK, why))
        except Exception as exc:
            checks.append(Check(f"dep: {mod}", FAIL, f"{type(exc).__name__}", f"uv pip install {mod}"))
    return checks


def check_ping(settings: Settings) -> Check:
    """Llamada mínima al modelo (gasta unos pocos tokens)."""
    import litellm

    litellm.suppress_debug_info = True
    start = time.perf_counter()
    try:
        litellm.completion(model=settings.model, messages=[{"role": "user", "content": "ping"}], max_tokens=5)
        return Check("Ping al modelo", OK, f"{int((time.perf_counter() - start) * 1000)} ms")
    except Exception as exc:
        return Check(
            "Ping al modelo",
            FAIL,
            f"{type(exc).__name__}: {exc}"[:200],
            "Revisá la clave y el nombre del modelo.",
        )


def run_all(settings: Settings, ping: bool = False) -> list[Check]:
    checks = [check_python(), check_package_location(), check_env_files()]
    checks += check_dependencies()
    checks += check_brain(settings)
    checks += check_brain_content(settings)
    checks += check_model(settings)
    if ping:
        checks.append(check_ping(settings))
    return checks
