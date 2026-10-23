"""Deterministic mock LLM upstream for the demo, the tests and the benchmark reader.

Three OpenAI-compatible surfaces, each following the documented contract of what it
simulates (and labelled as a simulation wherever results are reported):

  /v1/...              a plain OpenAI-compatible provider
  /tokenshield/v1/...  a TokenShield gateway: x-tokenshield-* headers, cost header,
                       402 budget_exceeded for model "over-budget" or user "over-budget"
  /smartrouter/v1/...  a SmartRouter: model "auto" or "auto:<policy>" routes to
                       gpt-4o-mini and reports x-smartrouter-* headers

Answers are deterministic: the ContextForge summarizer prompt gets a short (deliberately
incomplete) summary so the fact guard is exercised; the model "reader" answers with the
sentence that best matches the question; everything else gets a short acknowledgement.
Special models: "fail-500" returns 500, "slow" waits 3 s. GET /stats shows call counts and
the last request seen.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="ContextForge mock LLM", docs_url=None, redoc_url=None)
STATS: dict[str, Any] = {"calls": Counter(), "last": None}
_WORD = re.compile(r"[a-z0-9_]+")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def _reader(messages: list[dict[str, Any]]) -> str:
    question = next(
        (_text(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), ""
    )
    q = set(_WORD.findall(question.lower()))
    best, score = "I could not find that in the context.", 0
    for m in messages[:-1]:
        for sentence in re.split(r"(?<=[.!?])\s+", _text(m.get("content"))):
            s = len(q & set(_WORD.findall(sentence.lower())))
            if s > score:
                best, score = sentence.strip(), s
    return best


def _answer(body: dict[str, Any]) -> str:
    messages = body.get("messages") or []
    system = _text(messages[0].get("content")) if messages else ""
    if system.startswith("You are the ContextForge summarizer"):
        convo = _text(messages[-1].get("content"))
        first = next((ln for ln in convo.splitlines() if ln.startswith("user:")), "user: (none)")
        sentence = re.split(r"(?<=[.!?])\s+", first[5:].strip())[0]
        return f"Goals:\n- {sentence}"
    if body.get("model") == "reader":
        return _reader(messages)
    chars = sum(len(_text(m.get("content"))) for m in messages)
    return f"Mock answer. I received {len(messages)} messages ({chars:,} characters)."


def _usage(body: dict[str, Any], answer: str) -> dict[str, int]:
    prompt = sum(len(_text(m.get("content"))) for m in body.get("messages") or []) // 4 + 1
    completion = len(answer) // 4 + 1
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


async def _complete(request: Request, surface: str) -> Any:
    body = await request.json()
    STATS["calls"][surface] += 1
    STATS["last"] = {
        "surface": surface,
        "model": body.get("model"),
        "messages": len(body.get("messages") or []),
        "characters": sum(len(_text(m.get("content"))) for m in body.get("messages") or []),
        "headers": {
            k: v for k, v in request.headers.items() if k.startswith(("x-", "authorization"))
        },
    }
    model = str(body.get("model", "mock"))
    if model == "fail-500":
        return JSONResponse(
            {"error": {"message": "mock upstream failure", "type": "api_error"}}, 500
        )
    if model == "slow":
        await asyncio.sleep(3)
    headers: dict[str, str] = {}
    over = model == "over-budget" or request.headers.get("x-tokenshield-user") == "over-budget"
    if surface == "tokenshield" and over:
        return JSONResponse(
            {
                "error": {
                    "code": "budget_exceeded",
                    "type": "budget_error",
                    "message": "This request would exceed the monthly hard budget",
                    "details": {"remaining_usd": 0.0},
                }
            },
            402,
            headers={"x-tokenshield-request-id": "ts_mock_402"},
        )
    if surface == "smartrouter" and model.startswith("auto"):
        policy = model.split(":", 1)[1] if ":" in model else "balanced"
        model = "gpt-4o-mini"
        headers.update(
            {
                "x-smartrouter-model": model,
                "x-smartrouter-policy": policy,
                "x-smartrouter-task": "chat",
                "x-smartrouter-request-id": "sr_mock",
            }
        )
    answer = _answer(body)
    usage = _usage(body, answer)
    cost = f"{usage['prompt_tokens'] * 0.15e-6 + usage['completion_tokens'] * 0.6e-6:.9f}"
    if surface == "tokenshield":
        headers.update(
            {
                "x-tokenshield-request-id": f"ts_mock_{STATS['calls'][surface]}",
                "x-tokenshield-cache": "MISS",
                "x-tokenshield-cost-usd": cost,
            }
        )
    if surface == "smartrouter":
        headers["x-smartrouter-cost-usd"] = cost
    created = int(time.time())
    if body.get("stream"):

        async def events() -> Any:
            for i, word in enumerate(answer.split(" ")):
                chunk = {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": (" " if i else "") + word},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            done = {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": usage,
            }
            yield f"data: {json.dumps(done)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream", headers=headers)
    return JSONResponse(
        {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        },
        headers=headers,
    )


def _models() -> dict[str, Any]:
    names = ["gpt-4o", "gpt-4o-mini", "reader", "auto"]
    return {
        "object": "list",
        "data": [{"id": n, "object": "model", "owned_by": "mock"} for n in names],
    }


@app.post("/v1/chat/completions")
async def openai_chat(request: Request) -> Any:
    return await _complete(request, "openai")


@app.post("/tokenshield/v1/chat/completions")
async def tokenshield_chat(request: Request) -> Any:
    return await _complete(request, "tokenshield")


@app.post("/smartrouter/v1/chat/completions")
async def smartrouter_chat(request: Request) -> Any:
    return await _complete(request, "smartrouter")


@app.get("/v1/models")
@app.get("/tokenshield/v1/models")
@app.get("/smartrouter/v1/models")
async def models() -> dict[str, Any]:
    return _models()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
async def stats() -> dict[str, Any]:
    return {"calls": dict(STATS["calls"]), "last": STATS["last"]}


@app.post("/stats/reset")
async def reset() -> dict[str, bool]:
    STATS["calls"].clear()
    STATS["last"] = None
    return {"ok": True}
