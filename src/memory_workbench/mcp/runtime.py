"""MCP runtime identity resolver.

Resolves the authoritative caller identity for a tool call from `MW_CLIENT_ID`
environment variable. Tool argument `client_id` is accepted only for backward
compatibility and must agree with the environment-bound value when both are
present.

Plan §1 (cross-tool onboarding): the endpoint configuration is the authority
for `client_id`; LLM-supplied tool arguments can be spoofed and are therefore
non-authoritative.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from memory_workbench.domain.errors import ClientMismatch


ENV_CLIENT_ID = "MW_CLIENT_ID"


@dataclass(frozen=True)
class McpRuntimeContext:
    """Resolved caller identity for a single MCP tool invocation."""

    client_id: str
    source: str  # "environment" | "argument" — for auditability


def resolve_client_id(
    *,
    env: dict[str, str] | None = None,
    argument: str | None = None,
) -> McpRuntimeContext:
    """Pick authoritative client_id and reject mismatches.

    Rules:
    - env value wins when set.
    - env + argument both set and equal → ok (env wins, source recorded).
    - env + argument both set and differ → ClientMismatch.
    - env unset, argument set → backward-compat fallback to argument.
    - both unset → returns empty string; the tool layer treats this as
      "unbound" caller and falls back to scope-only behaviour.
    """
    env_map = env if env is not None else os.environ
    env_value = env_map.get(ENV_CLIENT_ID)

    if env_value:
        if argument is not None and argument != env_value:
            raise ClientMismatch(
                f"tool argument client_id={argument!r} conflicts with "
                f"environment {ENV_CLIENT_ID}={env_value!r}"
            )
        return McpRuntimeContext(client_id=env_value, source="environment")

    if argument:
        return McpRuntimeContext(client_id=argument, source="argument")

    return McpRuntimeContext(client_id="", source="missing")
