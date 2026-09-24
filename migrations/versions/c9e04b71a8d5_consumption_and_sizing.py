"""consumption, slab tariffs, and system sizing

Revision ID: c9e04b71a8d5
Revises: a1d8e5f37b62
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e04b71a8d5'
down_revision: Union[str, None] = 'a1d8e5f37b62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No plans are seeded: rates vary by DISCOM, category and revision, and a stale
    # tariff in a customer proposal is a commercial problem.
    op.create_table(
        'tariff_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('discom', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('slabs_json', sa.Text(), nullable=False),
        sa.Column('fixed_charge_inr_per_kw_month', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_tariff_plan'),
    )
    op.create_index(op.f('ix_tariff_plans_id'), 'tariff_plans', ['id'], unique=False)
    op.create_index(op.f('ix_tariff_plans_org_id'), 'tariff_plans', ['org_id'], unique=False)

    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.add_column(sa.Column('consumption_json', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('tariff_plan_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('budget_inr', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('savings_basis', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('self_consumed_kwh', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('exported_kwh', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('effective_rate_inr_per_kwh', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('recommended_kwp', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('sizing_json', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('tariff_check_json', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_project_tariff_plan', 'tariff_plans', ['tariff_plan_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.drop_constraint('fk_project_tariff_plan', type_='foreignkey')
        for column in ('tariff_check_json', 'sizing_json', 'recommended_kwp',
                       'effective_rate_inr_per_kwh', 'exported_kwh', 'self_consumed_kwh',
                       'savings_basis', 'budget_inr', 'tariff_plan_id', 'consumption_json'):
            batch_op.drop_column(column)

    op.drop_index(op.f('ix_tariff_plans_org_id'), table_name='tariff_plans')
    op.drop_index(op.f('ix_tariff_plans_id'), table_name='tariff_plans')
    op.drop_table('tariff_plans')
