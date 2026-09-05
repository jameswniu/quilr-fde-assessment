"""Run the gateway and the mock downstream MCP server together.

    uv run python -m task2_mcp_gateway

Gateway on 8080, mock downstream on 8081. Try it with:

    curl -s localhost:8080/mcp -H 'Authorization: Bearer tok-viewer-41ab77' \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from task2_mcp_gateway.auth import TOKENS
from task2_mcp_gateway.downstream import create_downstream_app
from task2_mcp_gateway.gateway import create_gateway_app

GATEWAY_PORT = 8080
DOWNSTREAM_PORT = 8081


async def _serve() -> None:
    downstream = uvicorn.Server(
        uvicorn.Config(create_downstream_app(), host="127.0.0.1", port=DOWNSTREAM_PORT, log_level="warning")
    )
    gateway = uvicorn.Server(
        uvicorn.Config(
            create_gateway_app(downstream_url=f"http://127.0.0.1:{DOWNSTREAM_PORT}/mcp"),
            host="127.0.0.1",
            port=GATEWAY_PORT,
            log_level="warning",
        )
    )
    await asyncio.gather(downstream.serve(), gateway.serve())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    log = logging.getLogger("task2_mcp_gateway")
    log.info("gateway on http://127.0.0.1:%d/mcp, mock downstream on port %d", GATEWAY_PORT, DOWNSTREAM_PORT)
    for token, role in TOKENS.items():
        log.info("demo token %s has role %s", token, role.value)
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
