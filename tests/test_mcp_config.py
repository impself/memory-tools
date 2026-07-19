"""Snapshot tests for MCP config renderers. Plan §2.

Each renderer must:
- emit valid JSON-serialisable dict
- include MW_CLIENT_ID in env (never empty, never a secret)
- use absolute paths only when a path is supplied
- reject empty client_id and non-absolute paths with ValidationError
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_workbench.domain.errors import ValidationError
from memory_workbench.domain.models import EndpointPlatform
from memory_workbench.mcp.config import (
    RenderInputs,
    render,
    render_claude,
    render_codex,
    render_cursor,
    to_json,
)

REPO = Path(__file__).resolve().parent.parent
DB = Path(__file__).resolve().parent / "memory.db"
CLIENT_ID = "codex-local"


def _inputs(**overrides) -> RenderInputs:
    base = {
        "client_id": CLIENT_ID,
        "platform": EndpointPlatform.CODEX,
        "profile": "installed",
        "repository_path": None,
        "db_path": None,
    }
    base.update(overrides)
    return RenderInputs(**base)


# --- installed profile --------------------------------------------------


def test_installed_codex_uses_bare_command():
    payload = render_codex(_inputs())
    server = payload["mcpServers"]["memory-workbench"]
    assert server["command"] == "memory-workbench-mcp"
    assert server["args"] == []
    assert server["env"] == {"MW_CLIENT_ID": CLIENT_ID}


def test_installed_claude_includes_env():
    payload = render_claude(_inputs(platform=EndpointPlatform.CLAUDE))
    server = payload["mcpServers"]["memory-workbench"]
    assert server["env"]["MW_CLIENT_ID"] == CLIENT_ID
    assert "MW_DB_PATH" not in server["env"]


def test_installed_cursor_round_trips_json():
    payload = render_cursor(_inputs(platform=EndpointPlatform.CURSOR))
    encoded = json.loads(to_json(payload))
    assert encoded["mcpServers"]["memory-workbench"]["command"] == "memory-workbench-mcp"


# --- repository profile -------------------------------------------------


def test_repository_profile_emits_uv_directory_args():
    payload = render_codex(
        _inputs(profile="repository", repository_path=REPO)
    )
    server = payload["mcpServers"]["memory-workbench"]
    assert server["command"] == "uv"
    assert server["args"] == [
        "--directory",
        str(REPO),
        "run",
        "memory-workbench-mcp",
    ]


def test_repository_profile_without_path_raises():
    with pytest.raises(ValidationError):
        _inputs(profile="repository", repository_path=None)


# --- env wiring ---------------------------------------------------------


def test_db_path_added_to_env_when_supplied():
    payload = render_codex(_inputs(db_path=DB))
    assert payload["mcpServers"]["memory-workbench"]["env"]["MW_DB_PATH"] == str(DB)


def test_relative_db_path_rejected():
    with pytest.raises(ValidationError):
        _inputs(db_path=Path("relative/memory.db"))


def test_relative_repository_path_rejected():
    with pytest.raises(ValidationError):
        _inputs(profile="repository", repository_path=Path("relative/repo"))


def test_empty_client_id_rejected():
    with pytest.raises(ValidationError):
        _inputs(client_id="")


# --- dispatch -----------------------------------------------------------


@pytest.mark.parametrize(
    "platform, renderer",
    [
        (EndpointPlatform.CODEX, render_codex),
        (EndpointPlatform.CLAUDE, render_claude),
        (EndpointPlatform.CURSOR, render_cursor),
    ],
)
def test_render_dispatch_matches_direct_call(platform, renderer):
    inputs = _inputs(platform=platform)
    assert render(platform, inputs) == renderer(inputs)


def test_render_rejects_custom_platform():
    with pytest.raises(ValidationError):
        render(EndpointPlatform.CUSTOM, _inputs(platform=EndpointPlatform.CUSTOM))


# --- safety: no secrets in payload --------------------------------------


def test_payload_never_contains_secret_markers():
    payload = render_codex(_inputs(db_path=DB))
    blob = json.dumps(payload)
    for needle in ("sk-", "ghp_", "AKIA", "BEGIN PRIVATE KEY", "xox"):
        assert needle not in blob
