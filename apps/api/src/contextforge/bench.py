"""Service latency and throughput against the running stack (``make bench``).

Measures, over HTTP against the production images:

* ``/v1/context/count-tokens`` on a short text (the floor: auth, rate limit, routing);
* ``/v1/context/optimize`` cold (a nonce in the system prompt defeats the result cache)
  on three committed samples of increasing size, and warm (an identical repeat);
* the proxy's overhead: the mock upstream called directly vs through
  ``/v1/chat/completions`` with a small conversation;
* throughput: concurrent cold optimizations of the 1.7K-token support sample.

Prints a markdown table. Numbers depend on the machine; the README records one run.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from contextforge.benchmarks import load_cases

API = os.environ.get("CONTEXTFORGE_API_URL", "http://localhost:4330")
MOCK = os.environ.get("MOCK_LLM_URL", "http://localhost:4350")
EMAIL = os.environ.get("DEMO_EMAIL", "admin@contextforge.local")
PASSWORD = os.environ.get("DEMO_PASSWORD", "ForgeDemo2026")


def pct(samples: list[float], q: float) -> float:
    s = sorted(samples)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


async def timed(n: int, fn: Callable[[int], Awaitable[httpx.Response]]) -> list[float]:
    out = []
    for i in range(n):
        t0 = time.perf_counter()
        resp = await fn(i)
        out.append((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
    return out


async def main() -> None:
    _, cases = load_cases()
    by_id = {c.id: c for c in cases}
    async with httpx.AsyncClient(base_url=API, timeout=60) as client:
        login = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        login.raise_for_status()
        admin = {"authorization": f"Bearer {login.json()['session_token']}"}
        key = (
            await client.post(
                "/api/v1/keys",
                headers=admin,
                json={
                    "name": f"bench-{uuid.uuid4().hex[:6]}",
                    "rpm_limit": 1_000_000,
                    "default_upstream": "mock-openai",
                },
            )
        ).json()
        auth = {"authorization": f"Bearer {key['key']}"}

        def body(case_id: str, nonce: str | None) -> dict[str, Any]:
            c = by_id[case_id]
            msgs = [m.model_dump(exclude_none=True) for m in c.messages]
            if nonce is not None:
                msgs[0] = {**msgs[0], "content": f"{msgs[0]['content']} ({nonce})"}
            return {
                "model": c.model,
                "messages": msgs,
                "documents": [d.model_dump(exclude_none=True) for d in c.documents],
                "options": {"max_input_tokens": c.max_input_tokens, "include_trace": False},
            }

        rows: list[tuple[str, list[float], str]] = []
        rows.append(
            (
                "count-tokens, 10 tokens",
                await timed(
                    200,
                    lambda _: client.post(
                        "/v1/context/count-tokens",
                        headers=auth,
                        json={
                            "model": "gpt-4o",
                            "text": "Less context. Fewer tokens. Same intelligence.",
                        },
                    ),
                ),
                "",
            )
        )
        for case_id in ("support-21", "rag-33", "coding-12"):
            c = by_id[case_id]
            sample = body(case_id, None)
            first = (await client.post("/v1/context/optimize", headers=auth, json=sample)).json()
            note = f"{first['stats']['original_tokens']:,} to {first['stats']['optimized_tokens']:,} tokens"
            n = 60 if case_id != "coding-12" else 30

            def cold(i: int, cid: str = case_id) -> Awaitable[httpx.Response]:
                return client.post(
                    "/v1/context/optimize",
                    headers=auth,
                    json=body(cid, f"{uuid.uuid4().hex[:8]}-{i}"),
                )

            def warm(_: int, s: dict[str, Any] = sample) -> Awaitable[httpx.Response]:
                return client.post("/v1/context/optimize", headers=auth, json=s)

            rows.append(
                (
                    f"optimize cold, {c.workload} sample",
                    await timed(
                        n,
                        cold,
                    ),
                    note,
                )
            )
            rows.append(
                (
                    f"optimize warm (cache hit), {c.workload} sample",
                    await timed(
                        n,
                        warm,
                    ),
                    note,
                )
            )

        chat = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello there"}]}
        async with httpx.AsyncClient(base_url=MOCK, timeout=30) as mock:
            direct = await timed(200, lambda _: mock.post("/v1/chat/completions", json=chat))
        proxied = await timed(
            200, lambda _: client.post("/v1/chat/completions", headers=auth, json=chat)
        )
        rows.append(("upstream called directly", direct, "mock provider"))
        rows.append(("through the ContextForge proxy", proxied, "optimize + forward"))

        # Throughput: N concurrent clients for a fixed window, cold every time.
        stop = time.perf_counter() + 10
        done = 0

        async def worker() -> None:
            nonlocal done
            while time.perf_counter() < stop:
                r = await client.post(
                    "/v1/context/optimize",
                    headers=auth,
                    json=body("support-21", uuid.uuid4().hex[:8]),
                )
                if r.status_code == 200:
                    done += 1

        await asyncio.gather(*(worker() for _ in range(16)))
        rps = done / 10

    print("| Measurement | p50 | p95 | Notes |")
    print("| --- | ---: | ---: | --- |")
    for name, samples, note in rows:
        print(
            f"| {name} | {statistics.median(samples):.1f} ms | {pct(samples, 0.95):.1f} ms | {note} |"
        )
    overhead = [p - d for p, d in zip(sorted(proxied), sorted(direct), strict=True)]
    print(
        f"| proxy overhead | {statistics.median(overhead):.1f} ms | {pct(overhead, 0.95):.1f} ms | proxied minus direct |"
    )
    print(
        f"\nThroughput: {rps:.0f} cold optimizations per second (support sample, 16 concurrent clients, 10 s)"
    )


if __name__ == "__main__":
    asyncio.run(main())
