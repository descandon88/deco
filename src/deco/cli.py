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
from deco.config import load_settings
from deco.context import load_prompt
from deco.db import build_db, run_query
from deco.memory import Brain
from deco.tools import Toolbox

app = typer.Typer(help="Deco: mentor de IA con memoria propia.", no_args_is_help=True)
console = Console()

HELP = """[bold]Comandos dentro del chat[/bold]
  /checkin            check-in guiado del día
  /jd <archivo>       analizar una descripción de puesto
  /mock <tema>        entrevista simulada (ej: /mock sql window functions)
  /roadmap \\[foco]     roadmap de 4 semanas basado en datos
  /weekly             revisión semanal
  /model <nombre>     cambiar de modelo en caliente
  /help  /salir"""


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
    return Agent(brain, toolbox, model=model or settings.model)


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
    if cmd == "/weekly":
        return load_prompt("weekly")
    console.print(f"[yellow]Comando desconocido: {cmd}[/yellow]")
    return None


def _answer(agent: Agent, text: str) -> None:
    with console.status("[cyan]pensando...[/cyan]"):
        reply = agent.ask(text, on_tool=_on_tool)
    console.print(Markdown(reply))


@app.command()
def chat(model: str | None = typer.Option(None, help="Override del modelo (formato LiteLLM).")):
    """Sesión interactiva."""
    agent = _make_agent(model)
    console.print(Panel(f"Deco · modelo: [bold]{agent.model}[/bold]\n{HELP}"))
    while True:
        try:
            line = console.input("[bold green]tú ›[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("/salir", "/exit", "/quit"):
            break
        if line == "/help":
            console.print(HELP)
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
    if not s.db_path.exists():
        build_db(Brain(s.brain_path), s.db_path)
    cols, rows = run_query(s.db_path, query)
    table = Table(*cols)
    for r in rows:
        table.add_row(*["" if v is None else str(v) for v in r])
    console.print(table)


if __name__ == "__main__":
    app()
