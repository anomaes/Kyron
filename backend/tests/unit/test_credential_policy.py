from __future__ import annotations

import uuid

import pytest

from backend.engine.waves import WaveExecutionError, load_run_credentials


async def test_credential_policy_loads_only_explicitly_permitted_secrets() -> None:
    user_id = uuid.uuid4()
    wave_id = uuid.uuid4()
    calls: list[uuid.UUID] = []

    async def load(requested_user_id: uuid.UUID) -> dict[str, str]:
        calls.append(requested_user_id)
        return {"ALLOWED": "yes", "DENIED": "no"}

    assert await load_run_credentials({"mode": "none"}, user_id, load, wave_id) == {}
    assert await load_run_credentials(
        {"mode": "allowlist", "keys": ["ALLOWED"]}, user_id, load, wave_id
    ) == {"ALLOWED": "yes"}
    assert await load_run_credentials({"mode": "all"}, user_id, load, wave_id) == {
        "ALLOWED": "yes",
        "DENIED": "no",
    }
    assert calls == [user_id, user_id]


@pytest.mark.parametrize(
    "policy", [None, {}, {"mode": "None"}, {"mode": "unexpected"}]
)
async def test_credential_policy_rejects_unknown_modes(
    policy: dict[str, object] | None,
) -> None:
    async def load(_: uuid.UUID) -> dict[str, str]:
        raise AssertionError("credentials must not be loaded for an invalid policy")

    with pytest.raises(WaveExecutionError, match="Unknown credential policy mode"):
        await load_run_credentials(policy, uuid.uuid4(), load, uuid.uuid4())
