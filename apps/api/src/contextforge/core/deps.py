"""FastAPI dependencies shared across domains."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from contextforge.core.container import Container


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


async def get_session(
    container: Annotated[Container, Depends(get_container)],
) -> AsyncIterator[AsyncSession]:
    async with container.db.sessionmaker() as session:
        yield session


ContainerDep = Annotated[Container, Depends(get_container)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
