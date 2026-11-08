# Decisiones de arquitectura

Registro de decisiones (estilo ADR liviano). Cada una con contexto, decisión y consecuencias.
Fecha de inicio: 2026-11-07.

## D1 — La memoria vive fuera del modelo
- **Contexto**: los chats de IA no recuerdan entre sesiones, comprimen el contexto en
  conversaciones largas y pueden alucinar datos sobre mí.
- **Decisión**: el modelo es intercambiable y sin estado. La memoria es mía: archivos de texto
  versionados en git + una DuckDB derivada.
- **Consecuencia**: puedo cambiar de proveedor sin perder nada y auditar cada cambio.

## D2 — Tres repositorios separados
| Repo | Visibilidad | Contenido |
|---|---|---|
| `deco` | Público | Código, esquema, plantillas, evals. Genérico y reutilizable. |
| `david-library` | Público | Conocimiento curado escrito por mí: conceptos, resúmenes, rúbricas (`standards/`), `sources.yaml`. |
| `david-brain` | **Privado** | Todo lo personal: perfil, skills, journal, eventos, puestos, entrevistas. |

- Un repo público se puede ver y clonar, pero nadie puede modificarlo sin permiso.
- Docs descargadas e índices de embeddings: caché local, no se versionan (se regeneran).
- Material con derechos de autor (libros, cursos pagos): solo local, nunca público.
- Para mostrar el sistema funcionando: brain de demo con datos ficticios.

## D3 — Fuente de verdad en texto, todo lo demás es derivado
- `markdown`/`yaml`/`jsonl` son la verdad. DuckDB e índices se reconstruyen (`deco build-db`).
- Eventos de aprendizaje: append-only (`events/AAAA-MM.jsonl`), como una tabla de hechos.

## D4 — Anti-alucinación por diseño
- Citas obligatorias a archivos del brain; si no hay evidencia, decirlo.
- Hechos (escritos por mí) vs. inferencias (del modelo), marcadas explícitamente.
- Un nivel de skill solo sube con evidencia verificable.
- El CV solo usa experiencia respaldada.
- SQL solo lectura; rutas limitadas al brain; cambios de memoria como diff con aprobación humana.

## D5 — Para construir, la precisión sale de verificar
- Grounding en metadata real (esquemas, `manifest.json` de dbt, definiciones de métricas).
- Verificación por ejecución: compilar, lintear, correr en dev, testear, reconciliar con números conocidos.
- Patrón: el modelo propone → las herramientas verifican → yo reviso.
- Reducir alucinaciones no es eliminarlas: tests de datos + reconciliación + mi criterio.

## D6 — No reinventar lo que ya existe
- Para editar código en repos: usar Claude Code / OpenCode.
- Para dbt: evaluar el servidor MCP oficial de dbt Labs.
- Deco aporta la capa de dominio (brain, library, standards, verificación, evals) y la expone
  como servidor MCP (Fase 5) para usarla desde cualquier cliente.

## D7 — Uso en el trabajo
- Revisar la política de la empresa antes de enviar código o datos a APIs externas.
- Nada de la empresa en repos públicos ni en el brain personal. El contexto de cada proyecto
  vive en su propio repo (`AGENTS.md` + project card).
- Credenciales de solo lectura, apuntando a dev, nunca producción. Cuidado con PII.

## D8 — Infraestructura mínima
- Fase inicial: todo local (laptop) + API del modelo. Sin servidores.
- Automatizaciones: GitHub Actions con cron en el repo privado.
- VPS + Tailscale solo si necesito acceso desde el celular.
- Streaming: no requiere infra, es un cambio del cliente (`stream=True`).

## D9 — Por qué construirlo en vez de usar solo un chat
- Mismo modelo, misma inteligencia. La ganancia está en: control del contexto, datos
  estructurados del progreso, verificación contra proyectos reales, evals medibles y
  aprendizaje + portfolio de AI/Data Engineering.
- Estrategia híbrida: usar Claude (chat / Claude Code) para lo que ya resuelve; construir en
  Deco solo lo que me diferencia.

## Pendientes
- [ ] Fase 2: streaming, observabilidad de costos, router de modelos, `deco ingest-repo`.
- [ ] `david-library` + `DECO_LIBRARY_PATH` + `search_library` + `deco ingest-docs`.
- [ ] Primera rúbrica: `standards/dbt-project.md`.
- [ ] Modo "build" con verificación sobre un proyecto dbt de práctica (DuckDB + datos públicos).
- [ ] Fase 3: migrar `schema.sql` a dbt-duckdb.
- [ ] Fase 4: embeddings + búsqueda híbrida + evals en CI.
