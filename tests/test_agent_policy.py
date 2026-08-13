from mycode.agents.models import AgentDefinition
from mycode.agents.policy import ChildToolPolicy
from mycode.tools.registry import create_default_registry


def definition(allowed: tuple[str, ...], denied: tuple[str, ...] = ()) -> AgentDefinition:
    return AgentDefinition(
        "role", "role", allowed, denied, "inherit", 4, "strict", "prompt",
        "project", "role.md", "fingerprint",
    )


def test_defined_visible_registry_intersects_role_plan_and_background() -> None:
    registry = create_default_registry()
    policy = ChildToolPolicy(
        role=definition(("read_file", "search_code", "write_file")),
        parent_mode="plan",
        background_allowed_tools=("read_file", "write_file"),
    )

    visible = policy.visible_registry(registry, background=True)

    assert visible.names() == ("read_file",)
    assert policy.authorize_call("write_file", background=True).reason_code == "plan_mode_readonly"


def test_global_deny_cannot_be_enabled_by_background_list() -> None:
    policy = ChildToolPolicy(
        role=None,
        parent_mode="default",
        background_allowed_tools=("Agent", "Task", "load_skill"),
    )

    for name in ("Agent", "Task", "load_skill"):
        assert policy.authorize_call(name, background=True).reason_code == "child_global_deny"
