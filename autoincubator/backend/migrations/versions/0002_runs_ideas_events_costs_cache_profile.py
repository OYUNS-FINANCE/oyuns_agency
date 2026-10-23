"""runs, ideas, idea_versions, agent_events, search_cache, run_costs, founder_profile

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "founder_profile",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "skills", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("capital_usd", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "risk_tolerance",
            sa.Enum("low", "medium", "high", name="risk_tolerance"),
            nullable=False,
        ),
        sa.Column("weekly_hours", sa.Integer(), nullable=True),
        sa.Column(
            "rejected_idea_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_founder_profile")),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.Enum("seeded", "autonomous", name="run_mode"), nullable=False),
        sa.Column("seed", sa.Text(), nullable=True),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "awaiting_human",
                "completed",
                "failed",
                "budget_exhausted",
                name="run_status",
            ),
            nullable=False,
        ),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("max_tokens", sa.BigInteger(), nullable=False),
        sa.Column("max_searches", sa.Integer(), nullable=False),
        sa.Column("tokens_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("searches_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("viable_count", sa.Integer(), nullable=True),
        sa.Column("shortfall", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_index(op.f("ix_runs_status"), "runs", ["status"], unique=False)
    op.create_index(
        "ix_runs_user_id_created_at",
        "runs",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "agent_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("agent", sa.String(length=40), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_agent_events_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_events")),
    )
    op.create_index("ix_agent_events_run_id_id", "agent_events", ["run_id", "id"], unique=False)
    op.create_index(op.f("ix_agent_events_user_id"), "agent_events", ["user_id"], unique=False)
    op.create_table(
        "ideas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "rejected", "merged", "selected", name="idea_status"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("composite_score", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_ideas_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ideas")),
        sa.UniqueConstraint("run_id", "key", name=op.f("uq_ideas_run_id_key")),
    )
    op.create_index(op.f("ix_ideas_run_id"), "ideas", ["run_id"], unique=False)
    op.create_index(op.f("ix_ideas_user_id"), "ideas", ["user_id"], unique=False)
    op.create_table(
        "run_costs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("agent", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_run_costs_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_costs")),
    )
    op.create_index(op.f("ix_run_costs_run_id"), "run_costs", ["run_id"], unique=False)
    op.create_index(op.f("ix_run_costs_user_id"), "run_costs", ["user_id"], unique=False)
    op.create_table(
        "search_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("query_norm", sa.Text(), nullable=False),
        sa.Column("max_results", sa.Integer(), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_search_cache_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_cache")),
        sa.UniqueConstraint(
            "run_id",
            "query_norm",
            "max_results",
            name=op.f("uq_search_cache_run_id_query_norm_max_results"),
        ),
    )
    op.create_index(op.f("ix_search_cache_user_id"), "search_cache", ["user_id"], unique=False)
    op.create_table(
        "idea_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("idea_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("agent", "cowork", "merge", "rescore", name="idea_version_source"),
            nullable=False,
        ),
        sa.Column("opportunity", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("critique", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("composite_score", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["idea_id"],
            ["ideas.id"],
            name=op.f("fk_idea_versions_idea_id_ideas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idea_versions")),
        sa.UniqueConstraint("idea_id", "version", name=op.f("uq_idea_versions_idea_id_version")),
    )
    op.create_index(op.f("ix_idea_versions_user_id"), "idea_versions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_idea_versions_user_id"), table_name="idea_versions")
    op.drop_table("idea_versions")
    op.drop_index(op.f("ix_search_cache_user_id"), table_name="search_cache")
    op.drop_table("search_cache")
    op.drop_index(op.f("ix_run_costs_user_id"), table_name="run_costs")
    op.drop_index(op.f("ix_run_costs_run_id"), table_name="run_costs")
    op.drop_table("run_costs")
    op.drop_index(op.f("ix_ideas_user_id"), table_name="ideas")
    op.drop_index(op.f("ix_ideas_run_id"), table_name="ideas")
    op.drop_table("ideas")
    op.drop_index(op.f("ix_agent_events_user_id"), table_name="agent_events")
    op.drop_index("ix_agent_events_run_id_id", table_name="agent_events")
    op.drop_table("agent_events")
    op.drop_index("ix_runs_user_id_created_at", table_name="runs")
    op.drop_index(op.f("ix_runs_status"), table_name="runs")
    op.drop_table("runs")
    op.drop_table("founder_profile")
    for enum in ("run_mode", "run_status", "idea_status", "idea_version_source", "risk_tolerance"):
        sa.Enum(name=enum).drop(op.get_bind(), checkfirst=True)
