"""CLI `deco`: la terminal de Deco."""

from __future__ import annotations

import shutil
import subprocess
from importlib.resources import as_file, files
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.table import Table

from deco.agent import Agent
from deco.banner import print_banner
from deco.config import load_settings
from deco.context import load_prompt
from deco.db import build_db, run_query
from deco.memory import Brain
from deco.telemetry import Telemetry
from deco.tools import Toolbox

# app = typer.Typer(help="Deco: mentor de IA con memoria propia. Sin argumentos abre el chat.")
app = typer.Typer(help="Deco: asesor técnico de IA con memoria propia. Sin argumentos abre el chat.")
console = Console()

HELP = """[bold]Comandos dentro del chat[/bold]
  /checkin            check-in guiado del día
  /jd <archivo>       analizar una descripción de puesto
  /mock <tema>        entrevista simulada (ej: /mock sql window functions)
  /roadmap \\[foco]     roadmap de 4 semanas basado en datos
  /weekly             revisión semanal
  /learn <tema>       explicación + preguntas (ej: /learn dbt incremental models)
  /lang es|en|mix     idioma de las respuestas
  /stats              tokens, costo y latencia de esta sesión
  /model <nombre>     cambiar de modelo en caliente
  /help  /salir"""

# Bienvenida mínima: solo lo básico; /help muestra la lista completa.
WELCOME = (
    "Contame en qué estás trabajando, o probá:\n"
    "  [bold]/checkin[/bold] · [bold]/roadmap[/bold] · [bold]/help[/bold]"
    "          [dim](/salir para terminar)[/dim]"
)


def _confirm(path: str, diff: str, reason: str) -> bool:
    console.print(
        Panel(Syntax(diff, "diff", word_wrap=True), title=f"Cambio propuesto: {path}", subtitle=reason)
    )
    return Confirm.ask("¿Aplicar este cambio a tu memoria?", default=False)


def _on_tool(name: str, args: str) -> None:
    console.print(f"[dim]  ↳ {name} {args[:110]}[/dim]")


