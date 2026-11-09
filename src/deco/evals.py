"""`deco eval`: mide el comportamiento de Deco con casos fijos sobre un brain FICTICIO.

Cada caso corre en una copia limpia de evals/demo_brain, con un agente nuevo y sin permiso
para escribir memoria. Los checks son deterministas (texto, herramientas usadas, citas), así
que un mismo modelo y prompt dan resultados comparables entre versiones.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

import deco
from deco.agent import Agent
from deco.config import Settings
from deco.memory import Brain
from deco.tools import Toolbox

REPO_ROOT = Path(deco.__file__).resolve().parents[2]
EVALS_DIR = REPO_ROOT / "evals"
_CITATION = re.compile(r"[\w./-]+\.(?:md|yaml)\b|fuentes?:", re.IGNORECASE)


def normalize(text: str) -> str:
    """Minúsculas y sin tildes, para comparar sin depender de la ortografía del modelo."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


@dataclass
class CheckResult:
    check: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    id: str
    passed: bool
    checks: list[CheckResult]
    answer: str
    tools_used: list[str]
    tokens: int
    latency_ms: int
    error: str | None = None


def evaluate(case: dict, answer: str, tools_used: list[str]) -> list[CheckResult]:
    text = normalize(answer)
    results: list[CheckResult] = []
    if phrases := case.get("must_include_all"):
        missing = [p for p in phrases if normalize(p) not in text]
        results.append(CheckResult("must_include_all", not missing, f"faltan: {missing}" if missing else ""))
    if phrases := case.get("must_include_any"):
        ok = any(normalize(p) in text for p in phrases)
        results.append(CheckResult("must_include_any", ok, "" if ok else "no apareció ninguna"))
    if phrases := case.get("must_not_include"):
        found = [p for p in phrases if normalize(p) in text]
        results.append(CheckResult("must_not_include", not found, f"apareció: {found}" if found else ""))
    if tools := case.get("must_call_tool"):
        tools = [tools] if isinstance(tools, str) else tools
        ok = any(t in tools_used for t in tools)
        results.append(CheckResult("must_call_tool", ok, "" if ok else f"usó: {tools_used or 'ninguna'}"))
    if case.get("cites_source"):
        ok = bool(_CITATION.search(answer))
        results.append(CheckResult("cites_source", ok, "" if ok else "no citó archivos del brain"))
    if (limit := case.get("max_questions")) is not None:
        n = answer.count("?")
        results.append(CheckResult("max_questions", n <= limit, f"{n} preguntas (máx. {limit})"))
    return results


def run_case(case: dict, demo_brain: Path, model: str, completion: Any = None) -> CaseResult:
    from deco.cli import _expand_command  # import diferido: evita ciclos

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "brain"
        shutil.copytree(demo_brain, root)
        settings = Settings(
            brain_path=root,
            model=model,
            fast_model=model,
            db_path=root / ".cache" / "brain.duckdb",
            auto_commit=False,
        )
        brain = Brain(root)
        toolbox = Toolbox(brain, settings, confirm=lambda *_: False)  # evals nunca escriben memoria
        kwargs = {"completion": completion} if completion else {}
        agent = Agent(brain, toolbox, model=model, temperature=0.3, **kwargs)
        tools_used: list[str] = []
        text = case.get("question") or _expand_command(case["command"]) or ""
        start = time.perf_counter()
        try:
            answer = agent.ask(text, on_tool=lambda name, _args: tools_used.append(name))
            error = None
        except Exception as exc:
            answer, error = "", f"{type(exc).__name__}: {exc}"[:300]
        latency = int((time.perf_counter() - start) * 1000)
        summary = agent.telemetry.summary()
        tokens = summary["tokens_entrada"] + summary["tokens_salida"]

    checks = [CheckResult("sin_error", False, error)] if error else evaluate(case, answer, tools_used)
    return CaseResult(
        id=case["id"],
        passed=all(c.passed for c in checks),
        checks=checks,
        answer=answer,
        tools_used=tools_used,
        tokens=tokens,
        latency_ms=latency,
        error=error,
    )


@dataclass
class EvalReport:
    model: str
    started_at: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def score(self) -> float:
        return sum(r.passed for r in self.results) / len(self.results) if self.results else 0.0

    def save(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        safe_model = re.sub(r"[^\w.-]+", "_", self.model)
        path = folder / f"{self.started_at.replace(':', '')}_{safe_model}.json"
        payload = {
            "model": self.model,
            "started_at": self.started_at,
            "score": round(self.score, 3),
            "results": [asdict(r) for r in self.results],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def load_cases(path: Path, only: str | None = None) -> list[dict]:
    cases = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [c for c in cases if only is None or c["id"] == only]


def run_evals(model: str, cases: list[dict], demo_brain: Path, on_result=None) -> EvalReport:
    report = EvalReport(model=model, started_at=datetime.now().isoformat(timespec="seconds"))
    for case in cases:
        result = run_case(case, demo_brain, model)
        report.results.append(result)
        if on_result:
            on_result(result)
    return report
