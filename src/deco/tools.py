"""Herramientas que el modelo puede llamar. El modelo NO tiene memoria propia:
todo lo que sabe de David lo obtiene a través de estas funciones.

Reglas de seguridad:
- Lectura libre dentro del brain.
- SQL solo lectura.
- Eventos: append-only (bajo riesgo, se guardan solos).
- Cambios a notas: el humano ve el diff y aprueba (human-in-the-loop).
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Callable

from deco.config import Settings
from deco.db import build_db, run_query
from deco.memory import Brain

MAX_TOOL_CHARS = 4000

EVENT_TYPES = ["study_session", "checkin", "mock_interview", "project_update", "assessment", "query"]

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "list_notes",
            "description": "Lista archivos del brain. Úsalo para orientarte antes de leer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "description": "Subcarpeta, ej 'projects'. Vacío = todo."}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Busca texto en las notas del brain. Devuelve ruta, línea y fragmento.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": "Lee un archivo del brain por su ruta relativa.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_db",
            "description": (
                "Ejecuta SQL de SOLO LECTURA (DuckDB) sobre la capa estructurada. Tablas: skills, "
                "events, projects, jobs, job_requirements. Vistas: mart_skill_gaps, "
                "mart_unmapped_requirements, mart_weekly_activity."
            ),
            "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_event",
            "description": (
                "Registra un evento de aprendizaje (append-only). Úsalo al cerrar un check-in, "
                "una sesión de estudio o un mock interview."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": EVENT_TYPES},
                    "summary": {"type": "string"},
                    "domain": {"type": "string"},
                    "skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "skill_ids existentes en skills.yaml",
                    },
                    "score": {"type": "number", "description": "0-10, solo para mocks/ejercicios"},
                    "duration_min": {"type": "integer"},
                    "source_ref": {"type": "string"},
                },
                "required": ["type", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_note_update",
            "description": (
                "Propone crear o reemplazar un archivo del brain con contenido COMPLETO. David verá "
                "el diff y decidirá. Nunca subas el nivel de una skill sin evidencia verificable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "new_content": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["path", "new_content", "reason"],
            },
        },
    },
]

ConfirmFn = Callable[[str, str, str], bool]  # (path, diff, reason) -> aprobado?


class Toolbox:
    def __init__(self, brain: Brain, settings: Settings, confirm: ConfirmFn):
        self.brain = brain
        self.settings = settings
        self.confirm = confirm
        # se reconstruye en la primera consulta de cada sesión: el brain pudo cambiar a mano
        self._db_dirty = True

    def call(self, name: str, raw_args: str | dict) -> str:
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
            handler = getattr(self, f"_t_{name}", None)
            if handler is None:
                return f"ERROR: herramienta desconocida '{name}'"
            result = handler(**args)
            if len(result) > MAX_TOOL_CHARS:  # cuidar el presupuesto de tokens
                result = result[:MAX_TOOL_CHARS] + "\n[... recortado; filtrá más la consulta]"
            return result
        except Exception as exc:  # el modelo recibe el error y puede corregirse
            return f"ERROR: {type(exc).__name__}: {exc}"

    # ---------- implementaciones ----------
    def _t_list_notes(self, folder: str = "") -> str:
        notes = self.brain.list_notes(folder)
        return "\n".join(notes) if notes else "(sin archivos)"

    def _t_search_notes(self, query: str) -> str:
        hits = self.brain.search(query)
        if not hits:
            return "Sin resultados. Probá otros términos o list_notes."
        return "\n".join(f"{h['path']}:{h['line']}  {h['snippet']}" for h in hits)

    def _t_read_note(self, path: str) -> str:
        return self.brain.read(path)

    def _t_query_db(self, sql: str) -> str:
        if self._db_dirty:
            build_db(self.brain, self.settings.db_path)
            self._db_dirty = False
        cols, rows = run_query(self.settings.db_path, sql)
        lines = [" | ".join(cols)] + [" | ".join("" if v is None else str(v) for v in r) for r in rows]
        return "\n".join(lines) if rows else " | ".join(cols) + "\n(0 filas)"

    def _t_log_event(self, **event) -> str:
        record = self.brain.append_event(event)
        self._db_dirty = True
        if self.settings.auto_commit:
            self.brain.git_commit(f"event: {record['type']} - {record['summary'][:60]}")
        return f"OK evento {record['event_id']} guardado"

    def _t_propose_note_update(self, path: str, new_content: str, reason: str) -> str:
        target = self.brain.resolve(path)
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        if not diff:
            return "Sin cambios: el contenido es idéntico."
        if not self.confirm(path, diff, reason):
            return "RECHAZADO por David. No insistas; preguntale qué ajustar."
        self.brain.write(path, new_content)
        self._db_dirty = True
        if self.settings.auto_commit:
            self.brain.git_commit(f"memory: {path} - {reason[:60]}")
        return f"OK {path} actualizado."
