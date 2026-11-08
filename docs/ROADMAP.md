# Roadmap de construcción

Cada fase deja algo funcionando y algo para mostrar en el portfolio.

## Fase 0 — Funcionando hoy (2-3 h)

1. **Dos repos en GitHub**
   - `deco` → **público** (este código).
   - `david-brain` → **privado** (tu memoria). Nunca lo mezcles con el público.
2. **Instalar**: `uv` (o pip) y `git`. Luego `uv venv && uv pip install -e ".[dev]"`.
3. **API key** (una alcanza para empezar):
   - Anthropic Console: cargá unos pocos dólares de créditos → modelo fuerte.
   - Groq: tiene plan gratuito con límites → modelo rápido/barato.
   - Sin presupuesto: Ollama local (modelos más flojos con herramientas).
4. `cp .env.example .env` y completá la key + `DECO_BRAIN_PATH`.
5. `deco init ~/david-brain` → `cd ~/david-brain && git remote add origin <repo-privado> && git push -u origin main`.
6. Completá **a mano** `profile.md` y `skills.yaml` (niveles honestos, con evidencia).
7. `deco chat` → `/checkin`. Listo: ya tenés un mentor con memoria.

> Plan B sin código: abrí `~/david-brain` con OpenCode o Claude Code, copiá `prompts/system.md`
> como `AGENTS.md`/`CLAUDE.md` y usalo así mientras construís el harness.

## Fase 1 — Cargar tu realidad (semana 1)

- Un `projects/<nombre>.md` por cada repo tuyo (usá la plantilla; el frontmatter alimenta la DB).
- Pegá 3-5 puestos reales con `/jd`. Después: `deco sql "select * from mart_skill_gaps limit 10"`.
- `/roadmap` y un primer `/mock`. Usalo todos los días; anotá en un issue qué falla.

## Fase 2 — Harness más sólido (semana 2)

- **Streaming** de respuestas (LiteLLM `stream=True` + armado de tool calls).
- **Observabilidad**: registrar cada llamada (modelo, tokens, costo, latencia, tools usadas) en `events/llm_calls.jsonl` → `mart_llm_costs`.
- **Router de modelos**: el modelo rápido para resúmenes; el fuerte para JDs, roadmap y mocks.
- Comando `deco ingest-repo <ruta|url>`: lee README, árbol, dependencias y commits → propone `projects/x.md`.

## Fase 3 — Capa de datos con dbt (semanas 3-4)  ← tu vitrina de AE/DE

- Migrar `schema.sql` a un proyecto **dbt-duckdb**: `sources` (jsonl/yaml) → `staging` → `intermediate` → `marts`.
- Tests (`unique`, `not_null`, `accepted_values`, relaciones), docs y linaje (`dbt docs`).
- **GitHub Actions nocturno en el repo PRIVADO**: `dbt build` + resumen semanal automático (secret con la API key).

## Fase 4 — Retrieval + evals (mes 2)  ← tu vitrina de AI Engineering

- Embeddings locales (LanceDB o sqlite-vec) + búsqueda **híbrida** (léxica + semántica).
- Runner de evals sobre `evals/questions.yaml` contra un **brain de demo con datos ficticios**; correrlo en CI.
- Ingesta de videos/cursos: `yt-dlp` + Whisper → resumen → `concepts/`.

## Fase 5 — "En producción" (mes 3)

- **Servidor MCP** que expone el brain (así lo usás desde Claude, OpenCode, etc.).
- VPS chico + Tailscale + `tmux`; opcional bot de Telegram para `/checkin` desde el celular.
- Brain de demo público + GIF de uso en el README + un post técnico explicando las decisiones.

## Agregar un dominio nuevo (ej. gobernanza, ML)

1. `/roadmap data_governance` → Deco propone los skills y targets para `skills.yaml`.
2. Aprobás el diff. A partir de ahí entra en `mart_skill_gaps`, los mocks y los roadmaps.
