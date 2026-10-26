"""Use an unmodified OpenAI SDK through ContextForge's proxy (needs `make up && make demo`).

    export CONTEXTFORGE_KEY=cfk_...      # printed by make demo
    cd apps/api && uv run python ../../examples/openai_proxy.py
"""

from __future__ import annotations

import os

from openai import OpenAI

client = OpenAI(
    base_url=os.environ.get("CONTEXTFORGE_URL", "http://localhost:4330") + "/v1",
    api_key=os.environ["CONTEXTFORGE_KEY"],
    default_headers={"x-contextforge-max-input-tokens": "300"},
)
filler = "I refreshed the page again and nothing changed on my side. " * 4
history = [{"role": "system", "content": "You are Acme support."},
           {"role": "user", "content": "Our account is ACC-77120; we need 42 seats by 2026-11-01."}]
history += [{"role": "user", "content": filler} for _ in range(12)]
history.append({"role": "user", "content": "Can you confirm the seat count?"})

raw = client.chat.completions.with_raw_response.create(model="gpt-4o", messages=history)
h = raw.headers
print(f"tokens {h['x-contextforge-original-tokens']} -> {h['x-contextforge-optimized-tokens']}"
      f" ({h['x-contextforge-reduction-percent']}% fewer), run {h['x-contextforge-run-id']}")
print("answer:", raw.parse().choices[0].message.content)
