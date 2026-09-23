"""shading: geometry-derived shading loss and building footprint cache

Revision ID: b8f21c4d9e07
Revises: e3b9d51c7a42
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8f21c4d9e07'
down_revision: Union[str, None] = 'e3b9d51c7a42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table so the same migration runs on SQLite (local) and Postgres (Render).
    # sa.false() renders as 0 on SQLite and false on Postgres.
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.add_column(sa.Column('shading_auto', sa.Boolean(), server_default=sa.false(), nullable=True))
        batch_op.add_column(sa.Column('shading_computed_pct', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('shading_neighbour_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('shading_heights_assumed', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('shading_monthly_json', sa.Text(), nullable=True))

    op.create_table('building_cache',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lat_key', sa.Integer(), nullable=False),
    sa.Column('lon_key', sa.Integer(), nullable=False),
    sa.Column('radius_m', sa.Integer(), nullable=False),
    sa.Column('buildings_json', sa.Text(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lat_key', 'lon_key', 'radius_m', name='uq_building_cell')
    )


def downgrade() -> None:
    op.drop_table('building_cache')
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.drop_column('shading_monthly_json')
        batch_op.drop_column('shading_heights_assumed')
        batch_op.drop_column('shading_neighbour_count')
        batch_op.drop_column('shading_computed_pct')
        batch_op.drop_column('shading_auto')
