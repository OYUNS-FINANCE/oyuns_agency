"""search_result_cache (cross-run provider cache) and run_costs.created_at index (daily cap)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_result_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("query_norm", sa.Text(), nullable=False),
        sa.Column("max_results", sa.Integer(), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_result_cache")),
        sa.UniqueConstraint(
            "provider",
            "query_norm",
            "max_results",
            name=op.f("uq_search_result_cache_provider_query_norm_max_results"),
        ),
    )
    op.create_index(
        op.f("ix_search_result_cache_fetched_at"), "search_result_cache", ["fetched_at"]
    )
    op.create_index(op.f("ix_run_costs_created_at"), "run_costs", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_run_costs_created_at"), table_name="run_costs")
    op.drop_index(op.f("ix_search_result_cache_fetched_at"), table_name="search_result_cache")
    op.drop_table("search_result_cache")
