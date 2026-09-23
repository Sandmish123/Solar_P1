"""inverter replacement: mid-life capex in the 25-year cashflow

Revision ID: c4a7e2b81f30
Revises: b8f21c4d9e07
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a7e2b81f30'
down_revision: Union[str, None] = 'b8f21c4d9e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Defaults ON (year 12), unlike shading_auto: omitting a known mid-life cost
    # overstates lifetime savings, which is the bug this corrects. Existing rows
    # only change when they are next recalculated.
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.add_column(sa.Column('inverter_replacement_year', sa.Integer(), server_default=sa.text('12'), nullable=True))
        batch_op.add_column(sa.Column('inverter_replacement_cost_inr', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('inverter_replacement_applied_inr', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.drop_column('inverter_replacement_applied_inr')
        batch_op.drop_column('inverter_replacement_cost_inr')
        batch_op.drop_column('inverter_replacement_year')
