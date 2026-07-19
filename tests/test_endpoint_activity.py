"""Runtime identity + endpoint activity tests. Plan §1, §3."""

from __future__ import annotations

from datetime import timedelta

import pytest

from memory_workbench.api.deps import reset_for_tests, session_dep
from memory_workbench.domain.errors import ClientMismatch
from memory_workbench.domain.models import (
    ENDPOINT_STALE_THRESHOLD_HOURS,
    EndpointPlatform,
    EndpointStatus,
    SyncMode,
    utcnow,
)
from memory_workbench.mcp.runtime import resolve_client_id
from memory_workbench.storage import repository as repo


@pytest.fixture
def session():
    reset_for_tests(":memory:")
    sess = session_dep()
    yield sess
    sess.close()


# --- runtime identity ---------------------------------------------------


def test_runtime_env_wins_over_argument():
    ctx = resolve_client_id(env={"MW_CLIENT_ID": "codex-local"}, argument="codex-local")
    assert ctx.client_id == "codex-local"
    assert ctx.source == "environment"


def test_runtime_env_rejects_mismatching_argument():
    with pytest.raises(ClientMismatch):
        resolve_client_id(
            env={"MW_CLIENT_ID": "codex-local"},
            argument="claude-local",
        )


def test_runtime_argument_only_is_backward_compat():
    ctx = resolve_client_id(env={}, argument="legacy-id")
    assert ctx.client_id == "legacy-id"
    assert ctx.source == "argument"


def test_runtime_neither_set_returns_empty():
    ctx = resolve_client_id(env={}, argument=None)
    assert ctx.client_id == ""
    assert ctx.source == "missing"


# --- endpoint activity --------------------------------------------------


def _make_endpoint(session, client_id="codex-local") -> str:
    asset = repo.create_agent_asset(
        session,
        name="Codex",
        description=None,
        role_tags=[],
        default_sync_mode=SyncMode.MANUAL,
    )
    endpoint = repo.add_agent_endpoint(
        session,
        asset_id=asset.id,
        client_id=client_id,
        platform=EndpointPlatform.CODEX,
        display_name="local",
    )
    session.commit()
    return endpoint.id


def test_observation_records_latest_operation(session):
    eid = _make_endpoint(session)
    repo.record_endpoint_observation(session, endpoint_id=eid, operation="search")
    session.commit()

    obs = repo.get_endpoint_observation(session, eid)
    assert obs is not None
    assert obs.last_operation == "search"
    assert obs.last_error_category is None


def test_status_never_seen_for_unused_endpoint(session):
    eid = _make_endpoint(session)
    assert repo.derive_endpoint_status(session, eid) == EndpointStatus.NEVER_SEEN


def test_status_active_after_observation(session):
    eid = _make_endpoint(session)
    repo.record_endpoint_observation(session, endpoint_id=eid, operation="search")
    session.commit()
    assert repo.derive_endpoint_status(session, eid) == EndpointStatus.ACTIVE


def test_status_stale_after_threshold(session):
    eid = _make_endpoint(session)
    repo.record_endpoint_observation(session, endpoint_id=eid, operation="search")
    session.commit()

    later = utcnow() + timedelta(hours=ENDPOINT_STALE_THRESHOLD_HOURS + 1)
    assert repo.derive_endpoint_status(session, eid, now=later) == EndpointStatus.STALE


def test_observation_redacts_unknown_error_to_internal(session):
    eid = _make_endpoint(session)
    repo.record_endpoint_observation(
        session,
        endpoint_id=eid,
        operation="search",
        error_category="EXOTIC_UNCATEGORIZED",
    )
    session.commit()
    obs = repo.get_endpoint_observation(session, eid)
    assert obs is not None
    assert obs.last_error_category == "internal"


def test_get_endpoint_for_client_id_round_trip(session):
    eid = _make_endpoint(session, client_id="cursor-x")
    found = repo.get_endpoint_for_client_id(session, "cursor-x")
    assert found is not None
    assert found.id == eid


def test_get_endpoint_for_unknown_client_returns_none(session):
    assert repo.get_endpoint_for_client_id(session, "nope") is None
