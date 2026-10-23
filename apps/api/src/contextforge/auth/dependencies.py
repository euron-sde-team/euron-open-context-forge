"""Dashboard authentication: session cookie (browser) or bearer session token (API).

Cookie-authenticated mutations must carry ``X-ContextForge-CSRF: 1``. Browsers cannot add a
custom header to a cross-site request without a CORS preflight, which the allowlist
refuses, so this blocks CSRF without server-side token state.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request

from contextforge.audit.service import Actor
from contextforge.core.deps import ContainerDep, SessionDep, client_ip
from contextforge.core.errors import AuthenticationError, PermissionDeniedError
from contextforge.core.security import decode_session
from contextforge.users.models import User

SESSION_COOKIE = "cf_session"
CSRF_HEADER = "x-contextforge-csrf"
ROLE_RANK = {"viewer": 0, "admin": 1, "owner": 2}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def current_user(request: Request, container: ContainerDep, session: SessionDep) -> User:
    # An explicit Authorization header wins: browsers never attach it cross-site, so it
    # needs no CSRF check. The cookie is the fallback for the dashboard.
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    via_cookie = False
    if not token:
        token = request.cookies.get(SESSION_COOKIE)
        via_cookie = token is not None
    if not token:
        raise AuthenticationError("Sign in to continue", code="not_signed_in")
    claims = decode_session(token, container.settings.session_secret)
    if claims is None:
        raise AuthenticationError("Your session expired. Sign in again", code="session_expired")
    user = await session.get(User, claims.user_id)
    if user is None or user.disabled or user.session_version != claims.session_version:
        raise AuthenticationError("Your session expired. Sign in again", code="session_expired")
    if (
        via_cookie
        and request.method not in _SAFE_METHODS
        and request.headers.get(CSRF_HEADER) != "1"
    ):
        raise PermissionDeniedError("Missing CSRF header", code="csrf_required")
    request.state.actor = Actor(user.id, user.email, user.role, client_ip(request))
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(role: str) -> Callable[..., Coroutine[Any, Any, Actor]]:
    async def dependency(request: Request, user: CurrentUser) -> Actor:
        if ROLE_RANK.get(user.role, -1) < ROLE_RANK[role]:
            raise PermissionDeniedError(
                f"This action needs the {role} role", code="insufficient_role"
            )
        actor: Actor = request.state.actor
        return actor

    return dependency


Viewer = Annotated[Actor, Depends(require_role("viewer"))]
Admin = Annotated[Actor, Depends(require_role("admin"))]
Owner = Annotated[Actor, Depends(require_role("owner"))]
