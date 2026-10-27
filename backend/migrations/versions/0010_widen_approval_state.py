"""widen outreach_messages.approval_state (awaiting_approval is 17 chars; PostgreSQL enforces varchar length)

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('outreach_messages') as b:
        b.alter_column('approval_state', existing_type=sa.String(16), type_=sa.String(24), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('outreach_messages') as b:
        b.alter_column('approval_state', existing_type=sa.String(24), type_=sa.String(16), existing_nullable=False)
