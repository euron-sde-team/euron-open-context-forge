"""Reproducible benchmark: committed synthetic datasets, baselines and the runner."""

from __future__ import annotations

import json
from pathlib import Path

from contextforge.benchmarks.datasets import Case

DATA_FILE = Path(__file__).parent / "data" / "cases.json"


def load_cases(path: Path = DATA_FILE) -> tuple[str, list[Case]]:
    """(dataset version, cases) from the committed dataset file."""
    raw = json.loads(path.read_text())
    return str(raw["version"]), [Case.model_validate(c) for c in raw["cases"]]
