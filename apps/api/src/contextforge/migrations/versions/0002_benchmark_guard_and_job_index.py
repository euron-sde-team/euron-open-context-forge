"""one active benchmark, benchmark started_at, jobs list index

Revision ID: 3b7c2e91d4a0 (file name 0002)
Revises: 160f0a778a3a
Create Date: 2026-10-26 12:00:00

* ``benchmark_runs.started_at``: staleness is measured from when a worker started a run,
  not from when it was queued.
* ``ux_benchmark_runs_active``: at most one queued or running benchmark, enforced by the
  database instead of a check-then-insert race.
* ``ix_jobs_created_at``: the jobs list sorts every status newest first.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3b7c2e91d4a0"
down_revision: Union[str, Sequence[str], None] = "160f0a778a3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("benchmark_runs", sa.Column("started_at", sa.DateTime(timezone=True)))
    # Any duplicates from before the guard: keep the newest active run.
    op.execute(
        """
        UPDATE benchmark_runs SET status = 'failed', error = 'Superseded by a newer run',
               finished_at = now()
        WHERE status IN ('queued', 'running')
          AND id NOT IN (
            SELECT id FROM benchmark_runs WHERE status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
          )
        """
    )
    op.create_index(
        "ux_benchmark_runs_active",
        "benchmark_runs",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index("ix_jobs_created_at", "jobs", [sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ux_benchmark_runs_active", table_name="benchmark_runs")
    op.drop_column("benchmark_runs", "started_at")
