__all__ = [
    "AgentAction",
    "CommandAction",
    "HookActionExecutor",
    "HookActionOutcome",
    "HookConfigLoader",
    "HookDiagnostic",
    "HookDispatchResult",
    "HookEvent",
    "HookPromptLease",
    "HookRule",
    "HookRuntime",
    "HookSnapshot",
    "HTTPAction",
    "PromptAction",
]


def __getattr__(name: str):
    if name == "HookActionExecutor":
        from .actions import HookActionExecutor

        return HookActionExecutor
    if name == "HookConfigLoader":
        from .config import HookConfigLoader

        return HookConfigLoader
    if name == "HookRuntime":
        from .runtime import HookRuntime

        return HookRuntime
    if name in {
        "AgentAction",
        "CommandAction",
        "HookActionOutcome",
        "HookDiagnostic",
        "HookDispatchResult",
        "HookEvent",
        "HookPromptLease",
        "HookRule",
        "HookSnapshot",
        "HTTPAction",
        "PromptAction",
    }:
        from . import models

        return getattr(models, name)
    raise AttributeError(name)
