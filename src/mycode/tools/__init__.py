__all__ = [
    "EditFileTool",
    "FindFilesTool",
    "ReadFileTool",
    "RunCommandTool",
    "SearchCodeTool",
    "ToolExecutor",
    "ToolRegistry",
    "WriteFileTool",
    "create_default_registry",
]


def __getattr__(name: str):
    if name == "RunCommandTool":
        from .command import RunCommandTool

        return RunCommandTool
    if name == "ToolExecutor":
        from .executor import ToolExecutor

        return ToolExecutor
    if name in {"EditFileTool", "ReadFileTool", "WriteFileTool"}:
        from .files import EditFileTool, ReadFileTool, WriteFileTool

        return {
            "EditFileTool": EditFileTool,
            "ReadFileTool": ReadFileTool,
            "WriteFileTool": WriteFileTool,
        }[name]
    if name in {"ToolRegistry", "create_default_registry"}:
        from .registry import ToolRegistry, create_default_registry

        return {
            "ToolRegistry": ToolRegistry,
            "create_default_registry": create_default_registry,
        }[name]
    if name in {"FindFilesTool", "SearchCodeTool"}:
        from .search import FindFilesTool, SearchCodeTool

        return {
            "FindFilesTool": FindFilesTool,
            "SearchCodeTool": SearchCodeTool,
        }[name]
    raise AttributeError(name)
