"""Tests sin red: brain temporal + modelo falso."""

from __future__ import annotations

import json
import shutil
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import pytest

from deco.agent import Agent, trim_repetition
from deco.cli import _expand_command
from deco.config import Settings
from deco.db import build_db, run_query
from deco.memory import Brain
from deco.tools import Toolbox


@pytest.fixture()
def brain(tmp_path: Path) -> Brain:
    shutil.copytree(Path(str(files("deco") / "brain_template")), tmp_path / "brain")
    b = Brain(tmp_path / "brain")
    b.write(
        "jobs/acme-ae.md",
        "---\nid: acme-ae\ncompany: Acme\ntitle: AE\n"
        "requirements:\n  - {skill: dbt, importance: must}\n"
        "  - {skill: spark, importance: nice}\n---\n# Acme\n",
    )
    return b


@pytest.fixture()
def settings(brain: Brain, tmp_path: Path) -> Settings:
    return Settings(
        brain_path=brain.root,
        model="fake",
        fast_model="fake",
        db_path=tmp_path / "brain.duckdb",
        auto_commit=False,
    )


def test_path_traversal_blocked(brain: Brain):
    with pytest.raises(ValueError):
        brain.resolve("../../etc/passwd")


def test_search_finds_skill(brain: Brain):
    hits = brain.search("window functions")
    assert any(h["path"] == "skills.yaml" for h in hits)


def test_build_db_and_gaps(brain: Brain, settings: Settings):
    brain.append_event({"type": "mock_interview", "summary": "mock dbt", "skills": ["dbt"], "score": 6})
    counts = build_db(brain, settings.db_path)
    assert counts["skills"] > 5 and counts["events"] == 1 and counts["jobs"] == 1
    _, rows = run_query(
        settings.db_path,
        "select skill_id, jobs_requiring, avg_mock_score from mart_skill_gaps where skill_id = 'dbt'",
    )
    assert rows == [("dbt", 1, 6.0)]
    _, unmapped = run_query(settings.db_path, "select * from mart_unmapped_requirements")
    assert unmapped == [("spark", 1)]


def test_query_db_is_read_only(settings: Settings, brain: Brain):
    build_db(brain, settings.db_path)
    with pytest.raises(ValueError):
        run_query(settings.db_path, "drop table skills")
    with pytest.raises(ValueError):
        run_query(settings.db_path, "select 1; drop table skills")


def test_propose_update_respects_rejection(brain: Brain, settings: Settings):
    tb = Toolbox(brain, settings, confirm=lambda *_: False)
    out = tb.call("propose_note_update", {"path": "profile.md", "new_content": "hack", "reason": "x"})
    assert out.startswith("RECHAZADO")
    assert "hack" not in brain.read("profile.md")


def _tool_call(name: str, args: dict):
    fn = SimpleNamespace(name=name, arguments=json.dumps(args))
    return SimpleNamespace(id=f"call_{name}", function=fn)


def test_agent_loop_uses_tools(brain: Brain, settings: Settings):
    script = [
        SimpleNamespace(
            content=None,
            tool_calls=[_tool_call("query_db", {"sql": "select skill_id from mart_skill_gaps limit 1"})],
        ),
        SimpleNamespace(content="Tu mayor brecha está en [skills.yaml].", tool_calls=None),
    ]
    seen: list[list[dict]] = []

    def fake_completion(**kwargs):
        seen.append(list(kwargs["messages"]))
        return SimpleNamespace(choices=[SimpleNamespace(message=script[len(seen) - 1])])

    agent = Agent(
        brain, Toolbox(brain, settings, confirm=lambda *_: True), "fake", completion=fake_completion
    )
    answer = agent.ask("¿qué estudio primero?")
    assert "brecha" in answer
    tool_msgs = [m for m in agent.messages if m["role"] == "tool"]
    assert tool_msgs and "skill_id" in tool_msgs[0]["content"]
    assert "Perfil de David" in seen[0][0]["content"]  # el contexto incluye el perfil


def test_failed_ask_does_not_leave_dangling_message(brain: Brain, settings: Settings):
    def boom(**kwargs):
        raise RuntimeError("rate limit")

    agent = Agent(brain, Toolbox(brain, settings, confirm=lambda *_: True), "fake", completion=boom)
    before = len(agent.messages)
    with pytest.raises(RuntimeError):
        agent.ask("/roadmap")
    assert len(agent.messages) == before


