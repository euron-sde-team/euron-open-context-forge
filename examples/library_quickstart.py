"""Optimize a coding agent's history in process: no server, no network, no model.

    cd apps/api && uv run python ../../examples/library_quickstart.py
"""

from __future__ import annotations

from contextforge import OptimizeRequest, optimize

LOG = "\n".join(
    [f"2026-10-24 12:00:{i:02d} INFO handled /api/items in {i}ms" for i in range(40)]
    + ["Traceback (most recent call last):", '  File "src/auth/login.py", line 42, in validate',
       "jwt.ExpiredSignatureError: Signature has expired"]
)

history = [
    {"role": "system", "content": "You are a careful coding assistant."},
    {"role": "user", "content": "Fix login for USR-4821. We must keep JWT_LEEWAY_SECONDS at 30s."},
]
for i in range(5):
    history += [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"run{i}", "type": "function", "function": {"name": "run_tests", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": f"run{i}", "content": LOG},
        {"role": "assistant", "content": f"Attempt {i}: still failing with ExpiredSignatureError."},
    ]
history += [
    {"role": "assistant", "content": "Root cause: decode() ignores JWT_LEEWAY_SECONDS. We decided to pass leeway=30."},
    {"role": "user", "content": "Write the fix for src/auth/login.py."},
]

result = optimize(OptimizeRequest.model_validate(
    {"model": "gpt-4o", "messages": history, "options": {"max_input_tokens": 800}}
))
s = result.stats
print(f"{s.original_tokens:,} tokens -> {s.optimized_tokens:,} ({s.reduction_percent}% fewer)")
print(f"budget met: {s.budget_met}, facts kept: {s.facts_retained}/{s.facts_total}, tokenizer: {result.tokenizer.id}")
print(f"messages: {s.messages_in} -> {s.messages_out}, warnings: {[w.code for w in result.warnings]}")
for step in result.trace:
    print(f"  {step.stage:<9} {step.tokens_before:>6} -> {step.tokens_after:<6} {'; '.join(step.notes)}")
