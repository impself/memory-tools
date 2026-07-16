# ADR 0001: Agent assets use grants, not memory copies

Status: Accepted
Date: 2026-07-16

## Context

The control plane must let a user give selected memories to multiple agents
while preserving correction history, revocation, scope isolation, and later
behaviour tracing. Copying a memory per agent makes each copy a competing
version and obscures which canonical memory caused a retrieval.

## Decision

`AgentAsset` is a durable logical identity. `AgentEndpoint` represents a
specific tool connection and binds to exactly one asset through a unique
`client_id`. `ProjectMembership` and `MemoryGrant` are relation records.

The visible memory set is calculated at read time. A grant references the
canonical `MemoryRecord`; it never stores a copy of content or events.

## Consequences

- A correction, revoke, quarantine, expiry, or purge affects every grantee
  consistently.
- Version lineage stays on the canonical record and remains explainable.
- Delivery state for physical clients can be added later as a separate
  `MemoryDelivery` projection without changing the ownership model.
- The current local MVP uses no identity authentication; this model must not be
  exposed to remote callers before an administrative authentication boundary is
  introduced.
