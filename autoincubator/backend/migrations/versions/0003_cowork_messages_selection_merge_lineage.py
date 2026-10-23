"""cowork_messages; run selection; merge lineage, rejection reason and applied patches

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cowork_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("idea_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "agent", sa.Enum("scout", "analyst", "skeptic", name="cowork_agent"), nullable=False
        ),
        sa.Column("role", sa.Enum("user", "assistant", name="cowork_role"), nullable=False),
        sa.Column(
            "state",
            sa.Enum("pending", "complete", "failed", name="cowork_message_state"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("proposed_patch", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("based_on_version", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["idea_id"],
            ["ideas.id"],
            name=op.f("fk_cowork_messages_idea_id_ideas"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_cowork_messages_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cowork_messages")),
    )
    op.create_index(
        "ix_cowork_messages_idea_id_created_at",
        "cowork_messages",
        ["idea_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cowork_messages_user_id"), "cowork_messages", ["user_id"], unique=False
    )
    op.add_column(
        "idea_versions", sa.Column("patch", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("idea_versions", sa.Column("message_id", sa.UUID(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_idea_versions_message_id"), "idea_versions", ["message_id"]
    )
    op.create_foreign_key(
        op.f("fk_idea_versions_message_id_cowork_messages"),
        "idea_versions",
        "cowork_messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "ideas",
        sa.Column(
            "merged_from",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column("ideas", sa.Column("reject_reason", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("selected_idea_id", sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "selected_idea_id")
    op.drop_column("ideas", "reject_reason")
    op.drop_column("ideas", "merged_from")
    op.drop_constraint(
        op.f("fk_idea_versions_message_id_cowork_messages"), "idea_versions", type_="foreignkey"
    )
    op.drop_constraint(op.f("uq_idea_versions_message_id"), "idea_versions", type_="unique")
    op.drop_column("idea_versions", "message_id")
    op.drop_column("idea_versions", "patch")
    op.drop_index(op.f("ix_cowork_messages_user_id"), table_name="cowork_messages")
    op.drop_index("ix_cowork_messages_idea_id_created_at", table_name="cowork_messages")
    op.drop_table("cowork_messages")
    for enum in ("cowork_agent", "cowork_role", "cowork_message_state"):
        sa.Enum(name=enum).drop(op.get_bind(), checkfirst=True)
