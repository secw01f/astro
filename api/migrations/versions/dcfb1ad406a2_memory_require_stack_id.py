"""memory require stack_id

Revision ID: dcfb1ad406a2
Revises: 6217818b6c73
Create Date: 2026-07-21 15:11:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "dcfb1ad406a2"
down_revision: Union[str, None] = "6217818b6c73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing memories predate stack scoping and cannot be backfilled reliably.
    op.execute(sa.text("DELETE FROM memory"))

    op.add_column("memory", sa.Column("stack_id", sa.Integer(), nullable=False))
    op.create_index(op.f("ix_memory_stack_id"), "memory", ["stack_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_memory_stack_id_stack"),
        "memory",
        "stack",
        ["stack_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_memory_stack_id_stack"), "memory", type_="foreignkey")
    op.drop_index(op.f("ix_memory_stack_id"), table_name="memory")
    op.drop_column("memory", "stack_id")
