"""El loop agéntico: modelo -> (tool calls -> resultados)* -> respuesta final.

`completion` es inyectable (por defecto litellm.completion), así se puede
cambiar de proveedor (Anthropic, Groq, Ollama...) o testear sin red.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from deco.context import build_system_prompt
from deco.memory import Brain
from deco.tools import TOOL_SPECS, Toolbox

MAX_STEPS = 12

OnToolFn = Callable[[str, str], None]


def _default_completion(**kwargs: Any) -> Any:
    import litellm  # import diferido: arranque rápido y tests sin red

    return litellm.completion(**kwargs)


class Agent:
    def __init__(
        self, brain: Brain, toolbox: Toolbox, model: str, completion: Callable[..., Any] = _default_completion
    ):
        self.brain = brain
        self.toolbox = toolbox
        self.model = model
        self.completion = completion
        self.messages: list[dict] = [{"role": "system", "content": build_system_prompt(brain)}]

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
            response = self.completion(
                model=self.model,
                messages=self.messages,
                tools=TOOL_SPECS,
                temperature=0.3,
                num_retries=3,  # reintenta con espera ante rate limits
            )
            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []

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

            if not tool_calls:
                return msg.content or ""

            for tc in tool_calls:
                if on_tool:
                    on_tool(tc.function.name, tc.function.arguments)
                result = self.toolbox.call(tc.function.name, tc.function.arguments)
                self.messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "name": tc.function.name, "content": result}
                )
        return "(Corté el loop: demasiados pasos de herramientas. Reformulá la pregunta.)"
