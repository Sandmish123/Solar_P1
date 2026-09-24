"""p90, site temperature loss, and mounting type

Revision ID: a1d8e5f37b62
Revises: f7a2b6c04d19
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1d8e5f37b62'
down_revision: Union[str, None] = 'f7a2b6c04d19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('solar_projects') as batch_op:
        # Off by default, like shading_auto: no existing proposal moves on its own.
        batch_op.add_column(sa.Column('temp_loss_auto', sa.Boolean(), server_default=sa.false(), nullable=True))
        batch_op.add_column(sa.Column('mounting_type', sa.String(), server_default=sa.text("'free'"), nullable=True))
        batch_op.add_column(sa.Column('annual_gen_p90_kwh', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('temp_loss_computed_pct', sa.Float(), nullable=True))

    # Rows cached before this migration were fetched without a mountingplace parameter,
    # and PVGIS defaults to free-standing, so backfilling 'free' is accurate rather
    # than merely convenient. The unique key gains mounting, so a building-mounted
    # lookup for the same cell fetches its own (hotter) temperature loss.
    with op.batch_alter_table('irradiance_cache') as batch_op:
        batch_op.add_column(sa.Column('mounting', sa.String(), server_default=sa.text("'free'"), nullable=False))
        batch_op.add_column(sa.Column('e_annual', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('sd_annual', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('temp_loss_pct', sa.Float(), nullable=True))
        batch_op.drop_constraint('uq_irradiance_cell', type_='unique')
        batch_op.create_unique_constraint(
            'uq_irradiance_cell', ['lat_key', 'lon_key', 'tilt_key', 'azimuth_key', 'mounting']
        )


def downgrade() -> None:
    with op.batch_alter_table('irradiance_cache') as batch_op:
        batch_op.drop_constraint('uq_irradiance_cell', type_='unique')
        batch_op.create_unique_constraint(
            'uq_irradiance_cell', ['lat_key', 'lon_key', 'tilt_key', 'azimuth_key']
        )
        batch_op.drop_column('temp_loss_pct')
        batch_op.drop_column('sd_annual')
        batch_op.drop_column('e_annual')
        batch_op.drop_column('mounting')

    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.drop_column('temp_loss_computed_pct')
        batch_op.drop_column('annual_gen_p90_kwh')
        batch_op.drop_column('mounting_type')
        batch_op.drop_column('temp_loss_auto')
