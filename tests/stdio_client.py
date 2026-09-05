"""A minimal stdio JSON-RPC client used to exercise the Task 1 server as a subprocess.

Deliberately hand rolled rather than built on the SDK client, because the point of the
test is to look at the raw bytes the server writes to stdout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType
from typing import Any, Self

READ_TIMEOUT_SECONDS = 20.0


class StdioServerProcess:
    """Spawn the server, speak newline delimited JSON-RPC to it, collect every raw line."""

    def __init__(self, *, env_overrides: dict[str, str] | None = None) -> None:
        env = dict(os.environ)
        env.update(env_overrides or {})
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "task1_mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._pool = ThreadPoolExecutor(max_workers=1)
        self.stdout_lines: list[str] = []
        self.stderr: str = ""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def send(self, message: dict[str, Any]) -> None:
        """Write one JSON-RPC message. Notifications get no response."""
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(message) + "\n")
        self._proc.stdin.flush()

    def read_message(self) -> dict[str, Any]:
        """Block until the server writes one line, and return it parsed."""
        assert self._proc.stdout is not None
        line = self._pool.submit(self._proc.stdout.readline).result(timeout=READ_TIMEOUT_SECONDS)
        if not line:
            raise AssertionError(f"server closed stdout early. stderr so far:\n{self._drain_stderr()}")
        self.stdout_lines.append(line.rstrip("\n"))
        parsed: dict[str, Any] = json.loads(line)
        return parsed

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send a request and read its response."""
        self.send(message)
        return self.read_message()

    def close(self) -> int:
        """Close stdin, wait for exit, and capture stderr."""
        if self._proc.stdin is not None and not self._proc.stdin.closed:
            self._proc.stdin.close()
        try:
            _, stderr = self._proc.communicate(timeout=READ_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            self._proc.kill()
            _, stderr = self._proc.communicate()
        self.stderr += stderr or ""
        self._pool.shutdown(wait=False)
        return self._proc.returncode

    def _drain_stderr(self) -> str:  # pragma: no cover - only on failure paths
        assert self._proc.stderr is not None
        self._proc.kill()
        _, stderr = self._proc.communicate()
        self.stderr += stderr or ""
        return self.stderr
