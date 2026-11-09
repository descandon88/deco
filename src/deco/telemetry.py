"""Observabilidad: una fila por llamada al modelo (tokens, latencia, costo, herramientas, errores).

Se guarda append-only en el brain (telemetry/llm_calls-AAAA-MM.jsonl) y se carga en DuckDB
como tabla `llm_calls`, con marts de uso diario y por sesión. No se commitea en cada llamada:
viaja con el próximo commit del brain.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from deco.memory import Brain


def _usage(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    return getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)


def _cost(response: Any) -> float | None:
    """Costo en USD según los precios públicos que conoce LiteLLM (None si no lo sabe).

    En planes gratuitos (ej. Groq free) es el costo "de lista": sirve para comparar modelos.
    """
    if not type(response).__module__.startswith("litellm"):
        return None
    try:
        import litellm

        return float(litellm.completion_cost(completion_response=response))
    except Exception:
        return None


@dataclass
class Telemetry:
    brain: Brain | None
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    calls: list[dict] = field(default_factory=list)

    def record(
        self,
        *,
        model: str,
        response: Any = None,
        latency_ms: int,
        waited_s: float = 0.0,
        tool_calls: list[str] | None = None,
        status: str = "ok",
        error: str | None = None,
        loop_trimmed: bool = False,
    ) -> dict:
        prompt_tokens, completion_tokens = _usage(response) if response is not None else (None, None)
        row = {
            "call_id": uuid.uuid4().hex,
            "session_id": self.session_id,
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "waited_s": round(waited_s, 1),
            "cost_usd": _cost(response) if response is not None else None,
            "tool_calls": tool_calls or [],
            "status": status,
            "error": (error or "")[:300] or None,
            "loop_trimmed": loop_trimmed,
        }
        self.calls.append(row)
        if self.brain is not None:
            path = self.brain.resolve(f"telemetry/llm_calls-{datetime.now(UTC):%Y-%m}.jsonl")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def summary(self) -> dict:
        """Resumen de la sesión actual (para /stats)."""
        ok = [c for c in self.calls if c["status"] == "ok"]
        prompt = sum(c["prompt_tokens"] or 0 for c in ok)
        completion = sum(c["completion_tokens"] or 0 for c in ok)
        costs = [c["cost_usd"] for c in ok if c["cost_usd"] is not None]
        return {
            "llamadas": len(self.calls),
            "errores": len(self.calls) - len(ok),
            "tokens_entrada": prompt,
            "tokens_salida": completion,
            "costo_usd": round(sum(costs), 4) if costs else None,
            "latencia_promedio_ms": round(sum(c["latency_ms"] for c in ok) / len(ok)) if ok else None,
            "espera_rate_limit_s": round(sum(c["waited_s"] for c in self.calls), 1),
            "herramientas": sum(len(c["tool_calls"]) for c in ok),
            "bucles_cortados": sum(c["loop_trimmed"] for c in ok),
        }
