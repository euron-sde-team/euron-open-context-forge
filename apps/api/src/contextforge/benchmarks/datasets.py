"""Synthetic benchmark datasets, generated deterministically from a seed.

The cases are modelled on real workload shapes (a coding agent looping on a failing test,
a long support thread, a RAG question over a noisy retrieval, a research question with
conflicting sources, an agent drowning in JSON search results) but every word is generated
here: no customer data, no LLM output. Each case carries **gold facts** (strings a correct
answer depends on, which must survive verbatim), **required citations** (document ids that
must stay resolvable) and **questions** for the simulated reader.

``python -m contextforge.benchmarks generate`` writes them to ``datasets/*.json``; the
committed files are what ``make benchmark`` runs, so results are reproducible.
"""

from __future__ import annotations

import json
import random
from typing import Any

from pydantic import BaseModel, Field

from contextforge.engine.types import Document, Message

VERSION = "2026.10"


class Question(BaseModel):
    question: str
    answer: str = Field(description="A gold fact; the reader is right when it finds it")


class Case(BaseModel):
    id: str
    workload: str
    title: str
    description: str
    model: str = "gpt-4o"
    max_input_tokens: int
    messages: list[Message] = Field(default_factory=list)
    documents: list[Document] = Field(default_factory=list)
    gold_facts: list[str]
    required_citations: list[str] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)


def _msg(role: str, content: str | None, **extra: Any) -> Message:
    return Message.model_validate({"role": role, "content": content, **extra})


# ─── Coding agent ─────────────────────────────────────────────────────────────────────

_SERVICES = ["billing", "auth", "search", "inventory", "notifications", "checkout"]
_ERRORS = [
    ("KeyError", "'currency_code'"),
    ("TimeoutError", "upstream did not answer within 30s"),
    ("IntegrityError", 'duplicate key value violates unique constraint "orders_pkey"'),
    ("ValueError", "invalid literal for int() with base 10: 'N/A'"),
    ("AssertionError", "expected status 200, got 500"),
]


