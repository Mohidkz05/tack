from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import make_manifest, write

from tack import cli, doctor, install, playbook, runtime

ROUTES = """
version = 1

[[route]]
name = "3d"
group = "design"
skill = "threejs-animation"
reason = "3D scenes"
words = ["three.js", "3d"]

[[route]]
name = "ui"
group = "design"
skill = "impeccable"
reason = "Any substantial UI work"
words = ["ui", "landing page"]
files = ["*.tsx", "*.css"]

[[route]]
name = "tests"
agent = "test-writer"
project = true
reason = "Behavior-focused tests"
words = ["write tests"]

[[route]]
name = "deploy"
skill = "vercel:deployments-cicd"
plugin = "vercel@claude-plugins-official"
reason = "Deploying"
words = ["deploy"]

[[route]]
name = "claude-api"
skill = "claude-api"
builtin = true
reason = "Claude API work"
words = ["anthropic"]
"""


def make_playbook(base: Path) -> Path:
    pb = base / "pb"
    write(pb, "routes.toml", ROUTES)
    write(pb, "stacks/web-app.md", "# Web app\n")
    write(pb, "stacks/api.md", "# API\n")
    return pb


def install_skill(home: Path, name: str) -> None:
    write(home, f".claude/skills/{name}/SKILL.md", f"---\nname: {name}\n---\n")


def project_with_playbook(tmp_path: Path, isolated_home: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    pb = make_playbook(tmp_path)
    make_manifest(
        root,
        [{"name": "app", "path": ".", "stack": "node", "commands": {}}],
        playbook={"source": str(pb)},
    )
    install_skill(isolated_home, "impeccable")
    install_skill(isolated_home, "threejs-animation")
    return root, pb


def route_hook(root: Path, **event) -> str | None:
    import contextlib
    import io

    event.setdefault("cwd", str(root))
    event.setdefault("session_id", "s1")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        runtime.run_hook("route", json.dumps(event))
    out = buf.getvalue()
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else None


# --------------------------------------------------------------------- matching


def test_word_matching_is_whole_word_and_case_insensitive() -> None:
    routes = runtime.load_routes(make_playbook(Path(__import__("tempfile").mkdtemp())))
    assert [r["name"] for r in runtime.match_routes(routes, "Fix the UI please")] == ["ui"]
    assert runtime.match_routes(routes, "build a guide") == []  # "ui" inside "guide"
    assert [r["name"] for r in runtime.match_routes(routes, "new Landing Page")] == ["ui"]


def test_group_picks_most_specific_route_only(tmp_path: Path) -> None:
    routes = runtime.load_routes(make_playbook(tmp_path))
    hits = runtime.match_routes(routes, "a 3d hero for the landing page ui")
    assert [r["name"] for r in hits] == ["3d"]  # one design skill, the specific one


def test_file_matching(tmp_path: Path) -> None:
    routes = runtime.load_routes(make_playbook(tmp_path))
    assert [r["name"] for r in runtime.match_routes(routes, file="/x/src/Button.TSX")] == ["ui"]
    assert runtime.match_routes(routes, file="/x/src/server.py") == []


# --------------------------------------------------------------------- availability


def test_route_targets_resolve_by_kind(tmp_path: Path, isolated_home: Path) -> None:
    root, pb = project_with_playbook(tmp_path, isolated_home)
    routes = {r["name"]: r for r in runtime.load_routes(pb)}
    assert runtime.resolve_route_target(routes["ui"], root, set()) == "impeccable"
    assert runtime.resolve_route_target(routes["claude-api"], root, set()) == "claude-api"
    assert runtime.resolve_route_target(routes["deploy"], root, set()) is None
    assert (
        runtime.resolve_route_target(routes["deploy"], root, {"vercel@claude-plugins-official"})
        == "vercel:deployments-cicd"
    )
    assert runtime.resolve_route_target(routes["tests"], root, set()) is None
    write(root, ".claude/agents/test-writer.md", "x")
    assert runtime.resolve_route_target(routes["tests"], root, set()) == "test-writer"


def test_project_routes_fall_back_to_tack_plugin(tmp_path: Path, isolated_home: Path) -> None:
    root, pb = project_with_playbook(tmp_path, isolated_home)
    tests = next(r for r in runtime.load_routes(pb) if r["name"] == "tests")
    assert runtime.resolve_route_target(tests, root, {"tack@tack"}) == "tack:test-writer"


def test_installed_plugins_reads_registry(isolated_home: Path) -> None:
    write(
        isolated_home,
        ".claude/plugins/installed_plugins.json",
        json.dumps({"version": 2, "plugins": {"vercel@claude-plugins-official": []}}),
    )
    assert runtime.installed_plugins() == {"vercel@claude-plugins-official"}


# --------------------------------------------------------------------- hook


def test_route_hook_on_prompt(tmp_path: Path, isolated_home: Path) -> None:
    root, _ = project_with_playbook(tmp_path, isolated_home)
    ctx = route_hook(
        root, hook_event_name="UserPromptSubmit", prompt="make the landing page look better"
    )
    assert "`impeccable` skill" in ctx and "Any substantial UI work" in ctx


def test_route_hook_once_per_session(tmp_path: Path, isolated_home: Path) -> None:
    root, _ = project_with_playbook(tmp_path, isolated_home)
    ev = {"hook_event_name": "UserPromptSubmit", "prompt": "tweak the ui"}
    assert route_hook(root, **ev)
    assert route_hook(root, **ev) is None  # same session: already told
    assert route_hook(root, session_id="s2", **ev)  # new session: told again


def test_route_hook_before_editing_a_file(tmp_path: Path, isolated_home: Path) -> None:
    root, _ = project_with_playbook(tmp_path, isolated_home)
    ctx = route_hook(
        root,
        hook_event_name="PreToolUse",
        tool_name="Write",
        tool_input={"file_path": str(root / "src/App.tsx")},
    )
    assert "impeccable" in ctx


def test_route_hook_skips_uninstalled_targets(tmp_path: Path, isolated_home: Path) -> None:
    root, _ = project_with_playbook(tmp_path, isolated_home)
    assert route_hook(root, hook_event_name="UserPromptSubmit", prompt="deploy it") is None


def test_route_hook_silent_without_playbook(tmp_path: Path) -> None:
    make_manifest(tmp_path, [])
    assert route_hook(tmp_path, hook_event_name="UserPromptSubmit", prompt="ui") is None


def test_routing_can_be_disabled(tmp_path: Path, isolated_home: Path) -> None:
    root, pb = project_with_playbook(tmp_path, isolated_home)
    make_manifest(root, [], playbook={"source": str(pb)}, hooks={"routing": False})
    assert route_hook(root, hook_event_name="UserPromptSubmit", prompt="ui") is None


def test_session_start_mentions_stacks_for_new_projects(
    tmp_path: Path, isolated_home: Path
) -> None:
    from conftest import hook

    pb = make_playbook(tmp_path)
    data = runtime.default_manifest("x", status="new")
    data["playbook"] = {"source": str(pb)}
    (tmp_path / "tack.toml").write_text(runtime.dump_toml(data))
    text = hook("session-start", {"cwd": str(tmp_path)})["text"]
    assert "api, web-app" in text and "Skill routing is on" in text


# --------------------------------------------------------------------- config & sync


def test_user_config_applies_to_every_project(tmp_path: Path) -> None:
    pb = make_playbook(tmp_path)
    playbook.set_user_source(str(pb))
    m = make_manifest(tmp_path / "proj", [])
    assert runtime.find_playbook(m) == pb.resolve()


def test_project_source_overrides_user_config(tmp_path: Path) -> None:
    playbook.set_user_source("github:someone/else")
    m = make_manifest(tmp_path / "proj", [], playbook={"source": str(make_playbook(tmp_path))})
    assert runtime.playbook_source(m) == str(tmp_path / "pb")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mohidkz05/playbook", "github:Mohidkz05/playbook"),
        ("github:a/b", "github:a/b"),
        ("https://gitlab.com/a/b.git", "https://gitlab.com/a/b.git"),
    ],
)
def test_normalize_source(raw: str, expected: str) -> None:
    assert playbook.normalize(raw) == expected


