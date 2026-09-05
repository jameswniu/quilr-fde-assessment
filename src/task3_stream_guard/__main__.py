"""Run the streaming guardrail gateway.

    uv run python -m task3_stream_guard

Then watch the redaction arrive live:

    curl -N localhost:8082/v1/generate -d '{"prompt":"summarise the account"}'
"""

from __future__ import annotations

import logging

import uvicorn

from task3_stream_guard.gateway import create_app

PORT = 8082


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("task3_stream_guard").info("POST http://127.0.0.1:%d/v1/generate", PORT)
    uvicorn.run(create_app(), host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
