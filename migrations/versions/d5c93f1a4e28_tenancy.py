"""tenancy: organisations, users, and org scoping on projects

Revision ID: d5c93f1a4e28
Revises: c4a7e2b81f30
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5c93f1a4e28'
down_revision: Union[str, None] = 'c4a7e2b81f30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ORG_ID = 1
DEFAULT_ORG_NAME = "Default Organisation"


def upgrade() -> None:
    organisations = op.create_table(
        'organisations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_organisations_id'), 'organisations', ['id'], unique=False)

    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('role', sa.String(), server_default=sa.text("'member'"), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_org_id'), 'users', ['org_id'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # Existing proposals must belong to someone, so give them a home before the
    # column is made mandatory. No user is created here: shipping a default password
    # would be worse than requiring scripts/create_user.py once.
    op.bulk_insert(organisations, [{"id": DEFAULT_ORG_ID, "name": DEFAULT_ORG_NAME}])

    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.add_column(sa.Column('org_id', sa.Integer(), nullable=True))
    op.execute(f"UPDATE solar_projects SET org_id = {DEFAULT_ORG_ID} WHERE org_id IS NULL")
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key('fk_solar_projects_org', 'organisations', ['org_id'], ['id'])
        batch_op.create_index(op.f('ix_solar_projects_org_id'), ['org_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.drop_index(op.f('ix_solar_projects_org_id'))
        batch_op.drop_constraint('fk_solar_projects_org', type_='foreignkey')
        batch_op.drop_column('org_id')

    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_org_id'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_organisations_id'), table_name='organisations')
    op.drop_table('organisations')
