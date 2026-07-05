from __future__ import annotations

import argparse
from pathlib import Path
import sys
from collections.abc import Sequence

from prompt_toolkit import prompt

from .config import load_config
from .providers.factory import create_provider
from .session import ChatSession
from .tools.registry import create_default_registry
from .types import ConfigError, ProviderError, ToolContext


EXIT_COMMANDS = {"exit", "quit", "退出"}
DEFAULT_CONFIG_PATH = "config.yaml"


def read_user_input(prompt_text: str) -> str:
    return prompt(prompt_text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mycode", description="myCode 命令行 AI 编程助手")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="配置文件路径")
    args = parser.parse_args(argv)

    try:
        config = load_config(Path(args.config))
        provider = create_provider(config)
    except ConfigError as exc:
        print(f"配置错误：{exc.user_message}", file=sys.stderr)
        return 1

    session = ChatSession(
        provider,
        tool_registry=create_default_registry(),
        tool_context=ToolContext(workspace_root=Path.cwd()),
    )
    print("myCode 已启动。输入 exit、quit 或 退出 结束。")

    while True:
        try:
            user_text = read_user_input("> ").strip()
        except KeyboardInterrupt:
            print("\n已退出。")
            return 0
        except EOFError:
            print()
            return 0

        if not user_text:
            continue
        if user_text.lower() in EXIT_COMMANDS or user_text in EXIT_COMMANDS:
            print("已退出。")
            return 0

        try:
            assistant_started = False
            for event in session.send(user_text):
                if event.type == "text_delta":
                    if not assistant_started:
                        print("● ", end="", flush=True)
                        assistant_started = True
                    print(event.text, end="", flush=True)
                elif event.type == "tool_started":
                    print(f"\n[tool] {event.tool_name} 开始", flush=True)
                elif event.type == "tool_finished":
                    result = event.tool_result
                    status = "成功" if result and result.ok else "失败"
                    message = result.message if result else ""
                    print(f"[tool] {event.tool_name} {status}：{message}", flush=True)
            print()
        except ProviderError as exc:
            print(f"请求错误：{exc.user_message}", file=sys.stderr)

    return 0