def test_cache_path_for_remote_sources(isolated_home: Path) -> None:
    path = runtime.playbook_path("github:Mohidkz05/playbook")
    assert path.is_relative_to(isolated_home / ".cache" / "tack" / "playbooks")
    assert path.name == "Mohidkz05-playbook"


def test_cache_names_stay_short_for_long_urls() -> None:
    long_url = "file:///" + "/".join(["very-long-directory-name"] * 12) + "/pb"
    name = runtime.playbook_path(long_url).name
    assert len(name) < 60 and name.endswith(name[-8:]) and "pb" in name
    assert runtime.playbook_path(long_url) != runtime.playbook_path(long_url + "2")


def test_sync_clones_then_pulls(tmp_path: Path) -> None:
    upstream = make_playbook(tmp_path)
    for args in (
        ["init", "-q"],
        ["add", "."],
        ["-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "init"],
    ):
        subprocess.run(["git", *args], cwd=upstream, check=True, capture_output=True)
    source = upstream.resolve().as_uri()  # file:// counts as remote, like a GitHub URL
    first = playbook.sync(source)
    assert first.ok and first.message == "cloned" and (first.path / "routes.toml").is_file()
    second = playbook.sync(source)
    assert second.ok and second.message == "updated"


def test_cli_use_show_and_route(tmp_path: Path, monkeypatch, capsys, isolated_home: Path) -> None:
    root, pb = project_with_playbook(tmp_path, isolated_home)
    monkeypatch.chdir(root)
    assert cli.main(["playbook", "use", str(pb), "--project"]) == 0
    capsys.readouterr()
    assert cli.main(["playbook"]) == 0
    out = capsys.readouterr().out
    assert "web-app" in out and "✓ ui" in out and "✗ deploy" in out
    assert cli.main(["playbook", "route", "make", "a", "3d", "scene"]) == 0
    assert "threejs-animation" in capsys.readouterr().out


def test_doctor_reports_missing_routed_skills(tmp_path: Path, isolated_home: Path) -> None:
    root, _ = project_with_playbook(tmp_path, isolated_home)
    msgs = " | ".join(f.message for f in doctor.check(root))
    assert "route 'deploy' needs 'vercel:deployments-cicd'" in msgs
    assert "routes usable" in msgs


# --------------------------------------------------------------------- settings merge


def test_new_hooks_join_existing_groups_without_duplicates(tmp_path: Path) -> None:
    old = json.loads(install.TEMPLATES.joinpath("core/dot-claude/settings.json").read_text())
    old["hooks"].pop("UserPromptSubmit")
    for g in old["hooks"]["PreToolUse"]:
        g["hooks"] = [h for h in g["hooks"] if "hook route" not in h["command"]]
    write(tmp_path, ".claude/settings.json", json.dumps(old))
    install.install(tmp_path, install.plan(install.context_for(tmp_path)))
    merged = json.loads((tmp_path / ".claude/settings.json").read_text())
    edit_groups = [
        g for g in merged["hooks"]["PreToolUse"] if g.get("matcher", "").startswith("Edit")
    ]
    assert len(edit_groups) == 1
    assert [h["command"].split()[-1] for h in edit_groups[0]["hooks"]] == ["protect-files", "route"]
    assert "UserPromptSubmit" in merged["hooks"]
