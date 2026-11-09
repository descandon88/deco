"""Construcción y consulta de la DuckDB derivada del brain."""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import yaml

from deco.memory import Brain

SCHEMA = Path(__file__).with_name("schema.sql")
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _frontmatter(path: Path) -> dict:
    match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    return (yaml.safe_load(match.group(1)) or {}) if match else {}


def build_db(brain: Brain, db_path: Path) -> dict[str, int]:
    """Reconstruye la base desde cero (es derivada: idempotente)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA.read_text(encoding="utf-8"))

    # skills.yaml
    skills_file = brain.root / "skills.yaml"
    data = yaml.safe_load(skills_file.read_text(encoding="utf-8")) if skills_file.exists() else {}
    for domain, items in (data or {}).get("domains", {}).items():
        for s in items or []:
            con.execute(
                "INSERT INTO skills VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    s["id"],
                    domain,
                    s.get("name", s["id"]),
                    int(s.get("level", 0)),
                    int(s.get("target", 3)),
                    list(s.get("evidence") or []),
                    s.get("notes"),
                ],
            )

    # events/*.jsonl
    for f in sorted((brain.root / "events").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            con.execute(
                "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    e["event_id"],
                    e["ts"],
                    e["type"],
                    e.get("domain"),
                    list(e.get("skills") or []),
                    e.get("summary"),
                    e.get("score"),
                    e.get("duration_min"),
                    e.get("source_ref"),
                ],
            )

    # projects/*.md
    for f in sorted((brain.root / "projects").glob("*.md")):
        if f.name.startswith("_"):
            continue
        fm = _frontmatter(f)
        con.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                fm.get("id", f.stem),
                fm.get("name", f.stem),
                fm.get("status"),
                fm.get("repo_url"),
                list(fm.get("domains") or []),
                list(fm.get("skills") or []),
                str(f.relative_to(brain.root)),
            ],
        )

    # jobs/*.md
    for f in sorted((brain.root / "jobs").glob("*.md")):
        if f.name.startswith("_"):
            continue
        fm = _frontmatter(f)
        job_id = fm.get("id", f.stem)
        con.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
            [
                job_id,
                fm.get("company"),
                fm.get("title"),
                fm.get("url"),
                fm.get("captured_at"),
                str(f.relative_to(brain.root)),
            ],
        )
        for r in fm.get("requirements") or []:
            con.execute(
                "INSERT INTO job_requirements VALUES (?, ?, ?)",
                [job_id, r["skill"], r.get("importance", "must")],
            )

    # telemetry/*.jsonl (observabilidad)
    for f in sorted((brain.root / "telemetry").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            con.execute(
                "INSERT OR IGNORE INTO llm_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    c["call_id"],
                    c.get("session_id"),
                    c.get("ts"),
                    c.get("model"),
                    c.get("prompt_tokens"),
                    c.get("completion_tokens"),
                    c.get("latency_ms"),
                    c.get("waited_s"),
                    c.get("cost_usd"),
                    list(c.get("tool_calls") or []),
                    c.get("status"),
                    c.get("error"),
                    c.get("loop_trimmed"),
                ],
            )

    counts = {
        t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("skills", "events", "projects", "jobs", "job_requirements", "llm_calls")
    }
    con.close()
    return counts


_READ_ONLY = re.compile(r"^\s*(select|with|describe|show|summarize)\b", re.IGNORECASE)


def run_query(db_path: Path, sql: str, max_rows: int = 25) -> tuple[list[str], list[tuple]]:
    """Consulta SOLO lectura: el agente puede mirar, nunca modificar."""
    if not _READ_ONLY.match(sql) or ";" in sql.strip().rstrip(";"):
        raise ValueError("Solo se permite una consulta SELECT/WITH/DESCRIBE/SHOW.")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        return cols, cur.fetchmany(max_rows)
    finally:
        con.close()
