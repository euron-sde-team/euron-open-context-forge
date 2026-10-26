"""Regression: a bare worker process must register every mapper before it writes."""

from __future__ import annotations

import subprocess
import sys


def test_worker_import_path_registers_every_table() -> None:
    code = (
        "import contextforge.worker\n"
        "from contextforge.core.db import Base, import_all_models\n"
        "import_all_models()\n"
        "from contextforge.benchmark_runs.models import BenchmarkRun\n"
        "from sqlalchemy.orm import configure_mappers\n"
        "configure_mappers()\n"
        "assert 'users' in Base.metadata.tables\n"
        "list(BenchmarkRun.__table__.foreign_keys)[0].column\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603 a fixed, local snippet
