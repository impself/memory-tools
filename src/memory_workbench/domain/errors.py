"""Domain errors. Distinct types so HTTP/MCP layers can map to status codes."""

from __future__ import annotations


class MemoryError(Exception):
    """Base for all domain-level errors."""


class MemoryNotFound(MemoryError):
    """Memory id does not exist or caller cannot see it."""


class InvalidTransition(MemoryError):
    """State machine transition not allowed from current state."""


class ScopeViolation(MemoryError):
    """Caller scope cannot read or modify this memory."""


class SecretContent(MemoryError):
    """Content matches a credential pattern; refused at write time."""


class ValidationError(MemoryError):
    """Domain input violates invariants (e.g. missing required scope id)."""


class ClientMismatch(MemoryError):
    """Tool argument client_id conflicts with environment-bound MW_CLIENT_ID."""