def _make_agent(model: str | None = None) -> Agent:
    settings = load_settings()
    brain = Brain(settings.brain_path)
    if not brain.exists():
        console.print(f"[red]No existe el brain en {brain.root}.[/red] Corré: deco init")
        raise typer.Exit(1)
    toolbox = Toolbox(brain, settings, confirm=_confirm)
    agent = Agent(
        brain,
        toolbox,
        model=model or settings.model,
        language=settings.language,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
    agent.telemetry = Telemetry(brain=brain)
    agent.on_wait = lambda s: console.print(
        f"[yellow]  ⏳ límite de tokens del proveedor: espero {s:.0f}s y reintento...[/yellow]"
    )
    return agent


def _expand_command(line: str) -> str | None:
    cmd, _, arg = line.partition(" ")
    arg = arg.strip()
    if cmd == "/checkin":
        return load_prompt("checkin")
    if cmd == "/jd":
        if not arg:
            console.print("[yellow]Uso: /jd ruta/al/puesto.txt[/yellow]")
            return None
        jd = Path(arg).expanduser().read_text(encoding="utf-8")
        return load_prompt("jd") + "\n" + jd
    if cmd == "/mock":
        return load_prompt("mock") + " " + (arg or "elegilo vos según mis brechas")
    if cmd == "/roadmap":
        return load_prompt("roadmap") + " " + (arg or "general")
    if cmd == "/learn":
        return load_prompt("learn") + " " + (arg or "elegilo vos según mis brechas")
    if cmd == "/weekly":
        return load_prompt("weekly")
    console.print(f"[yellow]Comando desconocido: {cmd}[/yellow]")
    return None


def _print_stats(summary: dict) -> None:
    table = Table("métrica", "valor", title="Esta sesión")
    for key, value in summary.items():
        table.add_row(key.replace("_", " "), "-" if value is None else str(value))
    console.print(table)


def _print_query(sql_text: str, title: str | None = None) -> None:
    s = load_settings()
    cols, rows = run_query(s.db_path, sql_text)
    table = Table(*cols, title=title)
    for r in rows:
        table.add_row(*["" if v is None else str(v) for v in r])
    console.print(table)


def _answer(agent: Agent, text: str) -> None:
    with console.status("[cyan]pensando...[/cyan]"):
        reply = agent.ask(text, on_tool=_on_tool)
    console.print(Markdown(reply))


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Sin subcomando, `deco` abre el chat."""
    if ctx.invoked_subcommand is None:
        chat(model=None)


@app.command()
def chat(model: str | None = typer.Option(None, help="Override del modelo (formato LiteLLM).")):
    """Sesión interactiva."""
    agent = _make_agent(model)
    print_banner(console)
    # console.print(Panel(f"Deco · modelo: [bold]{agent.model}[/bold]\n{HELP}"))
    console.print(Panel(f"[dim]modelo: {agent.model}[/dim]\n{WELCOME}"))
    while True:
        try:
            line = console.input("[bold green]tú ›[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("/salir", "/exit", "/quit"):
            break
        # if line == "/help":
        if line in ("/help", "/"):
            console.print(HELP)
            continue
        if line == "/stats":
            _print_stats(agent.telemetry.summary())
            continue
        if line.startswith("/lang"):
            try:
                agent.set_language(line.partition(" ")[2].strip().lower() or agent.language)
                console.print(f"Idioma: {agent.language}")
            except ValueError as exc:
                console.print(f"[yellow]{exc}[/yellow]")
            continue
        if line.startswith("/model"):
            agent.model = line.partition(" ")[2].strip() or agent.model
            console.print(f"Modelo: {agent.model}")
            continue
        if line.startswith("/"):
            expanded = _expand_command(line)
            if expanded is None:
                continue
            line = expanded
        try:
            _answer(agent, line)
        except Exception as exc:  # errores de red / API key / límites
            console.print(f"[red]Error: {exc}[/red]")
    console.print("[dim]Hasta la próxima.[/dim]")


@app.command()
def ask(question: str, model: str | None = None):
    """Pregunta única (útil para scripts)."""
    _answer(_make_agent(model), question)


@app.command()
def init(path: Path | None = typer.Argument(None, help="Dónde crear el brain.")):
    """Crea un brain nuevo desde la plantilla e inicializa git."""
    target = (path or load_settings().brain_path).expanduser()
    if target.exists() and any(target.iterdir()):
        console.print(f"[red]{target} ya existe y no está vacío.[/red]")
        raise typer.Exit(1)
    with as_file(files("deco") / "brain_template") as template:
        shutil.copytree(template, target, dirs_exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=target, check=False)
    subprocess.run(["git", "add", "-A"], cwd=target, check=False)
    subprocess.run(["git", "commit", "-qm", "brain: init"], cwd=target, check=False)
    console.print(f"[green]Brain creado en {target}[/green]. Editá profile.md y skills.yaml.")
    console.print("Recordá: este repo va PRIVADO (GitHub privado o tu VPS).")


@app.command("build-db")
def build_db_cmd():
    """Reconstruye la DuckDB derivada desde el brain."""
    s = load_settings()
    counts = build_db(Brain(s.brain_path), s.db_path)
    console.print(f"[green]OK[/green] {s.db_path}: {counts}")


@app.command()
def sql(query: str):
    """Consulta SQL de solo lectura sobre tu brain (ej: deco sql 'select * from mart_skill_gaps')."""
    s = load_settings()
    build_db(Brain(s.brain_path), s.db_path)  # siempre fresca: el brain pudo cambiar
    cols, rows = run_query(s.db_path, query)
    table = Table(*cols)
    for r in rows:
        table.add_row(*["" if v is None else str(v) for v in r])
    console.print(table)


@app.command()
def doctor(
    ping: bool = typer.Option(False, help="Hace una llamada mínima al modelo para probar clave y modelo."),
):
    """Diagnóstico del entorno: brain, git, .env, API key, dependencias y base de datos."""
    from deco.doctor import FAIL, OK, WARN, run_all

    icons = {OK: "[green]✓[/green]", WARN: "[yellow]![/yellow]", FAIL: "[red]✗[/red]"}
    table = Table("", "chequeo", "detalle", "cómo arreglarlo", title="deco doctor")
    checks = run_all(load_settings(), ping=ping)
    for ch in checks:
        table.add_row(icons[ch.status], ch.name, ch.detail, ch.hint)
    console.print(table)
    fails = sum(ch.status == FAIL for ch in checks)
    warns = sum(ch.status == WARN for ch in checks)
    console.print(f"{fails} errores · {warns} advertencias")
    if fails:
        raise typer.Exit(1)


@app.command("eval")
def eval_cmd(
    model: str | None = typer.Option(None, help="Modelo a evaluar (por defecto, DECO_MODEL)."),
    case: str | None = typer.Option(None, help="Correr un solo caso por id."),
    min_score: float = typer.Option(0.0, help="Falla (exit 1) si el puntaje queda por debajo."),
):
    """Evals: mide el comportamiento de Deco con casos fijos sobre un brain ficticio."""
    from deco.evals import EVALS_DIR, load_cases, run_evals

    model = model or load_settings().model
    cases = load_cases(EVALS_DIR / "questions.yaml", only=case)
    if not cases:
        console.print("[red]No hay casos para correr.[/red]")
        raise typer.Exit(1)
    console.print(f"Evaluando [bold]{model}[/bold] con {len(cases)} casos (usa la API: gasta tokens)...")

    def show(r):
        mark = "[green]✓[/green]" if r.passed else "[red]✗[/red]"
        failed = "; ".join(f"{c.check}: {c.detail}" for c in r.checks if not c.passed)
        console.print(f"  {mark} {r.id}  [dim]{r.tokens} tokens · {r.latency_ms} ms[/dim]  {failed}")

    report = run_evals(model, cases, EVALS_DIR / "demo_brain", on_result=show)
    path = report.save(EVALS_DIR / "results")
    passed = sum(r.passed for r in report.results)
    console.print(
        f"\n[bold]Puntaje: {passed}/{len(report.results)} ({report.score:.0%})[/bold]  ·  detalle: {path}"
    )
    if report.score < min_score:
        raise typer.Exit(1)


@app.command()
def stats(days: int = typer.Option(7, help="Cuántos días mirar.")):
    """Uso del modelo: llamadas, tokens, costo, latencia y herramientas (observabilidad)."""
    s = load_settings()
    counts = build_db(Brain(s.brain_path), s.db_path)
    if not counts.get("llm_calls"):
        console.print("[yellow]Todavía no hay llamadas registradas. Usá `deco` un rato y volvé.[/yellow]")
        return
    _print_query(
        "select day, model, calls, errors, prompt_tokens, completion_tokens, cost_usd, "
        f"avg_latency_ms, p95_latency_ms, rate_limit_wait_s, loops_trimmed from mart_llm_usage_daily "
        f"where day >= current_date - {int(days)}",
        title=f"Uso por día (últimos {days} días)",
    )
    _print_query("select * from mart_tool_usage", title="Herramientas más usadas")


if __name__ == "__main__":
    app()
