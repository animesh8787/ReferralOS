"""firebase_uid on users; password_hash becomes optional

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('firebase_uid', sa.String(length=128), nullable=True))
        b.alter_column('password_hash', existing_type=sa.String(255), nullable=True)
    op.create_index('ix_users_firebase_uid', 'users', ['firebase_uid'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_users_firebase_uid', table_name='users')
    with op.batch_alter_table('users') as b:
        b.alter_column('password_hash', existing_type=sa.String(255), nullable=False)
        b.drop_column('firebase_uid')
