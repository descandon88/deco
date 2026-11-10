"""Context engineering: qué ve el modelo en cada sesión.

Siempre: reglas + perfil + preferencias + mapa de skills + journal reciente + índice.
Bajo demanda (vía tools): proyectos, conceptos, JDs, SQL.
"""

from __future__ import annotations

from datetime import date
from importlib.resources import files
from pathlib import Path

import yaml

from deco.db import build_db, run_query
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


def priorities_context(brain: Brain, db_path: Path, top: int = 6) -> str:
    """Top de brechas priorizadas (brecha × demanda), precalculado para no depender de tools."""
    try:
        build_db(brain, db_path)
        _, rows = run_query(
            db_path,
            "select skill_id, name, level, target_level, jobs_requiring, priority_score "
            f"from mart_skill_gaps where priority_score > 0 limit {int(top)}",
        )
    except Exception:
        return ""
    return "\n".join(
        f"{i}. {name} ({sid}): nivel {lvl}/{tgt}, la piden {jobs} puestos guardados, prioridad {score}"
        for i, (sid, name, lvl, tgt, jobs, score) in enumerate(rows, 1)
    )


def latest_feedback(brain: Brain, max_chars: int = 1500) -> str:
    """Lo que hay que fortalecer según la evaluación externa más reciente (interviews/)."""
    files = sorted(
        (n for n in brain.list_notes("interviews") if n.endswith(".md") and not n.endswith("README.md")),
        reverse=True,
    )
    if not files:
        return ""
    text = brain.read(files[0], max_chars=20_000)
    start = text.find("## A fortalecer")
    if start != -1:
        end = text.find("\n## ", start + 5)
        text = text[start : end if end != -1 else None]
    return f"({files[0]})\n" + text[:max_chars]


def build_system_prompt(brain: Brain, language: str = "es", db_path: Path | None = None) -> str:
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
            "# PRIORIDADES ACTUALES (mart_skill_gaps: brecha × demanda)\n"
            + ((priorities_context(brain, db_path) if db_path else "") or "(sin datos)"),
            "# ÚLTIMO FEEDBACK EXTERNO (interviews/)\n" + (latest_feedback(brain) or "(sin feedback)"),
            "# ÍNDICE DEL BRAIN\n" + (index or "(vacío)"),
        ]
    )