class FakeRateLimitError(Exception):
    pass


def test_rate_limit_waits_and_retries(brain: Brain, settings: Settings):
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FakeRateLimitError("rate_limit_exceeded. Please try again in 2.055s.")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))]
        )

    agent = Agent(brain, Toolbox(brain, settings, confirm=lambda *_: True), "fake", completion=flaky)
    waits: list[float] = []
    agent.sleep = waits.append
    assert agent.ask("hola") == "ok"
    assert calls["n"] == 2
    assert 3.0 <= waits[0] < 3.1  # 2.055s + 1s de margen


def test_language_switch_rewrites_system_prompt(brain: Brain, settings: Settings):
    agent = Agent(brain, Toolbox(brain, settings, confirm=lambda *_: True), "fake", language="es")
    assert "español" in agent.messages[0]["content"]
    agent.set_language("en")
    assert "Always answer in English" in agent.messages[0]["content"]
    with pytest.raises(ValueError):
        agent.set_language("fr")
    assert agent.language == "en"  # un idioma inválido no rompe el estado


def test_db_is_rebuilt_each_session(brain: Brain, settings: Settings):
    build_db(brain, settings.db_path)  # DB "vieja"
    skills = brain.read("skills.yaml").replace(
        "id: dbt\n      name: dbt (modelos, tests, docs, macros, incrementales)\n      level: 0",
        "id: dbt\n      name: dbt (modelos, tests, docs, macros, incrementales)\n      level: 2",
    )
    brain.write("skills.yaml", skills)
    tb = Toolbox(brain, settings, confirm=lambda *_: True)  # nueva sesión
    out = tb.call("query_db", {"sql": "select level from skills where skill_id = 'dbt'"})
    assert out.splitlines()[1] == "2"


def test_learn_command_expands(brain: Brain):
    prompt = _expand_command("/learn dbt incremental models")
    assert prompt.startswith("Modo APRENDER") and prompt.endswith("dbt incremental models")


def test_trim_repetition_cuts_loops():
    looping = "Pregunta 3: ¿qué aprendiste?  " + "---   " * 200
    out = trim_repetition(looping)
    assert out.startswith("Pregunta 3: ¿qué aprendiste?")
    assert "bucle" in out and out.count("---") < 5
    normal = "Una respuesta normal con - guiones - y texto."
    assert trim_repetition(normal) == normal


def test_banner_matches_logo_grid():
    from deco.banner import ROW_COLORS, WORD, banner_lines

    lines = banner_lines()
    assert len(lines) == len(WORD) == len(ROW_COLORS) == 7
    assert all("██" in line for line in lines)


def test_dog_icon_renders_half_blocks():
    from deco.banner import DOG, dog_lines

    assert all(len(row) == len(DOG[0]) for row in DOG) and len(DOG) % 2 == 0
    lines = dog_lines()
    assert len(lines) == len(DOG) // 2
    assert any("▀" in line.plain for line in lines)


# ---------- observabilidad ----------
def _resp(content=None, tool_calls=None, prompt=100, completion=20):
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def test_telemetry_records_calls_and_loads_into_marts(brain: Brain, settings: Settings):
    from deco.telemetry import Telemetry

    script = [
        _resp(tool_calls=[_tool_call("query_db", {"sql": "select 1"})]),
        _resp(content="Listo [profile.md]"),
    ]
    agent = Agent(
        brain,
        Toolbox(brain, settings, confirm=lambda *_: True),
        "fake/model",
        completion=lambda **kw: script.pop(0),
    )
    agent.telemetry = Telemetry(brain=brain)
    agent.ask("hola")
    s = agent.telemetry.summary()
    assert s["llamadas"] == 2 and s["tokens_entrada"] == 200 and s["herramientas"] == 1

    counts = build_db(brain, settings.db_path)
    assert counts["llm_calls"] == 2
    _, rows = run_query(settings.db_path, "select calls, prompt_tokens from mart_llm_usage_daily")
    assert rows == [(2, 200)]
    _, tools = run_query(settings.db_path, "select tool, uses from mart_tool_usage")
    assert tools == [("query_db", 1)]


