"""Pure MCP configuration renderers. Plan cross-tool-onboarding §2.

Each renderer returns a JSON-serializable payload describing how a
specific MCP client (Codex / Claude / Cursor) should launch the local
memory-workbench-mcp command for a given AgentEndpoint.

The renderer never writes files, never reads secrets, and never invents a
client_id. Callers must supply a non-empty endpoint client_id.

Two launch profiles:
- `installed`: assumes `memory-workbench-mcp` is on PATH.
- `repository`: uses `uv --directory <repo> run memory-workbench-mcp`,
  intended for development without an install step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from memory_workbench.domain.errors import ValidationError
from memory_workbench.domain.models import EndpointPlatform

LaunchProfile = Literal["installed", "repository"]
_MCP_SERVER_NAME = "memory-workbench"


@dataclass(frozen=True)
class RenderInputs:
    """Inputs validated before any renderer is invoked."""

    client_id: str
    platform: EndpointPlatform
    profile: LaunchProfile
    repository_path: Path | None
    db_path: Path | None

    def __post_init__(self) -> None:
        if not self.client_id:
            raise ValidationError("client_id is required to render MCP config")
        if self.profile == "repository" and self.repository_path is None:
            raise ValidationError(
                "repository launch profile requires a repository path"
            )
        if self.repository_path is not None and not self.repository_path.is_absolute():
            raise ValidationError("repository_path must be absolute")
        if self.db_path is not None and not self.db_path.is_absolute():
            raise ValidationError("db_path must be absolute")


def _command(inputs: RenderInputs) -> list[str]:
    if inputs.profile == "repository":
        return [
            "uv",
            "--directory",
            str(inputs.repository_path),
            "run",
            "memory-workbench-mcp",
        ]
    return ["memory-workbench-mcp"]


def _environment(inputs: RenderInputs) -> dict[str, str]:
    env: dict[str, str] = {"MW_CLIENT_ID": inputs.client_id}
    if inputs.db_path is not None:
        env["MW_DB_PATH"] = str(inputs.db_path)
    return env


def render_codex(inputs: RenderInputs) -> dict[str, Any]:
    """Codex MCP server config shape."""
    return {
        "mcpServers": {
            _MCP_SERVER_NAME: {
                "command": _command(inputs)[0],
                "args": _command(inputs)[1:],
                "env": _environment(inputs),
            }
        },
    }


def render_claude(inputs: RenderInputs) -> dict[str, Any]:
    """Claude Desktop / Claude Code MCP server config shape."""
    cmd = _command(inputs)
    return {
        "mcpServers": {
            _MCP_SERVER_NAME: {
                "command": cmd[0],
                "args": cmd[1:],
                "env": _environment(inputs),
            }
        },
    }


def render_cursor(inputs: RenderInputs) -> dict[str, Any]:
    """Cursor MCP server config shape (also keyed under mcpServers)."""
    cmd = _command(inputs)
    return {
        "mcpServers": {
            _MCP_SERVER_NAME: {
                "command": cmd[0],
                "args": cmd[1:],
                "env": _environment(inputs),
            }
        },
    }


_RENDERERS = {
    EndpointPlatform.CODEX: render_codex,
    EndpointPlatform.CLAUDE: render_claude,
    EndpointPlatform.CURSOR: render_cursor,
}


def render(platform: EndpointPlatform, inputs: RenderInputs) -> dict[str, Any]:
    renderer = _RENDERERS.get(platform)
    if renderer is None:
        raise ValidationError(
            f"no renderer for platform {platform!r}; use a custom client config"
        )
    return renderer(inputs)


def to_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)
