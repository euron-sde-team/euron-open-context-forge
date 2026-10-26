from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from contextforge.core.schemas import ApiModel

NAME = r"^[a-z0-9][a-z0-9_-]{0,63}$"
Kind = Literal["openai", "tokenshield", "smartrouter"]
_AWS_METADATA_V6 = ipaddress.ip_address("fd00:ec2::254")
StrategyName = Literal["conservative", "balanced", "aggressive"]


def _url(v: str) -> str:
    v = v.strip().rstrip("/")
    if not v.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    host = (urlsplit(v).hostname or "").lower()
    if not host:
        raise ValueError("base_url needs a host")
    if host in _METADATA_HOSTS or _link_local(host):
        # Cloud instance metadata (169.254.169.254, fd00:ec2::254, link-local ranges) holds
        # the task's own credentials; the proxy must never be pointed at it.
        raise ValueError("base_url must not point at a link-local or instance metadata address")
    return v


_METADATA_HOSTS = {"metadata", "metadata.google.internal", "instance-data", "fd00:ec2::254"}


def _link_local(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False  # a name: resolved by the HTTP client when the proxy calls it
    return ip.is_link_local or ip.is_unspecified or ip == _AWS_METADATA_V6


class UpstreamIn(ApiModel):
    name: str = Field(pattern=NAME)
    kind: Kind = "openai"
    base_url: str = Field(
        max_length=500, description="OpenAI-compatible base, e.g. https://host/v1"
    )
    api_key: str | None = Field(None, max_length=4000, description="Write-only; sealed at rest")
    max_input_tokens: int | None = Field(None, ge=1, le=10_000_000)
    strategy: StrategyName = "balanced"
    enabled: bool = True

    _check_url = field_validator("base_url")(_url)


class UpstreamUpdate(ApiModel):
    kind: Kind | None = None
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=4000)
    clear_api_key: bool = False
    max_input_tokens: int | None = Field(None, ge=1, le=10_000_000)
    strategy: StrategyName | None = None
    enabled: bool | None = None

    @field_validator("base_url")
    @classmethod
    def _check(cls, v: str | None) -> str | None:
        return _url(v) if v is not None else None


class UpstreamOut(ApiModel):
    id: uuid.UUID
    name: str
    kind: str
    base_url: str
    has_api_key: bool
    key_hint: str | None
    max_input_tokens: int | None
    strategy: str
    enabled: bool
    created_at: datetime
