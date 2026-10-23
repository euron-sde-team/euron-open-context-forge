"""AC13: the committed benchmark proves reduction without losing task-critical facts."""

from __future__ import annotations

from contextforge.benchmarks import load_cases
from contextforge.benchmarks.datasets import build_cases, to_json
from contextforge.benchmarks.runner import reader_answers, run, to_markdown


def test_committed_dataset_matches_the_generator() -> None:
    from contextforge.benchmarks import DATA_FILE

    assert DATA_FILE.read_text() == to_json(build_cases()) + "\n"


def test_ac13_benchmark_beats_truncation() -> None:
    version, cases = load_cases()
    report = run(cases, runs=1, dataset_version=version)
    by = {s.method: s for s in report.summary}
    forge, trunc = by["contextforge-balanced"], by["truncate-oldest"]
    assert forge.budget_met == forge.cases == len(cases)
    assert forge.reduction_percent >= 70
    assert forge.fact_retention >= 0.95
    assert forge.citation_retention == 1.0
    assert forge.fact_retention > trunc.fact_retention
    assert forge.citation_retention > trunc.citation_retention
    md = to_markdown(report)
    assert "simulated" in md and "| contextforge-balanced |" in md


def test_reader_is_deterministic() -> None:
    ctx = "The sky is blue.\nThe ticket is ENG-1.\nCats sleep."
    assert reader_answers(ctx, "Which ticket?", k=1) == ["The ticket is ENG-1."]
