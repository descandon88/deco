"""Acceso al 'brain': el repo privado de markdown/yaml/jsonl que ES la memoria.

Principio: los archivos de texto son la fuente de verdad. Todo lo demás
(DuckDB, índices de búsqueda) es derivado y se puede reconstruir.
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".txt", ".jsonl"}
IGNORED_DIRS = {".git", ".cache", "__pycache__"}


class Brain:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    # ---------- rutas seguras ----------
    def resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Ruta fuera del brain: {rel}")
        return path

    def _iter_files(self, folder: str = ""):
        base = self.resolve(folder) if folder else self.root
        if not base.exists():
            return
        for p in sorted(base.rglob("*")):
            rel_parts = p.relative_to(self.root).parts
            if p.is_file() and p.suffix in TEXT_SUFFIXES and not IGNORED_DIRS.intersection(rel_parts):
                yield p

    # ---------- lectura ----------
    def exists(self) -> bool:
        return self.root.exists()

    def list_notes(self, folder: str = "") -> list[str]:
        return [str(p.relative_to(self.root)) for p in self._iter_files(folder)]

    def read(self, rel: str, max_chars: int = 20_000) -> str:
        text = self.resolve(rel).read_text(encoding="utf-8")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[... truncado, {len(text)} caracteres en total]"
        return text

    def read_optional(self, rel: str, max_chars: int = 6_000) -> str:
        try:
            return self.read(rel, max_chars)
        except FileNotFoundError:
            return ""

    def search(self, query: str, limit: int = 8) -> list[dict]:
        """Búsqueda léxica simple. Fase 4: reemplazar/combinar con embeddings."""
        terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
        if not terms:
            return []
        hits: list[dict] = []
        for p in self._iter_files():
            if p.suffix == ".jsonl":
                continue
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            for i, line in enumerate(lines):
                low = line.lower()
                score = sum(low.count(t) for t in terms)
                if score:
                    hits.append(
                        {
                            "path": str(p.relative_to(self.root)),
                            "line": i + 1,
                            "score": score,
                            "snippet": line.strip()[:240],
                        }
                    )
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]

    def recent_journal(self, n: int = 3, max_chars: int = 2_500) -> list[tuple[str, str]]:
        files = sorted(self._iter_files("journal"), reverse=True)[:n]
        return [
            (str(p.relative_to(self.root)), self.read(str(p.relative_to(self.root)), max_chars))
            for p in files
        ]

    # ---------- escritura ----------
    def write(self, rel: str, content: str) -> Path:
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def append_event(self, event: dict) -> dict:
        """Eventos append-only (jsonl por mes). Son la 'tabla de hechos' cruda."""
        now = datetime.now(UTC)
        record = {"event_id": str(uuid.uuid4()), "ts": now.isoformat(timespec="seconds"), **event}
        path = self.resolve(f"events/{now:%Y-%m}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def git_commit(self, message: str) -> bool:
        if not (self.root / ".git").exists():
            return False
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=False, capture_output=True)
        result = subprocess.run(
            ["git", "commit", "-m", message], cwd=self.root, check=False, capture_output=True
        )
        return result.returncode == 0