def _python_file(rng: random.Random, module: str, lines: int) -> str:
    out = [f'"""{module} service handlers."""', "", "from __future__ import annotations", ""]
    for i in range(lines // 6):
        name = f"{rng.choice(['load', 'save', 'parse', 'render', 'sync', 'check'])}_{module}_{i}"
        out += [
            f"def {name}(payload: dict) -> dict:",
            f"    value = payload.get('field_{i}', {rng.randint(0, 999)})",
            "    if value is None:",
            f"        return {{'ok': False, 'reason': 'missing field_{i}'}}",
            f"    return {{'ok': True, 'value': value * {rng.randint(2, 9)}}}",
            "",
        ]
    return "\n".join(out)


def _test_log(rng: random.Random, module: str, err: tuple[str, str], path: str, line: int) -> str:
    out = [
        "============================= test session starts =============================",
        f"collected {rng.randint(140, 260)} items",
        "",
    ]
    for i in range(rng.randint(60, 110)):
        out.append(f"tests/test_{module}.py::test_case_{i} PASSED{' ' * 20}[{i % 100:3d}%]")
    out += [
        f"tests/test_{module}.py::test_regression FAILED",
        "",
        "=================================== FAILURES ===================================",
        "Traceback (most recent call last):",
        f'  File "{path}", line {line}, in handle',
        "    result = process(order)",
        f'  File "src/{module}/core.py", line {line + 17}, in process',
        "    return totals[key]",
        f"{err[0]}: {err[1]}",
        f"FAILED tests/test_{module}.py::test_regression - {err[0]}: {err[1]}",
        f"======== 1 failed, {rng.randint(140, 250)} passed in {rng.randint(8, 40)}.{rng.randint(10, 99)}s ========",
    ]
    return "\n".join(out)


def coding_case(seed: int, attempts: int, file_lines: int, budget: int) -> Case:
    rng = random.Random(seed)
    module = rng.choice(_SERVICES)
    err = rng.choice(_ERRORS)
    ticket = f"ENG-{rng.randint(1000, 9999)}"
    path = f"src/{module}/handlers.py"
    line = rng.randint(40, 300)
    flag = f"{module.upper()}_STRICT_MODE"
    version = f"v{rng.randint(1, 4)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}"
    fix_value = rng.randint(2, 9) * 10
    msgs = [
        _msg(
            "system",
            "You are a senior engineer pairing on a Python monorepo. Explain fixes "
            "briefly and never commit secrets.",
        ),
        _msg(
            "user",
            f"Ticket {ticket}: the {module} service started failing after the "
            f"{version} release. The goal is to make tests/test_{module}.py pass "
            f"again. We must not disable {flag}, and the fix has to stay "
            f"backwards compatible with {version}.",
        ),
    ]
    call = 0
    for a in range(attempts):
        call += 1
        cid = f"call_{seed}_{call}"
        msgs.append(
            _msg(
                "assistant",
                None,
                tool_calls=[
                    {
                        "id": cid,
                        "type": "function",
                        "function": {"name": "read_file", "arguments": json.dumps({"path": path})},
                    }
                ],
            )
        )
        msgs.append(_msg("tool", _python_file(rng, module, file_lines), tool_call_id=cid))
        call += 1
        cid = f"call_{seed}_{call}"
        msgs.append(
            _msg(
                "assistant",
                None,
                tool_calls=[
                    {
                        "id": cid,
                        "type": "function",
                        "function": {
                            "name": "run_tests",
                            "arguments": json.dumps({"path": f"tests/test_{module}.py"}),
                        },
                    }
                ],
            )
        )
        msgs.append(_msg("tool", _test_log(rng, module, err, path, line), tool_call_id=cid))
        msgs.append(
            _msg(
                "assistant",
                f"Attempt {a + 1}: the regression test still fails with "
                f"{err[0]} at {path} line {line}. I will add more logging "
                "around process() and run the suite again.",
            )
        )
        if a % 3 == 1:
            msgs.append(
                _msg(
                    "user", "Any progress? Keep going, but remember the constraint from the ticket."
                )
            )
    msgs.append(
        _msg(
            "assistant",
            f"Root cause: process() reads totals before the cache warms "
            f"up. We decided to retry the lookup {fix_value} times "
            f"behind {flag} instead of disabling it.",
        )
    )
    msgs.append(_msg("user", f"Good. Write the patch for {path} and summarise what changed."))
    return Case(
        id=f"coding-{seed}",
        workload="coding",
        title=f"Coding agent, {attempts} attempts on {ticket}",
        description="A coding agent re-reads the same file and re-runs the same failing test "
        "many times before finding the root cause.",
        max_input_tokens=budget,
        messages=msgs,
        gold_facts=[ticket, path, flag, version, err[0], f"retry the lookup {fix_value} times"],
        questions=[
            Question(question="Which ticket is this?", answer=ticket),
            Question(question="Which setting must not be disabled?", answer=flag),
            Question(question="What exception does the regression test raise?", answer=err[0]),
        ],
    )


# ─── Support thread ───────────────────────────────────────────────────────────────────

_SMALLTALK = [
    "Thanks, I will check with my team and come back to you.",
    "I refreshed the page a few times and it looks the same as before.",
    "Sorry for the delay, we had a long meeting this afternoon.",
    "Could you hold on a moment while I look for the right screen?",
    "Our finance colleague is out today, so bear with me.",
    "That makes sense, I appreciate the patience.",
]


def support_case(seed: int, turns: int, budget: int) -> Case:
    rng = random.Random(seed)
    account = f"ACC-{rng.randint(10000, 99999)}"
    seats = rng.randint(12, 180)
    price = rng.choice([19, 29, 49, 79])
    date = f"2026-11-{rng.randint(10, 28):02d}"
    email = f"finance-{rng.randint(10, 99)}@northwind.example"
    discount = rng.choice([10, 15, 20])
    msgs = [
        _msg(
            "system",
            "You are the support assistant for a SaaS company. Be precise about "
            "billing and never change contact details without verification.",
        ),
        _msg(
            "user",
            f"Hello, our account is {account}. I need to move our {seats} seats from "
            f"Starter to Business before the renewal on {date}.",
        ),
        _msg(
            "assistant",
            f"Happy to help. Business is ${price} per seat per month. We must not "
            f"change the billing contact {email} without a verification call.",
        ),
    ]
    for i in range(turns):
        msgs.append(_msg("user", " ".join(rng.sample(_SMALLTALK, 3))))
        msgs.append(_msg("assistant", "No problem at all. " + " ".join(rng.sample(_SMALLTALK, 2))))
        if i == turns // 2:
            msgs.append(_msg("user", "Also, is single sign on included in Business?"))
            msgs.append(_msg("assistant", "Yes, single sign on with SAML is included in Business."))
    msgs.append(
        _msg(
            "assistant",
            f"We agreed to keep the annual discount of {discount}% and to switch plans on {date}.",
        )
    )
    msgs.append(_msg("user", "Great. Can you confirm the final monthly total for us?"))
    return Case(
        id=f"support-{seed}",
        workload="support",
        title=f"Support thread, {turns * 2 + 6} messages",
        description="A billing conversation where the key facts are stated early and buried "
        "under small talk.",
        max_input_tokens=budget,
        messages=msgs,
        gold_facts=[account, str(seats), f"${price}", date, email, f"{discount}%"],
        questions=[
            Question(question="What is the account id?", answer=account),
            Question(question="What is the Business price per seat?", answer=f"${price}"),
            Question(question="Which billing contact must not change?", answer=email),
        ],
    )


# ─── RAG and research ─────────────────────────────────────────────────────────────────

_TOPICS = {
    "retention": "Data retention for audit logs is {n} days on the Enterprise plan.",
    "regions": "Customer data can be stored in the {r} region when residency is enabled.",
    "limits": "The API rate limit is {n} requests per minute per key.",
    "sla": "The uptime commitment is {p}% measured monthly.",
}
_NOISE = [
    "The office kitchen is restocked every Monday morning.",
    "Our design team prefers rounded corners and soft shadows.",
    "The quarterly offsite will take place by the lake this year.",
    "Holiday requests should be submitted two weeks in advance.",
    "The company newsletter goes out on the first Friday of the month.",
    "Parking passes are available from the front desk.",
    "The style guide recommends sentence case for headings.",
    "New laptops are provisioned within three working days.",
]


def rag_case(seed: int, noise_docs: int, dup_docs: int, budget: int) -> Case:
    rng = random.Random(seed)
    n_ret = rng.choice([90, 180, 365])
    rpm = rng.choice([600, 1200, 3000])
    region = rng.choice(["eu-central", "ap-south", "us-east"])
    docs: list[Document] = []
    relevant = [
        Document(
            id=f"doc-{seed}-ret",
            source="handbook/security.md",
            title="Audit log retention",
            text=_TOPICS["retention"].format(n=n_ret) + " Older entries are archived to "
            "cold storage and can be restored on request. Retention applies to every "
            "workspace in the organisation.",
            metadata={"section": "security"},
        ),
        Document(
            id=f"doc-{seed}-rate",
            source="handbook/api.md",
            title="Rate limits",
            text=_TOPICS["limits"].format(n=rpm) + " Bursts above the rate limit "
            "receive HTTP 429 with a Retry-After header.",
            metadata={"section": "api"},
        ),
        Document(
            id=f"doc-{seed}-region",
            source="handbook/residency.md",
            title="Data residency",
            text=_TOPICS["regions"].format(r=region) + " Residency applies to audit "
            "logs and backups as well.",
            metadata={"section": "compliance"},
        ),
    ]
    docs.extend(relevant)
    for k in range(dup_docs):
        base = relevant[k % len(relevant)]
        docs.append(
            Document(
                id=f"doc-{seed}-dup{k}",
                source=f"{base.source}#copy{k}",
                title=base.title,
                text=base.text.replace(".", " .", 1) if k % 2 else base.text,
                metadata=dict(base.metadata),
            )
        )
    for k in range(noise_docs):
        para = " ".join(rng.sample(_NOISE, 4))
        docs.append(
            Document(
                id=f"doc-{seed}-n{k}", source=f"wiki/page-{k}.md", title=f"Wiki page {k}", text=para
            )
        )
    rng.shuffle(docs)
    msgs = [
        _msg("system", "Answer from the provided documents only and cite them as [id]."),
        _msg(
            "user",
            "How long are audit logs retained, what is the API rate limit, and can "
            "audit logs stay in a specific region?",
        ),
    ]
    return Case(
        id=f"rag-{seed}",
        workload="rag",
        title=f"RAG, {len(docs)} retrieved chunks",
        description="A retrieval with near-duplicate chunks and off-topic noise around three "
        "relevant passages.",
        max_input_tokens=budget,
        messages=msgs,
        documents=docs,
        gold_facts=[f"{n_ret} days", f"{rpm} requests per minute", region],
        required_citations=[d.id for d in relevant],
        questions=[
            Question(question="How long are audit logs retained?", answer=f"{n_ret} days"),
            Question(question="What is the API rate limit?", answer=f"{rpm} requests per minute"),
            Question(question="Which region can store customer data?", answer=region),
        ],
    )


def research_case(seed: int, noise_docs: int, budget: int) -> Case:
    rng = random.Random(seed)
    a, b = rng.choice([(31, 18), (42, 27), (25, 12)])
    docs = [
        Document(
            id=f"study-{seed}-a",
            source="journal/remote-work-2025.pdf",
            title="Study A",
            text=f"Study A followed 1,200 engineers and found remote teams shipped {a}% "
            "more pull requests per week, with no change in defect rates.",
            metadata={"year": 2025},
        ),
        Document(
            id=f"study-{seed}-b",
            source="journal/office-teams-2026.pdf",
            title="Study B",
            text=f"Study B contradicts this: co-located teams resolved incidents {b}% "
            "faster, and the authors argue throughput metrics overstate remote gains.",
            metadata={"year": 2026},
        ),
    ]
    for k in range(noise_docs):
        docs.append(
            Document(
                id=f"study-{seed}-n{k}",
                source=f"blog/post-{k}.html",
                title=f"Blog {k}",
                text=" ".join(rng.sample(_NOISE, 3)),
            )
        )
    rng.shuffle(docs)
    msgs = [
        _msg("system", "You are a research assistant. Compare the evidence and cite sources."),
        _msg(
            "user",
            "Compare the evidence on remote versus co-located engineering teams. "
            "Cite the sources that contradict each other.",
        ),
    ]
    return Case(
        id=f"research-{seed}",
        workload="research",
        title=f"Research with conflicting evidence, {len(docs)} sources",
        description="Two studies disagree; both must survive with their citations.",
        max_input_tokens=budget,
        messages=msgs,
        documents=docs,
        gold_facts=[f"{a}% more pull requests", f"{b}% faster"],
        required_citations=[f"study-{seed}-a", f"study-{seed}-b"],
        questions=[
            Question(
                question="How many more pull requests did remote teams ship?",
                answer=f"{a}% more pull requests",
            ),
            Question(
                question="How much faster did co-located teams resolve incidents?",
                answer=f"{b}% faster",
            ),
        ],
    )


def agent_json_case(seed: int, searches: int, budget: int) -> Case:
    rng = random.Random(seed)
    sku = f"SKU-{rng.randint(100000, 999999)}"
    warehouse = rng.choice(["Pune", "Leeds", "Austin"])
    msgs = [
        _msg("system", "You are a procurement agent. Use tools, then report the result."),
        _msg(
            "user",
            f"Find where {sku} is in stock and reserve 20 units. The budget limit is "
            "$5,000 and we must only use approved suppliers.",
        ),
    ]
    for s in range(searches):
        cid = f"search_{seed}_{s}"
        items = [
            {
                "sku": f"SKU-{rng.randint(100000, 999999)}",
                "warehouse": rng.choice(["Pune", "Leeds", "Austin", "Lyon"]),
                "qty": rng.randint(0, 500),
                "supplier": f"Supplier {rng.randint(1, 40)}",
                "description": "Industrial fastener, zinc plated, " + "standard grade " * 6,
            }
            for _ in range(80)
        ]
        if s == searches - 1:
            items[57] = {
                "sku": sku,
                "warehouse": warehouse,
                "qty": 240,
                "supplier": "Supplier 7",
                "description": "Approved supplier, in stock",
                "status": "approved",
            }
        msgs.append(
            _msg(
                "assistant",
                None,
                tool_calls=[
                    {
                        "id": cid,
                        "type": "function",
                        "function": {
                            "name": "search_inventory",
                            "arguments": json.dumps({"query": sku, "page": s + 1}),
                        },
                    }
                ],
            )
        )
        msgs.append(_msg("tool", json.dumps({"page": s + 1, "results": items}), tool_call_id=cid))
        msgs.append(
            _msg(
                "assistant",
                f"Page {s + 1} checked."
                + (" Found it." if s == searches - 1 else " Not found yet."),
            )
        )
    msgs.append(_msg("user", "Which warehouse has it and how many units are available?"))
    return Case(
        id=f"agent-{seed}",
        workload="agent",
        title=f"Agent with {searches} large JSON search results",
        description="Paginated JSON tool results where one item out of hundreds matters.",
        max_input_tokens=budget,
        messages=msgs,
        gold_facts=[sku, warehouse, "$5,000", "approved suppliers"],
        questions=[
            Question(question="Which SKU are we looking for?", answer=sku),
            Question(question="Which warehouse has it?", answer=warehouse),
        ],
    )


def build_cases() -> list[Case]:
    return [
        coding_case(11, attempts=4, file_lines=120, budget=3000),
        coding_case(12, attempts=8, file_lines=180, budget=4000),
        coding_case(13, attempts=14, file_lines=240, budget=6000),
        support_case(21, turns=20, budget=900),
        support_case(22, turns=45, budget=1200),
        support_case(23, turns=80, budget=1500),
        rag_case(31, noise_docs=20, dup_docs=6, budget=900),
        rag_case(32, noise_docs=45, dup_docs=10, budget=1200),
        rag_case(33, noise_docs=90, dup_docs=15, budget=1500),
        research_case(41, noise_docs=20, budget=700),
        research_case(42, noise_docs=40, budget=900),
        agent_json_case(51, searches=5, budget=4000),
    ]


def to_json(cases: list[Case]) -> str:
    return json.dumps(
        {"version": VERSION, "cases": [c.model_dump(exclude_none=True) for c in cases]},
        indent=1,
        ensure_ascii=False,
    )
