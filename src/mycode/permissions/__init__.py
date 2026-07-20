__all__ = [
    "ApprovalChoice",
    "ApprovalHandler",
    "ApprovalPrompt",
    "DenyApprovalHandler",
    "LocalRuleStore",
    "PermissionConfigLoader",
    "PermissionConfigSet",
    "PermissionDecision",
    "PermissionLayer",
    "PermissionMode",
    "PermissionRequest",
    "PermissionRule",
    "PermissionService",
    "TerminalApprovalHandler",
]


def __getattr__(name: str):
    if name in {"ApprovalHandler", "DenyApprovalHandler", "TerminalApprovalHandler"}:
        from .approval import ApprovalHandler, DenyApprovalHandler, TerminalApprovalHandler

        return {
            "ApprovalHandler": ApprovalHandler,
            "DenyApprovalHandler": DenyApprovalHandler,
            "TerminalApprovalHandler": TerminalApprovalHandler,
        }[name]
    if name in {"LocalRuleStore", "PermissionConfigLoader"}:
        from .config import LocalRuleStore, PermissionConfigLoader

        return {
            "LocalRuleStore": LocalRuleStore,
            "PermissionConfigLoader": PermissionConfigLoader,
        }[name]
    if name in {
        "ApprovalChoice",
        "ApprovalPrompt",
        "PermissionConfigSet",
        "PermissionDecision",
        "PermissionLayer",
        "PermissionMode",
        "PermissionRequest",
        "PermissionRule",
    }:
        from .models import (
            ApprovalChoice,
            ApprovalPrompt,
            PermissionConfigSet,
            PermissionDecision,
            PermissionLayer,
            PermissionMode,
            PermissionRequest,
            PermissionRule,
        )

        return {
            "ApprovalChoice": ApprovalChoice,
            "ApprovalPrompt": ApprovalPrompt,
            "PermissionConfigSet": PermissionConfigSet,
            "PermissionDecision": PermissionDecision,
            "PermissionLayer": PermissionLayer,
            "PermissionMode": PermissionMode,
            "PermissionRequest": PermissionRequest,
            "PermissionRule": PermissionRule,
        }[name]
    if name == "PermissionService":
        from .service import PermissionService

        return PermissionService
    raise AttributeError(name)
