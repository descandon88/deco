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


def build_system_prompt(brain: Brain) -> str:
    journal = "\n\n".join(f"### {path}\n{text}" for path, text in brain.recent_journal())
    index = "\n".join(brain.list_notes()[:200])
    return "\n\n".join(
        [
            load_prompt("system"),
            f"Fecha de hoy: {date.today().isoformat()}",
            "# PERFIL (profile.md)\n" + (brain.read_optional("profile.md") or "(vacío)"),
            "# PREFERENCIAS (preferences.md)\n" + (brain.read_optional("preferences.md") or "(vacío)"),
            "# MAPA DE SKILLS (resumen de skills.yaml)\n" + _skills_summary(brain),
            "# JOURNAL RECIENTE\n" + (journal or "(sin entradas)"),
            "# ÍNDICE DEL BRAIN\n" + (index or "(vacío)"),
        ]
    )
