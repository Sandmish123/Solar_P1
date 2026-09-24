"""catalog: panel and inverter models, project component links, compliance results

Revision ID: f7a2b6c04d19
Revises: d5c93f1a4e28
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a2b6c04d19'
down_revision: Union[str, None] = 'd5c93f1a4e28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def _shared_columns():
    """Fresh Column objects per call: a Column cannot be attached to two tables, and
    Column.copy() was removed in SQLAlchemy 2.0.

    org_id is nullable on both tables: NULL is the shared seed catalog every firm sees,
    a value is that firm's own addition.
    """
    return [
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=True),
        sa.Column('manufacturer', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('datasheet_verified', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        'panel_models',
        *_shared_columns(),
        sa.Column('wp', sa.Float(), nullable=False),
        sa.Column('voc', sa.Float(), nullable=True),
        sa.Column('isc', sa.Float(), nullable=True),
        sa.Column('vmp', sa.Float(), nullable=True),
        sa.Column('imp', sa.Float(), nullable=True),
        sa.Column('temp_coeff_voc_pct_per_c', sa.Float(), nullable=True),
        sa.Column('temp_coeff_pmax_pct_per_c', sa.Float(), nullable=True),
        sa.Column('length_mm', sa.Float(), nullable=True),
        sa.Column('width_mm', sa.Float(), nullable=True),
        sa.Column('efficiency_pct', sa.Float(), nullable=True),
        # Tri-state: NULL means "not recorded", which must never read as compliant.
        sa.Column('almm_listed', sa.Boolean(), nullable=True),
        sa.Column('almm_id', sa.String(), nullable=True),
        sa.Column('dcr', sa.Boolean(), nullable=True),
        sa.Column('is_bifacial', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'manufacturer', 'model', name='uq_panel_model'),
    )
    op.create_index(op.f('ix_panel_models_id'), 'panel_models', ['id'], unique=False)
    op.create_index(op.f('ix_panel_models_org_id'), 'panel_models', ['org_id'], unique=False)

    op.create_table(
        'inverter_models',
        *_shared_columns(),
        sa.Column('ac_kw', sa.Float(), nullable=True),
        sa.Column('max_dc_v', sa.Float(), nullable=True),
        sa.Column('start_v', sa.Float(), nullable=True),
        sa.Column('mppt_count', sa.Integer(), nullable=True),
        sa.Column('mppt_v_min', sa.Float(), nullable=True),
        sa.Column('mppt_v_max', sa.Float(), nullable=True),
        sa.Column('max_input_current_per_mppt', sa.Float(), nullable=True),
        sa.Column('max_isc_per_mppt', sa.Float(), nullable=True),
        sa.Column('phases', sa.Integer(), nullable=True),
        sa.Column('efficiency_pct', sa.Float(), nullable=True),
        sa.Column('bis_certified', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'manufacturer', 'model', name='uq_inverter_model'),
    )
    op.create_index(op.f('ix_inverter_models_id'), 'inverter_models', ['id'], unique=False)
    op.create_index(op.f('ix_inverter_models_org_id'), 'inverter_models', ['org_id'], unique=False)

    # Nullable: projects created before the catalog keep their free-text component names.
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.add_column(sa.Column('panel_model_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('inverter_model_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('compliance_json', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_project_panel_model', 'panel_models', ['panel_model_id'], ['id'])
        batch_op.create_foreign_key('fk_project_inverter_model', 'inverter_models', ['inverter_model_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('solar_projects') as batch_op:
        batch_op.drop_constraint('fk_project_inverter_model', type_='foreignkey')
        batch_op.drop_constraint('fk_project_panel_model', type_='foreignkey')
        batch_op.drop_column('compliance_json')
        batch_op.drop_column('inverter_model_id')
        batch_op.drop_column('panel_model_id')

    op.drop_index(op.f('ix_inverter_models_org_id'), table_name='inverter_models')
    op.drop_index(op.f('ix_inverter_models_id'), table_name='inverter_models')
    op.drop_table('inverter_models')
    op.drop_index(op.f('ix_panel_models_org_id'), table_name='panel_models')
    op.drop_index(op.f('ix_panel_models_id'), table_name='panel_models')
    op.drop_table('panel_models')
