"""Unit tests for the engine's building blocks."""

from __future__ import annotations

import json

from contextforge.engine.bm25 import BM25, rank
from contextforge.engine.profiles import BUILTIN_PROFILES, allocate, detect_workload
from contextforge.engine.summarizer import ExtractiveSummarizer, SummaryInput, SummaryUnit
from contextforge.engine.text import (
    classify,
    containment,
    extract_facts,
    jaccard,
    normalize,
    salient_facts,
    shingles,
    split_blocks,
    split_sentences,
    terms,
)
from contextforge.engine.tokenizers import TokenizerRegistry
from contextforge.engine.toolout import HARD, NORMAL, reduce_output
from contextforge.engine.types import Document, Message
from tests.unit.engine.fixtures import LOG

TOK = TokenizerRegistry().resolve("gpt-4o")


def test_code_fence_is_one_atomic_block() -> None:
    text = "Here is the fix:\n\n```python\ndef f():\n\n    return 1\n```\n\nDone."
    blocks = split_blocks(text)
    assert [b.kind for b in blocks] == ["prose", "code", "prose"]
    assert blocks[1].text.count("\n\n") == 1


def test_unterminated_fence_stays_whole() -> None:
    blocks = split_blocks("intro\n\n```\na\n\nb")
    assert blocks[-1].kind == "code" and "b" in blocks[-1].text


def test_whole_json_is_one_block() -> None:
    blocks = split_blocks(json.dumps({"a": [1, 2], "b": {"c": "d"}}, indent=2))
    assert len(blocks) == 1 and blocks[0].kind == "json"


def test_classify_log_and_list() -> None:
    assert classify(LOG) == "log"
    assert classify("- one\n- two\n- three") == "list"
    assert classify("A plain sentence.") == "prose"


def test_sentences_and_bullets() -> None:
    assert split_sentences("First one. Second one! Third?") == [
        "First one.",
        "Second one!",
        "Third?",
    ]
    assert split_sentences("- a\n- b") == ["- a", "- b"]


def test_terms_split_identifiers() -> None:
    t = terms("getUserById fails in user_service.py")
    assert {"getuserbyid", "user", "id", "fails", "user_service.py", "service"} <= set(t)
    assert "in" not in t


def test_facts_cover_common_shapes() -> None:
    facts = extract_facts(
        "Order ORD-12345 on 2026-10-28 failed with KeyError in src/app/main.py at port 5432; "
        "set MAX_RETRIES to 3, see https://example.com/x, v1.4.2, $49.50, 250ms, commit 3f9a2c1d."
    )
    for f in (
        "ORD-12345",
        "2026-10-28",
        "KeyError",
        "src/app/main.py",
        "MAX_RETRIES",
        "https://example.com/x",
        "v1.4.2",
        "$49.50",
        "250ms",
        "3f9a2c1d",
    ):
        assert f in facts, f


def test_plain_words_are_not_hashes() -> None:
    assert "1234567" not in extract_facts("call 1234567 now")
    assert "deadbeef" not in extract_facts("deadbeef")


def test_salient_facts_ignore_routine_log_lines() -> None:
    facts = salient_facts(LOG, tool=True)
    assert "ExpiredSignatureError" in facts and "USR-4821" in facts
    assert not any(f.endswith("ms") for f in facts)


def test_normalize_fuzzy_numbers() -> None:
    assert normalize("took 12ms  at 10:00") == "took 12ms at 10:00"
    assert normalize("took 12ms", fuzzy_numbers=True) == normalize("took 99ms", fuzzy_numbers=True)


def test_similarity_measures() -> None:
    a = shingles("the quick brown fox jumps over the lazy dog today", 3)
    b = shingles("the quick brown fox jumps over the lazy dog tomorrow", 3)
    assert 0.6 < jaccard(a, b) < 1.0
    assert containment(a, a | {1, 2, 3}) == 1.0
    assert jaccard(set(), a) == 0.0 and containment(set(), a) == 0.0


def test_bm25_prefers_relevant_passage() -> None:
    order = rank("expired jwt token", ["the dog sleeps", "jwt token expired at login", "token"])
    assert order[0][0] == 1
    assert BM25([]).scores("x") == []
    assert BM25(["a b"]).normalized("") == [0.0]


def test_reduce_logs_keeps_errors_and_collapses_repeats() -> None:
    reduced = reduce_output(LOG, NORMAL, set())
    assert reduced is not None
    assert "ExpiredSignatureError" in reduced and "USR-4821" in reduced
    assert "lines omitted" in reduced
    assert len(reduced) < len(LOG) / 2


