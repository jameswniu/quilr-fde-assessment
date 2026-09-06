"""Import a module in a fresh interpreter that refuses to hand out environment variables.

A key read at import time would be read on every ``make test``, on every machine, whether or
not anyone asked for the live path. Proving that never happens needs a process where such a
read fails loudly, so this is a subprocess rather than a monkeypatch: replacing ``os.environ``
inside the test runner would break the test runner.
"""

from __future__ import annotations

import subprocess
import sys

PROBE = """
# Dependencies first. They read the environment themselves and the trap below is not for them.
import asyncio
import httpx
import os


class Trap(dict):
    def __getitem__(self, key):
        raise AssertionError("read " + str(key) + " at import time")

    def get(self, key, default=None):
        raise AssertionError("read " + str(key) + " at import time")


os.environ = Trap()
import {module}
print("imported with every environment read trapped")
"""


def import_without_environment(module: str) -> subprocess.CompletedProcess[str]:
    """Import a module with every environment read trapped, and report how it went."""
    return subprocess.run(
        [sys.executable, "-c", PROBE.format(module=module)],
        capture_output=True,
        text=True,
        check=False,
    )
