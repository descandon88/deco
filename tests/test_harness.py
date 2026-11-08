"""Tests sin red: brain temporal + modelo falso."""

from __future__ import annotations

import json
import shutil
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import pytest

from deco.agent import Agent
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
