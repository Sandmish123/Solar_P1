"""financials: cost, tariff and subsidy inputs; payback, IRR, cashflow results

Revision ID: e3b9d51c7a42
Revises: 7c1e4f2a9b30
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3b9d51c7a42'
down_revision: Union[str, None] = '7c1e4f2a9b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (name, server_default) for inputs with a default; backfills existing rows.
_DEFAULTED_INPUTS = [
    ('tariff_inr_per_kwh', '8.0'),
    ('tariff_escalation_pct', '3.0'),
    ('export_ratio_pct', '30.0'),
    ('export_tariff_inr_per_kwh', '3.0'),
    ('om_cost_pct', '1.0'),
    ('discount_rate_pct', '8.0'),
]
# Nullable with no default: optional inputs and all results.
_NULLABLE_FLOATS = [
    'system_cost_inr',
    'subsidy_inr',
    'subsidy_applied_inr',
    'net_investment_inr',
    'year1_savings_inr',
    'payback_years',
    'discounted_payback_years',
    'irr_pct',
    'npv_inr',
    'lifetime_net_savings_inr',
    'lcoe_inr_per_kwh',
    'co2_offset_tonnes',
]


def upgrade() -> None:
    # batch_alter_table so the same migration runs on SQLite (local) and Postgres (Render).
    with op.batch_alter_table('solar_projects') as batch_op:
        for name, default in _DEFAULTED_INPUTS:
            batch_op.add_column(sa.Column(name, sa.Float(), server_default=sa.text(default), nullable=True))
        for name in _NULLABLE_FLOATS:
            batch_op.add_column(sa.Column(name, sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('cashflow_json', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.drop_column('cashflow_json')
        for name in reversed(_NULLABLE_FLOATS):
            batch_op.drop_column(name)
        for name, _ in reversed(_DEFAULTED_INPUTS):
            batch_op.drop_column(name)
