"""El loop agéntico: modelo -> (tool calls -> resultados)* -> respuesta final.

`completion` es inyectable (por defecto litellm.completion), así se puede
cambiar de proveedor (Anthropic, Groq, Ollama...) o testear sin red.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from deco.context import build_system_prompt
from deco.memory import Brain
from deco.telemetry import Telemetry
from deco.tools import TOOL_SPECS, Toolbox

MAX_STEPS = 12
MAX_RATE_LIMIT_WAITS = 5
MAX_WAIT_SECONDS = 65

MAX_REPEATED_TOKENS = 25

OnToolFn = Callable[[str, str], None]
OnWaitFn = Callable[[float], None]

_RETRY_IN = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s", re.IGNORECASE)


def trim_repetition(text: str) -> str:
    """Corta la respuesta si el modelo entra en un bucle (el mismo token repetido muchas veces)."""
    words = list(re.finditer(r"\S+", text))
    run_start = 0
    for i in range(1, len(words)):
        if words[i].group() != words[i - 1].group():
            run_start = i
        elif i - run_start + 1 >= MAX_REPEATED_TOKENS:
            cut = words[run_start].start()
            return text[:cut].rstrip() + "\n\n[respuesta cortada: el modelo entró en un bucle]"
    return text


def _rate_limit_wait(exc: Exception) -> float | None:
    """Si el error es un rate limit, devuelve cuántos segundos esperar (o None)."""
    text = str(exc)
    if "RateLimit" not in type(exc).__name__ and "rate_limit" not in text.lower():
        return None
    match = _RETRY_IN.search(text)
    if not match:
        return 20.0
    minutes = float(match.group(1) or 0)
    return min(minutes * 60 + float(match.group(2)) + 1.0, MAX_WAIT_SECONDS)


def _default_completion(**kwargs: Any) -> Any:
    import litellm  # import diferido: arranque rápido y tests sin red

    litellm.suppress_debug_info = True  # sin el texto "Give Feedback" en cada error
    return litellm.completion(**kwargs)


class Agent:
    def __init__(
        self,
        brain: Brain,
        toolbox: Toolbox,
        model: str,
        completion: Callable[..., Any] = _default_completion,
        language: str = "es",
        temperature: float = 0.7,
        max_tokens: int = 2500,
    ):
        self.brain = brain
        self.toolbox = toolbox
        self.model = model
        self.completion = completion
        self.language = language
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.messages: list[dict] = [{"role": "system", "content": build_system_prompt(brain, language)}]
        self.on_wait: OnWaitFn | None = None
        self.sleep: Callable[[float], None] = time.sleep
        self.telemetry = Telemetry(brain=None)  # la CLI la reemplaza por una que escribe en el brain

    def set_language(self, language: str) -> None:
        """Cambia el idioma en caliente: reescribe el prompt del sistema (se valida antes)."""
        prompt = build_system_prompt(self.brain, language)
        self.language = language
        self.messages[0] = {"role": "system", "content": prompt}

    def _complete(self) -> tuple[Any, int, float]:
        """Llama al modelo; ante un rate limit espera lo que pide el proveedor y reintenta.

        Devuelve (respuesta, latencia_ms de la llamada exitosa, segundos esperados por rate limit).
        """
        waited = 0.0
        for attempt in range(MAX_RATE_LIMIT_WAITS + 1):
            start = time.perf_counter()
            try:
                response = self.completion(
                    model=self.model,
                    messages=self.messages,
                    tools=TOOL_SPECS,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                return response, int((time.perf_counter() - start) * 1000), waited
            except Exception as exc:
                wait = _rate_limit_wait(exc)
                if wait is None or attempt == MAX_RATE_LIMIT_WAITS:
                    self.telemetry.record(
                        model=self.model,
                        latency_ms=int((time.perf_counter() - start) * 1000),
                        waited_s=waited,
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    raise
                if self.on_wait:
                    self.on_wait(wait)
                self.sleep(wait)
                waited += wait
        raise RuntimeError("unreachable")

    def ask(self, user_text: str, on_tool: OnToolFn | None = None) -> str:
        checkpoint = len(self.messages)
        try:
            return self._ask(user_text, on_tool)
        except Exception:
            # si falla (rate limit, red...), no dejar la pregunta "colgada" en el historial
            del self.messages[checkpoint:]
            raise

    def _ask(self, user_text: str, on_tool: OnToolFn | None = None) -> str:
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(MAX_STEPS):
            response, latency_ms, waited = self._complete()
            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []
            clean = None if tool_calls else trim_repetition(msg.content or "")
            self.telemetry.record(
                model=self.model,
                response=response,
                latency_ms=latency_ms,
                waited_s=waited,
                tool_calls=[tc.function.name for tc in tool_calls],
                loop_trimmed=clean is not None and clean != (msg.content or ""),
            )

            assistant: dict = {"role": "assistant", "content": msg.content}
            if tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ]
            self.messages.append(assistant)

            if clean is not None:
                assistant["content"] = clean  # no guardar el bucle en el historial
                return clean

            for tc in tool_calls:
                if on_tool:
                    on_tool(tc.function.name, tc.function.arguments)
                result = self.toolbox.call(tc.function.name, tc.function.arguments)
                self.messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "name": tc.function.name, "content": result}
                )
        return "(Corté el loop: demasiados pasos de herramientas. Reformulá la pregunta.)"