def test_telemetry_records_errors(brain: Brain, settings: Settings):
    def boom(**kw):
        raise RuntimeError("caída de red")

    agent = Agent(brain, Toolbox(brain, settings, confirm=lambda *_: True), "fake", completion=boom)
    with pytest.raises(RuntimeError):
        agent.ask("hola")
    assert agent.telemetry.summary()["errores"] == 1


# ---------- doctor ----------
def test_doctor_detects_wrong_key_format(monkeypatch, settings: Settings):
    from dataclasses import replace

    from deco.doctor import FAIL, check_model

    monkeypatch.setenv("GROQ_API_KEY", "grok_abc")
    checks = check_model(replace(settings, model="groq/openai/gpt-oss-120b"))
    key = next(c for c in checks if c.name == "API key")
    assert key.status == FAIL and "gsk_" in key.detail


def test_doctor_detects_shadow_package(tmp_path: Path):
    from deco.doctor import FAIL, check_package_location

    (tmp_path / "deco").mkdir()
    (tmp_path / "deco" / "__init__.py").write_text("")
    assert check_package_location(cwd=tmp_path).status == FAIL


def test_doctor_brain_content_ok(settings: Settings):
    from deco.doctor import FAIL, check_brain_content

    checks = check_brain_content(settings)
    assert all(c.status != FAIL for c in checks)


# ---------- evals ----------
def test_eval_checks_are_accent_and_case_insensitive():
    from deco.evals import evaluate

    case = {
        "must_include_any": ["no tengo registro"],
        "must_not_include": ["sí, tenés"],
        "cites_source": True,
        "max_questions": 1,
        "must_call_tool": ["query_db"],
    }
    results = {
        r.check: r.passed
        for r in evaluate(case, "No TENGO registro de Kafka. Fuentes: skills.yaml", ["query_db"])
    }
    assert all(results.values())
    bad = {r.check: r.passed for r in evaluate(case, "Sí, tenés mucha. ¿Algo más? ¿Y vos?", [])}
    assert not any(bad.values())


def test_run_case_on_demo_brain_with_fake_model():
    from deco.evals import EVALS_DIR, load_cases, run_case

    case = load_cases(EVALS_DIR / "questions.yaml", only="prioriza-con-datos")[0]
    script = [
        _resp(tool_calls=[_tool_call("query_db", {"sql": "select skill_id from mart_skill_gaps limit 1"})]),
        _resp(content="Empezá por Databricks. Fuentes: query mart_skill_gaps"),
    ]
    result = run_case(case, EVALS_DIR / "demo_brain", "fake", completion=lambda **kw: script.pop(0))
    assert result.passed, result.checks
    assert result.tools_used == ["query_db"] and result.tokens == 240


def test_demo_brain_is_consistent(tmp_path: Path):
    import shutil as sh

    from deco.evals import EVALS_DIR

    root = tmp_path / "demo"
    sh.copytree(EVALS_DIR / "demo_brain", root)
    counts = build_db(Brain(root), tmp_path / "demo.duckdb")
    assert counts["jobs"] == 1 and counts["projects"] == 1
    _, rows = run_query(tmp_path / "demo.duckdb", "select count(*) from mart_unmapped_requirements")
    assert rows == [(0,)]


def test_eval_length_and_table_checks():
    from deco.evals import evaluate

    case = {"max_words": 10, "no_tables": True}
    short = {r.check: r.passed for r in evaluate(case, "Empezá por SQL con CTEs.", [])}
    assert all(short.values())
    long_table = "palabra " * 20 + "\n| a | b |\n|---|---|"
    bad = {r.check: r.passed for r in evaluate(case, long_table, [])}
    assert not bad["max_words"] and not bad["no_tables"]


def test_system_prompt_includes_priorities_and_feedback(brain: Brain, settings: Settings):
    from deco.context import build_system_prompt

    brain.write(
        "interviews/2026-11-acme.md", "# Acme\n## Fortalezas\n- modelado\n## A fortalecer\n1. SQL en vivo\n"
    )
    prompt = build_system_prompt(brain, "es", settings.db_path)
    priorities = prompt.split("# PRIORIDADES ACTUALES")[1].split("# ÚLTIMO FEEDBACK")[0]
    assert "1. " in priorities
    feedback = prompt.split("# ÚLTIMO FEEDBACK EXTERNO")[1].split("# ÍNDICE")[0]
    assert "SQL en vivo" in feedback and "modelado" not in feedback
