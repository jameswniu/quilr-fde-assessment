"""Bearer token to role resolution.

The token table is a static map so the assessment runs with no identity provider. A real
deployment would verify a signed token and read the role from a claim. The shape of the
call site does not change: one function turns an Authorization header into a role or None.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class Role(StrEnum):
    """Roles the gateway understands."""

    ADMIN = "admin"
    VIEWER = "viewer"


#: Demo credentials. Printed at startup by ``python -m task2_mcp_gateway``.
TOKENS: Final[dict[str, Role]] = {
    "tok-admin-9f3c2d": Role.ADMIN,
    "tok-viewer-41ab77": Role.VIEWER,
}

#: A tool whose name starts with this prefix requires the admin role.
ADMIN_TOOL_PREFIX: Final = "admin_"


def resolve_role(authorization_header: str | None) -> Role | None:
    """Return the role behind a ``Bearer <token>`` header, or None when it is not usable."""
    if not authorization_header:
        return None
    scheme, _, token = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return TOKENS.get(token.strip())


def tool_requires_admin(tool_name: str) -> bool:
    """True when the named tool is restricted to admins."""
    return tool_name.startswith(ADMIN_TOOL_PREFIX)
