import pytest

from mycode.teams.models import TeamError
from mycode.teams.protocols import PlanDecisionPayload, protocol_dict


def test_protocol_union_is_strict() -> None:
    payload = PlanDecisionPayload(
        "plan_decision", "team_task_0000000000000001", "team_member_0000000000000001",
        1, "a" * 64, "approved", "ok",
    )
    assert protocol_dict(payload)["decision"] == "approved"
    with pytest.raises(TeamError):
        protocol_dict({"type": "unknown"})
    with pytest.raises(TeamError):
        protocol_dict({**protocol_dict(payload), "extra": True})