def test_reduce_json_stays_valid_and_keeps_signal_items() -> None:
    data = [{"id": i, "msg": "ok"} for i in range(100)]
    data[77]["msg"] = "timeout talking to db"
    reduced = reduce_output(json.dumps(data), HARD, set())
    assert reduced is not None
    parsed = json.loads(reduced)
    assert any(isinstance(x, dict) and x.get("id") == 77 for x in parsed)
    assert parsed[-1].startswith("[ContextForge:")


def test_reduce_skips_short_output() -> None:
    assert reduce_output("short", NORMAL, set()) is None


def test_reduce_long_single_line() -> None:
    reduced = reduce_output("x" * 20000, NORMAL, set())
    assert reduced is not None and "chars omitted" in reduced


def test_allocate_redistributes_unused_share() -> None:
    weights = BUILTIN_PROFILES["rag"].normalized()
    alloc = allocate(1000, {"history": 50, "tool": 0, "documents": 5000, "summary": 100}, weights)
    assert alloc["history"] == 50 and alloc["tool"] == 0
    assert sum(alloc.values()) <= 1000
    assert alloc["documents"] >= 800


def test_allocate_zero_and_zero_weight() -> None:
    assert (
        sum(
            allocate(
                0,
                {"history": 10, "tool": 10, "documents": 10, "summary": 10},
                {"history": 1, "tool": 0, "documents": 0, "summary": 0},
            ).values()
        )
        == 0
    )
    alloc = allocate(
        100,
        {"history": 10, "tool": 50, "documents": 0, "summary": 0},
        {"history": 1.0, "tool": 0.0, "documents": 0.0, "summary": 0.0},
    )
    assert alloc == {"history": 10, "tool": 50, "documents": 0, "summary": 0}


def test_profiles_normalize() -> None:
    for p in BUILTIN_PROFILES.values():
        assert abs(sum(p.normalized().values()) - 1.0) < 1e-9


def test_detect_workload_shapes() -> None:
    user = Message(role="user", content="compare the sources and cite evidence")
    docs = [Document(id=str(i), text="t") for i in range(3)]
    assert detect_workload([user], docs) == "research"
    assert detect_workload([Message(role="user", content="q")], docs[:1]) == "rag"
    assert detect_workload([Message(role="user", content="hello")], []) == "chat"
    code = Message(role="assistant", content="```py\nx\n```\n```py\ny\n```")
    assert detect_workload([code], []) == "coding"
    tools = [Message(role="tool", tool_call_id=str(i), content="ok") for i in range(6)]
    assert detect_workload(tools, []) == "agent"


def test_extractive_summary_sections_and_budget() -> None:
    units = [
        SummaryUnit("user", 1, "I need to migrate ACC-77120 before 2026-11-01."),
        SummaryUnit(
            "assistant",
            2,
            "We must not change billing@northwind.example. We decided to use 42 seats.",
        ),
        SummaryUnit("user", 3, "Does the plan include SSO?"),
        SummaryUnit("tool", 4, LOG, kind="log"),
        SummaryUnit("tool", 5, LOG, kind="log"),
        SummaryUnit("assistant", 6, "```py\nconfig.set('MAX_SEATS', 42)\n```", kind="code"),
    ]
    out = ExtractiveSummarizer().summarize(
        SummaryInput(
            units=units,
            query="seats",
            budget_tokens=400,
            count=TOK.count,
            messages_dropped=6,
            tokens_dropped=900,
        )
    )
    assert out.tokens <= 400
    for title in (
        "Goals:",
        "Requirements and constraints:",
        "Decisions and conclusions:",
        "Errors seen:",
        "Open questions:",
    ):
        assert title in out.text, title
    assert "(seen 2 times)" in out.text
    assert "ACC-77120" in out.facts_covered
    tiny = ExtractiveSummarizer().summarize(
        SummaryInput(units=units, query="", budget_tokens=5, count=TOK.count)
    )
    assert tiny.text == ""


def test_answered_questions_are_not_open() -> None:
    units = [SummaryUnit("user", 1, "Does the business plan include single sign on?")]
    out = ExtractiveSummarizer().summarize(
        SummaryInput(
            units=units,
            query="",
            budget_tokens=200,
            count=TOK.count,
            later_text="Yes, the business plan does include single sign on.",
        )
    )
    assert "Open questions" not in out.text
