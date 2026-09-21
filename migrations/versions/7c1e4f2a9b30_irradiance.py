"""irradiance: site orientation, PVGIS source tracking, irradiance cache

Revision ID: 7c1e4f2a9b30
Revises: 2a99e251619c
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c1e4f2a9b30'
down_revision: Union[str, None] = '2a99e251619c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table so the same migration runs on SQLite (local) and Postgres (Render).
    # server_default backfills existing rows; calibration matches
    # app.calculations.solar.DEFAULT_IRRADIANCE_CALIBRATION at the time of writing.
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.add_column(sa.Column('tilt_deg', sa.Float(), server_default=sa.text('25.0'), nullable=True))
        batch_op.add_column(sa.Column('azimuth_deg', sa.Float(), server_default=sa.text('0.0'), nullable=True))
        batch_op.add_column(sa.Column('irradiance_calibration', sa.Float(), server_default=sa.text('0.8305'), nullable=True))
        batch_op.add_column(sa.Column('irradiance_source', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('irradiance_h_annual', sa.Float(), nullable=True))

    op.create_table('irradiance_cache',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lat_key', sa.Integer(), nullable=False),
    sa.Column('lon_key', sa.Integer(), nullable=False),
    sa.Column('tilt_key', sa.Integer(), nullable=False),
    sa.Column('azimuth_key', sa.Integer(), nullable=False),
    sa.Column('monthly_h_json', sa.Text(), nullable=False),
    sa.Column('h_annual', sa.Float(), nullable=False),
    sa.Column('radiation_db', sa.String(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lat_key', 'lon_key', 'tilt_key', 'azimuth_key', name='uq_irradiance_cell')
    )


def downgrade() -> None:
    op.drop_table('irradiance_cache')
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.drop_column('irradiance_h_annual')
        batch_op.drop_column('irradiance_source')
        batch_op.drop_column('irradiance_calibration')
        batch_op.drop_column('azimuth_deg')
        batch_op.drop_column('tilt_deg')
