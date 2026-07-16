# Ubiquitous Language

## AgentAsset

A durable, user-named logical agent identity. It owns project memberships and
memory grants. It is not a particular desktop application, process, or session.

## AgentEndpoint

A concrete Cursor, Codex, Claude, or custom client installation bound to one
AgentAsset. Its `client_id` is globally unique, because an incoming client must
not silently resolve to multiple logical agents.

## ProjectMembership

The relationship between an AgentAsset and a Project. It carries the agent's
role and default sync mode in that project. It does not copy any memories.

## MemoryGrant

An explicit reference from an AgentAsset to a canonical MemoryRecord. It adds
visibility without duplicating content, history, version lineage, or lifecycle.

## Effective Memory Set

The active, in-validity memories an AgentAsset may currently read. It is
computed from global scope, matching project/workspace memberships,
agent-scoped memories for that asset, and explicit MemoryGrants.
