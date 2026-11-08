"""Context engineering: qué ve el modelo en cada sesión.

Siempre: reglas + perfil + preferencias + mapa de skills + journal reciente + índice.
Bajo demanda (vía tools): proyectos, conceptos, JDs, SQL.
"""

from __future__ import annotations

from datetime import date
from importlib.resources import files

import yaml

from deco.memory import Brain


def load_prompt(name: str) -> str:
    return (files("deco") / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def _skills_summary(brain: Brain) -> str:
    raw = brain.read_optional("skills.yaml", max_chars=50_000)
    if not raw:
        return "(skills.yaml no existe todavía)"
    data = yaml.safe_load(raw) or {}
    lines = []
    for domain, items in (data.get("domains") or {}).items():
        lines.append(f"[{domain}]")
        for s in items or []:
            ev = len(s.get("evidence") or [])
            lines.append(f"  - {s['id']}: nivel {s.get('level', 0)}/{s.get('target', 3)} (evidencias: {ev})")
    return "\n".join(lines)


LANGUAGES = {
    "es": "Respondé siempre en español.",
    "en": (
        "Always answer in English. If David writes in Spanish, still answer in English, "
        "and briefly correct his technical English when useful."
    ),
    "mix": (
        "Explicaciones, feedback y conversación en español. Preguntas de entrevista (/mock, "
        "/learn), términos técnicos y bullets de CV en INGLÉS. Si David responde en inglés, "
        "corregí brevemente su inglés técnico (vocabulario y forma de explicar)."
    ),
}


def language_rule(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"Idioma no soportado: {language}. Opciones: {', '.join(LANGUAGES)}")
    return "# IDIOMA\n" + LANGUAGES[language]


def build_system_prompt(brain: Brain, language: str = "es") -> str:
    journal = "\n\n".join(f"### {path}\n{text}" for path, text in brain.recent_journal(n=2, max_chars=1500))
    notes = [n for n in brain.list_notes() if "/_" not in n and not n.endswith(".gitkeep")]
    index = "\n".join(notes[:80])
    return "\n\n".join(
        [
            load_prompt("system"),
            language_rule(language),
            f"Fecha de hoy: {date.today().isoformat()}",
            "# PERFIL (profile.md)\n" + (brain.read_optional("profile.md") or "(vacío)"),
            "# PREFERENCIAS (preferences.md)\n" + (brain.read_optional("preferences.md") or "(vacío)"),
            "# MAPA DE SKILLS (resumen de skills.yaml)\n" + _skills_summary(brain),
            "# JOURNAL RECIENTE\n" + (journal or "(sin entradas)"),
            "# ÍNDICE DEL BRAIN\n" + (index or "(vacío)"),
        ]
    )
