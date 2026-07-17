from __future__ import annotations

import argparse
import asyncio
import os

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent
from starlette.middleware.base import BaseHTTPMiddleware


def build_server(*, host: str, port: int, json_response: bool) -> FastMCP:
    observed_header = {"value": ""}
    server = FastMCP(
        "mewcode-test-server",
        host=host,
        port=port,
        json_response=json_response,
    )

    @server.tool()
    def echo(text: str) -> str:
        """Return the provided text."""
        return text

    @server.tool()
    def structured(value: str) -> dict[str, object]:
        """Return structured JSON data."""
        return {"value": value, "nested": {"ok": True}}

    @server.tool()
    def environment() -> str:
        """Return the fixture environment value."""
        return os.environ.get("MCP_FIXTURE_VALUE", "")

    @server.tool()
    async def delayed(label: str, delay: float = 0.0) -> str:
        """Return a label after a delay."""
        await asyncio.sleep(delay)
        return label

    @server.tool()
    def process_id() -> str:
        """Return the server process id."""
        return str(os.getpid())

    @server.tool()
    def http_header() -> str:
        """Return the custom header observed by the HTTP transport."""
        return observed_header["value"]

    @server.tool()
    def fail() -> str:
        """Return an MCP tool error."""
        raise RuntimeError("fixture remote failure")

    @server.tool()
    def unsupported_image() -> list[ImageContent]:
        """Return an unsupported image block."""
        return [ImageContent(type="image", data="c2VjcmV0", mimeType="image/png")]

    @server.tool()
    def large(size: int) -> str:
        """Return a large text result."""
        return "x" * size

    setattr(server, "_fixture_observed_header", observed_header)
    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=("stdio", "http"), required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--json-response", action="store_true")
    args = parser.parse_args()

    server = build_server(
        host=args.host,
        port=args.port,
        json_response=args.json_response,
    )
    if args.transport == "stdio":
        server.run(transport="stdio")
        return

    app = server.streamable_http_app()
    observed_header = getattr(server, "_fixture_observed_header")

    async def capture_header(request: object, call_next: object) -> object:
        observed_header["value"] = request.headers.get("x-mcp-test", "")
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=capture_header)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="error",
    )


if __name__ == "__main__":
    main()
