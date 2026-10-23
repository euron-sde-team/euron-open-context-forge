"""Builders for realistic inputs shared by the engine tests."""

from __future__ import annotations

from typing import Any

LOG = "\n".join(
    [
        f"2026-10-0{i % 9 + 1} 12:00:{i:02d} INFO request handled in {i}ms path=/api/items"
        for i in range(60)
    ]
    + [
        "Traceback (most recent call last):",
        '  File "src/auth/login.py", line 42, in validate',
        "    token = decode(raw)",
        "jwt.ExpiredSignatureError: Signature has expired",
        "ERROR auth failed for user USR-4821",
    ]
)


def coding_trace(attempts: int = 6) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a careful coding assistant. Never print secrets."},
        {
            "role": "user",
            "content": "Help me debug the authentication service. The goal is to fix login for "
            "user USR-4821. We must keep the JWT_LEEWAY_SECONDS setting at 30s.",
        },
    ]
    for i in range(attempts):
        msgs.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {"name": "run_tests", "arguments": "{}"},
                    }
                ],
            }
        )
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": LOG})
        msgs.append(
            {
                "role": "assistant",
                "content": f"Attempt {i}: the test still fails with ExpiredSignatureError in "
                "src/auth/login.py. I think the clock skew is the issue. Let's try again.",
            }
        )
    msgs.append(
        {
            "role": "assistant",
            "content": "Root cause: decode() ignores JWT_LEEWAY_SECONDS. We decided to pass "
            "leeway=30 to jwt.decode().",
        }
    )
    msgs.append(
        {
            "role": "user",
            "content": "Great, now write the fix for src/auth/login.py and a regression test.",
        }
    )
    return msgs


FILLER = (
    "I checked the dashboard again and the page looks the same as before, nothing new to "
    "report on my side. "
)


def support_thread(turns: int = 30) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": "You are Acme support. Be concise."},
        {
            "role": "user",
            "content": "Hi, I need to move my team from the Starter plan to Business before the "
            "invoice on 2026-11-01. Our account id is ACC-77120.",
        },
        {
            "role": "assistant",
            "content": "Sure. Business costs $49 per seat per month. We must not change the billing "
            "email billing@northwind.example without verification.",
        },
    ]
    for i in range(turns):
        msgs.append(
            {"role": "user", "content": FILLER * 3 + (f"Is SSO included? ({i})" if i == 3 else "")}
        )
        msgs.append({"role": "assistant", "content": "Thanks for the update. " + FILLER * 2})
    msgs.append(
        {
            "role": "assistant",
            "content": "We decided to migrate on 2026-10-28 with 42 seats, keeping the annual discount of 15%.",
        }
    )
    msgs.append(
        {
            "role": "user",
            "content": "OK. What happens to our existing API keys during the migration?",
        }
    )
    return msgs


DOCS: list[dict[str, Any]] = [
    {
        "id": "kb-1",
        "text": "API keys are preserved when you change plans. Keys keep their scopes and rate limits.",
        "source": "kb/billing.md",
        "metadata": {"section": "plans"},
    },
    {
        "id": "kb-2",
        "text": "API keys are preserved when you change plans. Keys keep their scopes and rate limits!",
        "source": "kb/billing-copy.md",
    },
    {
        "id": "kb-3",
        "text": "Our office dog is called Biscuit and loves the garden.",
        "source": "kb/culture.md",
    },
    {
        "id": "kb-4",
        "text": "During a plan migration, SSO configuration and API keys are copied automatically. See [kb-1].",
        "source": "kb/sso.md",
        "score": 0.4,
    },
]
