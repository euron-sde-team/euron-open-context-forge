"""OpenAI-compatible proxy: optimize the context, then forward to an upstream.

Point any OpenAI SDK at ``http://<contextforge>/v1`` with a ``cfk_`` key. Every chat
completion is optimized first (budget, strategy and profile from the upstream's defaults,
overridable per request with ``x-contextforge-*`` headers) and then forwarded, streaming
or not, to the chosen upstream: any OpenAI-compatible API, TokenShield, or SmartRouter.

Request headers:
  x-contextforge-upstream            upstream name (default: the key's, then the first enabled)
  x-contextforge-max-input-tokens    budget for this call (default: the upstream's)
  x-contextforge-strategy            conservative | balanced | aggressive
  x-contextforge-profile             a workload profile name
  x-contextforge-optimize: off       forward untouched (still authenticated and logged)

Response headers: x-contextforge-original-tokens, -optimized-tokens, -reduction-percent,
-tokenizer, -exact, -budget-met, -run-id, -cache, plus the upstream's own headers.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import orjson
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

from contextforge.context.schemas import OptimizeResponse
from contextforge.context.service import Caller, ContextService, UpstreamInfo
from contextforge.core.container import Container
from contextforge.core.deps import ContainerDep
from contextforge.core.errors import AppError, UpstreamError, UpstreamTimeoutError
from contextforge.engine.types import Message, OptimizeOptions, OptimizeRequest
from contextforge.integrations.base import UpstreamAdapter
from contextforge.integrations.registry import adapter_for
from contextforge.keys.dependencies import KeyContext, ServiceKey
from contextforge.observability import metrics
from contextforge.upstreams import service as upstreams
from contextforge.upstreams.service import ResolvedUpstream

router = APIRouter(prefix="/v1", tags=["proxy"])
log = logging.getLogger("contextforge.proxy")
_HOP = {"content-length", "transfer-encoding", "connection", "content-encoding", "keep-alive"}


async def _upstream(container: Container, request: Request, key: KeyContext) -> ResolvedUpstream:
    name = (
        request.headers.get("x-contextforge-upstream")
        or key.default_upstream
        or container.settings.default_upstream
        or await upstreams.first_enabled(container)
    )
    if not name:
        raise AppError(
            "No upstream is configured. Add one in the dashboard (Upstreams) or set "
            "DEFAULT_UPSTREAM",
            code="no_upstream",
        )
    resolved = await upstreams.resolve(container, name)
    if resolved is None:
        raise AppError(f"Upstream {name!r} does not exist or is disabled", code="unknown_upstream")
    return resolved


def _int_header(request: Request, name: str) -> int | None:
    value = request.headers.get(name)
    if value is None:
        return None
    if not value.isdigit() or int(value) < 1:
        raise AppError(f"{name} must be a positive integer", code="invalid_header")
    return int(value)


def _options(
    request: Request, up: ResolvedUpstream, body: dict[str, Any], strategy: str
) -> OptimizeOptions:
    budget = _int_header(request, "x-contextforge-max-input-tokens") or up.max_input_tokens
    reserve = body.get("max_completion_tokens") or body.get("max_tokens") or 0
    data: dict[str, Any] = {
        "max_input_tokens": budget,
        "reserve_output_tokens": int(reserve)
        if budget and isinstance(reserve, int) and reserve < budget
        else 0,
        "strategy": request.headers.get("x-contextforge-strategy") or up.strategy or strategy,
        "include_trace": True,
    }
    if profile := request.headers.get("x-contextforge-profile"):
        data["profile"] = profile
    try:
        return OptimizeOptions.model_validate(data)
    except ValidationError as exc:
        raise AppError(
            "Invalid x-contextforge-* header",
            code="invalid_header",
            details={"errors": exc.errors(include_url=False)},
        ) from exc


def _forward_headers(
    request: Request, up: ResolvedUpstream, adapter: UpstreamAdapter
) -> dict[str, str]:
    headers = {"content-type": "application/json", "accept": request.headers.get("accept", "*/*")}
    for k, v in request.headers.items():
        lk = k.lower()
        if any(lk.startswith(p) for p in adapter.passthrough_prefixes) or lk == "x-request-id":
            headers[lk] = v
    if up.api_key:
        headers["authorization"] = f"Bearer {up.api_key}"
    return headers


def _response_headers(
    upstream: httpx.Response, adapter: UpstreamAdapter, opt: OptimizeResponse | None
) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in upstream.headers.items():
        lk = k.lower()
        if lk in _HOP:
            continue
        if lk == "content-type" or any(lk.startswith(p) for p in adapter.expose_prefixes):
            out[lk] = v
    if opt is not None:
        s = opt.stats
        out.update(
            {
                "x-contextforge-original-tokens": str(s.original_tokens),
                "x-contextforge-optimized-tokens": str(s.optimized_tokens),
                "x-contextforge-reduction-percent": f"{s.reduction_percent:.2f}",
                "x-contextforge-tokenizer": opt.tokenizer.id,
                "x-contextforge-exact": str(opt.tokenizer.exact).lower(),
                "x-contextforge-budget-met": str(s.budget_met).lower(),
                "x-contextforge-cache": "HIT" if opt.cached else "MISS",
            }
        )
        if opt.warnings:
            out["x-contextforge-warnings"] = ",".join(w.code for w in opt.warnings)[:200]
    return out


@router.post("/chat/completions", summary="OpenAI-compatible: optimize, then forward upstream")
async def chat_completions(request: Request, key: ServiceKey, container: ContainerDep) -> Response:
    try:
        body = orjson.loads(await request.body())
    except orjson.JSONDecodeError as exc:
        raise AppError("The request body is not valid JSON", code="invalid_json") from exc
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("messages"), list)
        or not body.get("model")
    ):
        raise AppError(
            "Send an OpenAI chat completion body with model and messages", code="invalid_request"
        )
    up = await _upstream(container, request, key)
    adapter = adapter_for(up.kind)
    svc = ContextService(container)
    caller = Caller(key, "proxy")
    opt: OptimizeResponse | None = None
    optimized_req: OptimizeRequest | None = None
    if request.headers.get("x-contextforge-optimize", "on").lower() != "off":
        try:
            messages = [Message.model_validate(m) for m in body["messages"]]
        except ValidationError as exc:
            raise AppError(
                "messages do not follow the chat format",
                code="invalid_request",
                details={"errors": exc.errors(include_url=False)[:10]},
            ) from exc
        optimized_req = OptimizeRequest(
            model=str(body["model"]),
            messages=messages,
            options=_options(request, up, body, container.settings.default_proxy_strategy),
        )
        opt = await svc.optimize(optimized_req, caller, record=False)
        body = {
            **body,
            "messages": [m.model_dump(exclude_none=True) for m in opt.optimized_messages],
        }

    url = up.base_url + "/chat/completions"
    headers = _forward_headers(request, up, adapter)
    payload = orjson.dumps(body)
    started = time.perf_counter()
    try:
        upstream_req = container.http.build_request("POST", url, content=payload, headers=headers)
        upstream = await container.http.send(upstream_req, stream=bool(body.get("stream")))
    except httpx.TimeoutException as exc:
        metrics.UPSTREAM_REQUESTS.labels(up.name, up.kind, "timeout").inc()
        raise UpstreamTimeoutError(f"Upstream {up.name} did not answer in time") from exc
    except httpx.HTTPError as exc:
        metrics.UPSTREAM_REQUESTS.labels(up.name, up.kind, "unreachable").inc()
        raise UpstreamError(f"Upstream {up.name} is unreachable: {type(exc).__name__}") from exc
    metrics.UPSTREAM_SECONDS.labels(up.name).observe(time.perf_counter() - started)
    metrics.UPSTREAM_REQUESTS.labels(up.name, up.kind, f"{upstream.status_code // 100}xx").inc()

    async def record(resp_body: Any) -> None:
        if opt is None or optimized_req is None:
            return
        rep = adapter.report(upstream.headers, resp_body)
        info = UpstreamInfo(up.name, rep.model, upstream.status_code, rep.cost_nusd)
        opt.run_id = await svc.record(optimized_req, opt, caller, info)

    out_headers = _response_headers(upstream, adapter, opt)
    if body.get("stream") and upstream.status_code < 400:
        await record(None)
        if opt is not None and opt.run_id is not None:
            out_headers["x-contextforge-run-id"] = str(opt.run_id)

        async def relay() -> AsyncIterator[bytes]:
            async for chunk in upstream.aiter_raw():
                yield chunk

        return StreamingResponse(
            relay(),
            status_code=upstream.status_code,
            headers=out_headers,
            media_type=upstream.headers.get("content-type", "text/event-stream"),
            background=BackgroundTask(upstream.aclose),
        )
    content = await upstream.aread()
    await upstream.aclose()
    try:
        parsed = orjson.loads(content)
    except orjson.JSONDecodeError:
        parsed = None
    await record(parsed)
    if opt is not None and opt.run_id is not None:
        out_headers["x-contextforge-run-id"] = str(opt.run_id)
    return Response(
        content=content,
        status_code=upstream.status_code,
        headers=out_headers,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


@router.get("/models", summary="Models of the default upstream (OpenAI-compatible)")
async def models(request: Request, key: ServiceKey, container: ContainerDep) -> Response:
    up = await _upstream(container, request, key)
    adapter = adapter_for(up.kind)
    try:
        upstream = await container.http.get(
            up.base_url + "/models", headers=_forward_headers(request, up, adapter)
        )
    except httpx.HTTPError as exc:
        raise UpstreamError(f"Upstream {up.name} is unreachable: {type(exc).__name__}") from exc
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )
