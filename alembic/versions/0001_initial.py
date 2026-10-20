"""initial

Revision ID: 0001
Revises:
Create Date: 2026-10-19 16:48:37.961954

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("content", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("type IN ('keywords')", name=op.f("ck_data_types_type_allowed")),
        sa.CheckConstraint(
            "cardinality(content) >= 1", name=op.f("ck_data_types_content_not_empty")
        ),
        sa.CheckConstraint("threshold >= 1", name=op.f("ck_data_types_threshold_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_types")),
    )
    op.create_index("uq_data_types_name_lower", "data_types", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "data_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_sets")),
    )
    op.create_index("uq_data_sets_name_lower", "data_sets", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "data_set_data_types",
        sa.Column("data_set_id", sa.Uuid(), nullable=False),
        sa.Column("data_type_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["data_set_id"],
            ["data_sets.id"],
            name=op.f("fk_data_set_data_types_data_set_id_data_sets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["data_type_id"],
            ["data_types.id"],
            name=op.f("fk_data_set_data_types_data_type_id_data_types"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("data_set_id", "data_type_id", name=op.f("pk_data_set_data_types")),
    )
    op.create_index("ix_data_set_data_types_data_type_id", "data_set_data_types", ["data_type_id"])


def downgrade() -> None:
    op.drop_index("ix_data_set_data_types_data_type_id", table_name="data_set_data_types")
    op.drop_table("data_set_data_types")
    op.drop_index("uq_data_sets_name_lower", table_name="data_sets")
    op.drop_table("data_sets")
    op.drop_index("uq_data_types_name_lower", table_name="data_types")
    op.drop_table("data_types")
